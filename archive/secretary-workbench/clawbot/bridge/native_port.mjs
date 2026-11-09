import fs from 'node:fs';
import path from 'node:path';
import {RPC} from './native_rpc.mjs';
import {reconcile} from './native_logic.mjs';
import {nativeAttachmentInputs} from './native_media.mjs';
import {NativeCorrelation} from './native_links.mjs';
import {loadedThread} from './native_session.mjs';
import crypto from 'node:crypto';
import {scanVisible,findVisibleSource} from './native_visible.mjs';
import {assertBridgeEnabled} from './desktop_bridge_status.mjs';

// This adapter only attaches to the public shared app-server; it never starts a model/server.
const max=262144;
if(!process.argv[2]){console.log('Usage: native_port.mjs PRIVATE_CONFIG < REQUEST_JSON');process.exit(0);}
const raw=fs.readFileSync(0,'utf8');
if(Buffer.byteLength(raw)>max)throw Error('request too large');
let request=JSON.parse(raw);
if(!['inspect','submit','poll','visible','verify_outgoing'].includes(request.action))throw Error('invalid action');
if(request.action==='visible'&&request.after_turn_id!==null&&(typeof request.after_turn_id!=='string'||request.after_turn_id.length>128))throw Error('invalid visible checkpoint');
if(request.action==='verify_outgoing'&&(typeof request.text!=='string'||!request.text||Buffer.byteLength(request.text)>32768))throw Error('invalid outgoing text');
const configPath=process.argv[2];
if(!configPath||!path.isAbsolute(configPath))throw Error('private configuration required');
for(let p=configPath;p!==path.dirname(p);p=path.dirname(p)){if(fs.lstatSync(p).isSymbolicLink())throw Error('symlink refused');}
const cs=fs.statSync(configPath);if(cs.uid!==process.getuid()||(cs.mode&0o077)||cs.size>65536)throw Error('unsafe configuration');
const cfg=JSON.parse(fs.readFileSync(configPath,'utf8'));
if(cfg.thread_id!==(process.env.SECRETARY_THREAD_ID || '00000000-0000-4000-8000-001c36bddfee'))throw Error('unapproved conversation');
if(cfg.socket_path!==path.join(path.dirname(configPath),'desktop','control.sock'))throw Error('unapproved native socket');
if(request.action==='submit'){
 try{request.inputs=nativeAttachmentInputs(path.dirname(configPath),request);}
 catch{
  // Deterministic pre-submit rejection: no native RPC or business submission occurred.
  console.log(JSON.stringify({state:'media_rejected',reason:'managed_attachment_validation_failed'}));
  process.exit(0);
 }
}
assertBridgeEnabled(path.dirname(cfg.socket_path));
const rpc=new RPC(cfg.socket_path);
let result;
try{
 let correlation;
 if(['submit','poll'].includes(request.action)){
  correlation=new NativeCorrelation(path.dirname(configPath),cfg.thread_id,request);
  request=correlation.request;
  if(request.action==='submit'){
   const hash=crypto.createHash('sha256').update(JSON.stringify({prompt:request.prompt,inputs:request.inputs,input_format:request.input_format??'legacy-v1'})).digest('hex');
   correlation.save({input_hash:hash});
  }
 }
 await rpc.connect();
 const thread=await loadedThread(rpc,cfg.thread_id);
 if(request.action==='inspect')result={state:'connected',thread_id:thread.id,status:thread.status};
 else if(request.action==='visible')result=await scanVisible(rpc,cfg.thread_id,request.after_turn_id);
 else if(request.action==='verify_outgoing')result={state:'verified',source:await findVisibleSource(rpc,cfg.thread_id,request.text,{proactiveOnly:true})};
 else result=await reconcile(rpc,cfg.thread_id,request,{checkpoint:update=>correlation.save(update)});
 console.log(JSON.stringify(result));
}catch(e){
 const reasons=new Set(['native_correlation_conflict','invalid_native_identity','invalid_native_correlation','unsafe_native_correlation']);
 console.log(JSON.stringify({state:reasons.has(e.message)?'identity_conflict':'unavailable',reason:reasons.has(e.message)?e.message:'native_shared_connection_unavailable'}));process.exitCode=2;
}
finally{rpc.close();}
