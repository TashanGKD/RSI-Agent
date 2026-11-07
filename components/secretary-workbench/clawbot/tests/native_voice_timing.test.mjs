import test from 'node:test';import assert from 'node:assert/strict';
import {reconcile} from '../bridge/native_logic.mjs';
const identity={client_id:'weixin-'+'b'.repeat(64),input_format:'raw-v2',turn_id:'t',native_message_id:'n',action:'poll'};
test('native actual timestamps are returned, not polling wall time',async()=>{
 const rpc={call:async(m,p)=>{
  if(m==='thread/queue/list')return{data:[]};
  if(m==='thread/turns/list')return{data:[{id:'t',status:'completed',startedAt:101,completedAt:110}]};
  if(m==='thread/items/list')return{data:p.sortDirection==='asc'?[{type:'userMessage',id:'n',content:[]}]:[{type:'agentMessage',phase:'final_answer',text:'done'}]};
  throw Error(m);
 }};
 const r=await reconcile(rpc,'main',identity);
 assert.equal(r.native_started_at,101);assert.equal(r.native_completed_at,110);
});
test('unobserved native start remains unknown',async()=>{
 const rpc={call:async m=>m==='thread/queue/list'?{data:[]}:m==='thread/turns/list'?{data:[{id:'t',status:'inProgress'}]}:{data:[{type:'userMessage',id:'n',content:[]}]}};
 const r=await reconcile(rpc,'main',identity);assert.equal(r.native_started_at,null);
});
