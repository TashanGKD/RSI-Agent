import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const workspace=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'portable-collaboration-')));
process.env.SECRETARY_WORKSPACE=workspace;
const {validate}=await import('../tools/conversations.mjs');
const thread='00000000-0000-4000-8000-000000000001';
test('unknown operation and malformed identity reject before any RPC',()=>{
  assert.throws(()=>validate({action:'shell',cmd:'id'}));
  assert.throws(()=>validate({action:'inspect',threadId:'not-a-thread'}));
});
test('bounded owned brief can be validated without delivery',()=>{
  const dir=path.join(workspace,'collaboration/briefs');fs.mkdirSync(dir,{recursive:true});
  const brief=path.join(dir,'fixture.md');fs.writeFileSync(brief,'Synthetic task; do not dispatch');
  validate({action:'assign',threadId:thread,requestId:'fixture-one',briefPath:brief});
});
test('outside or symlink brief rejects without touching a destination',()=>{
  const outside=path.join(workspace,'outside.md');fs.writeFileSync(outside,'fixture');
  assert.throws(()=>validate({action:'assign',threadId:thread,requestId:'fixture-two',briefPath:outside}));
  const link=path.join(workspace,'collaboration/briefs/link.md');fs.symlinkSync(outside,link);
  assert.throws(()=>validate({action:'assign',threadId:thread,requestId:'fixture-three',briefPath:link}));
});
test.after(()=>fs.rmSync(workspace,{recursive:true,force:true}));
