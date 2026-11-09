import {marker,unpackItems,finalReply} from './native_rpc.mjs';
const observedTime=t=>Number.isFinite(t)&&t>=0?t:null;

// New inputs correlate via native metadata only; markers serve legacy journals.
function matched(items,request){
 const id=request.client_id,legacy=(request.input_format??'legacy-v1')==='legacy-v1';
 return unpackItems(items).find(i=>i?.type==='userMessage'&&(
  i.clientId===id||i.id===id||
  (request.native_message_id&&i.id===request.native_message_id)||
  (legacy&&(i.content||[]).some(c=>c.type==='text'&&typeof c.text==='string'&&c.text.startsWith(marker(id)+'\n')))
 ));
}
export async function reconcile(rpc,threadId,request,{checkpoint=async()=>{}}={}){
 const id=request.client_id;
 if(typeof id!=='string'||!/^weixin-[a-f0-9]{64}$/.test(id))throw Error('invalid request identity');
 if(!['raw-v2','legacy-v1'].includes(request.input_format??'legacy-v1'))throw Error('invalid input format');
 let cursor=null,firstQueueId=null,existing=null,queueComplete=false;
 for(let page=0;page<10;page++){
  const q=await rpc.call('thread/queue/list',{threadId,limit:100,...(cursor?{cursor}:{})});
  if(!Array.isArray(q.data))throw Error('invalid native queue');
  firstQueueId??=q.data[0]?.id;
  const matches=q.data.filter(x=>x.clientUserMessageId===id);
  if(matches.length>1)return{state:'identity_conflict'};
  existing=matches[0];
  if(existing){queueComplete=true;break;}
  cursor=q.nextCursor;if(!cursor){queueComplete=true;break;}
 }
 if(!queueComplete)return{state:'history_incomplete'};
 if(existing){
  if(request.queue_id&&request.queue_id!==existing.id)return{state:'identity_conflict'};
  const state={state:'queued',queue_id:existing.id,queued_at:request.queued_at??null};
  await checkpoint(state);
  const latest=await rpc.call('thread/read',{threadId,includeTurns:false});
  if(latest.thread?.status?.type==='idle'&&firstQueueId===existing.id){
   await checkpoint({...state,state:'starting'});
   const started=await rpc.call('thread/queue/start',{threadId,queuedSubmissionId:existing.id});
   if(typeof started.turn?.id==='string'){
    state.turn_id=started.turn.id;
    state.native_started_at=observedTime(started.turn.startedAt)??request.native_started_at??null;
    const item=matched(started.turn.items||[],request);
    if(item)state.native_message_id=item.id;
   }
   await checkpoint(state);
  }
  return state;
 }
 cursor=null;let found=null,userItem=null,head=null,complete=false;
 for(let page=0;page<100;page++){
  const result=await rpc.call('thread/turns/list',{threadId,limit:100,sortDirection:'desc',itemsView:'notLoaded',...(cursor?{cursor}:{})});
  if(!Array.isArray(result.data))throw Error('invalid native history');
  head??=result.data[0]?.id;
  if(request.allow_new===true&&request.action==='poll'&&!request.submission_attempted&&!request.turn_id&&!request.queue_id)return{state:'not_found',head_turn_id:head};
  for(const t of result.data){
   if(!request.turn_id||t.id===request.turn_id){
    let itemCursor=null;
    for(let itemPage=0;itemPage<10;itemPage++){
     const start=await rpc.call('thread/items/list',{threadId,turnId:t.id,limit:100,sortDirection:'asc',...(itemCursor?{cursor:itemCursor}:{})});
     if(!Array.isArray(start.data))throw Error('invalid native items');
     userItem=matched(start.data,request);
     if(userItem){found=t;break;}
     itemCursor=start.nextCursor;if(!itemCursor)break;
     if(itemPage===9)return{state:'history_incomplete'};
    }
   }
   if(found)break;
   if(t.id===request.anchor_turn_id){complete=true;break;}
  }
  if(found||complete)break;
  cursor=result.nextCursor;if(!cursor){complete=true;break;}
 }
 if(found){
  const identity={turn_id:found.id,native_message_id:userItem.id,
   native_started_at:observedTime(found.startedAt)??request.native_started_at??null,native_completed_at:observedTime(found.completedAt)??request.native_completed_at??null};
  await checkpoint({state:'running',...identity});
  if(['completed','failed','interrupted'].includes(found.status)&&Number.isFinite(found.completedAt)){
   const page=await rpc.call('thread/items/list',{threadId,turnId:found.id,limit:100,sortDirection:'desc'});
   const reply=finalReply((page.data||[]).slice().reverse());
   const result={state:found.status==='completed'?'completed':'failed',...identity,reply:reply||'本次处理已结束，但未取得最终答复。请在同一个Codex对话查看结果。'};
   await checkpoint({...identity,state:result.state});return result;
  }
  return{state:'running',...identity};
 }
 if(!complete)return{state:'history_incomplete'};
 if(request.submission_attempted)return{state:'submission_unknown',head_turn_id:head};
 if(request.action==='submit'){
  if(typeof request.prompt!=='string'||Buffer.byteLength(request.prompt)>65536)throw Error('invalid prompt');
  const text=request.input_format==='raw-v2'?'[来源：ClawBot]\n'+request.prompt:marker(id)+'\n'+request.prompt;
  const inputs=request.inputs||[];
  if(!Array.isArray(inputs)||inputs.length>40||inputs.some(i=>!['localImage','localAudio','mention'].includes(i.type)||typeof i.path!=='string'||!i.path.startsWith('/')||(i.type==='mention'&&(typeof i.name!=='string'||i.name.length>128))))throw Error('invalid native attachment inputs');
  await checkpoint({state:'submitting',submission_attempted:true,anchor_turn_id:request.anchor_turn_id??head??null});
  const added=await rpc.call('thread/queue/add',{threadId,clientUserMessageId:id,input:[{type:'text',text,text_elements:[]},...inputs]});
  if(typeof added.queuedSubmission?.id!=='string')throw Error('native submission outcome unknown');
  const result={state:'queued',queue_id:added.queuedSubmission.id,queued_at:Date.now()/1000};
  await checkpoint(result);return result;
 }
 return{state:'not_found',head_turn_id:head};
}
