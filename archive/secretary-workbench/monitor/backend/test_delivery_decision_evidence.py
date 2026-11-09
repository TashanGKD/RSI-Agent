# -*- coding: utf-8 -*-
import json,tempfile,unittest,hashlib
from pathlib import Path
from unittest.mock import patch
from delivery_health import build_health
OWNER='00000000-0000-4000-8000-4344f0fd9daa';RID='secretary-fixture-478e9849-20260101';SOURCE='8000049102703223852'
class DecisionEvidenceTests(unittest.TestCase):
 def fixture(self,root):
  work=root/'work';work.mkdir();artifact=work/'OWNER-DECISION-SUPERSEDED.json';artifact.write_text(json.dumps({'originalQuestionId':RID,'originalQuestionRemains':'failed/noSend','r1NotAdmitted':True,'reason':'Owner answered in original group'+SOURCE,'newDecisionQuestionSends':0}))
  role={'id':'secretary','threadId':OWNER,'root':root};item={'id':'biz','employee':'secretary','title':'继续原范围转发','state':'待推进','commitment':'accepted','sourceId':'note','recordUpdatedAt':'2026-11-01T20:00:00+08:00'};seed={'businessId':'biz','employee':'secretary','ownerThreadId':OWNER,'requestIds':[],'sourceId':'note','retiredRequestIds':[]};old={'client':'secretary','employee':'secretary','request_id':RID,'peer':'owner','action':'send_text','state':'failed','created':100,'updated':101,'noSend':True,'reason':'UNSUPPORTED_LAYOUT','nativeReceiptVerified':False,'contentHash':'a'*64,'sourceId':'op'}
  head='本人原群回答，来源'+SOURCE+'。当前任务继续推进。';return artifact,role,item,seed,old,head
 def test_exact_structured_answer_retires_only_old_question_and_survives_note_rewrite(self):
  from delivery_decision_evidence import register_reference,apply_references
  with tempfile.TemporaryDirectory() as d:
   p,role,item,seed,old,head=self.fixture(Path(d).resolve());ref=register_reference(role,item['id'],p,SOURCE,old,head)
   sources={'note':{'text':'current business'},'op':{'text':'old failure'}};seeds,jobs,g=apply_references(role,[item],[seed],[],sources,[ref],'2026-11-01T20:01:00+08:00')
   # Different-peer success is irrelevant to this old DM question.
   ack={**old,'request_id':'secretary-fixture-bc096987-20260101-ack','peer':'group@chatroom','state':'succeeded','nativeReceiptVerified':True,'contentHash':'b'*64}
   h=build_health(items=[item],seeds=seeds,jobs=jobs+[ack],gaps=g,observed_at=2000000000);i=next(i for i in h['incidents'] if RID in i['requestIds']);self.assertEqual(i['status'],'not_required');self.assertFalse(i['nativeReceiptVerified']);self.assertEqual(i['reasonCode'],'question_answered_by_source');self.assertEqual(item['state'],'待推进')
   seeds,jobs,g=apply_references(role,[item],[{**seed,'requestIds':['secretary-fixture-29dadfa2-20260101']}],[],sources,[ref],'2026-11-01T21:01:00+08:00');self.assertIn(RID,seeds[0]['retiredRequestIds'])
 def test_unrelated_decision_wrong_source_path_scope_or_nonfinal_does_not_retire(self):
  from delivery_decision_evidence import register_reference
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p,r,i,s,j,head=self.fixture(root)
   for key,val in [('originalQuestionId','secretary-fixture-fbb5fb53-20260101'),('r1NotAdmitted',False),('newDecisionQuestionSends',1)]:
    original=json.loads(p.read_text());changed=dict(original);changed[key]=val;p.write_text(json.dumps(changed))
    with self.assertRaises(ValueError):register_reference(r,i['id'],p,SOURCE,j,head)
    p.write_text(json.dumps(original))
   with self.assertRaises(ValueError):register_reference(r,i['id'],p,'8000037419276118460',j,head)
   link=root/'work/LINK.json';link.symlink_to(p)
   with self.assertRaises(ValueError):register_reference(r,i['id'],link,SOURCE,j,head)
   with self.assertRaises(ValueError):register_reference(r,i['id'],Path('/etc/passwd'),SOURCE,j,head)
 def test_missing_file_is_observation_gap_but_explicit_changed_evidence_is_conflict(self):
  from delivery_decision_evidence import register_reference,apply_references
  with tempfile.TemporaryDirectory() as d:
   p,r,i,s,j,head=self.fixture(Path(d).resolve());ref=register_reference(r,i['id'],p,SOURCE,j,head);body=p.read_bytes();p.unlink();src={'note':{'text':'note'},'op':{'text':'op'}}
   seeds,jobs,gaps=apply_references(r,[i],[s],[],src,[ref],'2026-11-01T21:00:00+08:00');h=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=gaps,observed_at=2000000000);self.assertEqual(h['incidents'][0]['status'],'not_required');self.assertTrue(gaps)
   p.write_bytes(body);value=json.loads(body);value['originalQuestionId']='secretary-fixture-fbb5fb53-20260101';p.write_text(json.dumps(value));seeds,jobs,g=apply_references(r,[i],[s],[],src,[ref],'2026-11-01T21:01:00+08:00');h=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=g,observed_at=2000000000);self.assertEqual(h['incidents'][0]['status'],'unknown');self.assertEqual(h['incidents'][0]['reasonCode'],'retirement_evidence_conflict')
 def test_other_business_and_new_failed_component_do_not_inherit_retirement(self):
  from delivery_decision_evidence import register_reference,apply_references
  with tempfile.TemporaryDirectory() as d:
   p,r,i,s,j,head=self.fixture(Path(d).resolve());ref=register_reference(r,i['id'],p,SOURCE,j,head);sources={'note':{'text':'note'},'op':{'text':'op'}}
   other={**i,'id':'other'};seeds,jobs,g=apply_references(r,[other],[{**s,'businessId':'other'}],[],sources,[ref],'2026-11-01T21:00:00+08:00');self.assertFalse(jobs);self.assertFalse(seeds[0]['retiredRequestIds'])
   new={**j,'request_id':'secretary-fixture-29dadfa2-20260101','contentHash':'d'*64};seeds,jobs,g=apply_references(r,[i],[{**s,'requestIds':[new['request_id']]}],[new],sources,[ref],'2026-11-01T21:00:00+08:00');h=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=g,observed_at=2000000000);self.assertEqual(next(x for x in h['incidents'] if new['request_id'] in x['requestIds'])['status'],'blocked')
if __name__=='__main__':unittest.main()

class DecisionEvidenceBoundaryTests(unittest.TestCase):
 def fixture(self,root):return DecisionEvidenceTests().fixture(root)
 def test_deferred_lookalike_json_is_not_a_superseded_decision_type(self):
  from delivery_decision_evidence import register_reference
  with tempfile.TemporaryDirectory() as d:
   p,r,i,s,j,head=self.fixture(Path(d).resolve());other=p.parent/'TEMPORARILY-DEFERRED.json';other.write_bytes(p.read_bytes())
   with self.assertRaises(ValueError):register_reference(r,i['id'],other,SOURCE,j,head)
 def test_changed_question_identity_is_conflict_not_inherited_retirement(self):
  from delivery_decision_evidence import register_reference,apply_references
  with tempfile.TemporaryDirectory() as d:
   p,r,i,s,j,head=self.fixture(Path(d).resolve());ref=register_reference(r,i['id'],p,SOURCE,j,head);changed={**j,'peer':'another-person'};src={'note':{'text':'note'},'op':{'text':'op'}}
   seeds,jobs,g=apply_references(r,[i],[s],[changed],src,[ref],'2026-11-01T21:00:00Z');h=build_health(items=[i],seeds=seeds,jobs=jobs,gaps=g,observed_at=2000000000);self.assertEqual(h['incidents'][0]['status'],'unknown');self.assertEqual(h['incidents'][0]['reasonCode'],'retirement_evidence_conflict')

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
