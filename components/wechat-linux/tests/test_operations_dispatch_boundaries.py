import unittest,tempfile,copy,json,hashlib,importlib.util
from pathlib import Path
from unittest.mock import patch
from operations.public_api import PublicAPI,PublicError
from operations.store import Store,Conflict
from operations.driver import NativeDriver
from operations.runtime import BeforeEffect,Executor
from operations.assets import Assets,descriptor
CFG={'account':'self','clients':{'a':{'peers':['owner','missing'],'actions':['send_text','send_file','send_image']},'b':{'peers':['owner'],'actions':['send_text']}}}
def j(rid,peer='owner'):return {'client':'a','request_id':rid,'peer':peer,'action':'send_text','payload':{'text':'same text'}}
class Boundaries(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name).resolve()/'s';self.a=PublicAPI(self.root,copy.deepcopy(CFG));self.addCleanup(self.a.close)
 def admit(self,items,batch='x'):return self.a.call({'op':'admit','client':'a','batch_id':batch,'items':items})
 def test_same_body_different_source_ids_not_semantically_deduplicated(self):
  self.admit([{'job':j('source1')},{'job':j('source2')}]);self.assertEqual(len(self.a.s.list_jobs()),2)
 def test_unregistered_target_rejected_cleanly_before_any_ui_recipe(self):
  cfg=self.a.policy.cfg;f=self.root/'config.json';f.write_text(json.dumps(cfg));f.chmod(0o600);d=NativeDriver(self.root,cfg)
  with patch.object(d,'registered_binding',side_effect=BeforeEffect('target has no previously verified native/UI binding')),patch('operations.recipes.prepare') as recipe:
   try:d.prepare(j('new','missing'))
   except BeforeEffect as e:self.assertTrue(getattr(e,'clean',False));self.assertEqual(e.code,'TARGET_NOT_CALIBRATED')
   else:self.fail('missing registration must fail before UI')
   recipe.assert_not_called()
 def test_unrestored_private_journal_and_symlink_block_all_claims(self):
  out=self.admit([{'job':j('one')}]);jid=out['jobs'][0]['id'];f=self.root/(jid+'-composer.json');f.write_text(json.dumps({'state':'parked'}));f.chmod(0o600)
  self.assertIsNone(self.a.s.claim());f.unlink();f.symlink_to(self.root/'not-a-journal');self.assertIsNone(self.a.s.claim())
 def test_failed_second_supersession_rolls_back_first_cancellation_and_new_jobs(self):
  old=self.a.s.submit(j('old'));active=self.a.s.submit(j('active'));self.a.s.set_state(active['id'],'unknown',{'automaticReplay':False})
  with self.assertRaises(PublicError):self.admit([{'job':j('new'),'dispatch':{'supersedes':['old','active']}}])
  self.assertEqual(self.a.s.get('a','old')['state'],'queued');self.assertEqual(len(self.a.s.list_jobs()),2)
 def test_future_shared_asset_and_large_image_wait_for_actual_bytes(self):
  h=hashlib.sha256(b'x').hexdigest();aid=descriptor('b','x.txt',1,h)
  one=self.admit([{'job':dict(j('future-file'),action='send_file',payload={'asset':aid}),'dispatch':{'expected_asset':{'name':'x.txt','bytes':1,'sha256':h}}}])
  self.assertEqual(one['jobs'][0]['state'],'queued');self.assertIsNone(self.a.s.claim())
  h='a'*64;aid=descriptor('a','x.png',10000001,h)
  two=self.admit([{'job':dict(j('future-image'),action='send_image',payload={'asset':aid}),'dispatch':{'expected_asset':{'name':'x.png','bytes':10000001,'sha256':h}}}],batch='large-image')
  self.assertEqual(two['jobs'][0]['state'],'queued');self.assertIsNone(self.a.s.claim())
 def test_limits_and_duplicate_keys_fields_do_not_allocate_jobs(self):
  for req in [{'client':'a','batch_id':'x','items':[{'job':j(str(i))} for i in range(21)]},{'client':'a','batch_id':'x','items':[{'job':j('one')}],'ordered':True,'arbitrary_path':'/private'}]:
   with self.assertRaises(PublicError):self.a.call(dict(req,op='admit'))
  self.assertEqual(self.a.s.list_jobs(),[])
 def test_schema_upgrade_does_not_rewrite_legacy_rows_or_hashes(self):
  spec=importlib.util.spec_from_file_location('operations.old_store_fixture',Path(__file__).resolve().parents[1]/'test-fixtures/legacy-baseline/operations/store.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
  legacy=mod.Store(Path(self.t.name).resolve()/'legacy');old=legacy.submit(j('old'));rows=[tuple(r) for r in legacy.c.execute('select * from jobs')];events=[tuple(r) for r in legacy.c.execute('select * from events')];legacy.close()
  upgraded=Store(Path(self.t.name).resolve()/'legacy')
  try:self.assertEqual(rows,[tuple(r) for r in upgraded.c.execute('select * from jobs')]);self.assertEqual(events,[tuple(r) for r in upgraded.c.execute('select * from events')]);self.assertNotIn('dispatch',upgraded.get('a','old'))
  finally:upgraded.close()
if __name__=='__main__':unittest.main()

class Cancellation(unittest.TestCase):
 def test_positive_never_prepared_cancel_has_not_sent_outcome(self):
  with tempfile.TemporaryDirectory() as td:
   a=PublicAPI(Path(td).resolve()/'s',CFG)
   try:
    a.call({'op':'submit','job':j('old')});v=a.call({'op':'cancel','client':'a','request_id':'old'});self.assertEqual(v['outcome']['status'],'not_sent');self.assertTrue(v['result']['noSend'])
   finally:a.close()
 def test_queued_with_attempt_evidence_cannot_be_cancelled_as_never_sent(self):
  with tempfile.TemporaryDirectory() as td:
   a=PublicAPI(Path(td).resolve()/'s',CFG)
   try:
    row=a.s.submit(j('old'));(a.s.root/(row['id']+'-attempt.json')).write_text('{}')
    with self.assertRaises(ValueError):a.s.cancel('a','old')
   finally:a.close()

class MetadataIntegrity(unittest.TestCase):
 def test_changed_dispatch_metadata_without_immutable_hash_is_not_executed(self):
  with tempfile.TemporaryDirectory() as td:
   a=PublicAPI(Path(td).resolve()/'s',CFG)
   try:
    a.call({'op':'admit','client':'a','batch_id':'b','items':[{'job':j('one')}]})
    a.s.c.execute("UPDATE dispatch_metadata SET spec=?",(json.dumps({'kind':'reply','after':[],'expected_asset':None,'supersedes':[]}),))
    with self.assertRaises(ValueError):a.s.claim()
    self.assertEqual(a.s.c.execute('select state from jobs').fetchone()[0],'queued')
   finally:a.close()
