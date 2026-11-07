import test from 'node:test';import assert from 'node:assert/strict';
import {isDone,filterWork,sendVisible} from '../src/work/model.ts';
test('candidate membership and progress are independent; closed items remain queryable',()=>{
 const rows=[{id:'a',employee:'forum',title:'task',origin:'',goal:'',next:'',state:'待推进',commitment:'candidate'},{id:'b',employee:'forum',title:'done',origin:'',goal:'',next:'',state:'已办好'}];
 assert.deepEqual(filterWork(rows,'forum','','open').map(x=>x.id),['a']);assert.equal(filterWork(rows,'all','','closed')[0].id,'b');assert.equal(isDone('等反馈'),false);
});
test('consumed input and unknown send result are not presented as known un-sent; history stays accessible',()=>{
 const unknown={state:'unknown',phase:'unknown'},active={state:'unknown',phase:'processing'},sent={state:'sent',phase:'unknown'};
 assert.equal(sendVisible(unknown,'current'),false);assert.equal(sendVisible(unknown,'unknown'),true);assert.equal(sendVisible(active,'current'),true);assert.equal(sendVisible(sent,'current'),false);assert.equal(sendVisible(sent,'sent'),true);
});
test('failed current component stays visible without a central input; resolved remains history',()=>{
 assert.equal(sendVisible({state:'failed',phase:'unknown',deliveryStatus:'blocked'},'current'),true);
 assert.equal(sendVisible({state:'failed',phase:'unknown',deliveryStatus:'blocked'},'undelivered'),true);
 assert.equal(sendVisible({state:'sent',phase:'unknown',deliveryStatus:'resolved'},'undelivered'),false);
});
test('known unsent business deferral is distinct from active send and missing receipt',()=>{
 const deferred={state:'pending',phase:'unknown',deliveryStatus:'pending',deliveryReason:'business_deferred_unsent'};
 assert.equal(sendVisible(deferred,'current'),false);assert.equal(sendVisible(deferred,'deferred'),true);assert.equal(sendVisible(deferred,'undelivered'),true);assert.equal(sendVisible(deferred,'unknown'),false);
});
