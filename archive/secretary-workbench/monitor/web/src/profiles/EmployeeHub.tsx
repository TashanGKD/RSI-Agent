import type {Employee,Task,Snapshot} from '../model';
import type {HubMode,EmployeeProfile} from './model';
import {EmployeeGlyph,formatChecked} from './shared';
import {RelationshipMap} from './RelationshipMap';
import {EmployeePortrait,CapabilityPage,LifecyclePage} from './EmployeePages';
import './profiles.css';
import {WorkModesPanel,SystemObservation} from '../work/WorkPage';
export function EmployeeHub({snapshot,mode,person,onPerson,onNavigate,onSource,onTask}:{snapshot:Snapshot;mode:HubMode;person:string;onPerson:(id:string)=>void;onNavigate:(mode:HubMode,employee?:string)=>void;onSource:(id:string)=>void;onTask:(t:Task)=>void}){
 const profiles=snapshot.profiles||{};const employees=snapshot.employees;const current=employees.find(e=>e.id===person)||employees[0];const p=profiles[current?.id];
 const shown=mode==='relations'&&person==='all'?employees:employees.filter(e=>e.id===current?.id);
 return <div className="employee-hub"><div className="hub-picker"><div className="hub-person-tabs" role="group" aria-label="选择岗位">{mode==='relations'&&<button className={person==='all'?'selected all-employees':''} aria-pressed={person==='all'} onClick={()=>onPerson('all')}>全部员工</button>}{employees.map(e=><button key={e.id} className={person===e.id||mode!=='relations'&&current.id===e.id?'selected':''} aria-pressed={person===e.id||mode!=='relations'&&current.id===e.id} onClick={()=>onPerson(e.id)}><EmployeeGlyph employee={e}/><span>{e.name}<small>{profiles[e.id]?.roleName||'资料待同步'}</small></span></button>)}</div><span className="hub-read-state">{shown.some(e=>profiles[e.id]?.health.error)?'部分资料读取有缺口':'岗位属性 · 只读核对'}</span></div>
 {shown.some(e=>profiles[e.id]?.health.error)&&<div className="hub-warning">岗位资料有读取缺口，已保留上次画像。该状态不代表员工已停岗，也不影响其他已读取来源。</div>}
 {mode==='relations'?<RelationshipMap employees={shown} profiles={profiles} onSource={onSource} onNavigate={onNavigate}/>:!p?<section className="hub-empty"><h2>岗位资料正在接入</h2><p>原工作监控仍可读取；没有依据的属性不会用设计示例填充。</p></section>:mode==='people'?<EmployeePortrait employee={current} profile={p} tasks={snapshot.tasks} onSource={onSource} onTask={onTask} onNavigate={onNavigate}/>:mode==='capabilities'?<CapabilityPage employee={current} profile={p} snapshot={snapshot} onSource={onSource}/>:<LifecyclePage employee={current} profile={p} onSource={onSource}/>}
 {mode==='people'&&snapshot.workOverview?.employees.find(e=>e.id===current.id)&&<WorkModesPanel snapshot={snapshot} employee={snapshot.workOverview.employees.find(e=>e.id===current.id)!} onSource={onSource}/>}
 {mode==='capabilities'&&<SystemObservation snapshot={snapshot} onSource={onSource}/>}
 <footer className="hub-data-footer"><span>关系按ROLE、群约定及运行记录提取，来源有变化时随原5分钟周期更新。</span><span>{mode==='relations'&&person==='all'?'各岗位独立核读，时间见详情':'岗位核读 '+formatChecked(p?.health.lastSuccess)}</span></footer>
 </div>
}
