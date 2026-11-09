import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';
const impl=await import('../bridge/desktop_bridge_status.mjs').catch(()=>({}));
function fixture(){const root=fs.mkdtempSync('/private/tmp/wx-status-');fs.chmodSync(root,0o700);return{root,file:path.join(root,'bridge-state.json'),clean(){fs.rmSync(root,{recursive:true,force:true})}}}
test('bridge status refuses symlink, public file, and malformed content',()=>{
 assert.equal(typeof impl.assertBridgeEnabled,'function');
 for(const kind of ['symlink','public','malformed']){const f=fixture();try{
  if(kind==='symlink'){fs.writeFileSync(path.join(f.root,'keep'),'keep');fs.symlinkSync(path.join(f.root,'keep'),f.file)}
  else{fs.writeFileSync(f.file,kind==='malformed'?'{':'{"version":1,"enabled":true}',{mode:kind==='public'?0o644:0o600})}
  assert.throws(()=>impl.assertBridgeEnabled(f.root),/bridge|state|private/i);
 }finally{f.clean()}}
});
test('fallback pauses bridge; successful sharing explicitly restores it',()=>{
 assert.equal(typeof impl.writeBridgeStatus,'function');const f=fixture();try{
  impl.assertBridgeEnabled(f.root);
  impl.writeBridgeStatus(f.root,{enabled:false,reason:'shared_startup_failed'});
  assert.throws(()=>impl.assertBridgeEnabled(f.root),/unavailable/);
  impl.writeBridgeStatus(f.root,{enabled:true,enginePid:123});impl.assertBridgeEnabled(f.root);
  assert.equal(fs.statSync(f.file).mode&0o777,0o600);
 }finally{f.clean()}
});
