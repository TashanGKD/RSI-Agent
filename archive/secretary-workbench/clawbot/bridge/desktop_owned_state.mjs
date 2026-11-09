import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';

/**
 * 读取本机进程命令行，供核对是否仍是受管原生 CLI。
 *
 * @param {number} pid - 进程号
 * @returns {string|null} 命令行或空
 */
export function commandOfPid(pid){
 if(!Number.isInteger(pid)||pid<=0)return null;
 const result=spawnSync('/bin/ps',['-p',String(pid),'-o','command='],{encoding:'utf8'});
 if(result.status!==0)return null;
 const command=result.stdout.trim();
 return command||null;
}

/**
 * 判断 Unix 套接字当前是否可连接。
 *
 * @param {string} socketPath - 绝对套接字路径
 * @returns {Promise<boolean>} 是否可连接
 */
export function connectable(socketPath){
 return new Promise(resolve=>{
  const connection=net.createConnection(socketPath);
  const finish=result=>{connection.destroy();resolve(result);};
  connection.once('connect',()=>finish(true));
  connection.once('error',()=>finish(false));
  connection.setTimeout(300,()=>finish(false));
 });
}

function ownedPrivateFile(filename,uid){
 try{
  const stat=fs.lstatSync(filename);
  if(stat.isSymbolicLink()||!stat.isFile()||stat.uid!==uid||(stat.mode&0o077)||stat.nlink!==1||stat.size>65536)throw Error('unsafe private desktop metadata');
  return stat;
 }catch(error){if(error.code==='ENOENT')return null;throw error;}
}

function readMetadata(root,uid){
 const filename=`${root}/engine.json`;
 if(!ownedPrivateFile(filename,uid))return null;
 try{
  const data=JSON.parse(fs.readFileSync(filename,'utf8'));
  if(data?.version!==1||!Number.isInteger(data.enginePid)||data.enginePid<=0)throw Error('invalid desktop metadata');
  return data;
 }catch{throw Error('invalid desktop metadata');}
}

function nativeEngineAlive(pid,cli,{kill,commandOf}){
 try{kill(pid,0);}catch{return false;}
 const command=commandOf(pid);
 return typeof command==='string'&&(command===cli||command.startsWith(`${cli} `));
}

function unlinkOwned(filename,uid,{allowSymlink=false,allowSocket=false}={}){
 let stat;
 try{stat=fs.lstatSync(filename);}catch(error){if(error.code==='ENOENT')return;throw error;}
 if(stat.uid!==uid)throw new Error('refusing to remove foreign desktop state');
 if(stat.isSymbolicLink()){if(!allowSymlink)throw new Error('refusing to remove unexpected symlink');fs.unlinkSync(filename);return;}
 if(stat.isSocket()){if(!allowSocket)throw new Error('refusing to remove unexpected socket');fs.unlinkSync(filename);return;}
 if(!stat.isFile()||(stat.mode&0o077))throw new Error('refusing to remove unexpected desktop file');
 fs.unlinkSync(filename);
}

function inspectSocket(socketPath){
 try{return fs.lstatSync(socketPath);}catch(error){if(error.code==='ENOENT')return null;throw error;}
}

async function removeStaleSocket(socketPath,uid,metadata){
 const stat=inspectSocket(socketPath);
 if(!stat)return;
 if(stat.isSymbolicLink()){
  if(stat.uid!==uid||!new RegExp(`^/(?:private/)?tmp/codex-daemon-${uid}/[0-9a-f]{64}$`).test(fs.readlinkSync(socketPath)))throw Error('unknown socket namespace requires review');
  let missing=false;
  try{fs.statSync(socketPath);}catch(error){if(error.code==='ENOENT')missing=true;else throw error;}
  if(missing){unlinkOwned(socketPath,uid,{allowSymlink:true});return;}
  if(metadata?.socketAlias){
   const {validateManagedSocket}=await import('../../host/desktop/shared-launcher.js');
   await validateManagedSocket({socketPath,stateDir:path.dirname(socketPath)});
   // The dead engine's pinned private alias may remain after SIGKILL. Remove
   // only the alias; the native daemon owns cleanup of its actual socket.
   unlinkOwned(socketPath,uid,{allowSymlink:true});return;
  }
  throw Error('existing shared native socket requires review');
 }
}

/**
 * 审查桌面共享目录：过期元数据可清理后启动，活引擎则复用，未知占用拒绝接管。
 *
 * @param {object} options - 根目录、套接字、原生 CLI 与可注入的进程检查
 * @returns {Promise<{action:'start'}|{action:'reuse',enginePid:number}>} 启动决策
 */
export async function resolveOwnedDesktopState({root,socketPath,cli,uid=process.getuid(),kill=process.kill,commandOf=commandOfPid,connect,appToolsPipeHash}){
 if(typeof root!=='string'||typeof socketPath!=='string'||typeof cli!=='string'||!cli)throw new Error('invalid desktop ownership query');
 const tryConnect=connect||(()=>connectable(socketPath));
 const metadata=readMetadata(root,uid);
 const alive=metadata?nativeEngineAlive(metadata.enginePid,cli,{kill,commandOf}):false;
 if(alive){
  if(appToolsPipeHash!==undefined&&metadata.appToolsPipeHash!==appToolsPipeHash)throw Error('existing engine belongs to another Desktop session');
  if(await tryConnect())return {action:'reuse',enginePid:metadata.enginePid};
  throw new Error('existing native engine is running without a usable socket');
 }
 if(await tryConnect())throw new Error('existing shared native socket requires review');
 await removeStaleSocket(socketPath,uid,metadata);
 const leftover=inspectSocket(socketPath);
 if(leftover){
  if(leftover.isSocket()&&metadata)unlinkOwned(socketPath,uid,{allowSocket:true});
  else throw new Error('existing shared native socket requires review');
 }
 if(metadata)unlinkOwned(`${root}/engine.json`,uid);
 return {action:'start'};
}

// SQLite's process lock serializes every Desktop session using this root and
// is released by the OS on process death. No stale lock-file deletion is needed.
export async function acquireDesktopStartup(root,identity,{timeoutMs=3000}={}){
 if(!/^[0-9a-f]{64}$/.test(identity))throw Error('invalid startup identity');
 const directory=fs.lstatSync(root);
 if(!directory.isDirectory()||directory.isSymbolicLink()||directory.uid!==process.getuid()||(directory.mode&0o077))throw Error('private startup lock directory required');
 const filename=path.join(root,'.startup.sqlite');
 try{const fd=fs.openSync(filename,'wx',0o600);fs.closeSync(fd)}catch(error){if(error.code!=='EEXIST')throw error}
 const stat=fs.lstatSync(filename);
 if(!stat.isFile()||stat.isSymbolicLink()||stat.uid!==process.getuid()||(stat.mode&0o077)||stat.nlink!==1||stat.size>1048576)throw Error('unsafe startup lock database');
 const {DatabaseSync}=await import('node:sqlite');
 const database=new DatabaseSync(filename,{timeout:0});
 const deadline=Date.now()+timeoutMs;
 try{
  while(true){
   try{database.exec('BEGIN IMMEDIATE');break}catch(error){
    if(error.errcode!==5&&!String(error.message).includes('database is locked'))throw error;
    if(Date.now()>=deadline)throw Error('startup lock busy');
    await new Promise(resolve=>setTimeout(resolve,30));
   }
  }
 }catch(error){database.close();throw error}
 let released=false;
 return()=>{if(released)return;released=true;try{database.exec('ROLLBACK')}finally{database.close()}};
}

function processStart(pid){
 const result=spawnSync('/bin/ps',['-p',String(pid),'-o','lstart='],{encoding:'utf8'});
 return result.status===0?result.stdout.trim():null;
}
export function registerDesktopClient(root,enginePid,appToolsPipeHash){
 const started=processStart(process.pid);
 if(!started)throw Error('desktop client identity unavailable');
 const filename=path.join(root,`.client-${process.pid}-${crypto.randomUUID()}.json`);
 const fd=fs.openSync(filename,'wx',0o600);const stat=fs.fstatSync(fd);
 try{fs.writeFileSync(fd,JSON.stringify({version:1,pid:process.pid,started,enginePid,appToolsPipeHash}));fs.fsyncSync(fd)}finally{fs.closeSync(fd)}
 return()=>{try{const current=fs.lstatSync(filename);if(current.ino===stat.ino&&current.dev===stat.dev)fs.unlinkSync(filename)}catch(error){if(error.code!=='ENOENT')throw error}};
}
export function otherDesktopClients(root,enginePid){
 for(const name of fs.readdirSync(root)){
  if(!/^\.client-\d+-[0-9a-f-]{36}\.json$/.test(name))continue;
  const filename=path.join(root,name);
  if(!ownedPrivateFile(filename,process.getuid()))continue;
  let data;
  try{data=JSON.parse(fs.readFileSync(filename,'utf8'))}catch(error){if(error.code==='ENOENT')continue;throw error}
  if(data.version!==1||!Number.isInteger(data.pid)||data.pid<=0||data.enginePid!==enginePid)continue;
  if(processStart(data.pid)===data.started)return true;
 }
 return false;
}
