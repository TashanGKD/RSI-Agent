"""Isolated original Store/worker cleanup scheduling; never WeChat or production."""
import tempfile,json,time,unittest,hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from operations.runtime import Executor
from operations.store import Store
from operations import navigation,composer,audit
class D:
 def __init__(self):self.policy=SimpleNamespace(cfg={'account':'original'});self.calls=[];self.allow=True;self.fresh=True
 def acquire(self):self.calls.append('acquire');return self.allow
 def release(self):self.calls.append('release')
 def fast_versions(self,j):self.calls.append('versions')
 def prepare(self,j):raise AssertionError('cleanup must never prepare')
 def execute(self,j):raise AssertionError('cleanup must never Send')
 def verify(self,j):raise AssertionError('use independent audit, not replay')
 def finalize(self,j,p):self.calls.append('finalize');return dict(p,draftRestored=True,draftRecoveryPending=False)
class CleanupLoopTests(unittest.TestCase):
 def setUp(self):
  td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);self.s=Store(Path(td.name).resolve()/'state');self.addCleanup(self.s.close);self.d=D();self.e=Executor(self.s,self.d)
 def accepted(self):
  j=self.s.submit({'client':'original','request_id':'one','peer':'wxid_fixture_1987fcaa9f','action':'send_text','payload':{'text':'frozen original'}});self.s.claim();p=self.s.preview(j['id'],{'sha256':'a'*64});self.s.confirm('original','one',p['confirmation_token']);self.s.begin_execution(j['id']);old={'state':'accepted','serverId':'123456','uniqueCandidateCount':1,'sendClicks':1,'draftRestored':True,'draftRecoveryPending':False,'navigationRestored':False,'navigationRecoveryPending':True,'postActionPending':True,'textComparison':{'exact':False,'mode':'original-author-accepted-deviation'}}
  self.s.set_state(j['id'],'succeeded',old);(self.s.root/(j['id']+'-attempt.json')).write_text('original attempt immutable');return self.s.by_id(j['id'])
 def run_cleanup(self,j,settled=True,audited=True,cv=None):
  cv={'state':'restored'} if cv is None else cv
  with patch.object(audit,'audit_many',return_value={'allVerified':audited}),patch.object(navigation,'load',return_value={'state':'ready'}),patch.object(navigation,'finish',return_value=settled) as finish,patch.object(composer,'load',return_value=cv):r=self.e.step()
  return r,finish.call_count
 def test_accepted_pending_is_cleaned_in_worker_before_ordinary_claim(self):
  j=self.accepted();body=self.s.c.execute('select body,hash from jobs where id=?',(j['id'],)).fetchone();attempt=(self.s.root/(j['id']+'-attempt.json')).read_bytes();r,n=self.run_cleanup(j);self.assertEqual(r['state'],'cleanup_recovered');self.assertEqual(n,1);v=self.s.by_id(j['id']);self.assertEqual(v['state'],'succeeded');self.assertEqual(v['result']['serverId'],'123456');self.assertEqual(v['result']['textComparison'],j['result']['textComparison']);self.assertFalse(any(v['result'][k] for k in ['postActionPending','draftRecoveryPending','navigationRecoveryPending']));self.assertEqual(tuple(body),tuple(self.s.c.execute('select body,hash from jobs where id=?',(j['id'],)).fetchone()));self.assertEqual(attempt,(self.s.root/(j['id']+'-attempt.json')).read_bytes());self.assertEqual(self.s.c.execute("select count(*) from events where job_id=? and state='executing'",(j['id'],)).fetchone()[0],1)
 def test_failed_native_audit_preserves_protection_and_does_no_ui_cleanup(self):
  j=self.accepted();r,n=self.run_cleanup(j,audited=False);self.assertEqual(r['state'],'cleanup_pending');self.assertEqual(n,0);self.assertNotIn('finalize',self.d.calls);self.assertEqual(self.s.by_id(j['id'])['result'],j['result'])
 def test_foreign_or_unproved_scene_does_not_clear_flags(self):
  j=self.accepted();r,n=self.run_cleanup(j,settled=False);self.assertEqual(r['state'],'cleanup_pending');self.assertEqual(self.s.by_id(j['id'])['result'],j['result']);self.assertIn('release',self.d.calls)
 def test_only_original_restored_composer_skips_draft_cleanup(self):
  j=self.accepted();self.run_cleanup(j);self.assertNotIn('finalize',self.d.calls)
 def test_pending_original_draft_uses_existing_finalize_before_navigation(self):
  j=self.accepted();r,n=self.run_cleanup(j,cv={'state':'staged'});self.assertEqual(r['state'],'cleanup_recovered');self.assertIn('finalize',self.d.calls)
 def test_unproved_original_draft_never_marks_navigation_or_result_settled(self):
  j=self.accepted();self.d.finalize=lambda *_:{'draftRestored':False,'draftRecoveryPending':True};r,n=self.run_cleanup(j,cv={'state':'staged'});self.assertEqual(r['state'],'cleanup_pending');self.assertEqual(n,0);self.assertEqual(self.s.by_id(j['id'])['result'],j['result'])
 def test_no_active_job_is_preempted_for_old_cleanup(self):
  j=self.accepted();a=self.s.submit({'client':'original','request_id':'active','peer':'wxid_fixture_1987fcaa9f','action':'send_text','payload':{'text':'active'}});self.s.set_state(a['id'],'unknown',{'automaticReplay':False});self.d.verify=lambda _:{'state':'unknown'}
  with patch.object(audit,'audit_many') as native:r=self.e.step()
  self.assertEqual(r['state'],'unknown');native.assert_not_called();self.assertEqual(self.s.by_id(j['id'])['result'],j['result'])
 def test_actual_native_guard_contention_returns_busy_without_cleanup(self):
  j=self.accepted();self.d.allow=False
  with patch.object(audit,'audit_many') as native:r=self.e.step()
  self.assertEqual(r['state'],'window_busy');native.assert_not_called();self.assertEqual(self.s.by_id(j['id'])['result'],j['result'])
 def test_unproved_cleanup_retries_after_bounded_backoff_without_new_job(self):
  j=self.accepted();clock=[100.0]
  with patch('operations.runtime.time.monotonic',side_effect=lambda:clock[0]):
   self.assertEqual(self.run_cleanup(j,settled=False)[0]['state'],'cleanup_pending');self.run_cleanup(j,settled=False);n=len(self.d.calls);clock[0]+=6;self.assertEqual(self.run_cleanup(j)[0]['state'],'cleanup_recovered');self.assertGreater(len(self.d.calls),n)
  self.assertEqual(self.s.c.execute('select count(*) from jobs').fetchone()[0],1)
 def test_older_other_action_debt_does_not_hide_supported_accepted_original(self):
  unsupported=self.s.submit({'client':'original','request_id':'older-other-action','peer':'wxid_fixture_1987fcaa9f','action':'open_chat','payload':{}})
  old={'state':'accepted','postActionPending':True,'navigationRecoveryPending':True,'sendClicks':0}
  self.s.set_state(unsupported['id'],'succeeded',{'state':'accepted'});j=self.accepted();self.s.set_state(unsupported['id'],'succeeded',old);r,n=self.run_cleanup(j)
  self.assertEqual(r['state'],'cleanup_recovered');self.assertEqual(r['job'],j['id']);self.assertEqual(self.s.by_id(unsupported['id'])['result'],old)
 def test_legacy_optional_click_summary_uses_real_attempt_and_native_audit(self):
  for clicks in (None,0):
   with self.subTest(clicks=clicks):
    if clicks==0:
     td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);self.s.close();self.s=Store(Path(td.name).resolve()/'state');self.addCleanup(self.s.close);self.d=D();self.e=Executor(self.s,self.d)
    j=self.accepted();proof=dict(j['result']);proof.pop('sendClicks',None)
    if clicks is not None:proof['sendClicks']=clicks
    self.s.set_state(j['id'],'succeeded',proof);j=self.s.by_id(j['id']);a=self.s.root/(j['id']+'-attempt.json');a.write_text(json.dumps({'clickScheduled':True,'peer':j['peer'],'action':'send_text','startedAt':1.0,'beforeIds':[],'text':j['payload']['text']}));a.chmod(0o600)
    snap={'account':'original','receipt':{'consistency':'committed','integrity':'ok'},'rows':[{'peer':j['peer'],'serverId':'123456','senderId':'original','status':2,'kind':1,'time':2.0,'text':j['payload']['text']}],'truncated':False}
    with patch.object(audit,'native_snapshot',return_value=snap),patch.object(navigation,'load',return_value={'state':'ready'}),patch.object(navigation,'finish',return_value=True),patch.object(composer,'load',return_value={'state':'restored'}):r=self.e.step()
    self.assertEqual(r['state'],'cleanup_recovered' if clicks is None else 'cleanup_pending');actual=self.s.by_id(j['id'])['result']
    if clicks is None:self.assertNotIn('sendClicks',actual)
    else:self.assertEqual(actual,proof)
 def test_current_target_registration_is_not_a_new_cleanup_permission(self):
  j=self.accepted();self.d.fast_versions=lambda _ : (_ for _ in ()).throw(ValueError('current target binding unavailable'))
  r,n=self.run_cleanup(j);self.assertEqual(r['state'],'cleanup_recovered');self.assertEqual(n,1)
 def test_missing_original_navigation_keeps_navigation_debt(self):
  j=self.accepted()
  with patch.object(audit,'audit_many',return_value={'allVerified':True}),patch.object(composer,'load',return_value={'state':'restored'}),patch.object(navigation,'load',return_value=None),patch.object(navigation,'finish') as finish:r=self.e.step()
  self.assertEqual(r['state'],'cleanup_pending');finish.assert_not_called();self.assertEqual(self.s.by_id(j['id'])['result'],j['result'])
if __name__=='__main__':unittest.main(verbosity=2)
