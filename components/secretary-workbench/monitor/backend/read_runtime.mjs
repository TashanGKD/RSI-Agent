// This monitor has no submission, resume, start, interrupt or write methods.
import {RPC} from '../../clawbot/bridge/native_rpc.mjs';
const targets=JSON.parse(process.argv[2]||'{}');
const ids=new Set(JSON.parse(process.env.SECRETARY_MONITOR_THREADS||'[]'));
if(Object.values(targets).some(x=>!ids.has(x)))throw Error('unknown monitored thread');
if(!Object.keys(targets).length){console.log('{}');process.exit(0)}
if(!process.env.SECRETARY_CONTROL_SOCKET)throw Error('configure the existing native control socket');
const rpc=new RPC(process.env.SECRETARY_CONTROL_SOCKET);
const out={};try{await rpc.connect();for(const [name,threadId] of Object.entries(targets)){
 try{
  const r=await rpc.call('thread/read',{threadId,includeTurns:false});
  const q=await rpc.call('thread/queue/list',{threadId,limit:100});
  const t=await rpc.call('thread/turns/list',{threadId,limit:20,sortDirection:'desc',itemsView:'notLoaded'});
  if(r.thread?.id!==threadId)throw Error('native identity mismatch');
  out[name]={threadId,sampledAt:new Date().toISOString(),status:r.thread?.status?.type||'unknown',queueCount:q.data?.length??null,queueMore:!!q.nextCursor,turns:(t.data||[]).map(x=>({id:x.id,status:x.status,startedAt:x.startedAt,completedAt:x.completedAt,durationMs:x.durationMs})),error:null};
 }catch{out[name]={threadId,status:'unknown',queueCount:null,error:'原生状态读取失败'}}
}}catch{for(const name of Object.keys(targets))out[name]={threadId:targets[name],status:'unknown',queueCount:null,error:'原生连接不可用'}}finally{rpc.close()}
console.log(JSON.stringify(out));
