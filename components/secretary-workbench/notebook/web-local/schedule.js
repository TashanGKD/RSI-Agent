'use strict';
// A single UI adapter for all schedule views; business filters live on the server.
window.TashanSchedule=(()=>{
 const labels={'待办':'未完成','等对方':'等对方','暂缓':'暂缓','其他':'其他','已完成':'已完成','不用管了':'无需处理'};
 const states=['待办','已完成','等对方','暂缓','不用管了','其他'];
 const stateClass={'待办':'pending','已完成':'complete','等对方':'waiting','暂缓':'paused','不用管了':'ended','其他':'other'};
 const domains=['科研','他山','示例项目项目','个人生活'];
 const plus=(day,n)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);};
 const weekStart=d=>plus(d,-((new Date(d+'T12:00:00Z').getUTCDay()+6)%7));
 const monthStart=d=>d.slice(0,7)+'-01';
 const dateText=d=>new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'long',day:'numeric',weekday:'short'}).format(new Date(d+'T12:00:00Z'));
 const minutes=t=>Number(t.slice(0,2))*60+Number(t.slice(3,5));
 const timeText=e=>e.startTime?e.startTime+(e.endTime?'—'+e.endTime:''):'';
 const storeKey='tashan-schedule-drafts-v1';
 function create({api,node:N,button:B,notice,onTaskChange,today,owners=()=>[]}){
  let host,date=today(),mode='list',owner='我',domain='',data=null,generation=0,active=null,dialog=null;
  const drafts=new Map();try{for(const [id,d]of Object.entries(JSON.parse(localStorage.getItem(storeKey)||'{}')))drafts.set(id,{...d,legacyPostpone:d.postponeTo||d.legacyPostpone,saving:false});}catch{}
  const persist=()=>{try{localStorage.setItem(storeKey,JSON.stringify(Object.fromEntries([...drafts].map(([id,d])=>[id,{...d,saving:false}]))));}catch{}};
  function draft(e){let d=drafts.get(e.id);if(!d){d={state:e.state,note:'',followupChoice:e.followup?.date?{date:e.followup.date}:null,followupDirty:false,revision:e.revision,objectRevision:e.objectRevision,error:'',saving:false,attempt:null,otherText:'',customPostpone:false};drafts.set(e.id,d);}return d;}
  function period(){if(mode==='week'){const start=weekStart(date);return[start,plus(start,6)];}if(mode==='month'){const start=weekStart(monthStart(date));return[start,plus(start,41)];}return[date,date];}
  function opt(values,value,label,onchange){const s=N('select',{'aria-label':label,onchange:e=>onchange(e.target.value)});for(const [v,l]of values)s.append(N('option',{value:v},l));s.value=value;return s;}
  function nav(){
   const dateInput=N('input',{type:'date',value:date,'aria-label':'日程日期（北京时间）',onclick:ev=>{try{ev.target.showPicker?.();}catch{}},onchange:ev=>{if(ev.target.value){date=ev.target.value;refresh();}}});
   const dateControl=N('label',{class:'schedule-date-filter'},N('span',{class:'schedule-date-face','aria-hidden':'true'},`${Number(date.slice(5,7))}月${Number(date.slice(8,10))}日 ⌄`),dateInput);
   const ownerValues=[['我','我'],['AI','AI'],['','全部'],...[...new Set([...owners(),...(data?.entries||[]).map(e=>e.assignee)])].filter(x=>x&&!['我','AI'].includes(x)).map(x=>[x,x])];
   const filterStrip=N('div',{class:'schedule-filter-strip'},dateControl,
    opt([['','归属：全部'],...domains.map(x=>[x,'归属：'+x])],domain,'日程归属',v=>{domain=v;refresh();}),
    opt(ownerValues.map(([v,l])=>[v,'负责人：'+l]),owner,'日程负责人',v=>{owner=v;refresh();}));
   const views=N('div',{class:'schedule-view-switch','aria-label':'日程视图'},[['list','列表'],['day','日'],['week','周'],['month','月']].map(([v,l])=>B(l,'',{'aria-pressed':String(mode===v),'data-schedule-view':v,onclick:()=>{mode=v;refresh();}})));
   return N('section',{class:'schedule-toolbar','aria-label':'日程筛选与视图'},filterStrip,views);
  }
  function syncNav(){
   const toolbar=host?.querySelector('.schedule-toolbar');if(!toolbar)return;
   for(const b of toolbar.querySelectorAll('[data-schedule-view]'))b.setAttribute('aria-pressed',String(b.dataset.scheduleView===mode));
   toolbar.querySelector('.schedule-date-face').textContent=`${Number(date.slice(5,7))}月${Number(date.slice(8,10))}日 ⌄`;
   const input=toolbar.querySelector('input');if(input!==document.activeElement)input.value=date;
  }
  async function refresh(){
   if(!host?.isConnected)return;
   const focused=document.activeElement,focusId=focused?.closest('[data-schedule-editor]')?.dataset.scheduleEditor;
   const fieldClass=focused?.matches('.schedule-note')?'schedule-note':focused?.matches('.schedule-other-text')?'schedule-other-text':null;
   const selection=fieldClass?[focused.selectionStart,focused.selectionEnd]:null,scrollY=window.scrollY,token=++generation;
   if(!host.querySelector('.schedule-toolbar'))host.replaceChildren(nav(),N('div',{class:'schedule-content'}));
   syncNav();const area=host.querySelector('.schedule-content');area.setAttribute('aria-busy','true');area.inert=true;
   if(!data)area.replaceChildren(N('div',{class:'schedule-loading',role:'status'},'读取日程…'));
   const [start,end]=period();
   try{
    const q=new URLSearchParams({start,end,assignee:owner,domain}),result=await api('/api/schedule?'+q);
    if(token!==generation||!host?.isConnected)return;data=result;area.inert=false;area.setAttribute('aria-busy','false');renderContent();
    if(focusId&&selection){const restored=[...host.querySelectorAll('[data-schedule-editor]')].find(x=>x.dataset.scheduleEditor===focusId)?.querySelector('.'+fieldClass);if(restored?.getBoundingClientRect().height){restored.focus({preventScroll:true});restored.setSelectionRange(...selection);}}
    window.scrollTo({top:scrollY});
   }catch(err){if(token!==generation||!host?.isConnected)return;area.inert=false;area.setAttribute('aria-busy','false');area.replaceChildren(N('div',{class:'empty'},'日程读取失败：'+err.message,B('重试','',{onclick:refresh})));}
  }
  function renderContent(){const target=host.querySelector('.schedule-content');if(!target)return;target.replaceChildren();if(mode==='list')renderList(target);else if(mode==='month')renderMonth(target);else renderGrid(target);}
  function row(e){
   const r=N('article',{class:'schedule-row '+(e.state==='已完成'?'is-complete':''),'data-entry-id':e.id,tabindex:0,onfocusin:()=>active=e,onpointerdown:()=>active=e,onclick:ev=>{if(ev.target.closest('button,input,textarea,select,a,summary')||getSelection()?.toString())return;openDetail(e);}});
   r.append(N('div',{class:'schedule-domain'},e.domain||'未归属'),
    N('div',{class:'schedule-title'},N('div',{class:'schedule-title-line'},B(e.title,'schedule-title-button',{onclick:()=>openDetail(e)}),timeText(e)?N('span',{class:'schedule-time'},timeText(e)):null),e.summary?N('p',{class:'schedule-summary',title:e.summary},e.summary):null,(e.warnings||[]).map(w=>N('p',{class:'schedule-warning'},w))),
    editor(e),N('div',{class:'schedule-confirm'},B('确认','primary',{'data-schedule-confirm':e.id,onclick:()=>save(e)})));
   return r;
  }
  function renderList(target){const entries=data.entries;target.append(N('div',{class:'schedule-head','aria-hidden':'true'},['归属','事项','处理','确认'].map(x=>N('span',{},x))));let shown=false;
   for(const original of data.groups){const g=original.state==='待办'?{...original,entries:[...original.entries,...data.overdue].sort((a,b)=>(domains.indexOf(a.domain)<0?99:domains.indexOf(a.domain))-(domains.indexOf(b.domain)<0?99:domains.indexOf(b.domain))||String(a.startTime||'99:99').localeCompare(String(b.startTime||'99:99'))||a.date.localeCompare(b.date)||a.id.localeCompare(b.id))}:original;if(!g.entries.length)continue;shown=true;const details=N('details',{class:'schedule-group',open:g.state==='待办'},N('summary',{},g.label,N('span',{class:'count'},g.entries.length)));for(const e of g.entries)details.append(row(e));target.append(details);}
   if(data.unscheduled.length){shown=true;target.append(N('details',{class:'schedule-group'},N('summary',{},'未安排',N('span',{class:'count'},data.unscheduled.length)),data.unscheduled.map(t=>N('div',{class:'unscheduled-row'},N('span',{},t.title),B('安排日期','',{onclick:()=>scheduleExisting(t)})))));}
   if(!shown)target.append(N('div',{class:'empty'},'这一天暂无日程'));
  }
  function conflictButton(e){const d=draft(e);return B('保留草稿，核对最新版本','',{onclick:async()=>{try{const r=await api('/api/schedule/'+e.id);d.revision=r.entry.revision;d.objectRevision=r.entry.objectRevision;d.conflict=false;d.attempt=null;d.error='已载入最新版本：'+labels[r.entry.state]+'。请核对草稿后再次确认';sync(e);persist();}catch(err){notice(err.message);}}});}
  function editor(e,detail=false){
   const d=draft(e);
   const statesRow=N('div',{class:'schedule-states',role:'radiogroup','aria-label':'日程状态'},states.map(st=>B(labels[st],'schedule-state',{role:'radio','aria-checked':String(d.state===st),'data-value':st,onclick:()=>{active=e;d.state=st;d.attempt=null;d.error='';persist();sync(e);}})));
   const dateInput=N('input',{type:'date',class:'schedule-postpone-date',value:d.followupChoice?.date||'',min:today(),'aria-label':'复看日期（北京时间）',onchange:ev=>{d.followupChoice=ev.target.value?{date:ev.target.value}:null;d.followupDirty=true;d.attempt=null;d.error='';persist();sync(e);}});
   const postponeRow=N('div',{class:'schedule-inline-postpone',hidden:!['暂缓','等对方'].includes(d.state)&&!d.showFollowup},N('span',{class:'schedule-inline-label'},'再提醒我'),[[1,'1天后'],[2,'2天后'],[3,'3天后'],[7,'7天后']].map(([n,l])=>B(l,'',{'data-postpone':String(n),'aria-pressed':String(!d.customPostpone&&d.followupChoice?.date===plus(today(),n)),disabled:false,onclick:()=>{const value=plus(today(),n);d.followupChoice=!d.customPostpone&&d.followupChoice?.date===value?null:{date:value};d.followupDirty=true;d.customPostpone=false;d.attempt=null;d.error='';persist();sync(e);}})),B('指定日期','',{'data-postpone':'custom','aria-pressed':String(!!d.customPostpone),onclick:()=>{d.customPostpone=!d.customPostpone;persist();sync(e);if(d.customPostpone)dateInput.focus();}}),dateInput,N('span',{class:'schedule-postpone-label'}),B('取消复看','text-button',{onclick:()=>{d.followupChoice=null;d.followupDirty=true;d.customPostpone=false;persist();sync(e);}}));
   const otherRow=N('label',{class:'schedule-inline-other',hidden:d.state!=='其他'},N('span',{class:'schedule-inline-label'},'说明'),N('input',{type:'text',class:'schedule-other-text',placeholder:'补充其他情况…','aria-label':'其他说明',value:d.otherText||'',oninput:ev=>{d.otherText=ev.target.value;d.attempt=null;persist();sync(e);}}));
   const note=N('textarea',{class:'schedule-note',rows:1,placeholder:'写备注…','aria-label':'备注',value:d.note,oninput:ev=>{d.note=ev.target.value;d.attempt=null;persist();sync(e);}});
   const wrap=N('div',{class:'schedule-editor','data-schedule-editor':e.id},statesRow,postponeRow,otherRow,d.legacyPostpone?N('small',{class:'muted'},'旧改期草稿保留：'+d.legacyPostpone.date+'；本行改为只设复看，明确改期请在详情操作。'):null,N('div',{class:'schedule-note-line'},note,B('添加备注','text-button schedule-add-note',{onclick:()=>save(e,true)})),N('div',{class:'schedule-editor-error',role:'status'},d.error));
   if(d.conflict)wrap.querySelector('.schedule-editor-error').append(conflictButton(e));
   dateInput.hidden=!d.customPostpone;if(d.followupChoice?.date&&!d.customPostpone)postponeRow.querySelector('.schedule-postpone-label').textContent=`${Number(d.followupChoice.date.slice(5,7))}月${Number(d.followupChoice.date.slice(8,10))}日`;if(detail)wrap.append(B('确认','primary',{'data-schedule-confirm':e.id,onclick:()=>save(e)}));return wrap;
  }
  function sync(e){
   const d=draft(e);
   for(const w of document.querySelectorAll('[data-schedule-editor]')){
    if(w.dataset.scheduleEditor!==e.id)continue;
    for(const b of w.querySelectorAll('[data-value]')){b.setAttribute('aria-checked',String(b.dataset.value===d.state));b.disabled=d.saving;}
    for(const [selector,value]of [['.schedule-note',d.note],['.schedule-other-text',d.otherText||''],['.schedule-postpone-date',d.followupChoice?.date||'']]){const input=w.querySelector(selector);if(input!==document.activeElement)input.value=value;}
    w.querySelector('.schedule-inline-postpone').hidden=!['暂缓','等对方'].includes(d.state)&&!d.showFollowup;w.querySelector('.schedule-inline-other').hidden=d.state!=='其他';
    w.querySelector('.schedule-postpone-date').hidden=!d.customPostpone;
    w.querySelector('.schedule-postpone-label').textContent=d.followupChoice?.date&&!d.customPostpone?`${Number(d.followupChoice.date.slice(5,7))}月${Number(d.followupChoice.date.slice(8,10))}日`:'';
    for(const b of w.querySelectorAll('[data-postpone]')){const n=Number(b.dataset.postpone);b.setAttribute('aria-pressed',String(n?!d.customPostpone&&d.followupChoice?.date===plus(today(),n):!!d.customPostpone));b.disabled=d.saving;}
    w.querySelector('.schedule-add-note').disabled=d.saving;
    const error=w.querySelector('.schedule-editor-error');error.replaceChildren(d.error?N('span',{},d.error):null);
    if(d.conflict)error.append(conflictButton(e));
   }
   for(const b of document.querySelectorAll('[data-schedule-confirm]'))if(b.dataset.scheduleConfirm===e.id){b.disabled=d.saving;b.textContent=d.saving?'保存中…':'确认';}
  }
  async function save(e,noteOnly=false,extra={}){
   const d=draft(e);if(d.saving)return;
   if(d.conflict){notice('请先核对最新版本，草稿已保留');return;}
   if(noteOnly&&!d.note.trim()){notice('先写一句备注');return;}
   const combinedNote=[!noteOnly&&d.state==='其他'&&d.otherText?.trim()?'说明：'+d.otherText:'',d.note.trim()?d.note:''].filter(Boolean).join('\n');
   const base={expectedRevision:d.revision,expectedObjectRevision:d.objectRevision,...(noteOnly?{}:{state:d.state,...(d.followupDirty?{followup:d.followupChoice?{date:d.followupChoice.date}:null}:{})}),...(combinedNote?{note:combinedNote}:{}),...extra};
   const key=JSON.stringify(base),request=d.attempt?.key===key?d.attempt.body:{...base,requestId:crypto.randomUUID()};d.attempt={key,body:request};
   const sentNote=d.note,sentOther=d.otherText,sentDate=d.followupChoice;d.saving=true;d.error='';sync(e);
   try{
    const r=await api('/api/schedule/'+e.id+'/record',request);d.revision=r.entry.revision;d.objectRevision=r.entry.objectRevision;d.attempt=null;d.saving=false;
    if(d.followupChoice===sentDate&&!noteOnly){d.followupDirty=false;d.customPostpone=false;}
    if(d.note===sentNote)d.note='';if(!noteOnly&&d.state==='其他'&&d.otherText===sentOther)d.otherText='';if(!noteOnly)d.state=r.entry.state;
    persist();sync(e);notice('已保存');Object.assign(e,r.entry);
    try{const detail=await api('/api/tasks/'+e.objectId);onTaskChange(detail.task);}catch{}
    if(!noteOnly)await refresh();if(dialog?.isConnected){const updated=await api('/api/schedule/'+e.id);renderDetail(updated.entry,dialog,true);}
   }catch(err){d.saving=false;d.error=err.message+'；草稿已保留';d.conflict=err.status===409;persist();sync(e);}
  }
  // Reset WebKit's retained badInput in an explicitly cleared optional time field.
  function clearTimeButton(start,end){return B('不设时段','text-button',{onclick:()=>{for(const input of [start,end]){input.type='text';input.value='';input.type='time';}}});}
  function modal(title,cls='schedule-dialog'){const m=N('dialog',{class:cls,'aria-label':title},N('div',{class:'dialog-head'},N('h2',{},title),B('×','close-button',{'aria-label':'关闭'+title,onclick:()=>m.close()})),N('div',{class:'schedule-dialog-body'}));m.addEventListener('close',()=>{m.remove();});document.querySelector('#dialogs').append(m);m.showModal();return m;}
  function card(e){return B(N('span',{},e.title,timeText(e)?N('small',{},timeText(e)):null),'calendar-entry state-'+stateClass[e.state],{'data-calendar-entry':e.id,title:labels[e.state]+' · '+e.title,onclick:()=>openDetail(e)});}
  function renderGrid(target){const [start,end]=period();const days=[];for(let d=start;d<=end;d=plus(d,1))days.push(d);
   const scroller=N('div',{class:'schedule-grid-scroll',tabindex:0,'aria-label':mode==='week'?'周日程表，可横向滚动':'日日程表'});const grid=N('div',{class:'calendar-grid '+(mode==='week'?'week-grid':'day-grid')});grid.style.setProperty('--days',days.length);
   grid.append(N('div',{class:'calendar-corner day-label'},'北京时间'),...days.map(d=>B(dateText(d),'calendar-day-heading'+(d===today()?' is-today':''),{onclick:()=>{date=d;mode='list';refresh();}})));
   grid.append(N('div',{class:'calendar-corner no-time'},'当天事项'),...days.map(d=>N('div',{class:'calendar-unslotted'},data.entries.filter(e=>e.date===d&&!e.startTime).map(card))));
   const gutter=N('div',{class:'calendar-hours'},Array.from({length:24},(_,h)=>N('div',{},String(h).padStart(2,'0')+':00')));grid.append(gutter);
   for(const d of days){const events=data.entries.filter(e=>e.date===d&&e.startTime).sort((a,b)=>a.startTime.localeCompare(b.startTime));let maxLane=0;const lanes=[];const positions=events.map(e=>{const from=minutes(e.startTime),to=Math.max(from+42,e.endTime?minutes(e.endTime):from+42);let lane=lanes.findIndex(t=>t<=from);if(lane<0)lane=lanes.length;lanes[lane]=to;maxLane=Math.max(maxLane,lane+1);return{e,from,to,lane};});const column=N('div',{class:'calendar-day-track'});for(const {e,from,to,lane}of positions){const c=card(e);c.style.top=(from/60*60)+'px';c.style.height=Math.max(42,(to-from))+'px';c.style.left=`calc(${lane/maxLane*100}% + 3px)`;c.style.width=`calc(${100/maxLane}% - 6px)`;if(!e.endTime)c.classList.add('open-ended');column.append(c);}grid.append(column);}
   scroller.append(grid);target.append(scroller);const firstTimed=data.entries.filter(e=>e.startTime).map(e=>minutes(e.startTime));if(firstTimed.length)requestAnimationFrame(()=>{scroller.scrollTop=Math.max(0,(Math.min(...firstTimed)/60-1)*60);});
  }
  function renderMonth(target){const [start,end]=period();const grid=N('div',{class:'calendar-month'});for(const d of ['一','二','三','四','五','六','日'])grid.append(N('div',{class:'month-weekday'},d));for(let d=start;d<=end;d=plus(d,1)){const cellDate=d;const entries=data.entries.filter(e=>e.date===cellDate);const c=N('div',{class:'month-cell'+(d.slice(0,7)!==date.slice(0,7)?' outside-month':'')},B(d.slice(-2),'month-date'+(d===today()?' is-today':''),{onclick:()=>{date=cellDate;mode='list';refresh();}}));for(const e of entries.slice(0,3))c.append(card(e));if(entries.length>3)c.append(B('+'+(entries.length-3)+' 更多','month-more',{onclick:()=>{date=cellDate;mode='list';refresh();}}));grid.append(c);}target.append(grid);}
  async function openDetail(e){active=e;if(dialog)dialog.close();dialog=modal('日程详情','schedule-dialog schedule-detail');renderDetail(e,dialog);}
  async function renderDetail(e,m,preserveEditor=false){if(!m.isConnected)return;const body=m.querySelector('.schedule-dialog-body');if(!preserveEditor)body.replaceChildren(N('h2',{},e.title),N('p',{class:'muted'},e.domain+' · '+dateText(e.date)+(timeText(e)?' · '+timeText(e):'')),editor(e,true));let read=preserveEditor?body.querySelector('.schedule-detail-read'):null;if(!read){read=N('div',{class:'schedule-detail-read'},N('p',{class:'muted'},'读取依据与记录…'));body.append(read);}
   if(!preserveEditor){const timeStart=N('input',{type:'time',value:e.startTime||'','aria-label':'本次开始时间'}),timeEnd=N('input',{type:'time',value:e.endTime||'','aria-label':'本次结束时间'});body.append(N('details',{class:'schedule-edit-time'},N('summary',{},'调整本次时段'),N('div',{class:'schedule-time-inputs'},N('label',{},'开始（可空）',timeStart),N('label',{},'结束（可空）',timeEnd)),clearTimeButton(timeStart,timeEnd),B('保存时段','',{onclick:()=>save(e,false,{startTime:timeStart.value||null,endTime:timeEnd.value||null})})));}
   if(!preserveEditor){const moveDate=N('input',{type:'date','aria-label':'明确改期日期（北京时间）',min:plus(e.date,1)});body.append(N('details',{class:'schedule-edit-time'},N('summary',{},'明确改期'),N('label',{},'改到哪天执行',moveDate),B('保存改期','',{onclick:()=>{if(!moveDate.value){notice('请选择新的执行日期');return;}save(e,false,{state:'暂缓',postponeTo:{date:moveDate.value,startTime:e.startTime||null,endTime:e.endTime||null}});}})));}
   try{const r=await api('/api/tasks/'+e.objectId);if(!m.isConnected)return;const preservedTools=preserveEditor?read.querySelector('.tool-details'):null;read.replaceChildren(N('div',{class:'schedule-detail-facts'},r.task.counterparty?N('p',{},'相关人：'+r.task.counterparty):null,r.task.completionCriterion?N('p',{},'完成标准：'+r.task.completionCriterion):null,r.task.deadlineDate?N('p',{},'截止：'+r.task.deadlineDate):null),r.task.summary?N('section',{},N('h3',{},'事项摘要'),N('p',{},r.task.summary)):null,N('section',{},N('h3',{},'来源'),(r.task.sourceContacts||[]).map(c=>N('p',{},[c.channel,c.conversationName,c.senderName].filter(Boolean).join(' · '))),(r.evidence||[]).map(s=>N('blockquote',{},s.localOnly?'原始资料保留Mac；线上提供摘要与定位。':s.quote||''))),N('section',{},N('h3',{},'记录'),(r.timeline||[]).map(t=>N('article',{class:'timeline-entry'},N('small',{class:'muted'},(t.actor?.name||t.author||'记录')+' · '+formatStamp(t.at)),N('p',{},t.note||t.body||t.text||describe(t.changes))))));if(preservedTools){preservedTools.updateTask?.(r.task,r);read.append(preservedTools);}else window.TashanToolDetails?.mount({host:read,task:r.task,detail:r,api,node:N,button:B,notice,onTaskChange:async t=>{onTaskChange(t);await drafUpdate(t);await refresh();}});async function drafUpdate(t){const d=draft(e);const changed=d.note.trim()||d.otherText?.trim()||d.state!==e.state||d.followupDirty;const latest=(await api('/api/schedule/'+e.id)).entry;if(changed){d.conflict=true;d.error='事项有新变化，请核对草稿';}else{d.state=latest.state;d.revision=latest.revision;d.objectRevision=latest.objectRevision;Object.assign(e,latest);}d.attempt=null;sync(e);persist();}}catch(err){read.replaceChildren(N('p',{},'详情读取失败：'+err.message));}
  }
  function formatStamp(v){if(!v)return '';const d=new Date(v);return Number.isNaN(d.getTime())?v:new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(d);}
  function describe(changes){return Object.entries(changes||{}).filter(([k])=>!['updatedAt','updatedBy'].includes(k)).map(([k,v])=>({state:'状态',planDate:'安排日期',reviewDate:'复查日期',eventWindow:'时段'})[k]+': '+(typeof v==='object'?JSON.stringify(v):v)).join('；')||'保存安排';}
  function newSchedule(){editForm(null);}
  function scheduleExisting(t){editForm(t);}
  function editForm(task){const m=modal(task?'安排日期':'新建日程');const body=m.querySelector('.schedule-dialog-body');const title=N('input',{'aria-label':'事项名称',value:task?.title||'',required:true,readonly:!!task});const dt=N('input',{type:'date','aria-label':'安排日期',value:date,required:true});const st=N('input',{type:'time','aria-label':'开始时间'}),en=N('input',{type:'time','aria-label':'结束时间'});const ds=opt([['','未归属'],...domains.map(x=>[x,x])],task?.domain||domain,'归属',()=>{}),who=N('input',{'aria-label':'负责人',value:task?.assignee||owner||'我'});if(task){ds.disabled=true;who.readOnly=true;}const note=N('textarea',{'aria-label':'备注',placeholder:'写备注…'});const error=N('p',{role:'status',class:'schedule-editor-error'});
   const form=N('form',{class:'new-form',onsubmit:async ev=>{ev.preventDefault();const b=form.querySelector('[type=submit]');b.disabled=true;try{if(!dt.value)throw new Error('请选择安排日期');if(en.value&&(!st.value||en.value<=st.value))throw new Error('结束须晚于开始；跨日请分别安排');let r;if(task)r=await api('/api/schedule',{objectId:task.id,date:dt.value,startTime:st.value||null,endTime:en.value||null,note:note.value,expectedObjectRevision:task.revision,requestId:crypto.randomUUID()});else{const eventWindow=st.value?{start:dt.value+'T'+st.value+':00+08:00',end:en.value?dt.value+'T'+en.value+':00+08:00':null}:null;r=await api('/api/tasks',{title:title.value.trim(),state:'待办',kind:'action',domain:ds.value,assignee:who.value.trim(),planDate:dt.value,eventWindow,confirm:true,note:note.value,requestId:crypto.randomUUID()});onTaskChange(r.task);}m.close();date=dt.value;mode='list';await refresh();notice('日程已保存');}catch(err){error.textContent=err.message;b.disabled=false;}}},N('label',{},'事项名称',title),N('div',{class:'schedule-time-inputs'},N('label',{},'归属',ds),N('label',{},'负责人',who)),N('label',{},'北京日期',dt),N('div',{class:'schedule-time-inputs'},N('label',{},'开始（可空）',st),N('label',{},'结束（可空）',en)),clearTimeButton(st,en),N('label',{},'备注',note),error,N('button',{class:'primary',type:'submit'},'保存日程'));body.append(form);title.focus();
  }
  document.addEventListener('keydown',ev=>{const target=ev.target;if(ev.key!=='Enter'||!(target instanceof Element)||!target.closest('.schedule-root,.schedule-dialog'))return;if(ev.isComposing||ev.keyCode===229||ev.repeat||ev.shiftKey||ev.altKey||ev.metaKey||ev.ctrlKey){if(target.closest('.schedule-state,[data-postpone]'))ev.preventDefault();return;}if(target.closest('form,select,a')||(target.closest('input')&&!target.matches('.schedule-other-text'))||target.closest('dialog')&&!target.closest('.schedule-editor'))return;const id=target.closest('[data-schedule-editor]')?.dataset.scheduleEditor||target.closest('[data-entry-id]')?.dataset.entryId;if(!id)return;const e=[...(data?.entries||[]),...(data?.overdue||[])].find(e=>e.id===id)||active;if(!e)return;if(target.closest('button')&&!target.closest('.schedule-state,[data-postpone]'))return;ev.preventDefault();ev.stopPropagation();save(e);});
  return{mount(element){host=element;host.classList.add('schedule-root');refresh();},refresh,dispose(){generation++;host=null;},persist};
 }
 return{create};
})();
