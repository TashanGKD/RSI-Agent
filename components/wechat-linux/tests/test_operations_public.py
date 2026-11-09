import unittest,tempfile,sys,time,json,base64,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.public_api import PublicAPI,PublicError
class PublicTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve()/'state';self.cfg={'account':'s','clients':{'a':{'peers':['wxid_fixture_1987fcaa9f','wxid_fixture_4c90539d6a'],'actions':['send_text','send_file','reply','forward','mention']}}}
  self.a=PublicAPI(self.root,self.cfg,contacts=lambda peers:[{'peer':'wxid_fixture_1987fcaa9f','name':'本人','alias':'owner-id'},{'peer':'wxid_fixture_4c90539d6a','name':'另一人','alias':'other-id'}])
 def tearDown(self):self.a.close();self.t.cleanup()
 def submit(self,rid='r',**patch):
  j={'client':'a','request_id':rid,'action':'send_text','peer':'wxid_fixture_1987fcaa9f','payload':{'text':'  中文\n保留空格  '}};j.update(patch);return self.a.call({'op':'submit','job':j})
 def test_coordinate_operations_rejected_before_queue(self):
  for op in ['plan_step','assist','retry_native','shell']:
   with self.assertRaises(PublicError):self.a.call({'op':op,'point':[10,20]})
  self.assertEqual(self.a.s.list_jobs(),[])
 def test_public_job_cannot_select_internal_method_or_steps(self):
  for field,value in [('method','visual'),('point',[0,0]),('step',{'kind':'click'})]:
   with self.assertRaises(PublicError):self.submit(**{field:value})
  self.assertEqual(self.a.s.list_jobs(),[])
 def test_asset_path_not_accepted_and_no_allocation(self):
  with self.assertRaises((PublicError,ValueError)):self.submit(action='send_file',payload={'asset':'../../.ssh/id_rsa'})
  self.assertEqual(self.a.s.list_jobs(),[])
 def test_submission_never_confirms(self):
  j=self.submit();self.assertEqual(j['state'],'queued');self.assertIsNone(j['confirmation_token']);self.assertEqual(self.a.s.get('a','r')['payload']['text'],'  中文\n保留空格  ')
 def test_preview_metadata_has_no_coordinates_or_server_paths(self):
  j=self.submit();self.a.s.claim();self.a.s.preview(j['id'],{'sha256':'a'*64,'context':'private','header':'private','navigationPoint':[12,23],'asset':{'path':'/private/server','name':'x'},'summary':{'peer':'wxid_fixture_1987fcaa9f','text':'x'},'step':{'point':[12,34]}})
  v=self.a.call({'op':'get','client':'a','request_id':'r'});raw=json.dumps(v);self.assertNotIn('navigationPoint',raw);self.assertNotIn('/private/server',raw);self.assertNotIn('"step"',raw);self.assertEqual(v['preview']['sha256'],'a'*64)
 def test_wrong_token_does_not_send(self):
  j=self.submit();self.a.s.claim();self.a.s.preview(j['id'],{'sha256':'a'*64})
  with self.assertRaises(PublicError):self.a.call({'op':'confirm','client':'a','request_id':'r','token':'wrong'})
  self.assertEqual(self.a.s.get('a','r')['state'],'awaiting_confirmation')
 def test_duplicate_same_id_not_another_job(self):
  j=self.submit();self.assertEqual(self.submit()['id'],j['id'])
  with self.assertRaises(PublicError):self.submit(peer='wxid_fixture_4c90539d6a')
 def test_resolve_is_scoped_and_returns_exact_native_identity(self):
  v=self.a.call({'op':'resolve','client':'a','query':'本人'});self.assertEqual(v['peer'],'wxid_fixture_1987fcaa9f')
  with self.assertRaises(PublicError):self.a.call({'op':'resolve','client':'a','query':'unknown'})
 def test_ambiguous_name_returns_choices_instead_of_clicking(self):
  self.a.contacts=lambda peers:[{'peer':'wxid_fixture_1987fcaa9f','name':'同名','alias':''},{'peer':'wxid_fixture_4c90539d6a','name':'同名','alias':''}]
  with self.assertRaises(PublicError) as e:self.a.call({'op':'resolve','client':'a','query':'同名'})
  self.assertEqual(e.exception.code,'AMBIGUOUS_RECIPIENT');self.assertEqual(len(e.exception.details['candidates']),2)
 def test_unsupported_action_does_not_block_queue(self):
  with self.assertRaises(PublicError) as e:self.submit(action='mention',payload={'members':['wxid_fixture_4c90539d6a'],'text':'x'})
  self.assertEqual(e.exception.code,'UNSUPPORTED_ACTION');self.assertEqual(self.a.s.list_jobs(),[])
 def test_wait_is_bounded_and_never_executes(self):
  self.submit()
  with self.assertRaises(PublicError):self.a.call({'op':'get','client':'a','request_id':'r','wait_seconds':1000})
  self.assertEqual(self.a.s.get('a','r')['state'],'queued')
 def test_unknown_result_not_cancelled_or_resent(self):
  j=self.submit();self.a.s.claim();self.a.s.set_state(j['id'],'unknown',{'automaticReplay':False})
  with self.assertRaises(PublicError):self.a.call({'op':'cancel','client':'a','request_id':'r'})
  self.assertEqual(self.submit()['state'],'unknown');self.assertEqual(len(self.a.s.list_jobs()),1)
 def test_status_does_not_expose_another_request_body(self):
  self.submit();self.a.s.claim();v=self.a.call({'op':'status'});self.assertNotIn('payload',v['active']);self.assertNotIn('保留空格',json.dumps(v,ensure_ascii=False))
 def test_reconcile_keeps_read_only_evidence_visible(self):
  j=self.submit();self.a.s.claim();self.a.s.set_state(j['id'],'unknown',{'reason':'transport_lost'})
  from unittest.mock import patch
  with patch('operations.driver.NativeDriver.verify',return_value={'state':'unknown','reason':'no_unique_new_receipt','automaticReplay':False}):
   v=self.a.call({'op':'reconcile','client':'a','request_id':'r'})
  self.assertEqual(v['readOnlyReconciliation']['reason'],'no_unique_new_receipt')
  self.assertEqual(v['state'],'unknown')
