import tempfile,unittest,sys,hashlib,base64
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.api import API
class ApiTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve()/'private';self.a=API(self.root,{'account':'wxid_fixture_d756b9d49d','clients':{'a':{'peers':['wxid_fixture_1987fcaa9f'],'actions':['send_text','send_file']}}})
 def tearDown(self):self.a.close();self.t.cleanup()
 def test_unknown_operation_rejected(self):
  with self.assertRaises(ValueError):self.a.call({'op':'shell','cmd':'id'})
 def test_malformed_action_rejected_before_queue(self):
  with self.assertRaises(ValueError):self.a.call({'op':'submit','job':{'client':'a','request_id':'one','action':'shell','peer':'wxid_fixture_person','payload':{'text':'x'}}})
  self.assertEqual(self.a.s.list_jobs(),[])
 def test_upload_data_and_send_reference(self):
  data=b'test';asset=self.a.call({'op':'upload','client':'a','name':'t.txt','sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()})
  j=self.a.call({'op':'submit','job':{'client':'a','request_id':'one','action':'send_file','peer':'wxid_fixture_1987fcaa9f','payload':{'asset':asset['id']}}});self.assertEqual(j['state'],'queued')
 def test_get_is_read_only(self):
  j=self.a.call({'op':'submit','job':{'client':'a','request_id':'one','action':'send_text','peer':'wxid_fixture_1987fcaa9f','payload':{'text':'x'}}});self.assertEqual(self.a.call({'op':'get','client':'a','request_id':'one'})['id'],j['id'])
 def test_refresh_cannot_change_queued_or_confirmed_input(self):
  self.a.call({'op':'submit','job':{'client':'a','request_id':'one','action':'send_text','peer':'wxid_fixture_1987fcaa9f','payload':{'text':'x'}}})
  with self.assertRaises(ValueError):self.a.call({'op':'refresh','client':'a','request_id':'one'})
 def test_asset_download_preserves_uploader_across_attribution(self):
  data=b'abc';x=self.a.call({'op':'upload','client':'a','name':'x.txt','sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()})
  self.assertEqual(base64.b64decode(self.a.call({'op':'download','client':'a','asset':x['id']})['data']),data)
  r=self.a.call({'op':'download','client':'other','asset':x['id']});self.assertEqual(base64.b64decode(r['data']),data);self.assertEqual(r['client'],'a')
 def test_history_persists_and_is_read_only(self):
  j=self.a.call({'op':'submit','job':{'client':'a','request_id':'one','action':'send_text','peer':'wxid_fixture_1987fcaa9f','payload':{'text':'x'}}})
  h=self.a.call({'op':'events','client':'a','request_id':'one'});self.assertEqual(h['events'][0]['state'],'queued');self.assertEqual(self.a.s.get('a','one')['state'],'queued')
 def test_recent_health_from_a_dead_process_is_not_live(self):
  import json,time
  (self.root/'health.json').write_text(json.dumps({'pid':999999999,'birth':'old','at':time.time(),'state':'idle'}))
  v=self.a.call({'op':'status'});self.assertFalse(v['heartbeatFresh']);self.assertFalse(v['workerLive'])
