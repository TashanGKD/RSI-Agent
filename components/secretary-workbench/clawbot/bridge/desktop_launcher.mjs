// Desktop sharing is optional: before any RPC bytes are consumed, a sharing
// failure falls back to the official CLI. Consumed requests are never replayed.
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import crypto from 'node:crypto';
import {spawn} from 'node:child_process';

const cli='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex';
const root=process.env.TASHAN_DESKTOP_SOCKET_ROOT||process.env.TASHAN_DESKTOP_TEST_ROOT||path.join(os.homedir(),'Library/Application Support/TashanWeixinBridge/desktop');
const socketPath=path.join(root,'control.sock');
const args=process.argv.slice(2);
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
let traffic=false,stopping=false,writeBridgeStatus;

function nativeStartup(){
 return new Promise(resolve=>{
  const child=spawn(cli,args,{stdio:'inherit',env:process.env});
  const term=()=>child.kill('SIGTERM'),interrupt=()=>child.kill('SIGINT');
  process.once('SIGTERM',term);process.once('SIGINT',interrupt);
  const finish=code=>{process.off('SIGTERM',term);process.off('SIGINT',interrupt);resolve(code)};
  child.once('error',()=>{console.error('Official native startup failed; verify the installed Codex CLI.');finish(1)});
  child.once('exit',(code,signal)=>finish(code??(signal?1:0)));
 });
}

async function sharedStartup(){
 const imports=await Promise.all([
  import('./desktop_bridge_status.mjs'),
  import('./desktop_invocation.mjs'),
  import('./desktop_owned_state.mjs'),
  import('../../host/desktop/shared-launcher.js'),
  import('../../host/desktop/shared-stdio.js'),
 ]);
 writeBridgeStatus=imports[0].writeBridgeStatus;
 const {isDesktopFrontendInvocation}=imports[1];
 if(!isDesktopFrontendInvocation(args)||args.some(a=>['--help','-h','--print-startup-config'].includes(a)))return nativeStartup();
 const {resolveOwnedDesktopState,acquireDesktopStartup,registerDesktopClient,otherDesktopClients}=imports[2];
 const {engineArgs,validateManagedSocket}=imports[3];
 const {bridgeStdio}=imports[4];
 const stat=fs.lstatSync(root);
 if(!stat.isDirectory()||stat.isSymbolicLink()||stat.uid!==process.getuid()||(stat.mode&0o077))throw Error('private desktop directory required');
 const appToolsPipeHash=crypto.createHash('sha256').update(process.env.CODEX_APP_TOOLS_PIPE_PATH??'').digest('hex');
 let release=await acquireDesktopStartup(root,appToolsPipeHash);
 let decision;
 try{decision=await resolveOwnedDesktopState({root,socketPath,cli,appToolsPipeHash})}catch(error){release();throw error}
 const controller=new AbortController();
 const stop=()=>{stopping=true;controller.abort()};
 process.once('SIGTERM',stop);process.once('SIGINT',stop);
 let engine,exitResult,exited,metadataOwned=false,lease;
 const metadata=path.join(root,'engine.json');
 try{
  if(decision.action==='start'){
   engine=spawn(cli,engineArgs(args,socketPath),{stdio:['ignore','ignore','inherit'],env:process.env});
   exited=new Promise(resolve=>{
    engine.once('error',()=>{exitResult={code:1};controller.abort();resolve()});
    engine.once('exit',(code,signal)=>{exitResult={code:code??(signal?1:0)};controller.abort();resolve()});
   });
   const deadline=Date.now()+10000;
   while(!fs.existsSync(socketPath)&&!exitResult&&!stopping&&Date.now()<deadline)await sleep(30);
   if(stopping)return 0;
   if(exitResult||!fs.existsSync(socketPath))throw Error('native shared socket unavailable');
   const checked=await validateManagedSocket({socketPath,stateDir:root},{allowNewNative:true});
   const fd=fs.openSync(metadata,'wx',0o600);
   try{fs.writeFileSync(fd,JSON.stringify({version:1,enginePid:engine.pid,socketAlias:checked.socketAlias,appToolsPipeHash}));fs.fsyncSync(fd)}finally{fs.closeSync(fd)}
   metadataOwned=true;
  }else{
   // Reuse must keep the original pin; never accept a replaced socket alias.
   await validateManagedSocket({socketPath,stateDir:root});
  }
  lease=registerDesktopClient(root,engine?.pid??decision.enginePid,appToolsPipeHash);
  writeBridgeStatus(root,{enabled:true,enginePid:engine?.pid??decision.enginePid,appToolsPipeHash});
  release();release=null;
  const code=await bridgeStdio({socketPath:fs.realpathSync(socketPath),stateDir:root},{signal:controller.signal,onTraffic:()=>{traffic=true}});
  if(stopping)return 0;
  if(exitResult?.code||code!==0)throw Error('shared desktop transport ended');
  return 0;
 }finally{
  release?.();
  controller.abort();
  lease?.();
  let retirement;
  try{if(engine){
   // Keep the signed owner ancestor alive while a reused Desktop connection is
   // still attached. A whole-app SIGTERM/SIGINT still shuts everything down.
   while(true){
    retirement=await acquireDesktopStartup(root,appToolsPipeHash,{timeoutMs:10000});
    if(exitResult||stopping||!otherDesktopClients(root,engine.pid))break;
    retirement();retirement=null;await sleep(100);
   }
   if(!exitResult){
    engine.kill('SIGTERM');
    let timer;
    try{await Promise.race([exited,new Promise(resolve=>{timer=setTimeout(resolve,5000)})])}finally{clearTimeout(timer)}
   }
   if(!exitResult){engine.kill('SIGKILL');await exited}
   if(metadataOwned){
    // Retain the pin if a crashed native daemon left its alias behind; the
    // next startup can then prove ownership before removing that stale alias.
    let aliasPresent=true;try{fs.lstatSync(socketPath)}catch(error){if(error.code==='ENOENT')aliasPresent=false}
    if(!aliasPresent)try{const stat=fs.lstatSync(metadata);if(stat.isFile()&&stat.uid===process.getuid()&&JSON.parse(fs.readFileSync(metadata,'utf8')).enginePid===engine.pid)fs.unlinkSync(metadata)}catch{}
   }
  }}finally{retirement?.();process.off('SIGTERM',stop);process.off('SIGINT',stop)}
 }
}

if(!args.length){
 console.error('Desktop shared launcher: explicit native CLI arguments required.');
 process.exitCode=0;
}else{
 try{process.exitCode=await sharedStartup()}
 catch(error){
  const reason=String(error?.code??error?.message??'unknown').slice(0,160);
  // Guard the attach-only WeChat port before allowing an independent Desktop.
  try{
   writeBridgeStatus??=(await import('./desktop_bridge_status.mjs')).writeBridgeStatus;
   writeBridgeStatus(root,{enabled:false,reason:'shared_startup_failed',detail:reason});
  }catch{}
  if(stopping)process.exitCode=0;
  else if(traffic){console.error('Shared Desktop connection ended after traffic; requests were not replayed.');process.exitCode=1}
  else{console.error(`WeChat sharing unavailable (${reason}); continuing with official native startup.`);process.exitCode=await nativeStartup()}
 }
}
