// Read the one existing conversation. No injection, new turn, model or queue.
import {unpackItems,finalReply} from './native_rpc.mjs';
export function deliveryText(text){
 if(typeof text!=='string')throw Error('invalid visible text');
 const b=Buffer.from(text);let end=29000;while(end>0&&(b[end]&0xc0)===0x80)end--;
 return b.length>30000?b.subarray(0,end).toString('utf8')+'\n\n（答复较长，其余内容可在同一个Codex对话查看。）':text;
}
async function items(rpc,threadId,turnId){
 const all=[],seen=new Set();let cursor=null;
 for(let page=0;page<10;page++){
  const p=await rpc.call('thread/items/list',{threadId,turnId,limit:100,sortDirection:'asc',...(cursor?{cursor}:{})});
  if(!Array.isArray(p.data))throw Error('visible item history incomplete');
  all.push(...unpackItems(p.data));cursor=p.nextCursor;if(!cursor)return all;
  if(seen.has(cursor))break;seen.add(cursor);
 }
 throw Error('visible item history incomplete');
}
export async function scanVisible(rpc,threadId,after){
 const rows=[];let cursor=null,found=after==='__empty__';
 for(let page=0;page<10;page++){
  const p=await rpc.call('thread/turns/list',{threadId,limit:20,sortDirection:'desc',itemsView:'notLoaded',...(cursor?{cursor}:{})});
  if(!Array.isArray(p.data))throw Error('invalid visible history');
  if(after===null)return {state:'initialized',after_turn_id:p.data.find(t=>['completed','failed','interrupted'].includes(t.status))?.id||'__empty__',turns:[]};
  for(const t of p.data){if(t.id===after){found=true;break;}rows.push(t);}
  if(found&&after!=='__empty__')break;
  cursor=p.nextCursor;if(!cursor){if(after==='__empty__')found=true;break;}
 }
 if(!found)throw Error('visible history incomplete');
 let checkpoint=after;const turns=[];
 for(const t of rows.reverse()){
  if(!['completed','failed','interrupted'].includes(t.status))break;
  const ii=await items(rpc,threadId,t.id),finals=ii.filter(i=>i.type==='agentMessage'&&['final','final_answer'].includes(i.phase)&&typeof i.text==='string');
  const reply=deliveryText(finalReply(ii));
  if(reply)turns.push({turn_id:t.id,item_ids:finals.map(i=>i.id),client_id:ii.find(i=>i.type==='userMessage')?.clientId??null,reply});
  checkpoint=t.id;
  if(turns.length>=4)break;
 }
 return {state:'scanned',after_turn_id:checkpoint,turns};
}
export async function findVisibleSource(rpc,threadId,text,{proactiveOnly=false}={}){
 const p=await rpc.call('thread/turns/list',{threadId,limit:12,sortDirection:'desc',itemsView:'notLoaded'});
 if(!Array.isArray(p.data))throw Error('invalid visible history');
 for(const t of p.data){
  const ii=await items(rpc,threadId,t.id);
  const phases=proactiveOnly?['commentary']:['final','final_answer','commentary'];
  const exact=ii.find(i=>i.type==='agentMessage'&&phases.includes(i.phase)&&i.text===text);
  if(exact)return {turn_id:t.id,item_ids:[exact.id]};
  if(!proactiveOnly&&text&&deliveryText(finalReply(ii))===text)return {turn_id:t.id,item_ids:ii.filter(i=>i.type==='agentMessage'&&['final','final_answer'].includes(i.phase)).map(i=>i.id)};
 }
 return null;
}
