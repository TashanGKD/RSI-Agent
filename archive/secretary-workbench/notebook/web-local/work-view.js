'use strict';
// A view over canonical matters, never a second client-side work ledger.
window.TashanWorkView={create({api,node,button,openDetail,today,addDays}){
 let start=addDays(today(),-7),end=today(),person='',organization='',keyword='',generation=0,host;
 async function load(){
  const gen=++generation;const region=host.querySelector('.work-region');region.replaceChildren(node('p',{class:'muted'},'正在读取…'));
  try{
   let cursor=0,rows=[],data,snapshot='';
   do{data=await api('/api/notebook/work?'+new URLSearchParams({start,end,person,organization,keyword,cursor:String(cursor),snapshot,limit:'500'}));if(gen!==generation)return;rows.push(...data.objects);cursor=data.cursor;snapshot=data.snapshot;}while(data.hasMore);
   for(const [key,values,label]of [['person',data.people,'全部参与人'],['organization',data.organizations,'全部组织']]){
    const select=host.querySelector(`[name="${key}"]`),selected=select.value;select.replaceChildren(...['',...new Set(['待定',...values,selected].filter(Boolean))].map(v=>node('option',{value:v},v||label)));select.value=selected;
   }
   if(!rows.length){region.replaceChildren(node('p',{class:'empty'},'这个范围没有已记录的工作。'));return;}
   const table=node('section',{class:'work-table','aria-label':'发生的工作列表'},node('div',{class:'work-head','aria-hidden':'true'},['事项','相关人／组织','发生时间','当前状态'].map(x=>node('span',{},x))));
   for(const t of rows){
    const entries=t.workEntries;const latest=entries[0].work;const when=latest.start?(latest.start===latest.end?latest.start:`${latest.start} — ${latest.end}`):'发生时间待定';
    const row=node('article',{class:'work-row','data-task-id':t.id,tabindex:0,'aria-label':t.title,onclick:e=>{if(!e.target.closest('button,a,input,textarea,select'))openDetail(t.id);},onkeydown:e=>{if(e.key==='Enter'&&e.target===row){e.preventDefault();openDetail(t.id);}}},
     node('div',{},button(t.title,'task-title',{onclick:()=>openDetail(t.id)}),node('p',{class:'small muted'},`${entries.length}条进展`)),
     node('div',{class:'work-people'},t.workParticipants.join('、')||'参与人待定',node('p',{class:'small muted'},t.workOrganizations.join('、')||'组织待定')),
     node('div',{class:'work-time'},when),node('div',{},node('span',{class:'state-badge'},t.state)));
    table.append(row);
   }
   region.replaceChildren(node('div',{class:'small muted work-count'},`${rows.length}个事项`),table);
  }catch(e){if(gen!==generation)return;region.replaceChildren(node('p',{role:'alert'},'读取失败：'+e.message),button('重试','',{onclick:load}));}
 }
 function mount(el){
  host=el;const from=node('input',{type:'date',value:start,'aria-label':'发生日期从',onchange:e=>start=e.target.value});
  const to=node('input',{type:'date',value:end,'aria-label':'发生日期至',onchange:e=>end=e.target.value});
  const select=(name,label,value,change)=>node('label',{},node('span',{},label),node('select',{name,'aria-label':label,onchange:e=>change(e.target.value)},node('option',{value:''},'全部'),value?node('option',{value,selected:true},value):null));
  host.replaceChildren(node('form',{class:'work-filters',onsubmit:e=>{e.preventDefault();load();}},
   node('div',{class:'work-dates'},node('label',{},node('span',{},'从'),from),node('label',{},node('span',{},'至'),to)),
   select('person','实际参与人',person,v=>person=v),select('organization','组织',organization,v=>organization=v),
   node('label',{class:'work-search'},node('span',{},'搜索'),node('input',{type:'search',value:keyword,placeholder:'查事项或进展','aria-label':'搜索工作',oninput:e=>keyword=e.target.value})),node('button',{type:'submit',class:'primary'},'查看'),
   node('div',{class:'work-shortcuts'},[['今天',0],['近7天',6],['近30天',29],['全部时间',null]].map(([label,n])=>button(label,'text-button',{onclick:()=>{start=n===null?'':addDays(today(),-n);end=n===null?'':today();from.value=start;to.value=end;load();}})))),node('div',{class:'work-region','aria-live':'polite'}));load();
 }
 return {mount,dispose(){generation++;host=null;}};
}};
