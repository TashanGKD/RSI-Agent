# -*- coding:utf-8 -*-
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import send_tool_observer as st
import work_observer as w
from delivery_health import note_seed,build_health
CLIENT='employee_method';OWNER='00000000-0000-4000-8000-4e07f8267a19';PEER='wxid_fixture_owner'
class MethodClientTests(unittest.TestCase):
 def job(self,rid='method-fixture-50bd85a6-20260101'):
  text='normal frozen reply';h=hashlib.sha256(text.encode()).hexdigest();return {'client':CLIENT,'request_id':rid,'peer':PEER,'action':'send_text','payload':{'text':text},'state':'succeeded','created':100,'updated':110,'result':{'state':'accepted','peer':PEER,'serverId':'8000037419276118460','senderId':'wxid_fixture_operator','nativeStatus':2,'nativeCreateTime':105,'uniqueCandidateCount':1,'evidence':'native-sender-status-and-operation-semantics','textComparison':{'expectedSHA256':h,'actualSHA256':h}}}
 def test_exact_client_is_static_readonly_and_projects_verified_success(self):
  self.assertEqual(st.CLIENTS[CLIENT],'system');seen=[]
  st.readonly({'op':'get','client':CLIENT,'request_id':'method-one','audit':False,'wait_seconds':0},call=lambda r:seen.append(r) or {})
  self.assertEqual(len(seen),1);p=st.project(self.job());self.assertEqual(p['employee'],'system');self.assertTrue(p['nativeReceiptVerified'])
 def test_other_client_peer_action_or_mutation_not_admitted(self):
  for op in ['submit','confirm','cancel','reconcile','dispatch','upload']:
   with self.assertRaises(ValueError):st.readonly({'op':op,'client':CLIENT},call=lambda r:self.fail('mutation'))
  with self.assertRaises(ValueError):st.readonly({'op':'list','client':'employee_arbitrary'},call=lambda r:self.fail('unknown client'))
  for k,v in [('peer','other@chatroom'),('action','send_image'),('action','forward')]:self.assertFalse(st.project(dict(self.job(),**{k:v}))['nativeReceiptVerified'])
  j=self.job();j['result'].pop('senderId');self.assertFalse(st.project(j)['nativeReceiptVerified'])
 def test_real_successful_ack_is_a_component_not_new_unfinished_business(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();rid='method-fixture-accepted-ack-20260101';head='- **事情**：本岗接续\n- **怎么来的**：本人交办\n- **现在怎么样**：已办好\n- **过程笔记**：'+rid+' accepted / actual native success'
   role={'id':'system','threadId':OWNER,'root':root};seed=note_seed(role,root/'note.md',head,'business','source');self.assertIn(rid,seed['requestIds']);job=st.project(self.job(rid));item={'id':'business','employee':'system','title':'原责任','state':'已办好','commitment':'accepted'};h=build_health(items=[item],seeds=[seed],jobs=[job],gaps=[],observed_at=200);self.assertEqual(len(h['incidents']),1);self.assertEqual(h['incidents'][0]['status'],'resolved')
 def test_local_relative_job_receipt_does_not_depend_on_filename_or_id_prefix(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();folder=root/'normal';folder.mkdir();(folder/'proof.json').write_text(json.dumps({'jobs':[self.job('custom-fixture-b9291691-20260101')]}));head='- **事情**：本岗说明\n- **现在怎么样**：已办好\n- **过程笔记**：normal/proof.json'
   seed=note_seed({'id':'system','threadId':OWNER,'root':root},root/'workbook/a.md',head,'b','s');self.assertIn('custom-fixture-b9291691-20260101',seed['requestIds'])
 def test_identity_requires_same_thread_matching_role_and_state_preserves_aliases(self):
  from employee_identity import read_identity
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'ROLE.md').write_text('# 人事负责人\n称呼：人事负责人。原称呼方法负责人保留。');state={'identity':{'name':'人事负责人','thread_id':OWNER,'work_root':str(root),'previous_names':['数字员工方法','方法负责人']}};(root/'STATE.json').write_text(json.dumps(state))
   role={'id':'system','threadId':OWNER,'root':root,'name':'方法与统一系统'};identity=read_identity(role);self.assertEqual(identity['name'],'人事负责人');self.assertIn('方法与统一系统',identity['aliases']);self.assertIn('方法负责人',identity['aliases'])
   state['identity']['thread_id']='different';(root/'STATE.json').write_text(json.dumps(state));self.assertIsNone(read_identity(role))
if __name__=='__main__':unittest.main()

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
