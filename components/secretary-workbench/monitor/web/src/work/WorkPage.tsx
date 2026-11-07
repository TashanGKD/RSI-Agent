import {useEffect,useMemo,useRef,useState} from 'react';
import type {Snapshot} from '../model';
import type {WorkItem,SendItem,WorkPerson} from './model';
import {filterWork,isDone,sendVisible,workTone,sortSending,sortNotebook} from './model';
import {DeliveryPanel} from './DeliveryHealth';
import {NativeInboxView} from './NativeInbox';
import './work.css';
const compact=(s:string,n=110)=>{const clean=s.replace(/\b(?:secretary|science|forum|organoid|digital)[-_][a-zA-Z0-9_-]+/g,'').replace(/\b\d{15,}\b/g,'').replace(/[ \t]{2,}/g,' ').trim();return clean.length>n?clean.slice(0,n)+'…':clean};
const text=(s:string|undefined|null,f='原记录未单列')=>s?.trim()||f;
const fmt=(s:string|undefined)=>s?new Date(s.includes('T')?s:s.replace(' ','T')+'+08:00').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'待核';
function Glyph({name}:{name:string}){return <span className="wk-glyph" aria-hidden>{name.slice(0,1)}</span>}
export function WorkPage({snapshot,mode,onMode,onSource,onPerson}:{snapshot:Snapshot;mode:'work'|'sending';onMode:(m:'work'|'sending')=>void;onSource:(id:string)=>void;onPerson:(id:string)=>void}){
 const work=snapshot.workOverview;
 const [workTab,setWorkTab]=useState<'inbox'|'notebook'>('inbox'),[sortMode,setSortMode]=useState('execution');
 const [person,setPerson]=useState('all'),[query,setQuery]=useState(''),[filter,setFilter]=useState('open'),[sendFilter,setSendFilter]=useState('current');
 const [selected,setSelected]=useState<{type:'work'|'send';id:string}|null>(null),[coverage,setCoverage]=useState(false);
 const closer=useRef<HTMLButtonElement>(null),returnFocus=useRef<HTMLElement|null>(null);
 const people=work?.employees||[];const names=Object.fromEntries(people.map(p=>[p.id,p.name]));
 const raw=work?.items||[],sendItems=work?.sending.items||[];
 const list=useMemo(()=>sortNotebook(filterWork(raw,person,query,filter),sortMode),[raw,person,query,filter,sortMode]);
 const jobs=list.filter(x=>x.commitment!=='candidate'),candidates=list.filter(x=>x.commitment==='candidate');
 const sent=sortSending(sendItems.filter(x=>sendVisible(x,sendFilter)&&(person==='all'||x.employee===person)&&(!query||`${x.title} ${x.destination} ${names[x.employee]}`.toLowerCase().includes(query.toLowerCase()))),sortMode);
 const task=selected?.type==='work'?raw.find(x=>x.id===selected.id):undefined;
 const message=selected?.type==='send'?sendItems.find(x=>x.id===selected.id):undefined;
 const open=(type:'work'|'send',id:string)=>{returnFocus.current=document.activeElement as HTMLElement;setSelected({type,id})};
 const shut=()=>{setSelected(null);returnFocus.current?.focus()};
 useEffect(()=>{if(selected)closer.current?.focus();const key=(e:KeyboardEvent)=>{if(selected&&e.key==='Escape'&&!document.querySelector('.backdrop'))shut()};window.addEventListener('keydown',key);return()=>window.removeEventListener('keydown',key)},[selected?.id]);
 if(!work)return <section className="wk-empty"><h2>正在接入原工作记录</h2><p>没有取得来源时不显示为零待办。旧工作全景仍可查看。</p></section>;
 const employee=(id:string)=>names[id]||'发起员工待核';
 const workRow=(i:WorkItem)=><tr key={i.id} tabIndex={0} role="button" aria-label={'查看事情 '+i.title} onClick={()=>open('work',i.id)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();open('work',i.id)}}}>
  <td data-label="事情"><strong>{i.title}</strong>{i.sourceStale&&<small className="wk-warning">来源暂不可读 · 保留上次记录</small>}<small>{i.commitment==='unknown'?'原记录，承接性质待核':i.commitment==='candidate'?'尚未承接':'已承接（原记录）'}</small></td>
  <td data-label="员工"><span className="wk-person"><Glyph name={employee(i.employee)}/>{employee(i.employee)}</span></td>
  <td data-label="来自哪里"><span className="wk-summary">{compact(text(i.origin),90)}</span><small>{i.originKind}</small></td>
  <td data-label="理解要做到什么"><span className="wk-summary">{compact(text(i.goal),120)}</span></td>
  <td data-label="当前情况"><span className={'wk-state '+workTone(i.state)}>{work.deliveryHealth?.incidents.some(d=>d.businessId===i.id&&d.status==='blocked')?'未送达／等工具恢复':compact(i.state,70)}</span></td>
  <td data-label="下一步／在等什么"><span className="wk-summary">{compact(text(i.next),130)}</span><small className="wk-look">展开看依据 ↗</small></td>
 </tr>;
 const sendRow=(s:SendItem)=><tr key={s.id} tabIndex={0} role="button" aria-label={'查看消息 '+s.title} onClick={()=>open('send',s.id)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();open('send',s.id)}}}>
  <td data-label="顺序"><span className={'wk-state '+(s.phase==='processing'?'active':'waiting')}>{s.deliveryStatus==='blocked'?'需补交':s.deliveryStatus==='unknown'?'待核':s.phase==='processing'?'处理中':s.queuePosition?'第 '+s.queuePosition+' 项':'记录'}</span></td>
  <td data-label="发给谁"><strong>{s.destination}</strong></td>
  <td data-label="发送内容"><strong>{s.title}</strong>{s.attachments.length>0&&<small>附件：{s.attachments.join('、')}</small>}</td>
  <td data-label="当前情况"><span className={'wk-state '+(s.state==='sent'?'done':'waiting')}>{s.label}</span><small className="wk-summary">{s.state==='sent'?'原记录有发送依据，未核对方阅读':s.reason}</small></td>
  <td data-label="谁交来"><span className="wk-person"><Glyph name={employee(s.employee)}/>{employee(s.employee)}</span></td>
 </tr>;
 return <section className="work-page" aria-label="员工工作与发送记录">
  <nav className="wk-tabs" aria-label="工作视图"><button className={mode==='work'?'selected':''} onClick={()=>onMode('work')}>员工手里的事</button><button className={mode==='sending'?'selected':''} onClick={()=>onMode('sending')}>待发送消息</button><a href="#orbits">图形全景 ↗</a></nav>
  {work.error&&<p className="wk-warning" role="status">{work.error}</p>}
  {mode==='sending'&&work.sending.error&&<p className="wk-warning" role="status">{work.sending.error}</p>}
  {mode==='work'&&<ConversationPanel people={people.filter(p=>person==='all'||p.id===person)} onSource={onSource}/>}
  {mode==='work'&&<div className="wk-view-tabs"><button className={workTab==='inbox'?'selected':''} onClick={()=>setWorkTab('inbox')}>收件与处理</button><button className={workTab==='notebook'?'selected':''} onClick={()=>setWorkTab('notebook')}>工作本记录</button></div>}
  <DeliveryPanel health={work.deliveryHealth} people={people} sending={sendItems} employee={person} query={query} onSource={onSource}/>
  <div className={'wk-tools '+(mode==='sending'||workTab==='notebook'?'book-tools':'')}><label>员工<select aria-label="筛选员工" value={person} onChange={e=>setPerson(e.target.value)}><option value="all">全部员工</option><optgroup label="业务岗位">{people.filter(x=>x.category==='business').map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</optgroup><optgroup label="系统支撑">{people.filter(x=>x.category==='support').map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</optgroup></select></label><label className="wk-search">⌕<input aria-label="搜索工作记录" value={query} onChange={e=>setQuery(e.target.value)} placeholder={mode==='work'?'搜事情、员工理解或原话':'搜内容、员工或目标群'}/></label>{mode==='work'&&workTab==='notebook'?<select aria-label="筛选进展" value={filter} onChange={e=>setFilter(e.target.value)}><option value="open">未完成</option><option value="closed">已完成／不做了</option><option value="all">全部记录</option></select>:mode==='sending'?<select aria-label="筛选发送情况" value={sendFilter} onChange={e=>setSendFilter(e.target.value)}><option value="current">未交付／排队处理中</option><option value="undelivered">逐件交付未完成／待核</option><option value="deferred">业务暂缓（已知未发）</option><option value="unknown">历史交办结果待核</option><option value="sent">有发送依据</option><option value="cancelled">已撤销／被取代</option><option value="all">全部已读取交办</option></select>:null}<select aria-label="排序" value={sortMode} onChange={e=>setSortMode(e.target.value)}><option value="execution">{mode==='sending'?'处理优先、队列顺序':workTab==='inbox'?'按员工与队列顺序':'当前状态优先'}</option><option value="oldest">{workTab==='notebook'&&mode==='work'?'最早记录更新在前':'最早交办在前'}</option><option value="newest">{workTab==='notebook'&&mode==='work'?'最近记录更新在前':'最新交办在前'}</option></select></div>
  {mode==='work'?(workTab==='inbox'?<NativeInboxView people={people.filter(p=>person==='all'||p.id===person)} query={query} sort={sortMode} onSource={onSource}/>:<>
   <div className="wk-table-wrap"><table className="wk-table tasks-table"><thead><tr>{['事情','员工','来自哪里','理解要做到什么','当前情况','下一步／在等什么'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{jobs.map(workRow)}</tbody></table>{!jobs.length&&<div className="wk-empty"><strong>当前筛选未取得事项</strong><p>来源不足与没有待办不同，请看读取范围。</p></div>}</div>
   <details className="wk-fold"><summary>发现的建议 · 尚未承接 <span>{candidates.length} 项</span></summary><table className="wk-table"><tbody>{candidates.map(workRow)}</tbody></table></details>
   {people.filter(p=>(person==='all'||p.id===person)&&!raw.some(i=>i.employee===p.id)).map(p=><div className="wk-gap" key={p.id}><strong>{p.name}</strong><span>{p.error||'原入口已定位，未取得统一逐件工作本；可查看原对话与职责，不据此判断零待办。'}</span><a href={'codex://threads/'+p.threadId}>原对话 ↗</a></div>)}
  </>):<>
   <p className="wk-sending-note">各岗位直达与中央发送 · {work.sending.queueCount===undefined?'原队列待核':`原生队列 ${work.sending.queueCount} 条输入`} · 已交发送不等于已发出</p>
   <div className="wk-table-wrap"><table className="wk-table send-table"><thead><tr>{['顺序','发给谁','发送内容','当前情况','谁交来'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{sent.map(sendRow)}</tbody></table>{!sent.length&&<div className="wk-empty"><strong>此筛选没有可展示的发送交办</strong><p>历史结果待核和读取缺口分别保留，不推断全部已发。</p></div>}</div>
   <details className="wk-fold"><summary>发送读取范围与限制</summary><p>{work.sending.note}</p>{work.sending.toolCoverage&&<><p>工具侧已读索引 {work.sending.toolCoverage.indexed??'待核'} 项；定向读取 {work.sending.toolCoverage.targetedReads??'待核'} 个已知请求。</p>{work.sending.toolCoverage.gaps.map((g,i)=><p key={i}>{g}</p>)}</>}<p>发送源采样：{fmt(work.sending.sampledAt)}；此时刻不是业务发送时间。</p></details>
  </>}
  {work.discovery.consistency&&<p className="wk-footnote" data-read-consistency>本轮统一核对 {work.discovery.consistency.checkedEmployees} 名员工 · {work.discovery.consistency.verifiedIdentities} 个原生身份已核 · {work.discovery.consistency.employeesWithGaps} 名存在读取缺口或尚无结构化工作本，详见下方读取范围。</p>}
  <button className="wk-coverage-toggle" aria-expanded={coverage} onClick={()=>setCoverage(!coverage)}>各员工读到了哪里 <span>{people.some(p=>p.error)?'部分来源失效':'逐源范围独立核对'}　{coverage?'−':'＋'}</span></button>
  {coverage&&<div className="wk-coverage">{people.filter(p=>person==='all'||p.id===person).map(p=><article key={p.id}><div><strong>{p.name}</strong><span>{p.category==='support'?'系统支撑':'业务岗位'}</span></div><dl><dt>消息已读截止</dt><dd>{p.coverage?.readThrough||'待核'}<small>{p.coverage?.note||'来源暂不可读'}</small></dd><dt>本监控笔记采样</dt><dd>{fmt(p.observedAt)} · {p.notebooks??'未知'}份逐件笔记</dd><dt>工作本读取</dt><dd>{p.workRead?.state==='native_only'?'本轮未读到可用逐件工作本，0项不代表无工作':p.workRead?`${p.workRead.items}项原记录 · ${p.workRead.staleItems}项来源陈旧`:'范围待核'}</dd><dt>历史身份核对</dt><dd>{work.discovery.consistency?.employees.find(x=>x.employee===p.id)?.identity==='verified'?'本轮原生回合已核':'原生身份尚待核'}</dd><dt>原生运行</dt><dd>{p.runtime?.state||'未知'} · 输入排队 {p.runtime?.queueCount??'待核'}</dd></dl>{p.error&&<p role="status">{p.error}</p>}<button onClick={()=>onPerson(p.id)}>查看员工属性 ↗</button></article>)}</div>}
  <p className="wk-footnote" data-revision={snapshot.live?.revision||snapshot.generatedAt}>原工作记录自动读取 · 每5分钟检查 · 最近采样 {fmt(work.sampledAt)} · 北京时间</p>
  {selected&&(task||message)&&<div className="wk-backdrop" onClick={shut}><aside className="wk-drawer" role="dialog" aria-modal="true" aria-labelledby="wk-detail-title" onClick={e=>e.stopPropagation()} onKeyDown={e=>{if(e.key==='Tab'){const ns=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button,a')).filter(x=>!x.hasAttribute('disabled'));const first=ns[0],last=ns.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}}}>
   <header><strong>{task?'事情详情':'消息详情'}</strong><button ref={closer} onClick={shut} aria-label="关闭工作详情">×</button></header>
   <div className="wk-detail-body">{task?<>
    <h2 id="wk-detail-title">{task.title}</h2>{task.sourceStale&&<p className="wk-warning">当前原件暂不可读；以下保留上次记录，不判断已经完成。</p>}<p className="wk-detail-meta">{employee(task.employee)} <span className={'wk-state '+workTone(task.state)}>{task.state}</span></p>
    <DeliveryPanel health={work.deliveryHealth} people={people} sending={sendItems} businessId={task.id} onSource={onSource}/><dl><dt>这次要交付什么</dt><dd>{text(task.goal)}</dd><dt>从哪里来</dt><dd>{text(task.origin)}<small>{task.originKind}</small></dd><dt>员工的理解／判断</dt><dd>{text(task.thought,'未在原记录单独写出，不替员工补造理解')}<small>{task.interpretationKind}</small></dd><dt>下一步／在等什么</dt><dd>{text(task.next)}</dd><dt>时间约定</dt><dd>{text(task.time,'原提出时间／截止未单列，不用文件修改时间替代')}</dd><dt>承接性质</dt><dd>{task.commitment==='accepted'?'已承接（原记录）':task.commitment==='candidate'?'候选建议，尚未承接':'原专业记录未明确区分，待核'}</dd></dl>
    <section><h3>原工作本依据</h3>{task.evidence.map((ev,i)=><button className="wk-evidence" key={i} onClick={()=>onSource(ev.id)}><span>{task.sourceLabel} ↗</span><blockquote>{ev.quote}</blockquote></button>)}<small>笔记版本更新：{text(task.recordUpdatedAt)}；这是记录时间，不是交办时间。</small></section>
    {sendItems.some(s=>s.relatedItemIds.includes(task.id))&&<section><h3>关联发送</h3>{sendItems.filter(s=>s.relatedItemIds.includes(task.id)).map(s=><button className="wk-linked" key={s.id} onClick={()=>open('send',s.id)}>{s.label} → {s.destination} ↗</button>)}</section>}
   </>:message&&<>
    <h2 id="wk-detail-title">{compact(message.title,150)}</h2><p className="wk-detail-meta">{employee(message.employee)} → {message.destination}</p><span className="wk-state waiting">{message.label}</span>
    <section><h3>消息内容</h3><small>{message.bodyKind}</small><blockquote className="wk-message">{message.body||message.summary}</blockquote>{message.attachments.length>0&&<p>附件：{message.attachments.join('、')}</p>}</section>
    <dl><dt>当前情况</dt><dd>{message.state==='sent'?'原发送记录有发送依据；未核收件人已读':message.reason}</dd><dt>交办进入发送侧的时间</dt><dd>{message.requestedAt}</dd><dt>对方已读</dt><dd>未取得阅读依据</dd><dt>关联事情</dt><dd>{message.relatedItemIds.length?message.relatedItemIds.map(id=><button className="wk-linked" key={id} onClick={()=>open('work',id)}>{raw.find(x=>x.id===id)?.title||'原事项'} ↗</button>):'未取得明确关联，不自动猜测'}</dd></dl>
    <button className="wk-linked" onClick={()=>onSource(message.sourceId)}>查看原交办／队列依据 ↗</button>{message.proofSourceId&&<button className="wk-linked" onClick={()=>onSource(message.proofSourceId!)}>查看原发送结果依据 ↗</button>}{message.toolOperations?.map(op=><button className="wk-linked" key={op.requestId} onClick={()=>onSource(op.sourceId)}>操作记录：{op.state} · {op.requestId} ↗</button>)}
   </>}
   <footer>仅查看 · 不催办、不重发、不改变员工工作</footer></div>
  </aside></div>}
 </section>
}

export function WorkModesPanel({snapshot,employee,onSource}:{snapshot:Snapshot;employee:WorkPerson;onSource:(id:string)=>void}){
 const modes=snapshot.workOverview?.modes;if(!modes)return null;
 const p=snapshot.profiles?.[employee.id];
 return <section className="work-modes-panel"><h2>工作方式</h2><p>共同默认、原岗位约定与本次采用分开。模式可组合，非能力等级。</p><div className="wk-mode-table"><div className="wk-mode-head"><span>方面</span><span>共同默认与可选做法</span><span>本岗／本次</span></div>{modes.dimensions.map(d=><div className="wk-mode-row" key={d.dimension}><strong>{d.dimension}</strong><div><p>{d.default.replaceAll('**','')}</p><div className="wk-options">{d.options.map(o=><span key={o}>{o}</span>)}</div></div><div>约定见下方原岗位摘录<small>本次采用：未单独记录，不推断</small></div></div>)}</div>{employee.modeNotes&&<details className="wk-fold"><summary>本岗相关约定 · 原文摘录</summary><p style={{whiteSpace:'pre-wrap'}}>{employee.modeNotes.excerpt}</p><button className="wk-linked" onClick={()=>onSource(employee.modeNotes!.sourceId)}>查看原岗位依据 ↗</button></details>}<div className="wk-mode-links"><button onClick={()=>onSource(modes.sourceId)}>查看共同规范 ↗</button>{p?.identityEvidence[0]&&<button onClick={()=>onSource(p.identityEvidence[0].id)}>查看本岗原约定 ↗</button>}</div></section>
}

export function ConversationPanel({people,onSource}:{people:WorkPerson[];onSource:(id:string)=>void}){
 const known=people.filter(p=>p.reminders?.state==='known'&&!p.reminders.error),rows=people.flatMap(p=>(p.reminders?.conversations||[]).map(c=>({p,c}))),notices=people.flatMap(p=>(p.reminders?.existingNotices||[]).map(n=>({p,n})));
 return <details className="wk-fold reminder-panel"><summary>待看会话 <span>{rows.length}个已记录 · {known.length}名员工本轮取得结果</span></summary><p>提醒看人或群，不逐条建任务。同会话多次提醒合并，已转交不表示已经阅读；业务与发送另看下方列表。</p>
  {rows.length?<table className="wk-table reminder-table"><thead><tr>{['员工','待看的人／群','最新提醒','合并次数','依据'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{rows.map(({p,c})=><tr className="reminder-row" key={p.id+'|'+c.account+'|'+c.peer}><td data-label="员工">{p.name}{p.reminders?.error&&<small>上次结果 · 来源暂不可读</small>}</td><td data-label="会话"><strong>{c.name||c.peer}</strong><small>首次提醒 {fmt(new Date(c.firstSourceTime*1000).toISOString())}</small><small>账号：{c.account}</small></td><td data-label="最新提醒">{fmt(new Date(c.latestSourceTime*1000).toISOString())}<small>来源 {c.latestSourceId}</small></td><td data-label="合并次数">{c.reminderCount}次 → 1个会话</td><td>{p.reminders?.sourceId&&<button className="wk-linked" onClick={()=>onSource(p.reminders!.sourceId!)}>查看来源 ↗</button>}</td></tr>)}</tbody></table>:<p className="reminder-empty">{known.length?'本轮已取得结果的范围内，没有尚未转交的会话提醒。':'尚未取得待看会话结果。'}这不表示消息已读完、业务已完成或已经回复。</p>}
  {notices.length>0&&<div className="reminder-notices"><h3>已经排入／状态待核的提醒通知</h3>{notices.map(({p,n})=><p key={p.id+'|'+n.id}>{p.name} · {n.state}<small>通知已冻结，不代表会话阅读完成；不与新增待看会话相加。</small></p>)}</div>}
  <div className="reminder-scope">{people.map(p=><p key={p.id}><strong>{p.name}</strong> · {p.reminders?.error||p.reminders?.state==='known'?p.reminders?.error||`${p.reminders?.pending??'待核'}个待看会话，${p.reminders?.pendingEvidenceCount??'待核'}条提醒依据`:p.reminders?.state==='not_registered'?'未在此统一入口登记；不视为0':'来源待核'}{p.reminders?.sourceId&&<button onClick={()=>onSource(p.reminders!.sourceId!)}>依据 ↗</button>}</p>)}</div>
  <p className="wk-footnote">只覆盖统一系统已登记渠道；旧独立入口与未登记范围不因此视为已覆盖。来源时间和本监控采样时间分别保留。</p>
 </details>
}

export function SystemObservation({snapshot,onSource}:{snapshot:Snapshot;onSource:(id:string)=>void}){
 const w=snapshot.workOverview;if(!w)return null;
 return <section className="work-modes-panel"><h2>统一运行与原每日复核</h2><div className="wk-table-wrap"><table className="wk-table"><thead><tr><th>员工</th><th>当前回合</th><th>输入排队</th><th>待看会话</th><th>已登记渠道</th></tr></thead><tbody>{w.employees.map(p=><tr key={p.id}><td>{p.name}</td><td>{p.runtime?.state||'未知'}</td><td>{p.runtime?.queueCount??'待核'}</td><td>{p.reminders?.error?'上次结果 · 读取有缺口':p.reminders?.pending??'未登记／待核'}</td><td>{p.channels.length?`${p.channels.length} 个（配置）`:'未在此事件源登记'}</td></tr>)}</tbody></table></div><p className="wk-footnote">渠道登记不是自然运行或实际回复验收。采样 {fmt(w.sampledAt)}；不依据旧等待字段判定卡住。</p>{w.observation&&<><button className="wk-linked" onClick={()=>onSource(w.observation!.eventSourceId)}>查看统一事件来源状态 ↗</button>{w.observation.reviews.map(r=><details className="wk-fold" key={r.sourceId}><summary>{r.title}</summary><p style={{whiteSpace:'pre-wrap'}}>{r.excerpt}</p><p>原记录更新时间：{r.recordUpdatedAt}；实际复核范围以报告为准。</p><button className="wk-linked" onClick={()=>onSource(r.sourceId)}>查看原复核报告 ↗</button></details>)}</>}</section>
}

export function DirectoryPage({snapshot,onPerson}:{snapshot:Snapshot;onPerson:(id:string)=>void}){
 const [category,setCategory]=useState('all'),[q,setQ]=useState('');const w=snapshot.workOverview;
 if(!w)return <p>正在读取岗位目录；未知不显示为零。</p>;
 return <section className="work-page"><div className="wk-directory-tools"><div className="wk-tabs">{[['all','全部'],['business','业务岗位'],['support','系统支撑']].map(([id,label])=><button key={id} className={category===id?'selected':''} onClick={()=>setCategory(id)}>{label}</button>)}</div><input aria-label="搜索员工" placeholder="搜员工或职责" value={q} onChange={e=>setQ(e.target.value)}/></div><div className="wk-table-wrap"><table className="wk-table directory-table"><thead><tr>{['员工与职责','当前关注','已记录未闭环','本轮运行','最近依据'].map(x=><th key={x}>{x}</th>)}</tr></thead><tbody>{w.employees.filter(p=>(category==='all'||p.category===category)&&(!q||`${p.name} ${snapshot.profiles?.[p.id]?.purpose}`.includes(q))).map(p=>{const items=w.items.filter(x=>x.employee===p.id),open=items.filter(x=>!isDone(x.state)&&x.commitment!=='candidate'),profile=snapshot.profiles?.[p.id];return <tr key={p.id} role="button" tabIndex={0} onClick={()=>onPerson(p.id)} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();onPerson(p.id)}}}><td><strong><Glyph name={p.name}/>{p.name}</strong><small>{p.category==='support'?'系统支撑':'业务岗位'} · 查看职责与工作方式 ↗</small></td><td>{open.length?compact(open.slice(0,2).map(x=>x.title).join('；'),110):items.length?'已读记录中未见未闭环，原工作仍可能继续':'逐件工作记录未单列，见原对话'}</td><td>{items.length?<><span className="wk-state">{open.length} 项未闭环记录</span><small>候选 {items.filter(x=>x.commitment==='candidate').length} 项另列，非承诺</small></>:'待核，不显示为0'}</td><td><span className={'wk-state '+(p.runtime?.state==='活动中'?'active':'neutral')}>{p.runtime?.state||'未知'}</span><small>输入排队 {p.runtime?.queueCount??'待核'}</small><small>待看会话 {p.reminders?.pending??'待核'}{p.reminders?.error?'（上次结果）':''}</small></td><td>{p.error||`原笔记 ${p.notebooks??'待核'} 份`}<small>{profile?.roleName||'原岗位属性待核'}</small></td></tr>})}</tbody></table></div><p className="wk-footnote">{w.discovery.bindings}条原渠道按真实对话归并。{w.discovery.unadaptedThreads?`另有${w.discovery.unadaptedThreads}个已登记对话尚待读取适配。`:'当前已登记角色均有读取适配。'}已确认身份不代表所有能力或历史业务已经验收。</p></section>
}
