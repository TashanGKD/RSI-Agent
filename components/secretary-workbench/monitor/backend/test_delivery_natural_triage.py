# -*- coding: utf-8 -*-
import unittest,tempfile
from pathlib import Path
from delivery_health import note_seed,build_health,attach_health
OWNER='00000000-0000-4000-8000-4344f0fd9daa'
OLD='secretary-fixture-e8157b0b-20260101'
DRAFT='secretary-fixture-5b7b797a-20260101'
FINAL='secretary-fixture-6dac3751-20260101'
class NaturalTriageTests(unittest.TestCase):
 def role(self):return {'id':'secretary','threadId':OWNER,'root':Path('/tmp')}
 def item(self,state='已办好'):return {'id':'biz','employee':'secretary','title':'独立交付','state':state,'commitment':'accepted','sourceId':'note'}
 def job(self,rid,state='failed',fingerprint='a'*64,created=100):return {'employee':'secretary','client':'secretary','request_id':rid,'peer':'peer','action':'send_text','state':state,'contentHash':fingerprint,'nativeReceiptVerified':state=='succeeded','created':created,'updated':created+1,'noSend':state=='failed','reason':'DRAFT_PROTECTED','sourceId':'proof-'+rid,'supersedes':[]}
 def health(self,item,seed,jobs):return build_health(items=[item],seeds=[seed],jobs=jobs,gaps=[],observed_at=500)
 def test_only_explicit_recorded_short_retry_is_queried(self):
  head='- **事情**：回应招呼\n- **现在怎么样**：已办好\n- **过程笔记**：原单'+OLD+'定位失败/noSend；恢复后只用-r1成功，serverId123。'
  s=note_seed(self.role(),'note',head,'biz','note');self.assertEqual(s['requestIds'],[OLD,OLD+'-r1'])
  h=self.health(self.item(),s,[self.job(OLD),self.job(OLD+'-r1','succeeded',created=150)])
  self.assertEqual(len(h['incidents']),1);self.assertEqual(h['incidents'][0]['status'],'resolved')
 def test_retry_is_not_guessed_without_positive_note_or_with_ambiguous_bases(self):
  for head in ['原单'+OLD+'失败/noSend，之后再判断。','原单'+OLD+'失败；另单secretary-fixture-f5fb933e-20260101也失败；只用-r1成功。','原单'+OLD+'失败，未来可以试-r1。']:
   s=note_seed(self.role(),'note',head,'biz','note');self.assertNotIn(OLD+'-r1',s['requestIds'])
 def test_retired_old_draft_and_new_delivered_result_are_two_components(self):
  head='- **事情**：归并六项\n- **现在怎么样**：已办好\n- **下一步**：完成说明已交原群，旧未发理解稿不补。\n- **过程笔记**：原SDK ID '+DRAFT+'一次failed/noSend。首次拟理解发件已被真实归并结果超越；新独立结果ID '+FINAL+'已实发。'
  s=note_seed(self.role(),'note',head,'biz','note');h=self.health(self.item(),s,[self.job(DRAFT),self.job(FINAL,'succeeded','b'*64,150)])
  self.assertEqual(len(h['incidents']),2);old=next(i for i in h['incidents'] if DRAFT in i['requestIds']);new=next(i for i in h['incidents'] if FINAL in i['requestIds'])
  self.assertEqual(old['status'],'not_required');self.assertFalse(old['nativeReceiptVerified']);self.assertEqual(old['reasonCode'],'draft_retired_by_current_business');self.assertEqual(new['status'],'resolved')
 def test_later_success_alone_or_optional_idea_does_not_retire_old_draft(self):
  for nxt in ['原稿可能以后不补，尚未决定。','新结果已交，但旧理解稿是否还需答待核。']:
   head='- **事情**：同项目\n- **现在怎么样**：已办好\n- **下一步**：'+nxt+'\n- **过程笔记**：原单'+DRAFT+' failed/noSend，首次拟理解发件已被真实归并结果超越；新独立结果ID '+FINAL+'已实发。'
   s=note_seed(self.role(),'note',head,'biz','note');h=self.health(self.item(),s,[self.job(DRAFT),self.job(FINAL,'succeeded','b'*64,150)])
   self.assertNotEqual(next(i for i in h['incidents'] if DRAFT in i['requestIds'])['status'],'not_required')
 def test_deferred_known_unsent_is_pending_not_unknown_or_cancelled(self):
  head='- **事情**：书稿核问\n- **现在怎么样**：先放放\n- **下一步**：原澄清未发；条件恢复且仍有价值时再判断。\n- **过程笔记**：原单'+OLD+' failed/noSend。'
  s=note_seed(self.role(),'note',head,'biz','note');h=self.health(self.item('先放放'),s,[self.job(OLD)])
  i=h['incidents'][0];self.assertEqual(i['status'],'pending');self.assertEqual(i['reasonCode'],'business_deferred_unsent');self.assertFalse(i['nativeReceiptVerified']);self.assertIsNone(i['recoveryOwnerThreadId'])
  sending={'items':[]};attach_health(sending,h,[self.job(OLD)],{},'2026-11-01T09:00:00Z',lambda *a:'source',{})
  self.assertIn('暂缓',sending['items'][0]['label']);self.assertEqual(sending['items'][0]['state'],'pending')
 def test_deferred_with_missing_receipt_remains_unknown(self):
  head='- **事情**：暂缓核问\n- **现在怎么样**：先放放\n- **过程笔记**：原单'+OLD+'结果未知。'
  s=note_seed(self.role(),'note',head,'biz','note');j=self.job(OLD,'unknown');j['noSend']=None
  self.assertEqual(self.health(self.item('先放放'),s,[j])['incidents'][0]['status'],'unknown')
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
