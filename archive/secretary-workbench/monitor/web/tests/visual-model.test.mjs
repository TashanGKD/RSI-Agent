import test from 'node:test';import assert from 'node:assert/strict';
import {parseRecordTime,taskEvents,phaseOf,explicitRelations,featuredTasks,timeBounds,closed,visibleRecords} from '../src/visual/model.ts';
const t=(id,rest={})=>({id,employee:'science',title:id,state:'待推进',trajectory:[],evidence:[],kind:'workstream',time:'',...rest});
test('recorded time uses Beijing timezone and rejects invented dates and due phrases',()=>{
 assert.equal(parseRecordTime('2026-10-30 09:20:00').at,Date.parse('2026-10-30T01:20:00Z'));
 assert.equal(parseRecordTime('2026-10-30T09:20:00+08:00').at,Date.parse('2026-10-30T01:20:00Z'));
 assert.equal(parseRecordTime('2026-10-30').precision,'day');
 for(const x of ['未知','10月30日','截止2026-10-31','明天08:00','2026-02-30','2026-10-30 26:00:00'])assert.equal(parseRecordTime(x),null,x);
});
test('events preserve provenance, remove exact repeats and do not use task time as start',()=>{
 const a=t('a',{time:'下一轮北京时间2026-10-31 08:00。',trajectory:[{time:'2026-10-30 12:00',event:'第一次进展',source_id:'s'},{time:'2026-10-30 12:00',event:'第一次进展',source_id:'s'},{time:'未知',event:'待判断',source_id:'s'}]});
 const es=taskEvents(a);assert.equal(es.length,1);assert.equal(es[0].sourceId,'s');assert.equal(taskEvents(t('b',{time:'2026-10-01'})).length,0);
});
test('relations require explicit valid task IDs, never shared evidence or title similarity',()=>{
 const a=t('a'),b=t('b',{evidence:[{id:'same',quote:'共同资料'}]}),c=t('c',{origin:'关联原事项：a'});
 const rs=explicitRelations([a,b,c]);assert.deepEqual(rs,[{from:'a',to:'c'}]);
});
test('phase reflects actual recorded state and unknown remains undecided',()=>{
 assert.equal(phaseOf('等反馈'),'waiting');assert.equal(phaseOf('先放放'),'paused');assert.equal(phaseOf('已办好'),'done');assert.equal(phaseOf('进行中'),'active');assert.equal(phaseOf('未来状态'),'unknown');assert.equal(closed('不用管了'),true);
});
test('featured rows are only a reversible preview; all rows remain reachable',()=>{
 const rows=Array.from({length:12},(_,i)=>t('t'+i));assert.equal(featuredTasks(rows,5).length,5);assert.equal(featuredTasks(rows,Infinity).length,12);
 assert.equal(visibleRecords([...rows,t('h',{kind:'history'})]).length,12);
});
test('time range excludes unknowns, has a stable fallback and no zero-span axis',()=>{
 const now=Date.parse('2026-10-30T12:00:00Z');const b=timeBounds([t('a')],now,3);assert.ok(b.end>b.start);assert.ok(Number.isFinite(b.start));assert.equal(b.end,now);
});
