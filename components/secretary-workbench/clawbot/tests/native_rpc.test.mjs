import test from 'node:test';import assert from 'node:assert/strict';
import {marker,matchesInput,finalReply} from '../bridge/native_rpc.mjs';
test('matches only exact public user input identity',()=>{
 const id='weixin-'+ 'a'.repeat(64);
 assert.equal(matchesInput([{type:'agentMessage',text:marker(id)}],id),false);
 assert.equal(matchesInput([{type:'userMessage',content:[{type:'text',text:marker(id)+'\nhello'}]}],id),true);
 assert.equal(matchesInput([{type:'userMessage',content:[{type:'text',text:'quote '+marker(id)}]}],id),false);
});
test('only final assistant answer leaves native context',()=>{
 assert.equal(finalReply([{type:'reasoning',text:'secret'},{type:'agentMessage',phase:'commentary',text:'working'},{type:'agentMessage',phase:'final_answer',text:'done'}]),'done');
});
test('native ThreadItemEntry envelopes preserve user correlation and final text',()=>{
 const id='weixin-'+ 'c'.repeat(64);
 assert.equal(matchesInput([{turnId:'t',item:{type:'userMessage',id,content:[]}}],id),true);
 assert.equal(finalReply([{turnId:'t',item:{type:'agentMessage',phase:'final_answer',text:'verified'}}]),'verified');
});
