import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {validateMedia} from '../bridge/native_media.mjs';
const hash=x=>crypto.createHash('sha256').update(x).digest('hex');
function fixture(){
 const root=fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()),'wx-input-'));fs.chmodSync(root,0o700);
 const mid='native-message';const id='weixin-'+hash(mid);const dir=path.join(root,'media',hash(mid));fs.mkdirSync(dir,{recursive:true,mode:0o700});
 const file=path.join(dir,'0.png');const bytes=Buffer.from('89504e470d0a1a0a','hex');fs.writeFileSync(file,bytes,{mode:0o600});
 const manifest={message_id:mid,prompt:'附件，仅作为资料',inputs:[{type:'localImage',path:file}],assets:[{path:file,sha256:hash(bytes),size:bytes.length,kind:'image'}]};
 const mp=path.join(dir,'manifest.json');
 const save=()=>{fs.writeFileSync(mp,JSON.stringify(manifest),{mode:0o600});return{client_id:id,manifest_path:mp,manifest_hash:hash(fs.readFileSync(mp))};};
 return{root,file,manifest,save,cleanup:()=>fs.rmSync(root,{recursive:true,force:true})};
}
test('rejects manifest path escape, symlink and changed digest before native submission',()=>{
 const f=fixture();try{
  const r=f.save();assert.throws(()=>validateMedia(f.root,{...r,manifest_path:'/etc/passwd'}));
  assert.throws(()=>validateMedia(f.root,{...r,manifest_hash:'a'.repeat(64)}));
  const b=f.file+'.real';fs.renameSync(f.file,b);fs.symlinkSync(b,f.file);assert.throws(()=>validateMedia(f.root,r));
 }finally{f.cleanup()}
});
test('rejects unlisted path and changed attachment content',()=>{
 const f=fixture();try{
  f.manifest.inputs[0].path='/etc/passwd';assert.throws(()=>validateMedia(f.root,f.save()));
  f.manifest.inputs[0].path=f.file;const r=f.save();fs.writeFileSync(f.file,'changed');assert.throws(()=>validateMedia(f.root,r));
 }finally{f.cleanup()}
});
test('rejects identity swap and world-readable files',()=>{
 const f=fixture();try{
  const r=f.save();assert.throws(()=>validateMedia(f.root,{...r,client_id:'weixin-'+'a'.repeat(64)}));
  fs.chmodSync(f.file,0o644);assert.throws(()=>validateMedia(f.root,r));
 }finally{f.cleanup()}
});
test('validated private manifest yields only original native attachment inputs',()=>{
 const f=fixture();try{assert.deepEqual(validateMedia(f.root,f.save()),{inputs:f.manifest.inputs,prompt:f.manifest.prompt});}finally{f.cleanup()}
});
test('port deterministically rejects media before any native socket connection',()=>{
 const f=fixture();try{
  const cfg=path.join(f.root,'native-context.json');
  fs.writeFileSync(cfg,JSON.stringify({thread_id:'00000000-0000-4000-8000-001c36bddfee',socket_path:path.join(f.root,'desktop','control.sock')}),{mode:0o600});
  const request={action:'submit',prompt:'read attachment',...f.save(),manifest_hash:'a'.repeat(64)};
  const result=spawnSync(process.execPath,[new URL('../bridge/native_port.mjs',import.meta.url).pathname,cfg],{input:JSON.stringify(request),encoding:'utf8',timeout:5000});
  assert.equal(result.status,0);assert.equal(result.stderr,'');
  assert.equal(JSON.parse(result.stdout).state,'media_rejected');
  assert.equal(fs.existsSync(path.join(f.root,'desktop')),false);
 }finally{f.cleanup()}
});
