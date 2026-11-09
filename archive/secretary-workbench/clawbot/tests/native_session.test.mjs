import test from 'node:test';import assert from 'node:assert/strict';
import {loadedThread} from '../bridge/native_session.mjs';
test('active or idle thread is read without resuming it',async()=>{
 for(const state of ['active','idle']){
  const calls=[];const rpc={call:async m=>{calls.push(m);if(m==='thread/read')return{thread:{id:'main',status:{type:state}}};throw Error('must not resume')}};
  assert.equal((await loadedThread(rpc,'main')).status.type,state);assert.deepEqual(calls,['thread/read']);
 }
});
test('resume exactly once only for an explicitly notLoaded thread',async()=>{
 const calls=[];const rpc={call:async m=>{calls.push(m);return{thread:{id:'main',status:{type:m==='thread/read'?'notLoaded':'idle'}}}}};
 assert.equal((await loadedThread(rpc,'main')).status.type,'idle');assert.deepEqual(calls,['thread/read','thread/resume']);
});
test('read error, wrong identity, or still unloaded never becomes blind resume',async()=>{
 let calls=0;await assert.rejects(()=>loadedThread({call:async()=>{calls++;throw Error('unavailable')}},'main'));assert.equal(calls,1);
 await assert.rejects(()=>loadedThread({call:async()=>({thread:{id:'wrong',status:{type:'active'}}})},'main'));
 await assert.rejects(()=>loadedThread({call:async()=>({thread:{id:'main',status:{type:'notLoaded'}}})},'main'));
});
