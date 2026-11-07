import unittest,tempfile,json,concurrent.futures,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.contract import parse_request,validate_job
from operations.store import Store,Conflict

def job(i='one',client='alpha',**patch):
 x={'client':'alpha','request_id':i,'action':'send_text','peer':'wxid_fixture_1987fcaa9f','payload':{'text':'测试\nhello'},'method':'native'};x.update(client=client,**patch);return x

class ContractTests(unittest.TestCase):
 def test_duplicate_key(self):
  with self.assertRaises(ValueError):parse_request('{"op":"get","op":"submit"}')
 def test_unknown_action(self):
  with self.assertRaises(ValueError):validate_job(job(action='shell',payload={'cmd':'id'}))
 def test_asset_traversal(self):
  with self.assertRaises(ValueError):validate_job(job(action='send_file',payload={'asset':'../../.ssh/id_rsa'}))
 def test_unknown_field(self):
  with self.assertRaises(ValueError):validate_job(dict(job(),force=True))
 def test_author_text_has_no_artificial_20kb_limit(self):
  self.assertEqual(validate_job(job(payload={'text':'x'*25000}))['payload']['text'],'x'*25000)

class QueueTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()/'private';self.s=Store(self.root)
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def test_idempotent_and_conflict(self):
  a=self.s.submit(job());self.assertEqual(a['id'],self.s.submit(job())['id'])
  with self.assertRaises(Conflict):self.s.submit(job(peer='wxid_fixture_384977ff4d'))
  self.assertEqual(self.s.get('alpha','one')['peer'],'wxid_fixture_1987fcaa9f')
 def test_no_wrong_client_access(self):
  self.s.submit(job())
  with self.assertRaises(KeyError):self.s.get('beta','one')
 def test_one_active(self):
  self.s.submit(job('a'));self.s.submit(job('b'));a=self.s.claim();self.assertEqual(a['request_id'],'a');self.assertIsNone(self.s.claim())
 def test_confirm_binds_snapshot(self):
  self.s.submit(job());a=self.s.claim();self.s.preview(a['id'],{'sha256':'a'*64,'context':'b'*64},now=100,ttl=60)
  p=self.s.get('alpha','one')
  with self.assertRaises(ValueError):self.s.confirm('alpha','one','wrong',now=101)
  self.s.confirm('alpha','one',p['confirmation_token'],now=101);self.assertEqual(self.s.get('alpha','one')['state'],'confirmed')
 def test_expired_not_confirmed(self):
  self.s.submit(job());a=self.s.claim();self.s.preview(a['id'],{'sha256':'a'*64},now=100,ttl=60)
  with self.assertRaises(ValueError):self.s.confirm('alpha','one',self.s.get('alpha','one')['confirmation_token'],now=161)
 def test_cancel_queued(self):
  self.s.submit(job());self.s.cancel('alpha','one');self.assertEqual(self.s.get('alpha','one')['state'],'cancelled')
 def test_executing_recovery_unknown(self):
  self.s.submit(job());a=self.s.claim();self.s.set_state(a['id'],'executing');self.s.close();self.s=Store(self.root);self.s.recover()
  self.assertEqual(self.s.get('alpha','one')['state'],'unknown');self.assertIsNone(self.s.claim())
 def test_multi_client_concurrent_hundred(self):
  self.s.close()
  def create(i):
   s=Store(self.root)
   try:return s.submit(job(str(i),'c'+str(i%4)))['id']
   finally:s.close()
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:ids=list(ex.map(create,range(100)))
  self.s=Store(self.root);self.assertEqual(len(set(ids)),100);self.assertEqual(len(self.s.list_jobs()),100)
 def test_private_directory_symlink_rejected(self):
  link=Path(self.tmp.name)/'link';link.symlink_to(self.root,target_is_directory=True)
  with self.assertRaises(ValueError):Store(link)

if __name__=='__main__':unittest.main()

class RecoveryCancellation(unittest.TestCase):
 def test_interrupted_preparation_can_request_verified_cleanup(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(Path(td).resolve()/'private');j=s.submit(job());s.claim();s.recover();self.assertEqual(s.get('alpha','one')['state'],'needs_attention');s.cancel('alpha','one');self.assertEqual(s.get('alpha','one')['expires'],0);s.close()
 def test_attempted_effect_cannot_be_cancelled_as_a_draft(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(Path(td).resolve()/'private');j=s.submit(job());s.claim();s.set_state(j['id'],'needs_attention');(s.root/(j['id']+'-attempt.json')).write_text('{}')
   with self.assertRaises(ValueError):s.cancel('alpha','one')
   s.close()
