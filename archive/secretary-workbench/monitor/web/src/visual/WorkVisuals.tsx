import {useEffect,useMemo,useRef,useState} from 'react';
import {Button} from '../design-system/ui';
import type {Task,Employee} from '../model';
import {visualItems,sortItems,parseRecordTime,formatTime,PHASES} from './model';
import {OrbitView} from './OrbitView';import {GanttView} from './GanttView';import {MapView} from './MapView';import {StageView} from './StageView';
import './visuals.css';
const VIEWS=[['orbits','动态轨道'],['gantt','时间甘特'],['map','工作地图'],['flow','阶段流转']] as const;
type Mode=typeof VIEWS[number][0];
function initialMode():Mode{const h=location.hash.slice(1);if(VIEWS.some(v=>v[0]===h))return h as Mode;try{const v=localStorage.getItem('employee-monitor:visual-view:v1');if(VIEWS.some(x=>x[0]===v))return v as Mode}catch{}return 'orbits'}
function ViewIcon({mode}:{mode:Mode}){return <svg width="19" height="19" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>{mode==='gantt'?<><path d="M4 3v14M3 6h12M6 10h10M8 14h6"/></>:mode==='map'?<><circle cx="10" cy="4" r="2"/><rect x="2" y="12" width="5" height="5" rx="1"/><rect x="13" y="12" width="5" height="5" rx="1"/><path d="M10 6v3M4.5 12V9h11v3"/></>:mode==='flow'?<><rect x="2" y="3" width="4" height="14" rx="1"/><rect x="8" y="3" width="4" height="8" rx="1"/><rect x="14" y="3" width="4" height="11" rx="1"/></>:<><path d="M2 7c5-7 10 7 16 0M2 14c5-7 10 7 16 0"/><circle cx="11" cy="8" r="2" fill="currentColor"/></>}</svg>}
export function WorkVisuals({tasks,employees,cutoff,revision,onSelect,scopeKey}:{tasks:Task[];employees:Employee[];cutoff:string;revision:string;scopeKey:string;onSelect:(task:Task)=>void}){
 const [mode,setMode]=useState<Mode>(initialMode),[motion,setMotion]=useState(()=>!matchMedia('(prefers-reduced-motion: reduce)').matches),[playhead,setPlayhead]=useState<number|null>(null),[playing,setPlaying]=useState(false),[updates,setUpdates]=useState(0);
 const previous=useRef<Map<string,string>|null>(null),previousRevision=useRef(revision),tabs=useRef<HTMLDivElement>(null);
 const items=useMemo(()=>sortItems(visualItems(tasks)),[tasks]);const now=parseRecordTime(cutoff)?.at||Date.now();
 const es=useMemo(()=>items.flatMap(i=>i.events).filter(n=>n.at<=now),[items,now]);
 const begin=es.length?Math.min(...es.map(e=>e.at)):now-86400000,end=Math.max(begin+60000,es.length?Math.max(...es.map(e=>e.at)):now);
 useEffect(()=>{const h=()=>{const id=location.hash.slice(1);if(VIEWS.some(v=>v[0]===id))setMode(id as Mode)};addEventListener('hashchange',h);return()=>removeEventListener('hashchange',h)},[]);
 useEffect(()=>{try{localStorage.setItem('employee-monitor:visual-view:v1',mode)}catch{}setPlaying(false);setPlayhead(null)},[mode,scopeKey]);
 useEffect(()=>{const q=matchMedia('(prefers-reduced-motion: reduce)');const h=()=>{if(q.matches){setMotion(false);setPlaying(false)}};q.addEventListener('change',h);return()=>q.removeEventListener('change',h)},[]);
 useEffect(()=>{if(!playing)return;const timer=setInterval(()=>{if(document.hidden){setPlaying(false);return}setPlayhead(p=>{const next=(p??begin)+(end-begin)/100;return Math.min(end,next)})},150);return()=>clearInterval(timer)},[playing,begin,end]);
 useEffect(()=>{const next=new Map(items.map(i=>[i.task.id,JSON.stringify([i.task.title,i.task.state,i.task.pending,i.task.trajectory.length])]));if(previous.current&&previousRevision.current!==revision){let n=0;next.forEach((v,k)=>{if(previous.current!.get(k)!==v)n++});setUpdates(n)}else setUpdates(0);previous.current=next;previousRevision.current=revision},[revision,items]);
 useEffect(()=>{if(playing&&playhead!==null&&playhead>=end)setPlaying(false)},[playhead,playing,end]);
 const selectMode=(m:Mode)=>{setMode(m);history.replaceState(null,'','#'+m)};
 const props={items,employees,onSelect,motion,playhead,scope:scopeKey};
 return <VisualContent {...{mode,selectMode,motion,setMotion,playhead,setPlayhead,playing,setPlaying,updates,tabs,props,begin,end,now,hasEvents:es.length>0}}/>;
}
type ContentProps={mode:Mode;selectMode:(m:Mode)=>void;motion:boolean;setMotion:(v:boolean)=>void;playhead:number|null;setPlayhead:(v:number|null)=>void;playing:boolean;setPlaying:(v:boolean)=>void;updates:number;tabs:React.RefObject<HTMLDivElement|null>;props:Parameters<typeof OrbitView>[0];begin:number;end:number;now:number;hasEvents:boolean};
function VisualContent({mode,selectMode,motion,setMotion,playhead,setPlayhead,playing,setPlaying,updates,tabs,props,begin,end,now,hasEvents}:ContentProps){
 return <div className={`work-visuals mode-${mode} ${motion?'motion-enabled':'motion-disabled'}`}><div className="visual-toolbar"><div className="view-tabs" role="tablist" aria-label="工作可视化视图" ref={tabs} onKeyDown={e=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const at=VIEWS.findIndex(v=>v[0]===mode);const next=e.key==='Home'?0:e.key==='End'?3:(at+(e.key==='ArrowRight'?1:3))%4;selectMode(VIEWS[next][0]);(tabs.current?.children[next] as HTMLElement)?.focus()}}>{VIEWS.map(([id,label])=><button key={id} role="tab" id={'tab-'+id} aria-controls={'visual-'+id} aria-selected={id===mode} tabIndex={id===mode?0:-1} className={id===mode?'selected':''} onClick={()=>selectMode(id)}><ViewIcon mode={id}/>{label}</button>)}</div><div className="visual-options"><span className="visual-sync" role="status">{updates?`${updates} 项有变化`:'与记事本同步'}</span><Button variant="quiet" aria-pressed={motion} onClick={()=>{setMotion(!motion);if(motion)setPlaying(false)}}>动效 {motion?'开':'关'}</Button></div></div>
 <div id={'visual-'+mode} role="tabpanel" aria-labelledby={'tab-'+mode} className="visual-panel" key={mode}>
 {itemsEmpty(props.items.length)?<div className="visual-empty"><span>◌</span><h2>没有符合筛选的事项</h2><p>试着切换员工、状态或关键词。</p></div>:mode==='orbits'?<OrbitView {...props}/>:mode==='gantt'?<GanttView {...props} now={now}/>:mode==='map'?<MapView {...props}/>:<StageView {...props}/>}
 </div>
 {(mode==='orbits'||mode==='gantt')&&<div className="record-replay"><Button variant="secondary" disabled={!hasEvents} aria-label={playing?'暂停节点回放':'回放记录节点'} onClick={()=>{if(!playing&&(playhead===null||playhead>=end))setPlayhead(begin);setPlaying(!playing)}}>{playing?'Ⅱ':'▶'} {playing?'暂停':'回放节点'}</Button><input type="range" aria-label="记录回放时间" min={begin} max={end} step={1} value={playhead??end} disabled={!hasEvents} onChange={e=>{setPlaying(false);setPlayhead(+e.target.value)}}/><time>{formatTime(playhead??end)}</time>{playhead!==null&&<button className="back-live" onClick={()=>{setPlaying(false);setPlayhead(null)}}>回到最新</button>}<p>仅回放有时间的记录节点 · 状态仍为最新</p></div>}
 <div className="visual-legend">{PHASES.map(p=><span className={`phase-${p.id}`} key={p.id}><i/>{p.label}</span>)}<small>同一份记事本 · 只读</small></div></div>
}
const itemsEmpty=(n:number)=>n===0;
