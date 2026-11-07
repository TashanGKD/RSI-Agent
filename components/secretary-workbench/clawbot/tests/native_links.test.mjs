import test from 'node:test';import assert from 'node:assert/strict';
import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import crypto from 'node:crypto';
import {NativeCorrelation} from '../bridge/native_links.mjs';
import {reconcile} from '../bridge/native_logic.mjs';
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
function fixture(){const root=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'wx-link-'));fs.chmodSync(root,0o700);return{root,req:{client_id:'weixin-'+hash('wx-id'),wx_message_id:'wx-id',input_format:'raw-v2'},clean(){fs.rmSync(root,{recursive:true,force:true})}}}
test('rejects wrong WX hash before persisting correlation',()=>{
 const f=fixture();try{assert.throws(()=>new NativeCorrelation(f.root,'t',{...f.req,wx_message_id:'other'}));assert.equal(fs.existsSync(path.join(f.root,'native-links')),false)}finally{f.clean()}
});
test('private mappings survive lost stdout and reject identity or payload changes',()=>{
 const f=fixture();try{
  let c=new NativeCorrelation(f.root,'t',f.req);c.save({state:'submitting',submission_attempted:true,input_hash:hash('input')});c.save({state:'queued',queue_id:'q'});
  c=new NativeCorrelation(f.root,'t',{...f.req,allow_new:true});assert.equal(c.request.allow_new,false);assert.equal(c.request.queue_id,'q');assert.equal(c.request.submission_attempted,true);
  assert.throws(()=>c.save({input_hash:hash('different')}));
  assert.throws(()=>new NativeCorrelation(f.root,'other-thread',f.req));
  const value=JSON.parse(fs.readFileSync(c.path));value.native_message_id='native';value.turn_id='turn';fs.writeFileSync(c.path,JSON.stringify(value));
  c=new NativeCorrelation(f.root,'t',f.req);assert.equal(c.request.native_message_id,'native');assert.equal(c.request.turn_id,'turn');
 }finally{f.clean()}
});
test('rejects symlink and world-readable private mapping',()=>{
 const f=fixture();try{
  const c=new NativeCorrelation(f.root,'t',f.req);fs.chmodSync(c.path,0o644);assert.throws(()=>new NativeCorrelation(f.root,'t',f.req));
  fs.unlinkSync(c.path);const outside=path.join(f.root,'outside');fs.writeFileSync(outside,'{}',{mode:0o600});fs.symlinkSync(outside,c.path);assert.throws(()=>new NativeCorrelation(f.root,'t',f.req));
 }finally{f.clean()}
});
test('rejects a dangling mapping symlink rather than replacing it',()=>{
 const f=fixture();try{
  const dir=path.join(f.root,'native-links');fs.mkdirSync(dir,{mode:0o700});const p=path.join(dir,f.req.client_id.slice(7)+'.json');fs.symlinkSync(path.join(f.root,'missing'),p);
  assert.throws(()=>new NativeCorrelation(f.root,'t',f.req));assert.equal(fs.lstatSync(p).isSymbolicLink(),true);
 }finally{f.clean()}
});
test('real private mapping recovers an accepted submission after lost result and restart',async()=>{
 const f=fixture();try{
  let accepted=false,adds=0,queued=true;
  const rpc={call:async(m,p)=>{
   if(m==='thread/queue/list')return{data:accepted&&queued?[{id:'queue',clientUserMessageId:f.req.client_id}]:[]};
   if(m==='thread/read')return{thread:{status:{type:'active'}}};
   if(m==='thread/turns/list')return{data:accepted?[{id:'turn',status:'completed',completedAt:1}]:[]};
   if(m==='thread/queue/add'){adds++;accepted=true;throw Error('result lost')}
   if(m==='thread/items/list')return{data:p.sortDirection==='asc'?[{type:'userMessage',id:'native-message',clientId:f.req.client_id,content:[]}]:[{type:'agentMessage',phase:'final_answer',text:'answer'}]};
   throw Error(m);
  }};
  let c=new NativeCorrelation(f.root,'t',f.req);
  await assert.rejects(()=>reconcile(rpc,'t',{...c.request,action:'submit',prompt:'fixture'},{checkpoint:x=>c.save(x)}));
  c=new NativeCorrelation(f.root,'t',{...f.req,allow_new:true});
  let result=await reconcile(rpc,'t',{...c.request,action:'poll'},{checkpoint:x=>c.save(x)});assert.equal(result.queue_id,'queue');
  queued=false;c=new NativeCorrelation(f.root,'t',f.req);
  result=await reconcile(rpc,'t',{...c.request,action:'poll'},{checkpoint:x=>c.save(x)});
  assert.equal(result.reply,'answer');assert.equal(adds,1);
  const saved=JSON.parse(fs.readFileSync(c.path));
  assert.equal(saved.wx_message_id,'wx-id');assert.equal(saved.queue_id,'queue');assert.equal(saved.turn_id,'turn');assert.equal(saved.native_message_id,'native-message');
 }finally{f.clean()}
});
