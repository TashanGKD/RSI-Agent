"""V2 removes operation ACLs; observations still require actual identity and proof."""
import copy,hashlib,json,unittest
from unittest.mock import patch
import send_tool_observer as st
from delivery_receipt_cache import member,SAFE_FIELDS
from delivery_obligations import build
import work_observer as w
class PolicyV2Observation(unittest.TestCase):
 def job(self,client,action='send_file',peer='21546874409@chatroom'):
  text='current work';sha=hashlib.sha256(text.encode()).hexdigest();return {'id':'a'*32,'client':client,'request_id':'current-fixture-5c75bd9e-20260101','peer':peer,'action':action,'payload':{'text':text}if action=='send_text'else{'asset':'b'*64},'created':1793959000,'updated':1793959001,'state':'succeeded','result':{'state':'accepted','peer':peer,'serverId':'123456789','localId':91,'nativeFilenameMatch':True,'nativeSizeMatch':True,'nativeMD5Match':True,'senderId':'wxid_fixture_operator','nativeStatus':2,'nativeCreateTime':1793959001,'uniqueCandidateCount':1,'evidence':'native-sender-status-and-operation-semantics','textComparison':{'expectedSHA256':sha,'actualSHA256':sha}}}
 def test_known_author_new_target_file_and_matching_cache_are_observed(self):
  for c in ['employee_method','aup_support','research_secretary','forum_employee']:
   p=st.project(self.job(c));self.assertIsNotNone(p,c);self.assertTrue(p['nativeReceiptVerified'],c)
   out={};sid=w.source(out,'原微信工具:'+c+'/'+p['request_id'],json.dumps({k:v for k,v in p.items()if k in SAFE_FIELDS}),'now','proof');self.assertTrue(member(out[sid],c)['nativeReceiptVerified'])
 def test_permission_removal_does_not_prove_delivery_or_borrow_wrong_target(self):
  for c in ['employee_method','aup_support','research_secretary']:
   j=self.job(c);j['result']['nativeMD5Match']=False;p=st.project(j);self.assertIsNotNone(p);self.assertFalse(p['nativeReceiptVerified'])
   p=st.project(self.job(c));p['peer']='different@chatroom';out={};sid=w.source(out,'原微信工具:'+c+'/'+p['request_id'],json.dumps({k:v for k,v in p.items()if k in SAFE_FIELDS}),'now','tampered')
   with self.assertRaises(ValueError):member(out[sid],c)
 def test_v2_legacy_action_scope_wait_is_prepared_not_approval_or_delivered(self):
  from test_delivery_obligations import claim,OWNER
  p=build([claim(kind='authority',requestId=None,componentCount=4)],{},[],[{'id':'secretary','threadId':OWNER}],200,policy_format_version=2)
  self.assertEqual(p['rows'][0]['stage'],'committed_not_admitted');self.assertEqual(p['rows'][0]['componentCount'],4)
 def test_unknown_current_policy_does_not_reassert_stale_authority(self):
  from test_delivery_obligations import claim,OWNER
  p=build([claim(kind='authority',requestId=None)],{},[],[{'id':'secretary','threadId':OWNER}],200,policy_format_version=None)
  self.assertFalse(p['rows']);self.assertIn('source_read_or_format',p['coverage']['gaps'])
 def test_status_carries_actual_policy_version_not_registry_inference(self):
  def call(q):
   if q['op']=='status':return {'workerLive':True,'worker':{'policyFormatVersion':2}}
   return {'jobs':[]}if q['op']=='list'else{'items':[]}
  with patch.object(st,'readonly',side_effect=call):p=st.read_tools()
  self.assertEqual(p['status']['policyFormatVersion'],2)

def setUpModule():
 from unittest.mock import patch
 import contextlib,collect,send_tool_observer,delivery_obligations,employee_profiles,account_contract,model_accounts
 global _portable_patches
 _portable_patches=contextlib.ExitStack()
 clients={'secretary':'secretary','science':'science','organoid_bp':'organoid','forum_employee':'forum','employee_pilot':'employee-pilot','employee_method':'system','aup_support':'aup-support','research_secretary':'research-secretary'}
 ids={'secretary':'00000000-0000-4000-8000-4344f0fd9daa','science':'00000000-0000-4000-8000-37b7cd446cba','organoid':'00000000-0000-4000-8000-f709f264f942'}
 emails=tuple('fixture'+str(i)+'@example.invalid' for i in range(3))
 for mod,key,value in [(send_tool_observer,'CLIENTS',clients),(collect,'IDS',ids),(delivery_obligations,'CLIENTS',clients),(delivery_obligations,'OWNERS',ids),(employee_profiles,'IDS',ids),(account_contract,'EMAILS',emails),(model_accounts,'EMAILS',emails)]:
  _portable_patches.enter_context(patch.object(mod,key,value))
def tearDownModule():
 _portable_patches.close()
