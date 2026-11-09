/** Thin client for real persistent Codex conversations. No model, worker or scheduler. */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import * as senderRoute from './sender_route.mjs';
import {RPC,unpackItems} from '../../clawbot/bridge/native_rpc.mjs';
import {validateReport,localReport,executeReport,reportStatus} from './conversation-report.mjs';
const ROOT=process.env.SECRETARY_WORKSPACE || path.resolve('var/workspace');
const MAIN=process.env.SECRETARY_MAIN_THREAD_ID || '00000000-0000-4000-8000-000000000000';
const SOCKET=process.env.SECRETARY_NATIVE_SOCKET || path.resolve('var/clawbot/desktop/control.sock');
const RECEIPTS=ROOT+'/collaboration/receipts';
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const uuid=s=>typeof s==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(s);
function within(p,base){const rel=path.relative(base,p);return rel===''||(!rel.startsWith('..'+path.sep)&&rel!=='..'&&!path.isAbsolute(rel));}
function actual(p){if(typeof p!=='string'||!path.isAbsolute(p)||p.includes('\0'))throw Error('absolute path required');for(let q=p;q!==path.dirname(q);q=path.dirname(q))if(fs.lstatSync(q).isSymbolicLink())throw Error('symlink refused');return fs.realpathSync(p);}
export function validate(r){
 if(!r||typeof r!=='object'||Array.isArray(r))throw Error('object required');
 if(r.action==='report')return validateReport(r);
 const fields={inspect:['threadId'],list:['cwd'],read:['threadId','turnLimit'],assign:['threadId','requestId','briefPath','callerThreadId'],create:['cwd','title','requestId'],status:['requestId']};
 if(!Object.hasOwn(fields,r.action))throw Error('unknown action');
 if(Object.keys(r).some(k=>k!=='action'&&!fields[r.action].includes(k)))throw Error('unknown request field');
 if(['inspect','read','assign'].includes(r.action)&&!uuid(r.threadId))throw Error('invalid thread ID');
 if(['assign','create','status'].includes(r.action)&&!(typeof r.requestId==='string'&&/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/.test(r.requestId)))throw Error('invalid request ID');
 if(r.action==='assign'){
  if(r.threadId===MAIN)throw Error('self-delegation refused');
  const p=actual(r.briefPath);if(!within(p,ROOT+'/collaboration/briefs')||!fs.statSync(p).isFile()||fs.statSync(p).size>60000)throw Error('brief outside owned bounded directory');
 }
 if(r.cwd!==undefined){const p=actual(r.cwd);if(![ROOT,'/home/operator/aiwork/Tashan-Org','/var/lib/secretary-workspace/projects'].some(b=>within(p,b)))throw Error('cwd outside authorized work roots');}
 if(r.action==='create'&&(!r.cwd||typeof r.title!=='string'||!r.title.trim()||r.title.length>100||/[\r\n\0]/.test(r.title)))throw Error('create requires cwd and bounded title');
 if(r.turnLimit!==undefined&&(!Number.isInteger(r.turnLimit)||r.turnLimit<1||r.turnLimit>8))throw Error('turn limit must be 1..8');
 return r;
}
function save(p,d){const t=p+'.tmp';fs.writeFileSync(t,JSON.stringify(d,null,2),{mode:0o600});fs.renameSync(t,p);}
function briefThread(t){return {id:t?.id,name:t?.name,cwd:t?.cwd,status:t?.status};}
function clean(s){return String(s??'').replace(/((?:password|passwd|secret|token|aeskey|密码|口令)\s*[:：=]\s*)[^\s,，;；]+/gi,'$1[redacted]');}
async function turns(rpc,id,limit=3){
 const out=await rpc.call('thread/turns/list',{threadId:id,limit,sortDirection:'desc',itemsView:'notLoaded'});const result=[];
 for(const t of out.data||[]){const p=await rpc.call('thread/items/list',{threadId:id,turnId:t.id,limit:12,sortDirection:'desc'});const items=unpackItems(p.data||[]);result.push({id:t.id,status:t.status,completedAt:t.completedAt,progress:items.filter(x=>x.type==='agentMessage'&&x.phase==='commentary').slice(0,2).reverse().map(x=>({id:x.id,text:clean(x.text).slice(0,2500)})),activity:items.filter(x=>['commandExecution','fileChange','mcpToolCall'].includes(x.type)).slice(0,3).map(x=>({type:x.type,status:x.status})),final:items.filter(x=>x.type==='agentMessage'&&['final','final_answer'].includes(x.phase)).reverse().map(x=>({id:x.id,text:clean(x.text)}))});}
 return result;
}
async function queue(rpc,id){let cursor=null,rows=[];for(let i=0;i<8;i++){const q=await rpc.call('thread/queue/list',{threadId:id,limit:100,...(cursor?{cursor}:{})});rows.push(...q.data);cursor=q.nextCursor;if(!cursor)return rows;}throw Error('queue pagination budget');}
export async function findAssignment(rpc,id,prompt){
 const q=await rpc.call('thread/turns/list',{threadId:id,limit:12,sortDirection:'desc',itemsView:'notLoaded'});
 for(const t of q.data||[]){const p=await rpc.call('thread/items/list',{threadId:id,turnId:t.id,limit:4,sortDirection:'asc'});for(const i of unpackItems(p.data||[]))if(i.type==='userMessage'&&(i.content||[]).filter(c=>c.type==='text').map(c=>c.text).join('\n')===prompt)return {turnId:t.id,nativeUserMessageId:i.id,status:t.status};}
 return null;
}
export async function run(r,execute=false,options={}){
 validate(r);if(['assign','create','report'].includes(r.action)&&!execute)throw Error('mutation requires --execute');
 if(senderRoute.applies(r))return senderRoute.route(r);
 const root=options.root||ROOT;const reportInput=r.action==='report'?localReport(r,root):null;
 const rpc=options.rpcFactory?options.rpcFactory():new RPC(SOCKET);try{
  await rpc.connect();
  if(r.action==='report')return await executeReport(reportInput,rpc);
  if(r.action==='inspect')return briefThread((await rpc.call('thread/read',{threadId:r.threadId,includeTurns:false})).thread);
  if(r.action==='list'){const q=await rpc.call('thread/list',{limit:50,useStateDbOnly:true,...(r.cwd?{cwd:r.cwd}:{})});return {data:q.data.map(briefThread),nextCursor:q.nextCursor};}
  if(r.action==='read')return {thread:briefThread((await rpc.call('thread/read',{threadId:r.threadId,includeTurns:false})).thread),turns:await turns(rpc,r.threadId,r.turnLimit||3)};
  const file=(options.root?root+'/collaboration/receipts':RECEIPTS)+'/'+r.requestId+'.json';let saved=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):null;
  if(r.action==='status'){if(!saved)throw Error('unknown local request');let report;try{report=await reportStatus(r.requestId,rpc,root);}catch(e){report={state:'attention',reason:clean(e.message)};}return {...saved,live:saved.threadId?await turns(rpc,saved.threadId,3):null,...(report?{report}: {})};}
  if(r.action==='create'){
   const digest=hash(JSON.stringify({cwd:r.cwd,title:r.title}));
   if(saved){if(saved.hash!==digest)throw Error('request ID content conflict');if(saved.threadId)return saved;throw Error('prior create outcome unknown; inspect exact cwd, never recreate blindly');}
   saved={action:r.action,requestId:r.requestId,hash:digest,cwd:r.cwd,title:r.title,phase:'creating',at:new Date().toISOString()};save(file,saved);
   const q=await rpc.call('thread/start',{cwd:r.cwd,ephemeral:false,serviceName:'secretary-real-conversation'});if(!uuid(q.thread?.id))throw Error('missing real thread ID');
   saved.threadId=q.thread.id;saved.phase='created';save(file,saved);
   await rpc.call('thread/name/set',{threadId:saved.threadId,name:r.title});saved.named=true;save(file,saved);return saved;
  }
  const body=fs.readFileSync(r.briefPath,'utf8');if(!body.trim())throw Error('empty brief');const digest=hash(r.threadId+'\n'+body);
  if(saved&&saved.hash!==digest)throw Error('request ID content conflict');
  if(!saved){saved={action:'assign',requestId:r.requestId,hash:digest,threadId:r.threadId,clientId:'secretary-'+hash(r.requestId+'|'+r.threadId),phase:'prepared',at:new Date().toISOString()};save(file,saved);}
  if(saved.turnId)return {...saved,live:await turns(rpc,r.threadId,2)};
  const prompt='【秘书协作交办 '+r.requestId+'】\n'+body;
  let qs=await queue(rpc,r.threadId);let existing=qs.find(x=>x.clientUserMessageId===saved.clientId);
  if(!existing&&saved.phase!=='prepared'){const found=await findAssignment(rpc,r.threadId,prompt);if(found){Object.assign(saved,found,{phase:'started',readbackVerified:true});save(file,saved);return saved;}throw Error('submission outcome unknown; inspect history before another attempt');}
  if(!existing){saved.phase='submitting';save(file,saved);const q=await rpc.call('thread/queue/add',{threadId:r.threadId,clientUserMessageId:saved.clientId,input:[{type:'text',text:prompt,text_elements:[]}]});existing=q.queuedSubmission;if(!existing?.id)throw Error('missing queue receipt');saved.queueId=existing.id;saved.phase='queued';save(file,saved);qs=await queue(rpc,r.threadId);if(!qs.some(x=>x.id===existing.id)){const found=await findAssignment(rpc,r.threadId,prompt);if(found){Object.assign(saved,found,{phase:'started',readbackVerified:true});save(file,saved);return saved;}}}
  let t=(await rpc.call('thread/read',{threadId:r.threadId,includeTurns:false})).thread;
  if(t.status?.type==='notLoaded')t=(await rpc.call('thread/resume',{threadId:r.threadId,excludeTurns:true})).thread;
  if(t.status?.type==='idle'&&qs[0]?.id===existing.id){saved.phase='starting';save(file,saved);const q=await rpc.call('thread/queue/start',{threadId:r.threadId,queuedSubmissionId:existing.id});saved.turnId=q.turn?.id||q.turnId;saved.phase=saved.turnId?'started':'start-result-needs-readback';save(file,saved);}
  return saved;
 }finally{rpc.close();}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 if(!process.argv.includes('--request')){console.log('Usage: node conversations.mjs --request < request.json [--execute]. No default action.');}
 else{try{const raw=fs.readFileSync(0,'utf8');if(Buffer.byteLength(raw)>65536)throw Error('request size cap');console.log(JSON.stringify(await run(JSON.parse(raw),process.argv.includes('--execute'))));}catch(e){console.error(JSON.stringify({state:'attention',reason:clean(e.message)}));process.exitCode=2;}}
}
