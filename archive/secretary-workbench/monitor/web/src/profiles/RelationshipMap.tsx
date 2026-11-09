import {useMemo,useRef,useState,useEffect} from 'react';
import type {Employee} from '../model';
import {relationsFor,RELATION_LABEL,bandOf,type EmployeeProfile,type Relation,type HubMode} from './model';
import {Glyph,EmployeeGlyph,EvidenceButtons,LifeBadge,KindTag,formatChecked} from './shared';
const BANDS=[{id:'services',title:'服务对象',note:'人、组织与项目',accent:'purple'},{id:'employees',title:'数字员工',note:'持续岗位与负责结果',accent:'green'},{id:'channels',title:'沟通渠道',note:'同一渠道可兼具多种关系',accent:'teal'},{id:'sources',title:'信息来源',note:'授权取用的资料与记录',accent:'blue'},{id:'collaboration',title:'协作与交付',note:'执行分工与工作资源',accent:'amber'}] as const;
type Choice={employee:string;id:string}|null;
export function RelationshipMap({employees,profiles,onSource,onNavigate}:{employees:Employee[];profiles:Record<string,EmployeeProfile>;onSource:(id:string)=>void;onNavigate:(mode:HubMode,employee?:string)=>void}){
 const [choice,setChoice]=useState<Choice>(null),[expanded,setExpanded]=useState<string[]>([]),[zoom,setZoom]=useState(1),[showLinks,setShowLinks]=useState(true);
 const close=useRef<HTMLButtonElement>(null);const selected=choice?profiles[choice.employee]:null;const selectedEmployee=employees.find(e=>e.id===choice?.employee);const relation=selected?.relations.find(r=>r.id===choice?.id);const chosenRole=choice?.id==='employee';
 useEffect(()=>{if(choice)close.current?.focus()},[choice?.employee,choice?.id]);
 useEffect(()=>{if(choice&&!employees.some(e=>e.id===choice.employee))setChoice(null)},[employees,choice]);
 useEffect(()=>{const handler=(e:KeyboardEvent)=>{if(e.key==='Escape'&&!document.querySelector('.drawer'))setChoice(null)};document.addEventListener('keydown',handler);return()=>document.removeEventListener('keydown',handler)},[]);
 const layout=useMemo(()=>{
  const cols=employees.map(employee=>({employee,profile:profiles[employee.id]}));const col=268,label=116,w=label+cols.length*col+18;let y=12;const bands:Bands[]=[];
  for(const band of BANDS){const rows=band.id==='employees'?1:Math.max(1,...cols.map(c=>{const all=relationsFor(c.profile,band.id);return expanded.includes(c.employee.id+':'+band.id)?all.length:Math.min(2,all.length)}));const height=band.id==='employees'?168:Math.max(120,48+rows*66);bands.push({...band,y,height});y+=height+12}
  const nodes:Node[]=[];for(const [index,c]of cols.entries())for(const band of bands){const x=label+index*col+14;
   if(band.id==='employees'){nodes.push({key:c.employee.id+':employee',employee:c.employee.id,id:'employee',x,y:band.y+22,w:col-28,h:124});continue}
   const all=relationsFor(c.profile,band.id);const shown=expanded.includes(c.employee.id+':'+band.id)?all:all.slice(0,2);
   shown.forEach((r,i)=>nodes.push({key:c.employee.id+':'+r.id,employee:c.employee.id,id:r.id,relation:r,x,y:band.y+16+i*66,w:col-28,h:56}));
  }return {cols,bands,nodes,width:w,height:y};
 },[employees,profiles,expanded]);
 type Bands={id:typeof BANDS[number]['id'];title:string;note:string;accent:string;y:number;height:number};
 type Node={key:string;employee:string;id:string;relation?:Relation;x:number;y:number;w:number;h:number};
 const pick=(node:Node)=>setChoice({employee:node.employee,id:node.id});
 const links=layout.nodes.filter(n=>n.relation).flatMap((n,i)=>{const role=layout.nodes.find(x=>x.employee===n.employee&&x.id==='employee')!;const type=bandOf(n.relation!);let d='',color='';const right=role.x+role.w+6,left=role.x-7;
  if(type==='services'){d=`M${role.x+role.w/2},${role.y} C${role.x+role.w/2},${role.y-16} ${right},${role.y-12} ${right},${role.y-28} V${n.y+n.h/2} H${n.x+n.w}`;color='purple'}
  else if(type==='channels'){
   const rows:{n:Node;d:string;color:string}[]=[];
   if(n.relation!.types.some(t=>t==='communicates'||t==='delivers'))rows.push({n,color:'teal',d:`M${role.x+role.w/2},${role.y+role.h} C${role.x+role.w/2},${role.y+role.h+12} ${right},${role.y+role.h+14} ${right},${role.y+role.h+28} V${n.y+n.h/2} H${n.x+n.w}`});
   if(n.relation!.types.includes('reads'))rows.push({n,color:'blue',d:`M${n.x},${n.y+n.h/2} H${left} V${role.y+role.h/2} H${role.x}`});
   return rows;
  }
  else if(type==='sources'){const bus=role.x-10-(i%2)*3;d=`M${n.x},${n.y+n.h/2} H${bus} V${role.y+role.h/2} H${role.x}`;color='blue'}
  else{const bus=role.x+role.w+10+(i%2)*3;d=`M${role.x+role.w},${role.y+role.h/2} H${bus} V${n.y+n.h/2} H${n.x+n.w}`;color=n.relation!.types.some(t=>t==='collaborates'||t==='maintains')?'amber':'teal'}
  return [{n,d,color}];
 });
 return <div className={`relationship-layout ${choice?'has-choice':''}`}><section className="layer-map-panel"><div className="layer-map-tools"><span>属性分层 · 点开节点看关系与依据</span><div><button aria-pressed={showLinks} onClick={()=>setShowLinks(v=>!v)}>连线 {showLinks?'显示':'隐藏'}</button><button onClick={()=>setZoom(1)}>重置</button><button aria-label="关系图缩小" onClick={()=>setZoom(v=>Math.max(.6,+(v-.1).toFixed(2)))} disabled={zoom<=.6}>−</button><span>{Math.round(zoom*100)}%</span><button aria-label="关系图放大" onClick={()=>setZoom(v=>Math.min(1.4,+(v+.1).toFixed(2)))} disabled={zoom>=1.4}>＋</button></div></div>
 <div className="layer-map-viewport" role="region" aria-label="分层关系网络，可滚动查看" tabIndex={0}><div style={{width:layout.width*zoom,height:layout.height*zoom}}><svg width={layout.width} height={layout.height} className="layer-network" style={{transform:`scale(${zoom})`}} aria-label="服务对象、员工、沟通渠道、信息来源及协作五层关系"><defs>{['purple','teal','blue','amber'].map(color=><marker key={color} id={'layer-arrow-'+color} markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto"><path d="M0 0L6 3L0 6" className={'arrow-'+color}/></marker>)}</defs>
 {layout.bands.map(b=><g className={'network-band band-'+b.accent} key={b.id}><rect x={4} y={b.y} width={layout.width-8} height={b.height} rx={12}/><foreignObject x={18} y={b.y+25} width={95} height={90}><div className="band-label"><strong>{b.title}</strong><span>{b.note}</span></div></foreignObject></g>)}
 {showLinks&&links.map(({n,d,color})=><path key={'edge-'+n.key+'-'+color} className={`relation-edge edge-${color} ${choice?.id===n.id&&choice.employee===n.employee?'selected':''}`} d={d} markerEnd={'url(#layer-arrow-'+color+')'} onClick={()=>pick(n)} role="button" tabIndex={0} aria-label={`查看${profiles[n.employee]?.roleName||n.employee}与${n.relation?.label}的关系`} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();pick(n)}}}/>)}
 {layout.nodes.map(n=>{const e=employees.find(e=>e.id===n.employee)!;const p=profiles[n.employee];return <foreignObject key={n.key} x={n.x} y={n.y} width={n.w} height={n.h}>{n.id==='employee'?<button className={`layer-role ${choice?.employee===n.employee&&chosenRole?'selected':''}`} onClick={()=>pick(n)} data-employee={n.employee}><div><EmployeeGlyph employee={e}/><strong>{e.name}</strong></div><span className="role-specialty">{p?.roleName||'岗位资料待核'}</span><p>{p?.purpose||'尚未成功读取岗位结果'}</p><footer><span className={'runtime '+(e.runtime==='执行中'?'running':'')}>● {e.runtime}</span><span>{p?.health.error?'资料读取缺口':'只读属性'}</span></footer></button>:<button className={`layer-node node-${bandOf(n.relation!)} ${choice?.id===n.id&&choice.employee===n.employee?'selected':''}`} onClick={()=>pick(n)} title={n.relation!.label} data-relation-id={n.id}><span className="entity-icon"><Glyph kind={n.relation!.kind}/></span><span className="node-text"><strong>{n.relation!.label}</strong><small>{n.relation!.types.map(t=>RELATION_LABEL[t]).join(' · ')}</small></span><span className="node-chevron">›</span></button>}</foreignObject>})}
 {layout.cols.flatMap((c,k)=>layout.bands.filter(b=>b.id!=='employees').map(b=>{const all=relationsFor(c.profile,b.id as 'services');if(all.length<=2)return null;const key=c.employee.id+':'+b.id;return <foreignObject key={'more-'+key} x={116+k*268+14} y={b.y+b.height-28} width={240} height={26}><button className="layer-more" onClick={()=>setExpanded(a=>a.includes(key)?a.filter(v=>v!==key):[...a,key])}>{expanded.includes(key)?'收起':`另外 ${all.length-2} 个对象 ＋`}</button></foreignObject>}))}
 </svg></div></div><div className="relation-legend"><span className="legend-purple">↑ 服务 / 负责结果</span><span className="legend-blue">→ 读取</span><span className="legend-teal">↕ 沟通 / 交付</span><span className="legend-amber">┄ 协作 / 维护</span></div><p className="hub-footnote">图为岗位资料的只读投影。可读取、需服务与能公开分别判断；配置或范围不会因点图改变。</p></section>
 <aside className={`relationship-inspector ${choice?'open':''}`} aria-label="关系详情"><header><h2>{chosenRole?'员工属性':'关系详情'}</h2>{choice&&<button ref={close} aria-label="关闭关系详情" onClick={()=>setChoice(null)}>×</button>}</header>
 {!choice?<div className="inspector-empty"><Glyph kind="project" size={40}/><h3>选择节点查看关系</h3><p>选择一个人、渠道或资料，查看它与员工的关系、范围和来源。</p><div className="inspector-principles"><span>读取 ≠ 服务</span><span>关注 ≠ 扩权</span><span>事件触发 ≠ 业务交付</span></div></div>:selected&&selectedEmployee?<>
 <div className="inspector-head"><EmployeeGlyph employee={selectedEmployee}/><div><h3>{selected.roleName}</h3><small>{chosenRole?'持续岗位资料':relation?.label||'该关系已不在最新资料中'}</small></div></div>
 {selected.health.error&&<p className="hub-warning">岗位资料读取失败，保留上次结果。</p>}
 {chosenRole?<><LifeBadge profile={selected}/><p className="inspector-purpose">{selected.purpose}</p><h4>负责结果</h4><ul>{selected.responsibilities.map((s,i)=><li key={i}>{s.text}</li>)}</ul><EvidenceButtons evidence={selected.identityEvidence} onSource={onSource}/><button className="hub-link" onClick={()=>onNavigate('people',selectedEmployee.id)}>查看完整员工画像 ↗</button></>:relation?<>
 <div className="relation-tags">{relation.types.map(t=><span className={'rel-tag tag-'+t} key={t}>{RELATION_LABEL[t]}</span>)}</div><dl><dt>对象类型</dt><dd><KindTag kind={relation.kind}/></dd><dt>适用范围</dt><dd>{relation.scope}</dd><dt>约定来源</dt><dd>岗位资料记载，未据此新增授权</dd><dt>最近核读</dt><dd>{formatChecked(selected.health.lastSuccess)}</dd><dt>身份标识</dt><dd className="relation-real-id">{relation.realId||'原资料未单列真实ID'}</dd></dl><h4>原文依据</h4>{relation.evidence.map((ev,i)=><div className="relation-quote" key={ev.id+'-'+i}><p>{ev.quote}</p><EvidenceButtons evidence={[ev]} onSource={onSource} compact/></div>)}
 </>:<p className="hub-muted">资料已经变化，可从当前节点重新选择；原工作记录保留。</p>}
 <div className="inspector-footer">声明、配置与实际运行分别核验。<button onClick={()=>onNavigate('capabilities',selectedEmployee.id)}>能力与运行 ↗</button></div></>:<p className="hub-muted">岗位资料尚未取得。</p>}
 </aside></div>
}
