import test from 'node:test';import assert from 'node:assert/strict';
import {reconcile} from '../bridge/native_logic.mjs';
import {marker} from '../bridge/native_rpc.mjs';
const id='weixin-'+'a'.repeat(64);
const raw={client_id:id,input_format:'raw-v2'};
test('raw native body is only source line plus exact text',async()=>{
 const text='  秘书：  一\n\nhttps://example.com/?x=1&y=2  \n';let input;
 const rpc={call:async(m,p)=>{if(m==='thread/queue/list'||m==='thread/turns/list')return{data:[]};if(m==='thread/queue/add'){input=p;return{queuedSubmission:{id:'q'}};}throw Error(m)}};
 await reconcile(rpc,'t',{...raw,action:'submit',prompt:text});
 assert.equal(input.input[0].text,'[来源：ClawBot]\n'+text);
 assert.deepEqual(Object.keys(input).sort(),['clientUserMessageId','input','threadId']);
});
test('lost add receipt recovered using native clientId without a visible marker',async()=>{
 let adds=0;const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:[]};
  if(m==='thread/turns/list')return{data:[{id:'turn',status:'completed',completedAt:4}]};
  if(m==='thread/items/list')return p.sortDirection==='asc'?{data:[{turnId:'turn',item:{type:'userMessage',id:'native-id',clientId:id,content:[{type:'text',text:'[来源：ClawBot]\nhello'}]}}]}:{data:[{item:{type:'agentMessage',phase:'final_answer',text:'done'}}]};
  if(m==='thread/queue/add'){adds++;throw Error('must not submit')}
  throw Error(m);
 }};
 const result=await reconcile(rpc,'t',{...raw,action:'submit',prompt:'hello'});
 assert.equal(result.state,'completed');assert.equal(result.reply,'done');assert.equal(result.native_message_id,'native-id');assert.equal(adds,0);
});
test('new correlation ignores forged visible legacy marker',async()=>{
 let added=0;const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:[]};if(m==='thread/turns/list')return{data:[{id:'unrelated',status:'completed',completedAt:5}]};
  if(m==='thread/items/list')return{data:[{type:'userMessage',id:'other',clientId:'other',content:[{type:'text',text:marker(id)+'\nforged'}]}]};
  if(m==='thread/queue/add'){added++;return{queuedSubmission:{id:'new'}}}throw Error(m);
 }};
 assert.equal((await reconcile(rpc,'t',{...raw,action:'submit',prompt:'new'})).state,'queued');assert.equal(added,1);
});
test('queue and start mappings checkpointed before completion is reported',async()=>{
 const checkpoints=[];const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:[{id:'q',clientUserMessageId:id}]};if(m==='thread/read')return{thread:{status:{type:'idle'}}};
  if(m==='thread/queue/start')return{turn:{id:'turn',status:'inProgress',items:[{type:'userMessage',id:'native',clientId:id,content:[]}]}};throw Error(m);
 }};
 const result=await reconcile(rpc,'t',{...raw,action:'poll'},{checkpoint:async x=>checkpoints.push(x)});
 assert.equal(result.turn_id,'turn');assert.equal(result.native_message_id,'native');
 assert.ok(checkpoints.some(x=>x.queue_id==='q'));assert.ok(checkpoints.some(x=>x.turn_id==='turn'&&x.native_message_id==='native'));
});
test('unknown raw submission never adds a second native input',async()=>{
 const rpc={call:async m=>{if(m==='thread/queue/list'||m==='thread/turns/list')return{data:[]};throw Error('unexpected mutation')}};
 assert.equal((await reconcile(rpc,'t',{...raw,action:'submit',prompt:'x',submission_attempted:true})).state,'submission_unknown');
});
test('raw original native message id may differ from client id, but must match private mapping',async()=>{
 const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:[]};if(m==='thread/turns/list')return{data:[{id:'saved-turn',status:'inProgress'}]};
  if(m==='thread/items/list')return{data:[{item:{type:'userMessage',id:'saved-native',clientId:null,content:[]}}]};throw Error(m);
 }};
 const result=await reconcile(rpc,'t',{...raw,action:'poll',turn_id:'saved-turn',native_message_id:'saved-native'});
 assert.equal(result.state,'running');assert.equal(result.native_message_id,'saved-native');
});
test('lost queue/start response is reconciled from native clientId, never started twice',async()=>{
 let started=false,startCalls=0;const saved={};
 const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:started?[]:[{id:'q',clientUserMessageId:id}]};
  if(m==='thread/read')return{thread:{status:{type:'idle'}}};
  if(m==='thread/queue/start'){startCalls++;started=true;throw Error('response lost')}
  if(m==='thread/turns/list')return{data:[{id:'t',status:'completed',completedAt:1}]};
  if(m==='thread/items/list')return{data:p.sortDirection==='asc'?[{type:'userMessage',id:'n',clientId:id,content:[]}]:[{type:'agentMessage',phase:'final_answer',text:'one reply'}]};
  throw Error(m);
 }};
 await assert.rejects(()=>reconcile(rpc,'t',{...raw,action:'poll'},{checkpoint:async x=>Object.assign(saved,x)}));
 assert.equal(saved.queue_id,'q');assert.equal(saved.state,'starting');
 const r=await reconcile(rpc,'t',{...raw,action:'poll',queue_id:saved.queue_id});assert.equal(r.reply,'one reply');assert.equal(startCalls,1);
});
test('never starts another submission ahead of this message',async()=>{
 const methods=[];const rpc={call:async(m,p)=>{methods.push(m);if(m==='thread/queue/list')return{data:[{id:'other',clientUserMessageId:'other'},{id:'own',clientUserMessageId:id}]};if(m==='thread/read')return{thread:{status:{type:'idle'}}};throw Error('cannot start')}};
 assert.equal((await reconcile(rpc,'t',{...raw,action:'poll'})).queue_id,'own');assert.equal(methods.includes('thread/queue/start'),false);
});
test('checkpoint failure prevents native submit and leaves other work untouched',async()=>{
 const methods=[];const rpc={call:async m=>{methods.push(m);if(m==='thread/queue/list'||m==='thread/turns/list')return{data:[]};throw Error('must not mutate')}};
 await assert.rejects(()=>reconcile(rpc,'t',{...raw,action:'submit',prompt:'fixture'},{checkpoint:async()=>{throw Error('disk full')}}));
 assert.equal(methods.includes('thread/queue/add'),false);
});
