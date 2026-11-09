import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.store import Store
from operations.runtime import Executor

class Driver:
 def __init__(self):self.sent=[];self.prepared=[];self.cleaned=[];self.error=False;self.context='original'
 def acquire(self):return True
 def release(self):pass
 def prepare(self,j):self.prepared.append(j['id']);return {'sha256':'a'*64,'context':self.context}
 def execute(self,j):
  if self.context!=j['preview']['context']:raise ValueError('target changed before side effect')
  self.sent.append(j['id'])
  if self.error:raise OSError('lost response after click')
  return {'state':'accepted','serverId':str(len(self.sent))}
 def verify(self,j):return {'state':'accepted','serverId':'1'} if j['id'] in self.sent else {'state':'unknown'}
 def cleanup(self,j):self.cleaned.append(j['id']);return True

class ExecutionTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.s=Store(Path(self.t.name).resolve()/'private');self.d=Driver();self.e=Executor(self.s,self.d)
 def tearDown(self):self.s.close();self.t.cleanup()
 def submit(self,r='a'):return self.s.submit({'client':'test','request_id':r,'action':'send_text','peer':'wxid_fixture_1987fcaa9f','payload':{'text':'中文'},'method':'native'})
 def confirm(self,r='a'):
  p=self.s.get('test',r);self.s.confirm('test',r,p['confirmation_token'])
 def test_never_send_before_confirmation(self):
  self.submit();self.e.step();self.assertEqual(self.d.sent,[]);self.assertEqual(self.s.get('test','a')['state'],'awaiting_confirmation')
 def test_no_interleaving_awaiting_confirmation(self):
  self.submit();self.submit('b');self.e.step();self.e.step();self.assertEqual(len(self.d.prepared),1)
 def test_after_confirm_exactly_one(self):
  self.submit();self.e.step();self.confirm();self.e.step();self.e.step();self.assertEqual(len(self.d.sent),1);self.assertEqual(self.s.get('test','a')['state'],'succeeded')
 def test_response_lost_reconcile_without_replay(self):
  self.submit();self.e.step();self.confirm();self.d.error=True;self.e.step();self.assertEqual(self.s.get('test','a')['state'],'unknown');self.e.step();self.assertEqual(len(self.d.sent),1);self.assertEqual(self.s.get('test','a')['state'],'succeeded')
 def test_changed_context_no_send(self):
  self.submit();self.e.step();self.confirm();self.d.context='somebody-else';self.e.step();self.assertEqual(self.d.sent,[])
 def test_expiry_cleans_and_queue_continues(self):
  a=self.submit();self.submit('b');self.e.step();self.s.c.execute('UPDATE jobs SET expires=1 WHERE id=?',(a['id'],));self.e.step();self.e.step();self.assertEqual(self.s.get('test','a')['state'],'expired');self.assertEqual(len(self.d.prepared),2)
 def test_confirmed_expiry_does_not_send(self):
  a=self.submit();self.e.step();self.confirm();self.s.c.execute('UPDATE jobs SET expires=0 WHERE id=?',(a['id'],));self.e.step();self.assertEqual(self.d.sent,[])
 def test_hundred_jobs_serialized(self):
  for i in range(100):self.submit(str(i))
  for i in range(100):self.e.step();self.confirm(str(i));self.e.step()
  self.assertEqual(len(self.d.sent),100);self.assertEqual(len(set(self.d.sent)),100);self.assertEqual(self.d.prepared,self.d.sent)
 def test_unsupported_program_layout_fails_without_ai_handoff(self):
  from operations.recipes import PreparationError
  self.submit();self.submit('b');original=self.d.prepare
  self.d.prepare=lambda j:(_ for _ in ()).throw(PreparationError('UNSUPPORTED_LAYOUT','no supported layout'))
  self.e.step();j=self.s.get('test','a');self.assertEqual(j['state'],'failed');self.assertEqual(j['result']['code'],'UNSUPPORTED_LAYOUT');self.assertEqual(self.d.sent,[])
  self.d.prepare=original;self.e.step();self.assertEqual(self.s.get('test','b')['state'],'awaiting_confirmation')
 def test_cancellation_during_preparation_is_not_overwritten(self):
  self.submit();original=self.d.prepare
  def prepare(j):
   value=original(j);self.s.cancel('test','a');return value
  self.d.prepare=prepare;self.e.step();self.assertEqual(self.s.get('test','a')['state'],'cancelled');self.assertEqual(self.d.sent,[])

 def test_explicit_cancel_is_not_labelled_as_timeout(self):
  self.submit();self.e.step();self.s.cancel('test','a');self.e.step()
  self.assertEqual(self.s.get('test','a')['state'],'cancelled');self.assertEqual(self.d.sent,[])
 def test_image_read_lock_busy_never_prepares_or_executes(self):
  self.s.submit({'client':'test','request_id':'image','action':'save_attachment','peer':'wxid_fixture_1987fcaa9f','payload':{'source_id':'42'}});self.d.acquire=lambda:False
  self.assertEqual(self.e.step()['state'],'window_busy');self.assertEqual(self.d.prepared,[]);self.assertEqual(self.d.sent,[]);self.assertEqual(self.s.get('test','image')['state'],'queued')
 def test_image_unknown_is_not_reexported_without_receipt(self):
  self.s.submit({'client':'test','request_id':'image','action':'save_attachment','peer':'wxid_fixture_1987fcaa9f','payload':{'source_id':'42'}});self.e.step();p=self.s.get('test','image');self.s.confirm('test','image',p['confirmation_token']);self.d.error=True;self.d.verify=lambda j:{'state':'unknown'}
  self.e.step();self.assertEqual(self.s.get('test','image')['state'],'unknown');self.e.step();self.assertEqual(len(self.d.sent),1)
 def test_post_send_restore_failure_does_not_hide_native_acceptance(self):
  self.submit();self.e.step();self.confirm();self.d.finalize=lambda j,p:(_ for _ in ()).throw(OSError('restore unavailable'));self.e.step();j=self.s.get('test','a');self.assertEqual(j['state'],'succeeded');self.assertEqual(len(self.d.sent),1);self.e.step();self.assertEqual(len(self.d.sent),1)
