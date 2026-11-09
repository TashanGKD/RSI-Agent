import type {Task,Employee} from '../model';
export type Phase='unknown'|'todo'|'active'|'waiting'|'done'|'paused';
export type TimeFact={at:number;precision:'day'|'minute'|'second';raw:string};
export type RecordNode={key:string;at:number;precision:TimeFact['precision'];rawTime:string;label:string;text:string;sourceId:string;observation:boolean};
export type VisualItem={task:Task;events:RecordNode[];first:number|null;last:number|null;phase:Phase};
export type ViewProps={items:VisualItem[];employees:Employee[];onSelect:(task:Task)=>void;motion:boolean;playhead:number|null;scope?:string};
export const PHASES:{id:Phase;label:string;short:string}[]=[{id:'unknown',label:'待明确',short:'?'},{id:'todo',label:'待推进',short:'○'},{id:'active',label:'进行中',short:'↗'},{id:'waiting',label:'等反馈',short:'◷'},{id:'done',label:'已闭环',short:'✓'},{id:'paused',label:'暂缓',short:'Ⅱ'}];
export const closed=(s:string)=>['已完成','已交付','已办好','不做了','不用管了','已结束'].includes(s);
export function phaseOf(state:string):Phase{if(closed(state))return 'done';if(['先放放','暂缓'].includes(state))return 'paused';if(['等反馈','等对方'].includes(state))return 'waiting';if(state==='进行中')return 'active';if(['待推进','待处理','待办'].includes(state))return 'todo';return 'unknown'}
export function parseRecordTime(raw:string):TimeFact|null{
 const s=raw.trim();const m=s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,6})?)?(Z|[+-]\d{2}:\d{2})?)?$/);if(!m)return null;
 const [y,mo,d,h,mi,se]=[+m[1],+m[2],+m[3],+(m[4]||0),+(m[5]||0),+(m[6]||0)];const check=new Date(Date.UTC(y,mo-1,d));
 if(y<1900||mo<1||mo>12||d<1||check.getUTCDate()!==d||check.getUTCMonth()!==mo-1||h>23||mi>59||se>59)return null;
 let at:number;if(m[7])at=Date.parse(s.replace(' ','T'));else at=Date.UTC(y,mo-1,d,h-8,mi,se);
 return Number.isFinite(at)?{at,precision:!m[4]?'day':m[6]?'second':'minute',raw}:null;
}
export const formatTime=(at:number,dayOnly=false)=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',...(dayOnly?{}:{hour:'2-digit',minute:'2-digit',hour12:false})}).format(new Date(at));
export function taskEvents(task:Task):RecordNode[]{
 const out=new Map<string,RecordNode>();
 for(const e of task.trajectory||[]){
  let raw=e.time;const range=raw.match(/^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})至\d{2}:\d{2}:\d{2}$/);if(range)raw=range[1];
  const f=parseRecordTime(raw);if(!f||!e.source_id)continue;const observation=/笔记当前摘要更新|观察到|采集时刻/.test(e.event);
  const label=observation?'笔记更新':/已交付|交付闭环|发送成功|成功回执|已办好/.test(e.event)?'交付记录':/接到.*(?:任务|要求|交办)|收到.*(?:要求|交办)/.test(e.event)?'收到要求':'进展记录';
  const key=[e.source_id,e.time,e.event].join('|');out.set(key,{key,at:f.at,precision:f.precision,rawTime:e.time,label,text:e.event,sourceId:e.source_id,observation});
 }
 return [...out.values()].sort((a,b)=>a.at-b.at||a.key.localeCompare(b.key));
}
export const visibleRecords=(tasks:Task[])=>tasks.filter(t=>t.kind!=='history');
export function visualItems(tasks:Task[]):VisualItem[]{return visibleRecords(tasks).map(task=>{const events=taskEvents(task);return {task,events,first:events[0]?.at??null,last:events.at(-1)?.at??null,phase:phaseOf(task.state)}})}
const importance:Record<Phase,number>={active:0,todo:1,unknown:2,waiting:3,paused:5,done:4};
export function sortItems(items:VisualItem[]){return [...items].sort((a,b)=>importance[a.phase]-importance[b.phase]||(b.last??0)-(a.last??0)||a.task.title.localeCompare(b.task.title))}
export function featuredTasks(tasks:Task[],limit:number){const sorted=sortItems(visualItems(tasks));if(!Number.isFinite(limit)||sorted.length<=limit)return sorted.map(x=>x.task);const preview=sorted.slice(0,limit);const done=sorted.find(x=>x.phase==='done');if(done&&!preview.some(x=>x.phase==='done')&&limit>2)preview[preview.length-1]=done;return preview.map(x=>x.task)}
export function explicitRelations(tasks:Task[]):{from:string;to:string}[]{
 const ids=new Set(tasks.map(t=>t.id));const out=new Map<string,{from:string;to:string}>();
 for(const t of tasks){const raw=t as Task&{parentId?:string;relatedTaskIds?:string[]};const mentioned=[...(raw.relatedTaskIds||[]),...(raw.parentId?[raw.parentId]:[])];
  const m=(t.origin||'').match(/关联原事项[：:]\s*([^\s，。；;]+)/);if(m)mentioned.push(m[1]);
  for(const from of mentioned)if(ids.has(from)&&from!==t.id)out.set(from+'|'+t.id,{from,to:t.id});
 }
 return [...out.values()];
}
export function timeBounds(tasks:Task[],now:number,days:number){const dates=tasks.flatMap(t=>taskEvents(t).map(e=>e.at)).filter(n=>n<=now);const start=days?now-days*86400000:dates.length?Math.min(...dates):now-3*86400000;return {start:Math.min(start,now-3600000),end:now}}
export function eventSample(events:RecordNode[],count=5){if(events.length<=count)return events;return Array.from({length:count},(_,i)=>events[Math.round(i*(events.length-1)/(count-1))])}
export const phaseLabel=(p:Phase)=>PHASES.find(x=>x.id===p)?.label||'待明确';
