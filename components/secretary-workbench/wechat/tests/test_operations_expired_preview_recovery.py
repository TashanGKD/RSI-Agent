"""Exact pre-confirmation expiry and guarded maintenance inputs; isolated only."""
import hashlib,json,tempfile,time,types,unittest
from pathlib import Path
from unittest.mock import Mock,patch
from operations.store import Store
from operations import runtime,composer,recipes,sending,navigation

class ExpiredPreviewRecovery(unittest.TestCase):
 def fixture(self,reason='owned_draft_cleanup_not_proven',state='needs_attention',preview=True,journal=True):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);s=Store(Path(t.name).resolve());self.addCleanup(s.close)
  j=s.submit({'client':'fixture','request_id':'original','peer':'room@chatroom','action':'send_text','payload':{'text':'synthetic fixture'}});s.claim();s.preview(j['id'],{'sha256':'a'*64,'senderRecipe':True})
  s.c.execute('UPDATE jobs SET expires=? WHERE id=?',(time.time()-1,j['id']));s.set_state(j['id'],state,{'reason':reason});j=s.by_id(j['id'])
  if not preview:s.c.execute('UPDATE jobs SET preview=NULL WHERE id=?',(j['id'],));j=s.by_id(j['id'])
  if journal:composer.save(s.root,j,{'state':'staged','priorText':'','priorChars':0,'priorSHA':hashlib.sha256(b'').hexdigest(),'binding':{},'window':{}})
  d=types.SimpleNamespace(acquire=lambda:True,release=Mock(),cleanup=Mock(return_value=True),verify=Mock(return_value={'state':'unknown','reason':'fixture_only'}),prepare=Mock(return_value={'sha256':'b'*64}),execute=Mock(side_effect=AssertionError('no execute')))
  return s,d,j,runtime.Executor(s,d)
 def test_expired_ordinary_preview_without_navigation_bounds_retries_original_cleanup(self):
  s,d,j,e=self.fixture();e.step();v=s.by_id(j['id']);self.assertEqual(v['state'],'expired');self.assertTrue(v['result']['noSend']);d.cleanup.assert_called_once();d.verify.assert_not_called();d.prepare.assert_not_called();d.execute.assert_not_called()
 def test_initial_cleanup_failure_then_positive_restore_expires_without_send(self):
  s,d,j,e=self.fixture();s.set_state(j['id'],'awaiting_confirmation');d.cleanup.side_effect=[False,True];e.step();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention');e.step();self.assertEqual(s.by_id(j['id'])['state'],'expired');self.assertEqual(d.cleanup.call_count,2);d.execute.assert_not_called()
 def test_failed_retry_keeps_attention_and_is_bounded_for_same_worker(self):
  s,d,j,e=self.fixture();d.cleanup.return_value=False;e.step();e.step();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention');self.assertFalse((s.by_id(j['id']).get('result') or {}).get('noSend',False));self.assertEqual(d.cleanup.call_count,1)
 def test_cleanup_exception_keeps_original_attention_not_worker_crash(self):
  s,d,j,e=self.fixture();d.cleanup.side_effect=ValueError('unproven foreign or corrupt journal');e.step();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention');d.prepare.assert_not_called()
 def test_unknown_even_if_expired_never_enters_cleanup(self):
  s,d,j,e=self.fixture(state='unknown');e.step();d.cleanup.assert_not_called();d.execute.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'unknown')
 def test_confirmed_executing_or_terminal_evidence_blocks_expiry_shortcut(self):
  for signal in ('confirmed','executing','attempt','execution-check','step'):
   with self.subTest(signal=signal):
    s,d,j,e=self.fixture()
    if signal in ('confirmed','executing'):s.event(j['id'],signal)
    else:(s.root/(j['id']+('-step-1.json' if signal=='step' else '-'+signal+'.json'))).write_text('{}')
    e.step();d.cleanup.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention')
 def test_missing_or_symlink_original_journal_does_not_count_as_proof(self):
  for kind in ('missing','symlink'):
   with self.subTest(kind=kind):
    s,d,j,e=self.fixture(journal=False)
    if kind=='symlink':
     (s.root/'other').write_text('{}');(s.root/(j['id']+'-composer.json')).symlink_to(s.root/'other')
    e.step();d.cleanup.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention')
 def test_not_yet_expired_or_no_saved_preview_is_not_cancelled(self):
  for kind in ('future','missing_preview'):
   with self.subTest(kind=kind):
    s,d,j,e=self.fixture(preview=kind!='missing_preview')
    if kind=='future':s.c.execute('UPDATE jobs SET expires=? WHERE id=?',(time.time()+60,j['id']))
    e.step();d.cleanup.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention')
 def test_no_preconfirmation_event_is_not_just_no_attempt_proof(self):
  s,d,j,e=self.fixture();s.c.execute("DELETE FROM events WHERE job_id=? AND state='awaiting_confirmation'",(j['id'],));e.step();d.cleanup.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention')
 def test_dangling_execution_evidence_is_not_treated_as_absent(self):
  for suffix in ('-attempt.json','-execution-check.json'):
   with self.subTest(suffix=suffix):
    s,d,j,e=self.fixture();(s.root/(j['id']+suffix)).symlink_to(s.root/'missing');e.step();d.cleanup.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention')
 def test_negative_expiry_is_not_a_positive_expired_preview(self):
  s,d,j,e=self.fixture();s.c.execute('UPDATE jobs SET expires=-1 WHERE id=?',(j['id'],));e.step();d.cleanup.assert_not_called();self.assertEqual(s.by_id(j['id'])['state'],'needs_attention')
 def test_original_caller_cancellation_during_cleanup_is_preserved(self):
  s,d,j,e=self.fixture();d.cleanup.side_effect=lambda job:bool(s.cancel('fixture','original'));e.step();self.assertEqual(s.by_id(j['id'])['state'],'cancelled');d.execute.assert_not_called()
 def test_after_restore_original_queue_continues_without_reprepare_original(self):
  s,d,j,e=self.fixture()
  def cleanup(job):
   value=composer.load(s.root,job);value.update(state='restored',priorText=None);composer.save(s.root,job,value);return True
  d.cleanup.side_effect=cleanup;s.submit({'client':'fixture','request_id':'later','peer':'room@chatroom','action':'send_text','payload':{'text':'later synthetic'}});e.step();e.step();self.assertEqual(s.by_id(j['id'])['state'],'expired');self.assertEqual(s.get('fixture','later')['state'],'awaiting_confirmation');self.assertEqual(d.prepare.call_count,1);d.execute.assert_not_called()
 def test_accepted_cleanup_debt_is_not_reclassified_no_send(self):
  s,d,j,e=self.fixture();s.set_state(j['id'],'succeeded',{'state':'accepted','serverId':'1001','postActionPending':True});s.submit({'client':'fixture','request_id':'later','peer':'room@chatroom','action':'send_text','payload':{'text':'later'}});e.step();self.assertEqual(s.by_id(j['id'])['state'],'succeeded');d.cleanup.assert_not_called();d.execute.assert_not_called()

class GuardedMaintenanceControls(unittest.TestCase):
 def driver(self):
  d=types.SimpleNamespace(fds=[1],lease='same-original-lease');d.check_lease=Mock();return d
 def test_repl_guard_denied_following_line_cannot_create_raw_controls(self):
  d=self.driver();d.fds=[]
  try:assert False,'original acquire denied'
  except AssertionError:pass
  with patch('image_client.Controls') as raw:
   with self.assertRaises(runtime.BeforeEffect):recipes.controls(d)
   raw.assert_not_called()
 def test_cached_input_method_stops_after_guard_release(self):
  d=self.driver();raw=Mock()
  with patch('image_client.Controls',return_value=raw):c=recipes.controls(d)
  key=c.key;d.fds=[]
  with self.assertRaises(runtime.BeforeEffect):key(1)
  raw.key.assert_not_called()
 def test_old_control_cannot_cross_guard_reacquisition_even_same_fd_numbers(self):
  d=self.driver();raw=Mock()
  with patch('image_client.Controls',return_value=raw):c=recipes.controls(d)
  d.fds=[1]
  with self.assertRaises(runtime.BeforeEffect):c.click(1,2)
  raw.click.assert_not_called()
 def test_raw_raise_window_handle_is_guarded_and_close_remains_available(self):
  d=self.driver();raw=Mock()
  with patch('image_client.Controls',return_value=raw):c=recipes.controls(d)
  d.fds=[]
  with self.assertRaises(runtime.BeforeEffect):getattr(c,'x')
  c.close();raw.close.assert_called_once()
 def test_valid_original_guard_delegates_normal_controls(self):
  d=self.driver();raw=Mock()
  raw.one.return_value=None # This fixture has no Photos/Save window.
  with patch('image_client.Controls',return_value=raw):c=recipes.controls(d)
  c.click(1,2);c.key(3);raw.click.assert_called_once_with(1,2);raw.key.assert_called_once_with(3);self.assertGreaterEqual(d.check_lease.call_count,1)
 def test_cached_native_function_cannot_bypass_released_guard(self):
  d=self.driver();fn=Mock();raw=types.SimpleNamespace(t=types.SimpleNamespace(XTestFakeButtonEvent=fn),d=123,close=Mock())
  with patch('image_client.Controls',return_value=raw):c=recipes.controls(d)
  press,handle=c.t.XTestFakeButtonEvent,c.d;d.fds=[]
  with self.assertRaises(runtime.BeforeEffect):press(handle,1,1,0)
  fn.assert_not_called()
 def test_native_function_signature_setters_remain_compatible(self):
  d=self.driver();fn=Mock();raw=types.SimpleNamespace(x=types.SimpleNamespace(XRaiseWindow=fn),d=123,close=Mock())
  with patch('image_client.Controls',return_value=raw):c=recipes.controls(d)
  c.x.XRaiseWindow.argtypes=['fixture'];c.x.XRaiseWindow.restype=None;c.x.XRaiseWindow(123,456);self.assertEqual(fn.argtypes,['fixture']);self.assertIsNone(fn.restype);fn.assert_called_once_with(123,456)

class OriginalCleanupFocus(unittest.TestCase):
 def fixture(self,proof_ok=True,foreign=False):
  t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);r=Path(t.name).resolve();j={'id':'f'*32,'peer':'room@chatroom','action':'send_text','payload':{'text':'synthetic original'},'preview':{}}
  w={'id':'0x2','title':'Exact','x':0,'y':0,'width':623,'height':667};binding={'peer':j['peer'],'nativeTargetProof':{'fixture':True,'window':w}}
  composer.save(r,j,{'state':'staged','priorText':'','priorChars':0,'priorSHA':hashlib.sha256(b'').hexdigest(),'window':w,'binding':binding});state={'focused':False,'text':j['payload']['text']}
  ui=types.SimpleNamespace(cfg=binding,close=Mock())
  def draft():
   if not state['focused']:raise ValueError('original known window is not foreground')
   return state['text']
  ui.draft=draft;d=types.SimpleNamespace(root=r,session_bindings={},active_window=None,app_windows=lambda:[w],ui=lambda p:ui,_file_helper=lambda:types.SimpleNamespace(require_empty_editor=lambda u:None))
  for p in [patch.object(sending,'scene',side_effect=ValueError('unknown modal') if foreign else None),patch.object(navigation,'verify_session',side_effect=None if proof_ok else ValueError('wrong original identity'),return_value='verified'),patch.object(recipes,'controls',return_value=Mock()),patch.object(recipes,'activate',side_effect=lambda c,win:state.update(focused=True)),patch.object(composer,'clear',side_effect=lambda u:state.update(text=''))]:p.start();self.addCleanup(p.stop)
  return d,j,state
 def test_original_native_window_is_verified_and_focused_before_draft_restore(self):
  d,j,state=self.fixture();self.assertTrue(sending.cleanup(d,j));self.assertEqual(composer.load(d.root,j)['state'],'restored');self.assertTrue(state['focused'])
 def test_wrong_identity_or_foreign_modal_never_focuses_or_clears(self):
  for kind in ('identity','modal'):
   with self.subTest(kind=kind):
    d,j,state=self.fixture(proof_ok=kind!='identity',foreign=kind=='modal');self.assertFalse(sending.cleanup(d,j));self.assertFalse(state['focused']);self.assertEqual(state['text'],j['payload']['text'])
 def test_journal_window_must_equal_the_verified_native_proof_window(self):
  d,j,state=self.fixture();v=composer.load(d.root,j);v['window']=dict(v['window'],id='0x9',title='Other');composer.save(d.root,j,v)
  self.assertFalse(sending.cleanup(d,j));self.assertFalse(state['focused']);self.assertEqual(state['text'],j['payload']['text'])

if __name__=='__main__':unittest.main()
