import test from 'node:test';
import assert from 'node:assert/strict';
import {scanVisible,findVisibleSource} from '../bridge/native_visible.mjs';

function rpc(turns,byTurn){return {calls:[],async call(m,p){this.calls.push(m);if(m==='thread/turns/list')return {data:turns};if(m==='thread/items/list')return {data:byTurn[p.turnId]||[]};throw Error('unexpected mutation '+m);}};}
const final=(id,text)=>({type:'agentMessage',id,phase:'final_answer',text});
test('initial scan starts at present without replaying old replies',async()=>{
 const r=rpc([{id:'busy',status:'inProgress'},{id:'old',status:'completed'}],{});
 assert.deepEqual(await scanVisible(r,'main',null),{state:'initialized',after_turn_id:'old',turns:[]});
});
test('desktop final is synchronized, not commentary or tools',async()=>{
 const r=rpc([{id:'new',status:'completed'},{id:'old',status:'completed'}],{new:[{type:'reasoning',text:'hidden'},{type:'agentMessage',id:'c',phase:'commentary',text:'working'},final('f','done')]});
 const out=await scanVisible(r,'main','old');assert.equal(out.turns[0].reply,'done');assert.equal(out.after_turn_id,'new');assert.deepEqual(out.turns[0].item_ids,['f']);
});
test('ClawBot client identity is retained for existing outbox deduplication',async()=>{
 const client='weixin-'+'a'.repeat(64);const r=rpc([{id:'new',status:'completed'},{id:'old',status:'completed'}],{new:[{type:'userMessage',clientId:client},final('f','same')]});
 assert.equal((await scanVisible(r,'main','old')).turns[0].client_id,client);
});
test('unfinished turn does not advance the checkpoint',async()=>{
 const r=rpc([{id:'busy',status:'inProgress'},{id:'new',status:'completed'},{id:'old',status:'completed'}],{new:[final('f','done')]});
 assert.equal((await scanVisible(r,'main','old')).after_turn_id,'new');
});
test('missing cursor refuses to skip history',async()=>{
 await assert.rejects(()=>scanVisible(rpc([{id:'new',status:'completed'}],{}),'main','missing'),/incomplete/);
});
test('partial item list cannot commit a truncated reply',async()=>{
 const r=rpc([{id:'new',status:'completed'},{id:'old',status:'completed'}],{});r.call=async m=>m==='thread/turns/list'?{data:[{id:'new',status:'completed'},{id:'old',status:'completed'}]}:{data:[final('f','part')],nextCursor:'more'};
 await assert.rejects(()=>scanVisible(r,'main','old'),/incomplete/);
});
test('proactive text needs actual assistant text, not a user quotation',async()=>{
 const r=rpc([{id:'t',status:'inProgress'}],{t:[{type:'userMessage',text:'notice'}, {type:'agentMessage',id:'c',phase:'commentary',text:'notice'}]});
 assert.deepEqual(await findVisibleSource(r,'main','notice'),{turn_id:'t',item_ids:['c']});
 assert.equal(await findVisibleSource(r,'main','unseen'),null);
});
