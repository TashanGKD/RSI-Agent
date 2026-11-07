"""Offline only: real contract/Store/Executor; native I/O is isolated synthetic UI."""
import unittest,tempfile,json,time,hashlib,concurrent.futures,sys,copy,types
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.contract import validate_job,digest
from operations.store import Store,Conflict
from operations.public_api import PublicAPI,PublicError
from operations.runtime import Executor,BeforeEffect
from operations import sending,composer
from operations.driver import preview_context

def job(mode=None,rid='one',**kw):
 j={'client':'test','request_id':rid,'peer':'wxid_fixture_1987fcaa9f','action':'send_text','payload':{'text':'  测试🙂[微笑]\n保留  '}}
 if mode is not None:j['execution_mode']=mode
 j.update(kw);return j
VERS={'registeredBindingSHA256':'b'*64,'bindingIdentitySHA256':'c'*64,'scopeSHA256':'d'*64}
def preview(j):
 return {'sha256':'a'*64,'senderRecipe':True,'programRecipe':True,'text':j['payload']['text'],'uiBinding':{'peer':j['peer']},'sendWindows':[], 'fastVersions':dict(VERS),'summary':{'peer':j['peer'],'action':j['action'],'text':j['payload']['text']}}
def certificate(j):
 return {'version':1,'eligible':True,'guardVerified':True,'peer':j['peer'],'action':j['action'],'payloadSHA256':digest(j['payload']),'previewSHA256':j['preview']['sha256'],'versions':dict(j['preview']['fastVersions'])}
class Native:
 def __init__(self):self.sent=[];self.cleaned=[];self.prepares=0;self.reject=None;self.after=None;self.unknown=False;self.flags=True;self.busy=False
 def acquire(self):return not self.busy
 def release(self):pass
 def prepare(self,j):
  self.prepares+=1;p=preview(j)
  if not self.flags:p.pop('senderRecipe')
  return p
 def certify_fast(self,j):
  if self.after:self.after()
  if self.reject:raise BeforeEffect(self.reject)
  return certificate(j)
 def execute(self,j):self.sent.append(j['id']);return {'state':'unknown','reason':'ambiguous','automaticReplay':False} if self.unknown else {'state':'accepted','serverId':'42','sendClicks':1}
 def verify(self,j):return {'state':'unknown','automaticReplay':False} if self.unknown else {'state':'accepted','serverId':'42'}
 def cleanup(self,j):self.cleaned.append(j['id']);return True
class ContractTests(unittest.TestCase):
 def test_omitted_mode_preserves_exact_old_canonical(self):
  original=job();wanted=dict(original,method='native');self.assertEqual(validate_job(original),wanted);self.assertEqual(digest(validate_job(original)),digest(wanted))
 def test_strict_opt_in_and_manual_supported(self):
  
  try:fast=validate_job(job('verified_fast'));manual=validate_job(job('manual'))
  except ValueError:self.fail('explicit execution_mode is not implemented')
  self.assertEqual(fast['execution_mode'],'verified_fast');self.assertEqual(manual['execution_mode'],'manual')
 def test_three_adversarial_modes_rejected(self):
  for value in [True,{},'auto',1,'verified_fast\0','Verified_fast']:
   with self.subTest(value=value):
    with self.assertRaises(ValueError):validate_job(job(value))
 def test_nonordinary_actions_and_visual_reject(self):
  for action,payload in [('reply',{'source_id':'1','text':'x'}),('forward',{'source_peer':'wxid_fixture_1987fcaa9f','source_id':'1'}),('join_group',{'inviter':'wxid_fixture_1987fcaa9f','source_id':'1'}),('save_attachment',{'source_id':'1'})]:
   with self.subTest(action=action):
    with self.assertRaises(ValueError):validate_job(job('verified_fast',action=action,payload=payload))
  with self.assertRaises(ValueError):validate_job(job('verified_fast',method='visual'))
 def test_caller_certificate_or_coordinate_injection_rejected(self):
  for k,v in [('fastVerification',{'eligible':True}),('confirmation_source','programmatic'),('point',[1,2])]:
   with self.assertRaises(ValueError):validate_job(dict(job('verified_fast'),**{k:v}))
class LifecycleTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve()/'state';self.s=Store(self.root);self.d=Native();self.e=Executor(self.s,self.d)
 def tearDown(self):self.s.close();self.t.cleanup()
 def create(self,value):
  try:return self.s.submit(value)
  except Conflict:raise
  except ValueError:self.fail('fast canonical job support is not implemented')
 def submit(self,mode='verified_fast'):return self.create(job(mode))
 def test_default_manual_never_auto_confirms(self):
  self.submit(None);self.e.step();self.e.step();self.assertEqual(self.s.get('test','one')['state'],'awaiting_confirmation');self.assertEqual(self.d.sent,[])
 def test_verified_text_programmatic_confirm_then_one_effect(self):
  self.submit();self.e.step();j=self.s.get('test','one');self.assertEqual(j['state'],'confirmed');self.assertEqual(j['preview']['confirmationSource'],'programmatic');self.assertEqual(self.d.sent,[]);self.e.step();self.e.step();self.assertEqual(len(self.d.sent),1);self.assertEqual(self.s.get('test','one')['state'],'succeeded')
 def test_mode_same_id_conflicts(self):
  self.submit(None)
  with self.assertRaises(Conflict):self.submit()
  self.assertEqual(len(self.s.list_jobs()),1)
 def test_repeat_fast_id_returns_one_receipt(self):
  first=self.submit();self.e.step();self.e.step();self.assertEqual(self.submit()['id'],first['id']);self.e.step();self.assertEqual(len(self.d.sent),1)
 def test_fake_recipe_cannot_auto_confirm(self):
  self.d.flags=False;self.submit();self.e.step();j=self.s.get('test','one');self.assertEqual(j['state'],'awaiting_confirmation');self.assertTrue(j['preview']['reviewRequired']);self.assertEqual(self.d.sent,[])
 def test_unknown_guard_identity_or_body_requires_review(self):
  for reason in ['lost_guard','changed_target','changed_body','foreign_draft','unknown_modal','binding_changed']:
   with self.subTest(reason=reason):
    self.d.reject=reason;self.create(job('verified_fast',rid=reason));self.e.step();j=self.s.get('test',reason);self.assertEqual(j['state'],'awaiting_confirmation');self.assertTrue(j['preview']['reviewRequired']);self.s.cancel('test',reason);self.e.step()
  self.assertEqual(self.d.sent,[])
 def test_cancel_during_certification_never_confirms(self):
  self.submit();self.d.after=lambda:self.s.cancel('test','one');self.e.step();self.e.step();self.assertEqual(self.s.get('test','one')['state'],'cancelled');self.assertEqual(self.d.sent,[])
 def test_expiry_during_certification_never_confirms(self):
  j=self.submit();self.d.after=lambda:self.s.c.execute('UPDATE jobs SET expires=1 WHERE id=?',(j['id'],));self.e.step();self.e.step();self.assertEqual(self.s.get('test','one')['state'],'expired');self.assertEqual(self.d.sent,[])
 def test_window_busy_waits_same_queued_job(self):
  j=self.submit();self.d.busy=True;self.assertEqual(self.e.step()['state'],'window_busy');self.assertEqual(self.s.get('test','one')['state'],'queued');self.d.busy=False;self.e.step();self.e.step();self.assertEqual(self.d.sent,[j['id']])
 def test_unknown_never_reexecutes(self):
  self.d.unknown=True;self.submit();self.e.step();self.e.step();self.e.step();self.e.step();self.assertEqual(len(self.d.sent),1);self.assertEqual(self.s.get('test','one')['state'],'unknown')
 def test_recovery_of_executing_is_unknown_never_replay(self):
  j=self.submit();self.e.step();self.s.set_state(j['id'],'executing');self.s.recover();self.d.unknown=True;self.e.step();self.assertEqual(self.s.get('test','one')['state'],'unknown');self.assertEqual(self.d.sent,[])
 def test_restarted_awaiting_review_is_not_blindly_confirmed(self):
  self.d.reject='review';self.submit();self.e.step();self.s.recover();self.d.reject=None;self.e.step();self.assertEqual(self.s.get('test','one')['state'],'awaiting_confirmation');self.assertEqual(self.d.sent,[])
 def test_manual_fallback_confirmation_source_is_retained(self):
  self.d.reject='foreign_draft';self.submit();self.e.step();j=self.s.get('test','one');self.s.confirm('test','one',j['confirmation_token']);j=self.s.get('test','one');self.assertEqual(j['preview']['confirmationSource'],'manual');self.e.step();self.assertEqual(len(self.d.sent),1)
 def test_atomic_execution_claim_only_one_winner(self):
  self.assertTrue(callable(getattr(self.s,'begin_execution',None)));j=self.submit(None);self.e.step();v=self.s.get('test','one');self.s.confirm('test','one',v['confirmation_token'])
  def claim(_):
   s=Store(self.root)
   try:return bool(s.begin_execution(j['id']))
   finally:s.close()
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:results=list(ex.map(claim,range(2)))
  self.assertEqual(sum(results),1)
class PublicContractTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.a=PublicAPI(Path(self.t.name).resolve()/'state',{'account':'me','clients':{'test':{'peers':['wxid_fixture_1987fcaa9f'],'actions':['send_text','reply','send_file']}}},contacts=lambda p:[])
 def tearDown(self):self.a.close();self.t.cleanup()
 def test_mode_public_field_and_capabilities(self):
  
  try:v=self.a.call({'op':'submit','job':job('verified_fast')})
  except PublicError:self.fail('public fast execution mode is not implemented')
  self.assertEqual(v['execution_mode'],'verified_fast');self.assertEqual(v['outcome']['status'],'pending');self.assertEqual(set(self.a.capabilities()['verifiedFast']['eligibleActions']),{'send_text','send_image','send_file'})
 def test_owner_authorized_work_does_not_require_peer_registration(self):
  v=self.a.call({'op':'submit','job':job('verified_fast',peer='wxid_fixture_4c90539d6a')})
  self.assertEqual(v['state'],'queued');self.assertEqual(v['peer'],'wxid_fixture_4c90539d6a');self.assertEqual(len(self.a.s.list_jobs()),1)
 def test_no_send_requires_positive_proof_not_missing_receipt(self):
  j=self.a.s.submit(job());self.a.s.claim();self.a.s.set_state(j['id'],'unknown',{'reason':'missing_attempt'});v=self.a.call({'op':'get','client':'test','request_id':'one'});self.assertIn('outcome',v);self.assertEqual(v['outcome']['status'],'unknown');self.assertEqual(v['outcome']['next_action'],'reconcile_same_request');self.assertNotIn('noSend',v['outcome'])
 def test_positive_no_send_is_classified(self):
  j=self.a.s.submit(job());self.a.s.claim();self.a.s.set_state(j['id'],'failed',{'noSend':True,'code':'DRAFT_PROTECTED'});v=self.a.call({'op':'get','client':'test','request_id':'one'});self.assertIn('outcome',v);self.assertEqual(v['outcome']['status'],'not_sent');self.assertTrue(v['result']['noSend'])
class NativeCertificateTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve();self.cfg={'peer':'wxid_fixture_1987fcaa9f','header_box':[0,0,10,10],'editor':[10,50],'send':[20,80]};self.j=dict(job('verified_fast'),id='a'*32);self.j['preview']=preview(self.j)
  from PIL import Image
  self.im=Image.new('RGB',(100,100),'white');self.previews=self.root/'previews';self.previews.mkdir(mode=0o700);self.artifact=self.previews/(self.j['id']+'.png');self.im.save(self.artifact);self.artifact.chmod(0o600);self.j['preview']['sha256']=hashlib.sha256(self.artifact.read_bytes()).hexdigest();self.versions=dict(VERS,bindingIdentitySHA256=digest({k:self.cfg.get(k) for k in ('peer','displayName','paired_account','observedTitle','nativeMemberIds')}));self.j['preview']['fastVersions']=dict(self.versions)
  self.j['preview'].update(uiBinding=self.cfg,context=preview_context(self.j['peer'],hashlib.sha256(self.im.crop((0,0,10,10)).tobytes()).hexdigest(),self.j['payload']['text'],None))
  self.u=types.SimpleNamespace(cfg=self.cfg,draft=lambda:self.j['payload']['text'],check=lambda:None,close=lambda:None)
  self.d=types.SimpleNamespace(root=self.root,previews=self.previews,session_bindings={},active_window=None,lease='lease',check_lease=lambda x:None,fast_versions=lambda j:dict(self.versions),binding=lambda p:self.cfg,ui=lambda p:self.u)
  composer.save(self.root,self.j,{'state':'staged','priorText':'','priorChars':0,'priorSHA':hashlib.sha256(b'').hexdigest(),'binding':self.cfg,'window':{}})
 def tearDown(self):self.t.cleanup()
 def certify(self):
  fn=getattr(sending,'certify_fast',None);self.assertTrue(callable(fn))
  with patch('operations.sending.scene',return_value=[]),patch('operations.sending.enabled',return_value=[20,80]),patch('operations.recipes.screen',return_value=self.im):return fn(self.d,self.j)
 def test_real_staged_journal_exact_body_guard_versions_can_certify(self):self.assertTrue(self.certify()['eligible'])
 def test_no_journal_cannot_certify(self):
  composer.path(self.root,self.j).unlink()
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_prior_plain_foreign_draft_requires_manual_review(self):
  v=composer.load(self.root,self.j);v.update(priorText='old',priorChars=3,priorSHA=hashlib.sha256(b'old').hexdigest());composer.save(self.root,self.j,v)
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_body_drift_rejects(self):
  self.u.draft=lambda:'different'
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_binding_or_scope_version_drift_rejects(self):
  self.d.fast_versions=lambda j:dict(self.versions,scopeSHA256='e'*64)
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_changed_preview_artifact_rejects(self):
  self.artifact.write_bytes(b'changed')
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_missing_preview_artifact_rejects(self):
  self.artifact.unlink()
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_symlink_preview_artifact_rejects(self):
  other=self.root/'other.png';other.write_bytes(self.artifact.read_bytes());self.artifact.unlink();self.artifact.symlink_to(other)
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_wide_mode_preview_artifact_rejects(self):
  self.artifact.chmod(0o644)
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()
 def test_lost_guard_rejects(self):
  self.d.check_lease=lambda x:(_ for _ in ()).throw(BeforeEffect('lost'))
  with self.assertRaises((BeforeEffect,ValueError)):self.certify()

class PendingCertificationTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.a=PublicAPI(Path(self.t.name).resolve()/'state',{'account':'me','clients':{'test':{'peers':['wxid_fixture_1987fcaa9f'],'actions':['send_text']}}},contacts=lambda p:[])
 def tearDown(self):self.a.close();self.t.cleanup()
 def pending(self):
  j=self.a.s.submit(job('verified_fast'));self.a.s.claim();return self.a.s.preview(j['id'],preview(j))
 def test_pending_native_certification_does_not_expose_human_confirm_token(self):
  self.pending();v=self.a.call({'op':'get','client':'test','request_id':'one'});self.assertEqual(v['outcome']['status'],'pending');self.assertIsNone(v['confirmation_token']);self.assertFalse(v['preview']['review_required'])
 def test_pending_native_certification_cannot_be_publicly_confirmed(self):
  p=self.pending()
  with self.assertRaises(PublicError):self.a.call({'op':'confirm','client':'test','request_id':'one','token':p['confirmation_token']})
  self.assertEqual(self.a.s.get('test','one')['state'],'awaiting_confirmation')
 def test_restart_pending_certificate_requires_real_review_instead_of_hanging(self):
  self.pending();self.a.s.recover();v=self.a.call({'op':'get','client':'test','request_id':'one'});self.assertEqual(v['outcome']['status'],'review_required');self.assertTrue(v['preview']['review_required']);self.assertIsInstance(v['preview']['fast_verification'],dict);self.assertEqual(v['preview']['fast_verification']['reason'],'RESTART_REVIEW_REQUIRED')

if __name__=='__main__':unittest.main()
