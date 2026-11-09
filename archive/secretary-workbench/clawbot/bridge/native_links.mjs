import fs from 'node:fs';import path from 'node:path';import crypto from 'node:crypto';
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const stages=new Set(['new','submitting','starting','queued','running','completed','failed']);
const ids=['queue_id','turn_id','native_message_id','anchor_turn_id'];
const times=['queued_at','native_started_at','native_completed_at'];
function owned(p,directory=false){
 for(let q=p;q!==path.dirname(q);q=path.dirname(q))if(fs.lstatSync(q).isSymbolicLink())throw Error('unsafe_native_correlation');
 const st=fs.lstatSync(p);
 if(st.uid!==process.getuid()||(st.mode&0o077)||(directory?!st.isDirectory():!st.isFile()||st.nlink!==1||st.size>8192))throw Error('unsafe_native_correlation');
}
function read(p){owned(p);return JSON.parse(fs.readFileSync(p,'utf8'));}
function exists(p){try{fs.lstatSync(p);return true}catch(e){if(e.code==='ENOENT')return false;throw e}}
function write(p,value){
 if(exists(p))owned(p);
 const data=JSON.stringify(value,null,2);if(Buffer.byteLength(data)>8192)throw Error('invalid_native_correlation');
 const temporary=p+'.'+crypto.randomUUID()+'.tmp';let fd;
 try{
  fd=fs.openSync(temporary,fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW,0o600);
  fs.writeFileSync(fd,data);fs.fsyncSync(fd);fs.closeSync(fd);fd=undefined;
  fs.renameSync(temporary,p);const dir=fs.openSync(path.dirname(p),fs.constants.O_RDONLY);try{fs.fsyncSync(dir)}finally{fs.closeSync(dir)}
 }finally{if(fd!==undefined)fs.closeSync(fd);if(fs.existsSync(temporary))fs.unlinkSync(temporary)}
}
export class NativeCorrelation{
 constructor(root,threadId,request){
  const id=request.client_id;
  if(typeof id!=='string'||!/^weixin-[a-f0-9]{64}$/.test(id))throw Error('invalid_native_identity');
  owned(root,true);
  let mid=request.wx_message_id;
  if(mid===undefined&&(request.input_format??'legacy-v1')==='legacy-v1'){
   // Compatibility for an old worker finishing its already-persisted request.
   const prior=read(path.join(root,'native-requests',id.slice(7)+'.json'));
   mid=prior.message_id;
  }
  if(typeof mid!=='string'||!mid.length||mid.length>512||mid.includes('\0')||hash(mid)!==id.slice(7))throw Error('invalid_native_identity');
  const dir=path.join(root,'native-links');
  if(!fs.existsSync(dir))fs.mkdirSync(dir,{mode:0o700});owned(dir,true);
  this.path=path.join(dir,id.slice(7)+'.json');
  const identity={client_id:id,wx_message_id:mid,thread_id:threadId,input_format:request.input_format??'legacy-v1'};
  if(exists(this.path))this.value=read(this.path);
  else{this.value={version:1,...identity,state:'new',submission_attempted:false};write(this.path,this.value)}
  for(const [key,v]of Object.entries(identity))if(this.value[key]!==v)throw Error('native_correlation_conflict');
  this.validate(this.value);
  this.request={...request,wx_message_id:mid};
  for(const key of ids){
   if(request[key]&&this.value[key]&&request[key]!==this.value[key])throw Error('native_correlation_conflict');
   if(this.value[key])this.request[key]=this.value[key];
  }
  for(const key of times)if(this.value[key]!=null)this.request[key]=this.value[key];
  this.request.submission_attempted=this.value.submission_attempted===true;
  if(this.request.submission_attempted)this.request.allow_new=false;
 }
 validate(v){
  if(v.version!==1||!stages.has(v.state)||typeof v.submission_attempted!=='boolean')throw Error('invalid_native_correlation');
  for(const key of ids)if(v[key]!=null&&(typeof v[key]!=='string'||!v[key].length||v[key].length>512||v[key].includes('\0')))throw Error('invalid_native_correlation');
  if(v.input_hash!==undefined&&(typeof v.input_hash!=='string'||! /^[a-f0-9]{64}$/.test(v.input_hash)))throw Error('invalid_native_correlation');
  for(const key of times)if(v[key]!=null&&(!Number.isFinite(v[key])||v[key]<0))throw Error('invalid_native_correlation');
 }
 save(update){
  const allowed=new Set(['state','submission_attempted','input_hash',...ids,...times]);
  if(Object.keys(update).some(k=>!allowed.has(k)))throw Error('invalid_native_correlation');
  if(this.value.input_hash&&update.input_hash&&this.value.input_hash!==update.input_hash)throw Error('native_correlation_conflict');
  const value={...this.value,...update};
  for(const key of times)if(value[key]==null&&this.value[key]!=null)value[key]=this.value[key];
  // Never erase proof of a submission attempt during polling or restart.
  value.submission_attempted=this.value.submission_attempted||update.submission_attempted===true;
  this.validate(value);write(this.path,value);this.value=value;
 }
}
