import {useState} from 'react';
import {eventSample,featuredTasks,formatTime,type ViewProps} from './model';
import {Avatar,Status,More} from './shared';
export function OrbitView({items,employees,onSelect,motion,playhead}:ViewProps){
 const [expanded,setExpanded]=useState<string[]>([]);
 return <section className={`orbit-view ${motion?'has-motion':''}`} aria-label="动态轨道图"><div className="orbit-heading"><div><span className="v-kicker">WORK IN MOTION</span><h2>工作正在发生<span className="live-spark"/></h2></div><span>按记录先后排列 · 间距不代表工时</span></div>
 {employees.map(e=>{const all=items.filter(x=>x.task.employee===e.id);if(!all.length)return null;const ids=new Set(featuredTasks(all.map(x=>x.task),expanded.includes(e.id)?Infinity:2).map(t=>t.id));const rows=all.filter(x=>ids.has(x.task.id));return <article className="orbit-employee" key={e.id}><header className="orbit-person"><Avatar employee={e}/><div><h3>{e.name}</h3><span>{e.runtime} · {all.length} 项</span></div></header><div className="orbit-tracks">{rows.map(item=>{const es=eventSample(item.events,5);const active=item.phase==='active';return <div className={`orbit-track phase-${item.phase}`} data-task-id={item.task.id} key={item.task.id}>
 <div className="orbit-track-title"><button onClick={()=>onSelect(item.task)} title={item.task.title}>{item.task.title}</button><Status task={item.task}/></div>
 <div className="orbit-route"><svg viewBox="0 0 800 52" preserveAspectRatio="none" aria-hidden><path className="route-base" d="M 20 27 C 190 10, 280 46, 405 28 S 650 15, 775 27"/>{active&&<path className="route-flow" d="M 20 27 C 190 10, 280 46, 405 28 S 650 15, 775 27"/>}</svg>
 {es.length?es.map((n,i)=><button key={n.key} className={`orbit-stop ${n.observation?'observation':''} ${i===es.length-1?'latest':''} ${playhead!==null&&n.at<=playhead?'record-lit':''}`} style={{left:`${es.length===1?48:3+i/(es.length-1)*92}%`}} onClick={()=>onSelect(item.task)} aria-label={`${item.task.title}，${n.label}，${n.rawTime}`} title={n.rawTime+'\n'+n.text}><i/>{i===es.length-1&&item.phase==='done'&&<b aria-hidden>✓</b>}<time>{formatTime(n.at,n.precision==='day')}</time></button>):<button className="orbit-undated" onClick={()=>onSelect(item.task)}>◌ 尚无可定位日期的节点</button>}
 </div><div className="orbit-track-meta"><span>{item.events.length?`${item.events.length} 个日期节点${item.events.length>5?' · 图示首尾与中间代表节点':''}`:'原记录未给时间，不推断起止'}</span><button onClick={()=>onSelect(item.task)}>轨迹与依据 ↗</button></div>
 </div>})}<More limit={2} count={all.length} expanded={expanded.includes(e.id)} onClick={()=>setExpanded(x=>x.includes(e.id)?x.filter(v=>v!==e.id):[...x,e.id])}/></div></article>})}
 </section>
}
