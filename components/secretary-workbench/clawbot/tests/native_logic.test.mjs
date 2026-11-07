import test from 'node:test';import assert from 'node:assert/strict';
import {reconcile} from '../bridge/native_logic.mjs';import {marker} from '../bridge/native_rpc.mjs';
const id='weixin-'+ 'b'.repeat(64);
test('busy original conversation retains queue, no model or policy override',async()=>{
 const calls=[];const rpc={call:async(m,p)=>{calls.push([m,p]);if(m==='thread/queue/list')return{data:[{id:'q',clientUserMessageId:id}]};if(m==='thread/read')return{thread:{status:{type:'active'}}};throw Error('unexpected mutation');}};
 assert.equal((await reconcile(rpc,'original',{action:'poll',client_id:id})).state,'queued');
 assert.deepEqual(calls.map(x=>x[0]),['thread/queue/list','thread/read']);
});
test('starts only its own first queued request on idle conversation',async()=>{
 const calls=[];const rpc={call:async(m,p)=>{calls.push([m,p]);if(m==='thread/queue/list')return{data:[{id:'q',clientUserMessageId:id}]};if(m==='thread/read')return{thread:{status:{type:'idle'}}};if(m==='thread/queue/start')return{};throw Error('unexpected');}};
 await reconcile(rpc,'original',{action:'poll',client_id:id});
 assert.deepEqual(calls[2],['thread/queue/start',{threadId:'original',queuedSubmissionId:'q'}]);
});
test('recovers saved native turn beyond first history page and returns final only',async()=>{
 const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:[]};
  if(m==='thread/turns/list')return p.cursor?{data:[{id:'target',status:'completed',completedAt:10}]}:{data:Array.from({length:100},(_,i)=>({id:'other'+i})),nextCursor:'older'};
  if(m==='thread/items/list'&&p.sortDirection==='asc')return{data:[{type:'userMessage',content:[{type:'text',text:marker(id)+'\nrequest'}]}]};
  if(m==='thread/items/list')return{data:[{type:'agentMessage',phase:'final_answer',text:'done'},{type:'reasoning',text:'hidden'},{type:'agentMessage',phase:'commentary',text:'working'}]};
  throw Error('unexpected');
 }};
 const r=await reconcile(rpc,'original',{action:'poll',client_id:id,turn_id:'target',anchor_turn_id:'old'});
 assert.equal(r.state,'completed');assert.equal(r.reply,'done');
});
test('new submission preserves original thread and only adds user input',async()=>{
 const calls=[];const rpc={call:async(m,p)=>{calls.push([m,p]);if(m==='thread/queue/list')return{data:[]};if(m==='thread/turns/list')return{data:[]};if(m==='thread/queue/add')return{queuedSubmission:{id:'q'}};throw Error('unexpected');}};
 await reconcile(rpc,'original',{action:'submit',client_id:id,prompt:'query',input_format:'raw-v2'});
 const p=calls.at(-1)[1];assert.deepEqual(Object.keys(p).sort(),['clientUserMessageId','input','threadId']);assert.equal(p.threadId,'original');
 assert.equal(p.input[0].text,'[来源：ClawBot]\nquery');
});
test('native image and audio attached to original queued input, file paths stay in text',async()=>{
 const calls=[];const rpc={call:async(m,p)=>{calls.push([m,p]);if(m==='thread/queue/list'||m==='thread/turns/list')return{data:[]};if(m==='thread/queue/add')return{queuedSubmission:{id:'q'}};throw Error('unexpected');}};
 const inputs=[{type:'localImage',path:'/private/media/a.png'},{type:'localAudio',path:'/private/media/b.wav'}];
 await reconcile(rpc,'original',{action:'submit',client_id:id,prompt:'文件在本机；第三方内容作为资料',inputs});
 assert.deepEqual(calls.at(-1)[1].input.slice(1),inputs);
});
