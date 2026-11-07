import copy,json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import send_tool_observer as st

class DeliveryTests(unittest.TestCase):
 def reducer(self,**kw):
  import delivery_health as d
  return d.build_health(**kw)
 def base(self):
  item={'id':'biz','employee':'secretary','title':'核示例课程原材料并对齐','state':'等反馈','commitment':'accepted','sourceId':'note'}
  seed={'businessId':'biz','employee':'secretary','ownerThreadId':'00000000-0000-4000-8000-4344f0fd9daa','requestIds':['secretary-fixture-11fe9c9a-20260101'],'operationEvidenceIds':['secretary-fixture-11fe9c9a-20260101'],'sourceId':'note'}
  j={'client':'secretary','employee':'secretary','request_id':'secretary-fixture-11fe9c9a-20260101','peer':'owner','action':'send_text','state':'failed','created':100,'updated':110,'reason':'CHAT_POPOUT_NOT_OPENED','contentHash':'a'*64,'nativeReceiptVerified':False,'recoveryOwnerThreadId':'00000000-0000-4000-8000-7cd0d4e0445a','supersedes':[]}
  return item,seed,j
 def runhealth(self,jobs=None,**kw):
  i,s,j=self.base();return self.reducer(items=[i],seeds=[s],jobs=jobs or [j],gaps=[],observed_at=200,**kw)
 def test_failed_direct_visible_without_central_assignment(self):
  h=self.runhealth();i=h['incidents'][0];self.assertEqual(i['status'],'blocked');self.assertEqual(i['businessId'],'biz');self.assertEqual(i['reasonCode'],'CHAT_POPOUT_NOT_OPENED');self.assertFalse(i['nativeReceiptVerified']);self.assertTrue(i['recoveryOwnerThreadId'])
 def test_same_content_retry_resolves_only_same_component(self):
  i,s,j=self.base();r={**j,'request_id':j['request_id']+'-r1','state':'succeeded','updated':150,'created':140,'nativeReceiptVerified':True,'serverId':'123'}
  h=self.runhealth([j,r]);self.assertEqual(h['incidents'][0]['status'],'resolved');self.assertEqual(len(h['incidents'][0]['requestIds']),2)
 def test_other_success_does_not_close_image_or_different_body(self):
  _,_,j=self.base();r={**j,'request_id':j['request_id']+'-r1','state':'succeeded','contentHash':'b'*64,'updated':150,'nativeReceiptVerified':True}
  h=self.runhealth([j,r]);self.assertEqual(h['incidents'][0]['status'],'blocked')
  r.update(contentHash=j['contentHash'],action='send_image');self.assertEqual(self.runhealth([j,r])['incidents'][0]['status'],'blocked')
 def test_same_peer_and_content_new_day_not_recovery(self):
  _,_,j=self.base();r={**j,'request_id':'secretary-fixture-7c7b9b5a-20260101','state':'succeeded','updated':150,'nativeReceiptVerified':True};self.assertEqual(self.runhealth([j,r])['incidents'][0]['status'],'blocked')
 def test_unknown_and_missing_not_healthy(self):
  _,_,j=self.base();self.assertEqual(self.runhealth([{**j,'state':'unknown'}])['incidents'][0]['status'],'unknown')
  h=self.runhealth([{**j,'request_id':'other'}]);self.assertEqual(h['incidents'][0]['status'],'unknown');self.assertFalse(h['incidents'][0]['nativeReceiptVerified'])
 def test_closed_and_ack_dont_create_new_debt(self):
  i,s,j=self.base();i['state']='不用管了';h=self.reducer(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200);self.assertEqual(h['incidents'][0]['status'],'not_required')
  s['requestIds']=['secretary-fixture-1cf6dadb-20260101-ack'];j.update(request_id=s['requestIds'][0]);self.assertEqual(self.reducer(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200)['incidents'],[])
 def test_stable_identity_and_change_time_not_sampling(self):
  a=self.runhealth();b=self.runhealth(previous=a);self.assertEqual(a['incidents'],b['incidents']);self.assertEqual(a['incidents'][0]['updatedAt'],110)
 def test_failed_projection_keeps_history_after_resolved(self):
  from delivery_health import attach_health
  _,_,j=self.base();r={**j,'request_id':j['request_id']+'-r1','state':'succeeded','updated':150,'nativeReceiptVerified':True}
  h=self.runhealth([j,r]);sending={'items':[]};out={};attach_health(sending,h,[j,r],out,'2026-11-01T08:00:00Z',lambda *a:'safe-source',{})
  self.assertEqual(len(sending['items']),1);self.assertEqual(sending['items'][0]['state'],'sent');self.assertEqual(len(sending['items'][0]['toolOperations']),2)
 def test_public_summary_never_contains_payload_secret_paths(self):
  i,s,j=self.base();i['title']='正常事情 password=supersecret';j.update(text='token=hidden',preview='binary',reason='path /home/operator/private/a SECRET')
  h=self.reducer(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200);v=json.dumps(h);self.assertNotIn('supersecret',v);self.assertNotIn('hidden',v);self.assertNotIn('/Users/',v);self.assertNotIn('binary',v)
 def test_readonly_batch_bounds_and_mutation_rejected(self):
  for req in [{'op':'get_many','client':'secretary','request_ids':['../secret'],'wait_seconds':0,'audit':False},{'op':'get_many','client':'secretary','request_ids':['x']*51,'wait_seconds':0,'audit':False},{'op':'dispatch_summary','client':'secretary','limit':21},{'op':'get_many','client':'secretary','request_ids':['x'],'wait_seconds':0,'audit':True}]:
   with self.assertRaises(ValueError):st.readonly(req,call=lambda r:self.fail('transport must not run'))
  self.assertEqual(st.readonly({'op':'dispatch_summary','client':'secretary','limit':20},call=lambda r:{'items':[]}),{'items':[]})
 def test_native_success_requires_matching_receipt(self):
  j={'client':'secretary','request_id':'x','peer':'owner','action':'send_text','state':'succeeded','payload':{'text':'hi'},'result':{'state':'accepted','peer':'other','serverId':'123','nativeStatus':2,'nativeCreateTime':100,'uniqueCandidateCount':1,'textComparison':{'expectedSHA256':'a'*64,'actualSHA256':'a'*64}}}
  self.assertFalse(st.project(j)['nativeReceiptVerified']);j['result']['peer']='owner';self.assertFalse(st.project(j)['nativeReceiptVerified'])
 def test_recent_summary_ids_target_get_not_old_list_only(self):
  def fake(req):
   if req['op']=='status':return {}
   if req['op']=='list':return {'jobs':[]}
   if req['op']=='dispatch_summary':return {'items':[{'request_id':'fresh-fixture-36cf2ba0-20260101'}],'truncated':True}
   return {'jobs':[{'client':req['client'],'request_id':rid,'action':'send_text','payload':{},'result':{}} for rid in req['request_ids']]}
  with patch.object(st,'readonly',side_effect=lambda req:fake(req)):
   x=st.read_tools();self.assertTrue(any(j['request_id']=='fresh-fixture-36cf2ba0-20260101' for j in x['jobs']));self.assertTrue(x['gaps'])
if __name__=='__main__':unittest.main()

class ContractTests(unittest.TestCase):
 def test_new_health_is_accepted_and_its_evidence_synced(self):
  from work_contract import validate_work,source_refs
  h={'version':1,'observedAt':100,'incidents':[],'coverage':{'bounded':True,'gaps':[]}}
  w={'version':1,'readOnly':True,'employees':[],'items':[],'sending':{'items':[]},'modes':{'sourceId':'s'},'deliveryHealth':h}
  validate_work(w,{'s':{'text':'ok'}})
  self.assertIn('proof',source_refs({'deliveryHealth':{'incidents':[{'evidenceRefs':['proof']}]}}))
 def test_health_rejects_extra_payload_invalid_owner_or_future_health_claim(self):
  from work_contract import validate_work
  i,s,j=DeliveryTests().base();from delivery_health import build_health
  h=build_health(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200)
  base={'version':1,'readOnly':True,'employees':[],'items':[],'sending':{'items':[]},'modes':{'sourceId':'note'},'deliveryHealth':h}
  for field,value in [('text','password=secret'),('ownerThreadId','not-a-uuid'),('nativeReceiptVerified',True)]:
   w=copy.deepcopy(base);w['deliveryHealth']['incidents'][0][field]=value
   with self.assertRaises(ValueError):validate_work(w,{'note':{'text':'ok'}})

class DiscoveryTests(unittest.TestCase):
 def test_only_explicit_normal_receipts_inside_approved_roots(self):
  from delivery_health import receipt_ids
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();work=root/'work';work.mkdir();p=work/'RESULT.json';p.write_text(json.dumps({'jobs':[{'client':'secretary','request_id':'secretary-fixture-dca54413-20260101','peer':'owner','action':'send_text'}]}))
   self.assertEqual(receipt_ids(str(p),'secretary',[root]),['secretary-fixture-dca54413-20260101'])
   link=work/'LINK-RESULT.json';link.symlink_to(p)
   self.assertEqual(receipt_ids(str(link),'secretary',[root]),[])
   self.assertEqual(receipt_ids('/etc/passwd','secretary',[root]),[])
   secret=work/'password-RESULT.json';secret.write_text(p.read_text());self.assertEqual(receipt_ids(str(secret),'secretary',[root]),[])
 def test_temporary_source_failure_retains_known_unresolved_incident(self):
  i,s,j=DeliveryTests().base();from delivery_health import build_health
  prev=build_health(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200)
  h=build_health(items=[i],seeds=[],jobs=[],gaps=['source failed'],observed_at=300,previous=prev)
  self.assertEqual(h['incidents'][0]['id'],prev['incidents'][0]['id']);self.assertEqual(h['incidents'][0]['status'],'unknown')


class IdentityTests(unittest.TestCase):
 def test_delayed_failure_annotation_not_new_attempt(self):
  t=DeliveryTests();i,s,j=t.base();r={**j,'request_id':j['request_id']+'-r1','state':'succeeded','created':140,'updated':150,'nativeReceiptVerified':True}
  j['updated']=190
  self.assertEqual(t.runhealth([j,r])['incidents'][0]['status'],'resolved')
 def test_missing_then_found_does_not_change_component_id(self):
  t=DeliveryTests();missing=t.runhealth([{'request_id':'other','employee':'science'}]);found=t.runhealth()
  self.assertEqual(missing['incidents'][0]['id'],found['incidents'][0]['id'])

class SourceFilterTests(unittest.TestCase):
 def test_business_id_is_not_an_api_key_but_real_key_is_redacted(self):
  from work_observer import public_text
  self.assertIn('task-d973dd3c3122cf',public_text('businessId=task-d973dd3c3122cf'))
  self.assertEqual(public_text('key sk-'+'z'*30),'')

class ClosureTests(unittest.TestCase):
 def test_cancel_of_tool_attempt_is_not_cancel_of_business(self):
  t=DeliveryTests();_,_,j=t.base();j['state']='cancelled'
  self.assertEqual(t.runhealth([j])['incidents'][0]['status'],'unknown')
 def test_explicit_replacement_with_proven_new_delivery_can_close(self):
  t=DeliveryTests();_,_,j=t.base();r={**j,'request_id':'secretary-fixture-3e5ee41b-20260101','contentHash':'b'*64,'state':'succeeded','nativeReceiptVerified':True,'created':150,'updated':160,'supersedes':[j['request_id']]}
  self.assertEqual(t.runhealth([j,r])['incidents'][0]['status'],'resolved')

class ChineseIdTests(unittest.TestCase):
 def test_ids_adjacent_to_chinese_do_not_disappear_or_become_path_names(self):
  from delivery_health import note_seed
  r={'id':'secretary','threadId':'00000000-0000-4000-8000-4344f0fd9daa','root':Path('/tmp')}
  s=note_seed(r,'note','原secretary-fixture-0e5d36e6-20260101为failed；目录/employee-fixture-ab027e21-20260101/原处。','b','s')
  self.assertEqual(s['requestIds'],['secretary-fixture-0e5d36e6-20260101'])

class SemanticReviewTests(unittest.TestCase):
 def test_completed_business_does_not_hide_failed_delivery(self):
  t=DeliveryTests();i,s,j=t.base();i['state']='已办好'
  h=t.reducer(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200)
  self.assertEqual(h['incidents'][0]['status'],'unknown')
 def test_completed_with_actual_accepted_is_resolved(self):
  t=DeliveryTests();i,s,j=t.base();i['state']='已完成';j.update(state='succeeded',nativeReceiptVerified=True)
  self.assertEqual(t.reducer(items=[i],seeds=[s],jobs=[j],gaps=[],observed_at=200)['incidents'][0]['status'],'resolved')
 def test_arbitrary_reference_does_not_invent_unknown_send(self):
  t=DeliveryTests();i,s,j=t.base();s['operationEvidenceIds']=[]
  h=t.reducer(items=[i],seeds=[s],jobs=[],gaps=[],observed_at=200)
  self.assertEqual(h['incidents'],[]);self.assertGreater(h['coverage']['missingCurrentReceipts'],0)
 def test_needs_attention_not_ordinary_pending(self):
  t=DeliveryTests();_,_,j=t.base();j.update(state='needs_attention',reason=None)
  self.assertEqual(t.runhealth([j])['incidents'][0]['status'],'blocked')
 def test_manual_confirmation_is_pending_not_fault(self):
  t=DeliveryTests();_,_,j=t.base();j.update(state='awaiting_confirmation',reason=None)
  self.assertEqual(t.runhealth([j])['incidents'][0]['status'],'pending')

class CurrentResponsibilityTests(unittest.TestCase):
 def test_stage_end_requires_exact_replacement_not_only_same_peer(self):
  t=DeliveryTests();i,s,j=t.base();s['requestIds']+=['secretary-fixture-c626b04d-20260101'];s['noLongerWaitingForSend']=True
  r={**j,'request_id':s['requestIds'][-1],'kind':'reply','created':140,'updated':150,'state':'succeeded','nativeReceiptVerified':True,'contentHash':'b'*64}
  h=t.reducer(items=[i],seeds=[s],jobs=[j,r],gaps=[],observed_at=200);self.assertEqual(len(h['incidents']),2)
  r['supersedes']=[j['request_id']];h=t.reducer(items=[i],seeds=[s],jobs=[j,r],gaps=[],observed_at=200);self.assertEqual(len(h['incidents']),1);self.assertEqual(h['incidents'][0]['status'],'resolved')
  r['supersedes']=[];s['recurring']=True;h=t.reducer(items=[i],seeds=[s],jobs=[j,r],gaps=[],observed_at=200);self.assertEqual(len(h['incidents']),2)
 def test_bad_previous_reference_is_removed_not_preserved_forever(self):
  t=DeliveryTests();i,s,j=t.base();old=t.runhealth();old['incidents'][0].update(status='unknown',reasonCode='no_current_receipt',requestIds=['employee-fixture-ab027e21-20260101'])
  h=t.reducer(items=[i],seeds=[],jobs=[],gaps=['not indexed'],observed_at=300,previous=old,proven_requests=set())
  self.assertEqual(h['incidents'],[])

class UnassociatedReceiptTests(unittest.TestCase):
 def test_recent_actual_failure_stays_in_send_history_without_inventing_business_debt(self):
  import work_observer as w
  j={'client':'secretary','employee':'secretary','request_id':'secretary-fixture-dca54413-20260101','peer':'owner','action':'send_image','state':'failed','created':100,'updated':110,'serverId':None,'noSend':True,'reason':'CHAT_POPOUT_NOT_OPENED','recent':True,'nativeReceiptVerified':False}
  with tempfile.TemporaryDirectory() as d,patch.object(w,'SEC',Path(d)),patch('send_tool_observer.read_tools',return_value={'jobs':[j],'gaps':[],'targetedReads':1,'status':{}}):
   x=w.enrich_sending({'items':[],'note':''},{},'2026-11-01T08:00:00Z')
   self.assertEqual(len(x['items']),1);self.assertEqual(x['items'][0]['state'],'unknown');self.assertEqual(x['items'][0]['relatedItemIds'],[])

class NativeMediaTests(unittest.TestCase):
 def test_real_file_result_schema_requires_all_three_native_matches(self):
  j={'client':'secretary','request_id':'file-01','peer':'owner','action':'send_file','state':'succeeded','payload':{'asset':'a'*64},'result':{'state':'accepted','peer':'owner','serverId':'123','localId':532,'nativeFilenameMatch':True,'nativeSizeMatch':True,'nativeMD5Match':True}}
  self.assertTrue(st.project(j)['nativeReceiptVerified']);j['result']['nativeMD5Match']=False;self.assertFalse(st.project(j)['nativeReceiptVerified'])
 def test_real_image_schema_keeps_frozen_asset_identity_and_native_commit(self):
  j={'client':'secretary','request_id':'image-01','peer':'owner','action':'send_image','state':'succeeded','payload':{'asset':'a'*64},'result':{'state':'accepted','peer':'owner','serverId':'124','localId':533,'evidence':'sender-native-committed','payloadSha256':'b'*64}}
  p=st.project(j);self.assertTrue(p['nativeReceiptVerified']);self.assertEqual(p['contentHash'],'a'*64)
  j['result']['peer']='someone-else';self.assertFalse(st.project(j)['nativeReceiptVerified'])

class AcceptedMonotonicityTests(unittest.TestCase):
 def test_later_failed_duplicate_same_content_does_not_reopen_delivered_component(self):
  t=DeliveryTests();_,_,j=t.base();good={**j,'request_id':j['request_id']+'-r1','state':'succeeded','created':140,'updated':150,'nativeReceiptVerified':True};later={**j,'request_id':j['request_id']+'-r2','created':160,'updated':170}
  self.assertEqual(t.runhealth([j,good,later])['incidents'][0]['status'],'resolved')
 def test_accepted_old_version_does_not_close_explicit_new_version_failure(self):
  t=DeliveryTests();_,_,j=t.base();good={**j,'state':'succeeded','nativeReceiptVerified':True};new={**j,'request_id':'secretary-fixture-3e5ee41b-20260101','contentHash':'b'*64,'created':150,'updated':160,'supersedes':[j['request_id']]}
  h=t.runhealth([good,new]);self.assertEqual(len(h['incidents']),2);self.assertEqual(next(i for i in h['incidents'] if j['request_id'] in i['requestIds'])['status'],'resolved');self.assertEqual(next(i for i in h['incidents'] if new['request_id'] in i['requestIds'])['status'],'blocked')

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
