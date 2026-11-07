import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

function statusFile(root){
 const stat=fs.lstatSync(root);
 if(!stat.isDirectory()||stat.isSymbolicLink()||stat.uid!==process.getuid()||(stat.mode&0o077))throw Error('private bridge state directory required');
 return path.join(root,'bridge-state.json');
}
function readState(filename){
 let stat;
 try{stat=fs.lstatSync(filename)}catch(error){if(error.code==='ENOENT')return null;throw error}
 if(!stat.isFile()||stat.isSymbolicLink()||stat.uid!==process.getuid()||(stat.mode&0o077)||stat.nlink!==1||stat.size>4096)throw Error('unsafe private bridge state');
 const fd=fs.openSync(filename,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
 try{
  const current=fs.fstatSync(fd);
  if(current.ino!==stat.ino||current.dev!==stat.dev||current.size>4096)throw Error('bridge state changed');
  const state=JSON.parse(fs.readFileSync(fd,'utf8'));
  if(state?.version!==1||typeof state.enabled!=='boolean')throw Error('invalid bridge state');
  return state;
 }catch{throw Error('invalid private bridge state')}
 finally{fs.closeSync(fd)}
}
export function assertBridgeEnabled(root){
 const state=readState(statusFile(root));
 if(state?.enabled===false)throw Error('shared Desktop unavailable; bridge is waiting');
}
export function writeBridgeStatus(root,state){
 const filename=statusFile(root);readState(filename);
 if(typeof state.enabled!=='boolean')throw Error('invalid bridge state');
 const temporary=path.join(root,`.bridge-state-${crypto.randomUUID()}.tmp`);
 const fd=fs.openSync(temporary,'wx',0o600);
 try{fs.writeFileSync(fd,JSON.stringify({version:1,...state}));fs.fsyncSync(fd)}finally{fs.closeSync(fd)}
 try{fs.renameSync(temporary,filename)}finally{try{fs.unlinkSync(temporary)}catch(error){if(error.code!=='ENOENT')throw error}}
}
