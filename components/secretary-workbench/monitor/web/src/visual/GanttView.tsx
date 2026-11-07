import {useState,useMemo,useRef,useEffect} from 'react';
import {featuredTasks,formatTime,timeBounds,eventSample,type ViewProps} from './model';
import {Avatar,Status,More} from './shared';
export function GanttView({items,employees,onSelect,playhead,now}:ViewProps&{now:number}){
 const [days,setDays]=useState(3),[zoom,setZoom]=useState(1),[offset,setOffset]=useState(0),[expanded,setExpanded]=useState<string[]>([]);
 const viewport=useRef<HTMLDivElement>(null);
 useEffect(()=>{const el=viewport.current;if(el)el.scrollLeft=el.scrollWidth-el.clientWidth},[days,zoom,offset]);
 const bounds=useMemo(()=>timeBounds(items.map(i=>i.task),now,days),[items,now,days]);const span=bounds.end-bounds.start;const start=bounds.start+offset*span,end=bounds.end+offset*span;const width=900*zoom;
 const x=(at:number)=>Math.max(0,Math.min(width,(at-start)/(end-start)*width));
 const dated=items.filter(i=>i.events.length);const undated=items.filter(i=>!i.events.length);
 return <section className="gantt-view" aria-label="时间甘特图"><div className="v-chart-tools"><div className="v-segment" aria-label="时间范围">{[[1,'24小时'],[3,'3天'],[7,'7天'],[0,'全部']].map(([v,l])=><button key={v} aria-pressed={days===v} onClick={()=>{setDays(Number(v));setOffset(0)}}>{l}</button>)}</div><div className="v-zoom-tools"><button aria-label="查看更早时间" onClick={()=>setOffset(x=>x-1)}>←</button><button onClick={()=>setOffset(0)}>最新</button><button aria-label="查看更晚时间" onClick={()=>setOffset(x=>Math.min(0,x+1))} disabled={offset>=0}>→</button><button aria-label="时间轴缩小" onClick={()=>setZoom(z=>Math.max(.75,z-.25))} disabled={zoom<=.75}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="时间轴放大" onClick={()=>setZoom(z=>Math.min(2,z+.25))} disabled={zoom>=2}>＋</button></div></div>
 <div ref={viewport} className="gantt-viewport" role="region" aria-label="时间轴，可左右及上下滚动" tabIndex={0}><div className="gantt-inner" style={{width:`calc(${width}px + var(--gantt-label-width))`}}><div className="gantt-axis"><div className="gantt-label">员工 / 事项</div><div className="gantt-scale" style={{width}}>{Array.from({length:7},(_,i)=><span key={i} style={{left:`${i/6*100}%`}}>{formatTime(start+(end-start)*i/6,span>86400000*2)}</span>)}</div></div>
 {employees.map(e=>{const all=dated.filter(t=>t.task.employee===e.id);if(!all.length)return null;const ids=new Set(featuredTasks(all.map(i=>i.task),expanded.includes(e.id)?Infinity:5).map(t=>t.id));return <div key={e.id} className="gantt-group"><header><Avatar employee={e}/><strong>{e.name}</strong><span>{all.length} 项有时间记录</span></header>{all.filter(i=>ids.has(i.task.id)).map(item=>{const points=item.events.filter(n=>n.at>=start&&n.at<=end);const left=x(item.first!),right=x(item.last!);return <div className="gantt-row" data-task-id={item.task.id} key={item.task.id}><div className="gantt-label"><button onClick={()=>onSelect(item.task)} title={item.task.title}>{item.task.title}</button><Status task={item.task}/></div><div className={`gantt-track phase-${item.phase}`} style={{width}}>
 {points.length>0&&<button className={`gantt-span ${item.first===item.last?'single-point':''}`} style={{left,width:Math.max(3,right-left)}} onClick={()=>onSelect(item.task)} title="首条至最近一条记录，不代表持续工作"><span/></button>}
 {!points.length&&<button className="gantt-no-points" onClick={()=>onSelect(item.task)}>本范围无日期节点 · 查看记录</button>}
 {eventSample(points,8).map(n=><button className={`gantt-point ${n.observation?'observation':''} ${playhead!==null&&n.at<=playhead?'record-lit':''}`} key={n.key} style={{left:x(n.at)}} onClick={()=>onSelect(item.task)} aria-label={`${item.task.title}，${n.label} ${n.rawTime}`} title={n.rawTime+'\n'+n.text}><i/></button>)}
 {playhead!==null&&playhead>=start&&playhead<=end&&<span className="gantt-playhead" style={{left:x(playhead)}}/>}
 </div></div>})}<div className="gantt-more"><More count={all.length} expanded={expanded.includes(e.id)} onClick={()=>setExpanded(x=>x.includes(e.id)?x.filter(v=>v!==e.id):[...x,e.id])}/></div></div>})}
 </div></div><p className="v-note">条带仅连接首条与最近记录，不表示连续工时；空心节点为笔记观察。日期精度不含具体时刻。</p>
 {!!undated.length&&<div className="undated-shelf"><h3>时间待核 <small>{undated.length}</small></h3><div>{undated.map(i=><button key={i.task.id} onClick={()=>onSelect(i.task)}>{i.task.title}<span>{i.task.state}</span></button>)}</div></div>}
 </section>
}
