/** Deployment routing only. All other real chats keep their current native route. */
import fs from 'node:fs';import crypto from 'node:crypto';import {spawnSync} from 'node:child_process';
export const SENDER=process.env.SECRETARY_SENDER_THREAD_ID || '00000000-0000-4000-8000-000000000000';
import path from 'node:path';
const ROOT=process.env.SECRETARY_WORKSPACE || path.resolve('var/workspace'), hash=s=>crypto.createHash('sha256').update(s).digest('hex');
export function applies(r){
 if(['inspect','read','assign'].includes(r.action))return r.threadId===SENDER;
 if(r.action==='status'){const p=ROOT+'/collaboration/receipts/'+r.requestId+'.json';return fs.existsSync(p)&&JSON.parse(fs.readFileSync(p)).threadId===SENDER;}
 return false;
}
export function route(r){
 let q;
 if(r.action==='inspect')q={op:'inspect'};
 if(r.action==='read')q={op:'read',limit:r.turnLimit??3};
 if(r.action==='status')q={op:'status',request_id:r.requestId};
 if(r.action==='assign'){
  const body=fs.readFileSync(r.briefPath,'utf8');const caller=r.callerThreadId??process.env.CODEX_THREAD_ID;if(!caller)throw Error('Original caller chat ID required; never assume a receiver');
  q={op:'assign',request_id:r.requestId,text:'【秘书协作交办 '+r.requestId+'】\n'+body,client_message_id:'secretary-'+hash(r.requestId+'|'+SENDER),caller:{host:'mac',threadId:caller}};
 }
 const p=spawnSync('/usr/bin/python3',[ROOT+'/tools/wechat_sender.py','--request'],{input:JSON.stringify(q),encoding:'utf8',timeout:120000,maxBuffer:4*1024*1024});
 let d;try{d=JSON.parse(p.stdout)}catch{throw Error('AUP native collaboration outcome unknown: inspect original request, do not resubmit')}
 if(p.status!==0||d.state==='attention')throw Error(d.reason??'AUP route unavailable');
 if(r.action==='assign'){
  const f=ROOT+'/collaboration/receipts/'+r.requestId+'.json';if(!fs.existsSync(f))fs.writeFileSync(f,JSON.stringify({action:'assign',requestId:r.requestId,threadId:SENDER,host:'aup',clientId:q.client_message_id,phase:d.phase,queueId:d.queueId,turnId:d.turnId},null,2),{mode:0o600});
 }
 return {...d,host:'aup',threadId:SENDER};
}
