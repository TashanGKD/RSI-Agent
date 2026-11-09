import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import * as state from '../bridge/desktop_owned_state.mjs';
const {resolveOwnedDesktopState}=state;

const cli='/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex';
const uid=process.getuid();

function fixture(){
 const root=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'wx-desk-'));
 fs.chmodSync(root,0o700);
 return {root,socketPath:path.join(root,'control.sock'),clean(){fs.rmSync(root,{recursive:true,force:true})}};
}

function writeMeta(root,enginePid){
 fs.writeFileSync(path.join(root,'engine.json'),JSON.stringify({version:1,enginePid}),{mode:0o600});
}

async function listen(socketPath){
 const server=net.createServer();
 await new Promise((resolve,reject)=>{server.once('error',reject);server.listen(socketPath,resolve);});
 return server;
}

test('dangling native socket plus dead engine metadata is stale and can start',async()=>{
 const f=fixture();
 try{
  writeMeta(f.root,16397);
  fs.symlinkSync(`/private/tmp/codex-daemon-${uid}/${'0'.repeat(64)}`,f.socketPath);
  const result=await resolveOwnedDesktopState({root:f.root,socketPath:f.socketPath,cli,uid,kill:()=>{throw Object.assign(new Error('ESRCH'),{code:'ESRCH'})},commandOf:()=>null,connect:async()=>false});
  assert.equal(result.action,'start');
  assert.equal(fs.existsSync(path.join(f.root,'engine.json')),false);
  assert.throws(()=>fs.lstatSync(f.socketPath),{code:'ENOENT'});
 }finally{f.clean()}
});

test('a live native engine with a usable socket is reused, not replaced',async()=>{
 const f=fixture();
 const server=await listen(f.socketPath);
 try{
  writeMeta(f.root,process.pid);
  const result=await Promise.resolve(resolveOwnedDesktopState({
   root:f.root,socketPath:f.socketPath,cli,uid,
   kill:pid=>{if(pid!==process.pid)throw Object.assign(new Error('ESRCH'),{code:'ESRCH'});},
   commandOf:pid=>pid===process.pid?`${cli} app-server --listen unix://${f.socketPath}`:null,
   connect:async()=>true,
  }));
  assert.equal(result.action,'reuse');
  assert.equal(result.enginePid,process.pid);
  assert.equal(fs.existsSync(path.join(f.root,'engine.json')),true);
  assert.ok(fs.existsSync(f.socketPath));
 }finally{server.close();f.clean()}
});

test('a live native engine without a usable socket still requires review',async()=>{
 const f=fixture();
 try{
  writeMeta(f.root,process.pid);
  await assert.rejects(()=>resolveOwnedDesktopState({
   root:f.root,socketPath:f.socketPath,cli,uid,
   kill:pid=>{if(pid!==process.pid)throw Object.assign(new Error('ESRCH'),{code:'ESRCH'});},
   commandOf:()=>`${cli} app-server`,
   connect:async()=>false,
  }),/existing native engine is running without a usable socket/);
  assert.equal(fs.existsSync(path.join(f.root,'engine.json')),true);
 }finally{f.clean()}
});

test('an unmanaged live socket is never taken over',async()=>{
 const f=fixture();
 const server=await listen(f.socketPath);
 try{
  await assert.rejects(()=>resolveOwnedDesktopState({
   root:f.root,socketPath:f.socketPath,cli,uid,
   kill:()=>{throw Object.assign(new Error('ESRCH'),{code:'ESRCH'});},
   commandOf:()=>null,
   connect:async()=>true,
  }),/existing shared native socket requires review/);
  assert.ok(fs.existsSync(f.socketPath));
 }finally{server.close();f.clean()}
});

test('unknown live socket refusal preserves stale metadata for recovery',async()=>{
 const f=fixture();const server=await listen(f.socketPath);
 try{
  writeMeta(f.root,16397);const before=fs.readFileSync(path.join(f.root,'engine.json'));
  await assert.rejects(()=>resolveOwnedDesktopState({root:f.root,socketPath:f.socketPath,cli,uid,
   kill:()=>{throw Error('dead')},commandOf:()=>null,connect:async()=>true}),/requires review/);
  assert.deepEqual(fs.readFileSync(path.join(f.root,'engine.json')),before);
 }finally{server.close();f.clean()}
});

test('metadata symlink is rejected without removing either target or socket',async()=>{
 const f=fixture();
 try{
  const outside=path.join(f.root,'other.json');fs.writeFileSync(outside,'private',{mode:0o600});
  fs.symlinkSync(outside,path.join(f.root,'engine.json'));
  await assert.rejects(()=>resolveOwnedDesktopState({root:f.root,socketPath:f.socketPath,cli,uid,connect:async()=>false}),/metadata|private/);
  assert.equal(fs.readFileSync(outside,'utf8'),'private');
  assert.ok(fs.lstatSync(path.join(f.root,'engine.json')).isSymbolicLink());
 }finally{f.clean()}
});

test('unknown socket symlink outside native namespace is not deleted',async()=>{
 const f=fixture();
 try{
  const outside=path.join(f.root,'keep');fs.writeFileSync(outside,'keep',{mode:0o600});
  fs.symlinkSync(outside,f.socketPath);
  await assert.rejects(()=>resolveOwnedDesktopState({root:f.root,socketPath:f.socketPath,cli,uid,connect:async()=>false}),/socket|namespace/);
  assert.equal(fs.readFileSync(outside,'utf8'),'keep');assert.ok(fs.lstatSync(f.socketPath).isSymbolicLink());
 }finally{f.clean()}
});

test('live engine from another Desktop pipe is refused without killing it',async()=>{
 const f=fixture();
 try{
  writeMeta(f.root,process.pid);
  const before=fs.readFileSync(path.join(f.root,'engine.json'));
  await assert.rejects(()=>resolveOwnedDesktopState({root:f.root,socketPath:f.socketPath,cli,uid,
   kill:()=>{},commandOf:()=>`${cli} app-server`,connect:async()=>true,appToolsPipeHash:'new-session'}),/Desktop session/);
  assert.deepEqual(fs.readFileSync(path.join(f.root,'engine.json')),before);
 }finally{f.clean()}
});

test('startup election rejects invalid identity, symlink and a foreign database',async()=>{
 assert.equal(typeof state.acquireDesktopStartup,'function');
 const hash='a'.repeat(64);const f=fixture();const lock=path.join(f.root,'.startup.sqlite');
 try{
  await assert.rejects(()=>state.acquireDesktopStartup(f.root,'../../outside'),/identity/);
  const keep=path.join(f.root,'keep');fs.writeFileSync(keep,'keep',{mode:0o600});fs.symlinkSync(keep,lock);
  await assert.rejects(()=>state.acquireDesktopStartup(f.root,hash),/lock/);assert.equal(fs.readFileSync(keep,'utf8'),'keep');fs.unlinkSync(lock);
  fs.writeFileSync(lock,'foreign content',{mode:0o600});
  await assert.rejects(()=>state.acquireDesktopStartup(f.root,hash));assert.equal(fs.readFileSync(lock,'utf8'),'foreign content');
 }finally{f.clean()}
});

test('concurrent startup election waits for the current owner and releases exact file',async()=>{
 assert.equal(typeof state.acquireDesktopStartup,'function');const f=fixture();const hash='b'.repeat(64);
 try{
  const first=await state.acquireDesktopStartup(f.root,hash);let acquired=false;
  const pending=state.acquireDesktopStartup(f.root,'c'.repeat(64)).then(release=>{acquired=true;return release});
  await new Promise(r=>setTimeout(r,60));assert.equal(acquired,false);first();
  const second=await pending;assert.equal(acquired,true);second();
  const third=await state.acquireDesktopStartup(f.root,hash);third();
 }finally{f.clean()}
});

test('kernel startup lock is released after an ungraceful owner exit',{timeout:5000},async()=>{
 const f=fixture();let child;
 try{
  const code=`import {acquireDesktopStartup} from ${JSON.stringify(new URL('../bridge/desktop_owned_state.mjs',import.meta.url).href)};await acquireDesktopStartup(process.argv[1],'d'.repeat(64));console.log('ready');setInterval(()=>{},1000);`;
  child=spawn(process.execPath,['--input-type=module','-e',code,f.root],{stdio:['ignore','pipe','pipe']});
  child.stderr.resume();await once(child.stdout,'data');const exited=once(child,'exit');child.kill('SIGKILL');await exited;
  const release=await state.acquireDesktopStartup(f.root,'e'.repeat(64));release();
 }finally{if(child&&child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');f.clean()}
});
