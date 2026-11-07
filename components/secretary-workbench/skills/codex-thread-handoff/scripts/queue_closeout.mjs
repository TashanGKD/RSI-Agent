// Reviewed one-shot queue closeout. No classifier, watcher, new queue or database writes.
import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';import {pathToFileURL} from 'node:url';
export const inputSHA=input=>crypto.createHash('sha256').update(JSON.stringify(input)).digest('hex');
async function pending(call,threadId){let cursor,rows=[];do{const p=await call('thread/queue/list',{threadId,limit:100,...(cursor?{cursor}:{})});rows.push(...p.data);cursor=p.nextCursor}while(cursor);return rows}
function save(file,data){const raw=JSON.stringify(data,null,2)+'\n';if(fs.existsSync(file)){if(fs.readFileSync(file,'utf8')!==raw)throw Error('Archive already exists with another value: '+file);return}fs.writeFileSync(file,raw,{flag:'wx',mode:0o600})}
export async function applyPlan(plan,{call,archiveDir,execute=false}){
 const operations=[...(plan.merge??[]).map(x=>({...x,kind:'merge'})),...(plan.retire??[]).map(x=>({...x,kind:'retire'}))];
 const keys=new Set();for(const x of operations){if(!x.threadId||!x.id||!x.expectedInputSHA||!x.reason||!x.evidence?.length)throw Error('Reviewed disposition and original evidence required');const k=x.threadId+'|'+x.id;if(keys.has(k))throw Error('Same item has two dispositions');keys.add(k);if(x.kind==='merge'&&!x.replacementInput?.length)throw Error('Merged retained input required')}
 if(!execute)return{execute:false,merge:plan.merge?.length??0,retire:plan.retire?.length??0};
 fs.mkdirSync(archiveDir,{recursive:true,mode:0o700});save(path.join(archiveDir,'reviewed-plan.json'),plan);
 const result={startedAt:Date.now()/1000,items:[]};
 for(const x of operations){const rows=await pending(call,x.threadId),current=rows.find(r=>r.id===x.id);let state;
  if(!current)state='no_longer_pending';
  else if(inputSHA(current.input)!==x.expectedInputSHA)state='changed_kept';
  else{
   save(path.join(archiveDir,x.id+'.original.json'),current);save(path.join(archiveDir,x.id+'.disposition.json'),x);
   const method=x.kind==='merge'?'thread/queue/update':'thread/queue/delete';const params={threadId:x.threadId,queuedSubmissionId:x.id,...(x.kind==='merge'?{input:x.replacementInput}:{})};
   save(path.join(archiveDir,x.id+'.intent.json'),{method,params});let error=null,receipt=null;try{receipt=await call(method,params)}catch(e){error=String(e.message??e)}
   const after=(await pending(call,x.threadId)).find(r=>r.id===x.id);
   if(x.kind==='merge'){if(!after||inputSHA(after.input)!==inputSHA(x.replacementInput)){save(path.join(archiveDir,x.id+'.unresolved.json'),{error,receipt,current:after??null});throw Error('Merged item not positively retained; dependent removals stopped')}state='merged_retained'}
   else{if(after){save(path.join(archiveDir,x.id+'.unresolved.json'),{error,receipt,current:after});throw Error('Item still queued; outcome unresolved, no repeat mutation')}state='archived_removed'}
   save(path.join(archiveDir,x.id+'.receipt.json'),{state,error,receipt,verifiedAt:Date.now()/1000});
  }
  result.items.push({threadId:x.threadId,id:x.id,kind:x.kind,state});
 }
 result.finishedAt=Date.now()/1000;fs.writeFileSync(path.join(archiveDir,'RESULT.json'),JSON.stringify(result,null,2)+'\n',{mode:0o600});return result;
}
if(import.meta.url===pathToFileURL(process.argv[1]??'').href){
 const args=process.argv.slice(2),i=args.indexOf('--plan'),j=args.indexOf('--archive');
 if(i<0||j<0){console.log('Usage: node queue_closeout.mjs --plan reviewed.json --archive output-dir [--execute]. Without --execute: no connection or changes.');process.exit(0)}
 const plan=JSON.parse(fs.readFileSync(args[i+1],'utf8'));let rpc;
 try{if(args.includes('--execute')){const{RPC}=await import('../../../clawbot/bridge/native_rpc.mjs');rpc=new RPC(process.env.SECRETARY_NATIVE_SOCKET || path.resolve('var/clawbot/desktop/control.sock'));await rpc.connect()}console.log(JSON.stringify(await applyPlan(plan,{call:(...x)=>rpc.call(...x),archiveDir:args[j+1],execute:args.includes('--execute')})))}finally{rpc?.close()}
}
