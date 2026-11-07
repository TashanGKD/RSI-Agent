# -*- coding:utf-8 -*-
import copy,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import work_observer as w
from delivery_health import build_health
OWNER='00000000-0000-4000-8000-4344f0fd9daa';MONITOR='00000000-0000-4000-8000-e855c5107607';HISTORY='00000000-0000-4000-8000-1b7a62c8f9fa';TURN='00000000-0000-4000-8000-c1fde7392e69'
OLD='secretary-fixture-c815b521-20260101';NEW='secretary-fixture-639661da-20260101'
class DailySupplementTests(unittest.TestCase):
 def fixture(self,root):
  work=root/'work';work.mkdir();role={'id':'secretary','threadId':OWNER,'root':root}
  old={'client':'secretary','employee':'secretary','request_id':OLD,'peer':'22862004294@chatroom','action':'send_text','state':'cancelled','created':100,'updated':101,'noSend':True,'nativeReceiptVerified':False,'contentHash':'a'*64}
  frozen={'job':{'client':'secretary','request_id':NEW,'peer':old['peer'],'action':'send_text','payload':{'text':'已审核的成熟邀请稿'}}}
  def save(n,j):p=work/n;p.write_text(json.dumps(j,ensure_ascii=False));return str(p)
  files={'cancelled':save('OLD-ACK-CANCELLED-BY-READY-DRAFT.json',{'client':old['client'],'request_id':OLD,'peer':old['peer'],'action':old['action'],'state':'cancelled','result':{'reason':'caller_cancelled_before_preparation','noSend':True}}),'acceptance':save('MAIN-DRAFT-ACCEPTANCE.json',{'readComplete':True,'oldAckReplacedIfQueued':True,'approvedForTalentInternalReviewOnly':True}),'frozen':save('MATURE-DRAFT-FROZEN.json',[frozen])}
  item={'id':'business','employee':'secretary','title':'期刊合作邀请','state':'等反馈','commitment':'accepted','sourceId':'note'};seed={'businessId':'business','employee':'secretary','ownerThreadId':OWNER,'requestIds':[OLD],'sourceId':'note','retiredRequestIds':[]};return role,files,old,item,seed
 def test_mapping_uses_exact_native_turn_not_directory_similarity_and_preserves_primary(self):
  from monitor_history_mapping import register_mapping,resolve_mapping
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('create table thread_turns(thread_id text,turn_id text,started_at int)');c.execute('insert into thread_turns values(?,?,?)',(HISTORY,TURN,100))
  with patch.object(w,'ro',return_value=c):
   ref=register_mapping(MONITOR,MONITOR,[TURN],'native read_thread metadata');h,g=resolve_mapping(MONITOR,MONITOR,ref)
   self.assertEqual(h,HISTORY);self.assertIsNone(g);self.assertEqual(ref['threadId'],MONITOR);self.assertIn(MONITOR,ref['previousHistoryThreadIds'])
   h,g=resolve_mapping('00000000-0000-4000-8000-5f5c684d999c',MONITOR,ref);self.assertEqual(h,MONITOR);self.assertIsNotNone(g)
  c.close()
 def test_mapping_ambiguous_turn_or_damaged_scope_not_adopted(self):
  from monitor_history_mapping import register_mapping,resolve_mapping
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('create table thread_turns(thread_id text,turn_id text,started_at int)')
  with patch.object(w,'ro',return_value=c):
   with self.assertRaises(ValueError):register_mapping(MONITOR,MONITOR,[TURN],'native metadata')
   for h in [HISTORY,MONITOR]:c.execute('insert into thread_turns values(?,?,?)',(h,TURN,100))
   with self.assertRaises(ValueError):register_mapping(MONITOR,MONITOR,[TURN],'native metadata')
  c.close()
 def test_cancelled_ack_retired_only_with_exact_normal_readiness_artifacts(self):
  from delivery_decision_evidence import register_ack_reference,apply_references,index_references
  with tempfile.TemporaryDirectory() as d:
   role,f,q,i,s=self.fixture(Path(d).resolve());ref=register_ack_reference(role,i['id'],f,q);out={};seeds=index_references([s],[ref]);self.assertIn(NEW,seeds[0]['requestIds'])
   seeds,rows,g=apply_references(role,[i],seeds,[q],out,[ref],'now');h=build_health(items=[i],seeds=seeds,jobs=rows,gaps=g,observed_at=2000000000)
   old=next(x for x in h['incidents'] if OLD in x['requestIds']);self.assertEqual(old['status'],'not_required');self.assertEqual(old['reasonCode'],'ack_cancelled_by_ready_draft');self.assertFalse(old['nativeReceiptVerified']);self.assertEqual(i['state'],'等反馈')
   # The ready draft is a distinct delivery: cancellation is not its receipt.
   self.assertFalse(any(x['status']=='resolved' for x in h['incidents']))
 def test_do_not_retire_arbitrary_cancelled_or_wrong_frozen_peer_unreviewed_and_symlink(self):
  from delivery_decision_evidence import register_ack_reference
  with tempfile.TemporaryDirectory() as d:
   role,f,q,i,s=self.fixture(Path(d).resolve())
   for key,value in [('state','succeeded'),('noSend',False),('request_id','secretary-fixture-fbb5fb53-20260101')]:
    with self.assertRaises(ValueError):register_ack_reference(role,i['id'],f,dict(q,**{key:value}))
   p=Path(f['frozen']);original=p.read_text();j=json.loads(original);j[0]['job']['peer']='different@chatroom';p.write_text(json.dumps(j))
   with self.assertRaises(ValueError):register_ack_reference(role,i['id'],f,q)
   p.write_text(original);p=Path(f['acceptance']);j=json.loads(p.read_text());j['oldAckReplacedIfQueued']=False;p.write_text(json.dumps(j))
   with self.assertRaises(ValueError):register_ack_reference(role,i['id'],f,q)
   link=Path(d).resolve()/'work/link.json';link.symlink_to(p)
   with self.assertRaises(ValueError):register_ack_reference(role,i['id'],dict(f,acceptance=str(link)),q)
 def test_rewritten_note_and_missing_source_do_not_revive_cancelled_ack_conflict_stays_unknown(self):
  from delivery_decision_evidence import register_ack_reference,apply_references
  with tempfile.TemporaryDirectory() as d:
   role,f,q,i,s=self.fixture(Path(d).resolve());ref=register_ack_reference(role,i['id'],f,q);s['requestIds']=[];p=Path(f['cancelled']);raw=p.read_text();p.unlink()
   seeds,rows,g=apply_references(role,[i],[s],[],{},[ref],'now');h=build_health(items=[i],seeds=seeds,jobs=rows,gaps=g,observed_at=2000000000);self.assertEqual(h['incidents'][0]['status'],'not_required');self.assertTrue(g)
   j=json.loads(raw);j['request_id']='secretary-fixture-94b30949-20260101';p.write_text(json.dumps(j));seeds,rows,g=apply_references(role,[i],[s],[q],{},[ref],'now');h=build_health(items=[i],seeds=seeds,jobs=rows,gaps=g,observed_at=2000000000);self.assertEqual(h['incidents'][0]['status'],'unknown')
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
