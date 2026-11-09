import test from 'node:test';import assert from 'node:assert/strict';
import {sortInputs,sortSending,sortNotebook,inboxSampleWindow} from '../src/work/model.ts';
test('the visible sample age remains the original read time, not page refresh time',()=>{
 const sample=Date.parse('2026-10-31T14:47:14Z'),now=Date.parse('2026-10-31T14:49:00Z');
 const x=inboxSampleWindow([{inbox:{sampledAt:'2026-10-31T14:47:14Z'}}],now);
 assert.equal(x.first,sample);assert.equal(x.ageSeconds,106);assert.deepEqual(inboxSampleWindow([{}],now),{first:null,last:null,ageSeconds:null});
});
test('native per-employee order is preserved independently of submission timestamps',()=>{
 const rows=[{id:'b',employee:'a',queuePosition:2,receivedAtMs:2000},{id:'a',employee:'a',queuePosition:1,receivedAtMs:3000}];
 assert.deepEqual(sortInputs(rows,'execution').map(x=>x.id),['a','b']);assert.deepEqual(sortInputs(rows,'oldest').map(x=>x.id),['b','a']);assert.equal(rows[0].id,'b');
});
test('sender processing precedes queued items; queue positions are not replaced by date sorting',()=>{
 const rows=[{id:'b',phase:'queued',queuePosition:2,receivedAtMs:100},{id:'a',phase:'queued',queuePosition:1,receivedAtMs:200},{id:'run',phase:'processing',receivedAtMs:300}];
 assert.deepEqual(sortSending(rows,'execution').map(x=>x.id),['run','a','b']);assert.deepEqual(sortSending(rows,'newest').map(x=>x.id),['run','a','b']);
});
test('notebook ordering uses update time, not an invented proposed or deadline time',()=>{
 const rows=[{id:'old',state:'等反馈',recordUpdatedAt:'2026-10-30 20:00:00'},{id:'new',state:'进行中',recordUpdatedAt:'2026-10-31 20:00:00'}];
 assert.deepEqual(sortNotebook(rows,'newest').map(x=>x.id),['new','old']);assert.deepEqual(sortNotebook(rows,'oldest').map(x=>x.id),['old','new']);
});
