import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {fileURLToPath} from 'node:url';
import {RPC} from '../../../clawbot/bridge/native_rpc.mjs';
const root='/var/lib/secretary-workspace/collaboration/receipts/sender-aup';const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
export function validate(r){if(!r||r.op!=='sender.report'||Object.keys(r).some(k=>!['op','sourceRequestId','text'].includes(k))||typeof r.sourceRequestId!=='string'||!(/^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/).test(r.sourceRequestId)||typeof r.text!=='string'||!r.text.trim()||Buffer.byteLength(r.text)>64000||r.text.includes('\0'))throw Error('registered original request and bounded text only');return r;}
function load(p){for(let q=p;q!==path.dirname(q);q=path.dirname(q))if(fs.lstatSync(q).isSymbolicLink())throw Error('symlink refused');const st=fs.statSync(p);if(st.uid!==process.getuid()||st.mode&0o077||!st.isFile()||st.size>90000)throw Error('private original receipt required');return JSON.parse(fs.readFileSync(p,'utf8'));}
function save(p,d){fs.writeFileSync(p+'.tmp',JSON.stringify(d,null,2),{mode:0o600});fs.renameSync(p+'.tmp',p)}
export async function run(r){
 validate(r);const original=load(root+'/'+sha(r.sourceRequestId)+'.json');if(original.request_id!==r.sourceRequestId||original.caller.host!=='mac')throw Error('original registration mismatch');
 const target=original.caller.threadId;if(target==='00000000-0000-4000-8000-006912130405'||!(/^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/).test(target))throw Error('invalid/old sender callback');
 const file=root+'/'+sha(r.sourceRequestId)+'.return.json';let receipt=fs.existsSync(file)?load(file):null;const clientId='sender-return-'+sha(r.sourceRequestId),text='【发送员工回报 '+r.sourceRequestId+'】\n'+r.text;
 if(receipt&&receipt.sha256!==sha(text))throw Error('callback content conflict');
 const rpc=new RPC('/var/lib/secretary-clawbot/desktop/control.sock');
 try{
  await rpc.connect();const meta=(await rpc.call('thread/read',{threadId:target,includeTurns:false})).thread;if(meta.id!==target)throw Error('target mismatch');
  const find=async()=>{const q=await rpc.call('thread/queue/list',{threadId:target,limit:100});if(q.nextCursor)throw Error('incomplete queue');const same=q.data.find(x=>x.clientUserMessageId===clientId);if(same){if(same.input.filter(x=>x.type==='text').map(x=>x.text).join('')!==text)throw Error('native callback collision');return {phase:'queued',queueId:same.id};}
   const ts=await rpc.call('thread/turns/list',{threadId:target,limit:30,sortDirection:'desc',itemsView:'notLoaded'});for(const t of ts.data){const page=await rpc.call('thread/items/list',{threadId:target,turnId:t.id,limit:100,sortDirection:'asc'});for(const entry of page.data){const i=entry.item??entry;if(i.type==='userMessage'&&i.clientId===clientId){if(i.content.filter(x=>x.type==='text').map(x=>x.text).join('')!==text)throw Error('native callback collision');return {phase:'delivered',turnId:t.id,nativeUserMessageId:i.id};}}}return null;};
  let observed=await find();if(!observed){if(receipt)throw Error('prior callback unknown; never resubmit');receipt={sourceRequestId:r.sourceRequestId,target,clientId,sha256:sha(text),phase:'submitting'};save(file,receipt);const added=await rpc.call('thread/queue/add',{threadId:target,clientUserMessageId:clientId,input:[{type:'text',text,text_elements:[]}]});receipt.queueId=added.queuedSubmission?.id;receipt.phase='queued';save(file,receipt);observed=await find();}
  if(!observed)throw Error('original callback awaiting native readback');receipt={...receipt,...observed,target,sha256:sha(text)};save(file,receipt);
  const last=(await rpc.call('thread/turns/list',{threadId:target,limit:1,sortDirection:'desc',itemsView:'notLoaded'})).data[0];let now=(await rpc.call('thread/read',{threadId:target,includeTurns:false})).thread;
  if(observed.phase==='queued'&&last?.status!=='inProgress'){
   if(now.status.type==='notLoaded')now=(await rpc.call('thread/resume',{threadId:target,excludeTurns:true})).thread;
   const q=await rpc.call('thread/queue/list',{threadId:target,limit:100});now=(await rpc.call('thread/read',{threadId:target,includeTurns:false})).thread;
   if(now.status.type==='idle'&&q.data[0]?.id===observed.queueId){try{await rpc.call('thread/queue/start',{threadId:target,queuedSubmissionId:observed.queueId})}catch{}}
  }
  return receipt;
 }finally{rpc.close()}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 if(process.argv[2]!=='--serve'){console.log('Usage: mac_sender_report.mjs --serve; no default action.');}
 else{try{const raw=fs.readFileSync(0,'utf8');if(Buffer.byteLength(raw)>70000)throw Error('request too large');console.log(JSON.stringify({ok:true,result:await run(JSON.parse(raw))}));}catch(e){console.log(JSON.stringify({ok:false,reason:e.message}));process.exitCode=2}}
}
