'use strict';
// Shared detail tools. No model calls: explicit metadata and history operations only.
window.TashanToolDetails={
 mount({host,task,detail,api,node:N,button:B,onTaskChange,notice}){
  const box=N('section',{class:'tool-details'}),feedback=N('p',{class:'inline-feedback',role:'status'});
  const refs=task.sourceContacts||[];
  if(refs.length)box.append(N('section',{},N('h3',{},'群聊与联系人'),refs.map(r=>{
   const label=[r.conversation||r.conversationName,r.sender||r.senderName].filter(Boolean).join(' · ');
   const p=N('p',{},label||r.sourceId||'原始来源');
   if(label)p.append(B('复制','text-button',{'aria-label':'复制来源 '+label,onclick:async()=>{try{await navigator.clipboard.writeText(label);notice('已复制群名与昵称');}catch{feedback.textContent='可直接选取上方名称复制';}}}));
   if(r.nativeId||r.recordId)p.append(N('small',{class:'muted'},' '+(r.nativeId||r.recordId)+(r.version?' · '+r.version:'')));
   return p;
  })));
  const beijingLocal=at=>at?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(at)).replace(' ','T'):'';
  const deadline=N('input',{type:'date',value:task.deadlineDate||'','aria-label':'明确截止日期（北京时间）'});
  const condition=N('input',{value:task.followup?.condition||task.condition||'','aria-label':'复看条件',placeholder:'可空；条件尚未证实不会自动触发'});
  const followAt=N('input',{type:'datetime-local',value:beijingLocal(task.followup?.at),'aria-label':'精确复看时刻（北京时间）'});
  const meta=N('details',{class:'tool-metadata'},N('summary',{},'截止与复看'),N('label',{},'截止（可空）',deadline),N('label',{},'复看条件（可空）',condition),N('label',{},'精确复看（北京时间，可空）',followAt),B('保存这些字段','',{onclick:async ev=>{
   const b=ev.currentTarget;b.disabled=true;
   try{
    const body={expectedRevision:task.revision,requestId:crypto.randomUUID(),deadlineDate:deadline.value||null,condition:condition.value};
    if(followAt.value)body.followup={at:followAt.value+':00+08:00',condition:condition.value};
    else if(task.followup?.at||condition.value!==task.followup?.condition)body.followup={date:task.reviewDate||null,condition:condition.value};
    const r=await api('/api/tasks/'+task.id+'/record',body);Object.assign(task,r.task);metadataSnapshot=JSON.stringify([task.deadlineDate,task.condition,task.followup,task.reviewDate]);Object.assign(initialValues,{deadline:deadline.value,condition:condition.value,at:followAt.value});await onTaskChange(r.task);feedback.textContent='字段已保存';
   }catch(e){feedback.textContent=e.message+'；输入保留';}finally{b.disabled=false;}
  }}));
  const initialValues={deadline:deadline.value,condition:condition.value,at:followAt.value};let metadataSnapshot=JSON.stringify([task.deadlineDate,task.condition,task.followup,task.reviewDate]);
  box.updateTask=(next,info)=>{renderAssets(info);const nextSnapshot=JSON.stringify([next.deadlineDate,next.condition,next.followup,next.reviewDate]);const dirty=deadline.value!==initialValues.deadline||condition.value!==initialValues.condition||followAt.value!==initialValues.at;if(dirty&&nextSnapshot!==metadataSnapshot){feedback.textContent='这些字段有新变化；输入保留，保存时请核对版本';return;}task={...next};metadataSnapshot=nextSnapshot;if(!dirty){deadline.value=task.deadlineDate||'';condition.value=task.followup?.condition||task.condition||'';followAt.value=beijingLocal(task.followup?.at);initialValues.deadline=deadline.value;initialValues.condition=condition.value;initialValues.at=followAt.value;}};
  box.append(meta);
  const assetSection=N('section');
  function renderAssets(info){const records=(info?.timeline||[]).filter(e=>e.attachments?.length);assetSection.hidden=!records.length;assetSection.replaceChildren(N('h3',{},'已保存附件'),...records.flatMap(e=>e.attachments.map(a=>N('p',{},N('a',{href:'/api/assets/'+encodeURIComponent(a.id),target:'_blank',rel:'noopener noreferrer'},a.name||a.id),N('small',{class:'muted'},' · '+(e.actor?.name||e.author||'记录'))))));}
  renderAssets(detail);box.append(assetSection);
  const attachments=N('div',{class:'tool-attachments'}),files=N('input',{type:'file',multiple:true,'aria-label':'补充事项附件'}),note=N('textarea',{rows:2,'aria-label':'附件备注',placeholder:'附件说明，可空'});let selected=[];let uploading=false;let attempt=null;
  function renderFiles(){attachments.replaceChildren(selected.map(f=>N('p',{},f.file.name,B('移除','text-button',{onclick:()=>{if(!uploading){selected=selected.filter(v=>v!==f);renderFiles();}}}))));}
  function addFiles(values){for(const file of values){if(file.size>8*1024*1024||selected.length>=10){feedback.textContent='每个附件上限8MB，每次最多10个';continue;}selected.push({file});}renderFiles();}
  files.addEventListener('change',()=>{addFiles(files.files);files.value='';});
  const attachBox=N('details',{class:'tool-attach'},N('summary',{},'补充附件'),files,attachments,note,B('保存附件与备注','',{onclick:async ev=>{
   if(uploading||!selected.length)return;uploading=true;const b=ev.currentTarget;b.disabled=true;const batch=[...selected],sent=note.value;
   try{
    for(const item of batch)if(!item.asset){const bytes=new Uint8Array(await item.file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));item.asset=(await api('/api/uploads',{name:item.file.name,mime:item.file.type,data:btoa(binary)})).asset;}
    const key=JSON.stringify([task.revision,batch.map(x=>x.asset.id),sent]);if(!attempt||attempt.key!==key)attempt={key,body:{expectedRevision:task.revision,attachments:batch.map(x=>x.asset.id),note:sent,requestId:crypto.randomUUID()}};
    const r=await api('/api/tasks/'+task.id+'/record',attempt.body);Object.assign(task,r.task);attempt=null;selected=selected.filter(x=>!batch.includes(x));if(note.value===sent)note.value='';renderFiles();await onTaskChange(r.task);feedback.textContent='附件与备注已保存';
   }catch(e){feedback.textContent=e.message+'；附件和备注保留，可重试';}finally{uploading=false;b.disabled=false;}
  }}));
  attachBox.addEventListener('paste',e=>{const images=[...(e.clipboardData?.files||[])].filter(x=>x.type.startsWith('image/'));if(images.length){e.preventDefault();addFiles(images);}});box.append(attachBox);
  const history=N('details',{class:'tool-history'},N('summary',{},'操作历史与恢复'));
  const list=N('div'),load=B('读取操作历史','',{onclick:async()=>{
   load.disabled=true;try{const result=await api('/api/notebook/changes?'+new URLSearchParams({object_id:task.id,limit:100,cursor:0}));renderOps(result.operations,result.hasMore?result.cursor:null);}catch(e){feedback.textContent='历史读取失败：'+e.message;}finally{load.disabled=false;}
  }});
  function renderOps(ops,next){list.replaceChildren(...[...ops].reverse().map(op=>{
   const e=op.effects.find(e=>e.kind==='object'&&e.id===task.id),changed=e?.before&&e.after?Object.keys(e.after).filter(k=>JSON.stringify(e.before[k])!==JSON.stringify(e.after[k])):[];
   const restorable=changed.filter(k=>['title','kind','domain','state','assignee','counterparty','summary','proposedAt','timeRequirement','deadlineDate','planDate','eventWindow','reviewDate','followup','condition','relatedRecordIds','completionCriterion','recommendation','sourceContacts'].includes(k));
   const item=N('article',{class:'timeline-entry'},N('small',{class:'muted'},`${op.actor.name} · ${new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',dateStyle:'short',timeStyle:'short'}).format(new Date(op.at))} · #${op.sequence}`),N('p',{},restorable.length?'修改：'+restorable.join('、'):'补充记录 / 安排'),N('small',{class:'muted'},op.id));
   if(restorable.length){const choices=N('div',{class:'restore-fields'},restorable.map(k=>N('label',{},N('input',{type:'checkbox',value:k,checked:true}),k)));
    item.append(N('details',{},N('summary',{},'恢复这次修改前的字段'),choices,B('预览恢复','',{onclick:async()=>{
     const fields=[...choices.querySelectorAll('input:checked')].map(x=>x.value);if(!fields.length){feedback.textContent='请先选择字段';return;}
     try{const preview=await api('/api/tasks/'+task.id+'/restore-preview',{sequence:op.sequence-1,fields});const view=N('div',{class:'restore-preview'},N('p',{},'只恢复所选字段，后续记录全部保留。'),Object.entries(preview.changes).map(([k,v])=>N('p',{},k+'：'+JSON.stringify(v.before)+' → '+JSON.stringify(v.after))));const requestId=crypto.randomUUID();view.append(B('确认恢复','primary',{onclick:async ev=>{ev.currentTarget.disabled=true;try{const r=await api('/api/tasks/'+task.id+'/restore',{sequence:preview.sequence,fields,expectedRevision:preview.expectedRevision,requestId});Object.assign(task,r.task);await onTaskChange(r.task);feedback.textContent='已追加恢复记录';view.remove();}catch(e){feedback.textContent=e.message+'；请重新预览';ev.currentTarget.disabled=false;}}}));item.append(view);}catch(e){feedback.textContent=e.message;}
    }})));
   }return item;
  }));if(next!==null)list.append(B('下一页操作','',{onclick:async()=>{try{const r=await api('/api/notebook/changes?'+new URLSearchParams({object_id:task.id,limit:100,cursor:next}));renderOps(r.operations,r.hasMore?r.cursor:null);}catch(e){feedback.textContent=e.message;}}}));}
  history.append(load,list);box.append(history,feedback);host.append(box);return box;
 }
};
