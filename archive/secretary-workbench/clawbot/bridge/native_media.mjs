import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const digest=bytes=>crypto.createHash('sha256').update(bytes).digest('hex');
function owned(p,directory=false){
 for(let q=p;q!==path.dirname(q);q=path.dirname(q))if(fs.lstatSync(q).isSymbolicLink())throw Error('media symlink refused');
 const st=fs.lstatSync(p);
 if(st.uid!==process.getuid()||(st.mode&0o077)||(directory?!st.isDirectory():!st.isFile()||st.nlink!==1))throw Error('unsafe private media');
 return st;
}
export function validateMedia(root,request){
 if(!request.manifest_path&&!request.manifest_hash)return{inputs:[],prompt:''};
 if(typeof request.manifest_path!=='string'||!/^weixin-[a-f0-9]{64}$/.test(request.client_id)||!/^([a-f0-9]{64})$/.test(request.manifest_hash))throw Error('invalid media identity');
 const dir=path.join(root,'media',request.client_id.slice(7));
 if(request.manifest_path!==path.join(dir,'manifest.json'))throw Error('media escaped managed directory');
 owned(root,true);owned(path.join(root,'media'),true);owned(dir,true);
 const st=owned(request.manifest_path);if(st.size>65536)throw Error('media manifest too large');
 const raw=fs.readFileSync(request.manifest_path);if(digest(raw)!==request.manifest_hash)throw Error('media manifest changed');
 const m=JSON.parse(raw);
 if(typeof m.message_id!=='string'||digest(m.message_id)!==request.client_id.slice(7)||typeof m.prompt!=='string'||Buffer.byteLength(m.prompt)>20000||!Array.isArray(m.inputs)||m.inputs.length>20||!Array.isArray(m.assets)||m.assets.length>40)throw Error('invalid media manifest');
 const assets=new Set();let total=0;
 for(const a of m.assets){
  if(typeof a.path!=='string'||path.dirname(a.path)!==dir||assets.has(a.path)||!Number.isSafeInteger(a.size)||a.size<1||a.size>100*1024*1024||typeof a.sha256!=='string'||!/^([a-f0-9]{64})$/.test(a.sha256))throw Error('invalid asset');
  const st=owned(a.path);if(st.size!==a.size)throw Error('asset size changed');
  total+=st.size;if(total>200*1024*1024)throw Error('message media budget exceeded');
  const fd=fs.openSync(a.path,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  try{
   const before=fs.fstatSync(fd);if(!before.isFile()||before.ino!==st.ino||before.size!==st.size)throw Error('media changed');
   const h=crypto.createHash('sha256'),buf=Buffer.alloc(65536);let got=0,n;
   while((n=fs.readSync(fd,buf,0,buf.length,null))>0){got+=n;if(got>a.size)throw Error('asset grew');h.update(buf.subarray(0,n));}
   const after=fs.fstatSync(fd);if(got!==a.size||h.digest('hex')!==a.sha256||before.mtimeMs!==after.mtimeMs)throw Error('asset content changed');
  }finally{fs.closeSync(fd)}
  assets.add(a.path);
 }
 let nativeBytes=0;
 for(const i of m.inputs){
  if(!['localImage','localAudio'].includes(i.type)||Object.keys(i).some(k=>!['type','path'].includes(k))||!assets.has(i.path))throw Error('unapproved native attachment');
  nativeBytes+=m.assets.find(a=>a.path===i.path).size;
  if(nativeBytes>32*1024*1024)throw Error('native attachment budget exceeded');
 }
 return{inputs:m.inputs,prompt:m.prompt};
}

export function nativeAttachmentInputs(root,request){
 const validated=validateMedia(root,request),inputs=[...validated.inputs];
 if(request.manifest_path){
  // validateMedia already proved ownership, immutable asset hashes and scope.
  const m=JSON.parse(fs.readFileSync(request.manifest_path,'utf8'));
  let count=0;
  for(const a of m.assets)if(a.kind==='file')inputs.push({type:'mention',name:'ClawBot文件'+(++count),path:a.path});
  inputs.push({type:'mention',name:'ClawBot附件收据',path:request.manifest_path});
 }
 if(request.metadata_path||request.metadata_hash){
  if(typeof request.metadata_path!=='string'||!/^weixin-[a-f0-9]{64}$/.test(request.client_id)||! /^[a-f0-9]{64}$/.test(request.metadata_hash??''))throw Error('invalid media receipt');
  const dir=path.join(root,'native-receipts'),expected=path.join(dir,request.client_id.slice(7)+'.json');
  if(request.metadata_path!==expected)throw Error('media receipt escaped managed directory');
  owned(root,true);owned(dir,true);const st=owned(expected);if(st.size>8192)throw Error('media receipt too large');
  const raw=fs.readFileSync(expected);if(digest(raw)!==request.metadata_hash)throw Error('media receipt changed');
  const m=JSON.parse(raw);
  if(m.version!==1||typeof m.message_id!=='string'||digest(m.message_id)!==request.client_id.slice(7)||m.source!=='ClawBot'||m.status!=='failed'||m.read_status!=='unread'||typeof m.code!=='string'||m.code.length>512)throw Error('invalid media receipt');
  inputs.push({type:'mention',name:'ClawBot附件状态',path:expected});
 }
 if(inputs.length>40)throw Error('native attachment item limit');
 return inputs;
}
