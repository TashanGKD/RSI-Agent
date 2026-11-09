"""Rejection cases precede the validator: traversal, symlink escape, duplicate keys."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts/verify_audit.py'

class Audit(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)/'packet';self.root.mkdir()
  self.body='@所有人：年度考核\n名单：甲同学\n10月23日前邮件反馈题目\n秘书11月30日前汇总\n好的\n好的\n'
  (self.root/'notice.txt').write_text(self.body);sha=hashlib.sha256(self.body.encode()).hexdigest()
  self.p={
   'scope':{'mode':'as_of','timezone':'America/New_York','as_of':'2026-10-20T12:00:00-04:00','source_start':'2026-08-01T00:00:00-04:00','source_end_exclusive':'2026-10-21T00:00:00-04:00','required_channels':['wechat'],'user_excluded_source_ids':[]},
   'channels':[{'id':'wechat','enumeration':'complete','pagination_exhausted':True,'identity_verified':True,'range_verified':True,'enumeration_receipt':'native query exhausted at requested bounds','inventory_ids':['wechat:acct:group:part1']}],
   'sources':[{'id':'wechat:acct:group:part1','channel':'wechat','kind':'chat_text','status':'read','units_total':6,'read_ranges':[[1,6]],'unit_basis':'visible business-text units','semantic_read':True,'scope_verified':True,'date_basis':'native_timestamp','body_sha256':sha}],
   'evidence':[{'id':'wechat:acct:m1:3','source_id':'wechat:acct:group:part1','kind':'original_text','actor':'通知人','occurred_at':'2026-10-16','normalized_at':'2026-10-16T08:00:00Z','date_basis':'native_timestamp','locator':'m1 line3','source_file':'notice.txt','source_sha256':sha,'line_start':3,'line_end':3,'quote':'10月23日前邮件反馈题目','quote_kind':'verbatim'},
               {'id':'wechat:acct:m1:2','source_id':'wechat:acct:group:part1','kind':'original_text','actor':'通知人','occurred_at':'2026-10-16','date_basis':'native_timestamp','locator':'m1 line2','source_file':'notice.txt','source_sha256':sha,'line_start':2,'line_end':2,'quote':'名单：甲同学','quote_kind':'verbatim'}],
   'followups':[],
   'actions':[{'id':'a:topic','counterparty':'通知人','action':'邮件反馈题目','proposed_at':'2026-10-16','kind':'notice','attribution':'self','applicability':'confirmed','applicability_evidence_ids':['wechat:acct:m1:2'],'deadline_text':'10月23日前','deadline_role':'personal','deadline_evidence_ids':['wechat:acct:m1:3'],'status':'unknown','evidence_ids':['wechat:acct:m1:3','wechat:acct:m1:2']}]
  }
  self.inventory={'channel':'wechat','inventory_ids':['wechat:acct:group:part1'],'pagination_exhausted':True,'identity_verified':True,'range_verified':True,'capture_basis':'fixed directory from native enumeration, not selected reading queue'}
  self.freeze_inventory()
  spec=importlib.util.spec_from_file_location('verify_audit',SCRIPT)
  self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
 def freeze_inventory(self):
  raw=(json.dumps(self.inventory,ensure_ascii=False)+'\n').encode();(self.root/'inventory.json').write_bytes(raw)
  self.p['channels'][0]['enumeration_receipt']={'source_file':'inventory.json','source_sha256':hashlib.sha256(raw).hexdigest()}
 def result(self):return self.m.validate_packet(self.p,self.root)
 def codes(self):
  r=self.result();return {x['code'] for x in r['errors']+r['gaps']}
 def test_happy_scope_unknown_progress_is_not_coverage_gap(self):self.assertTrue(self.result()['coverage_complete'])
 def test_path_traversal_rejected(self):
  self.p['evidence'][0]['source_file']='../outside.txt';self.assertIn('source_path_rejected',self.codes())
 def test_symlink_escape_rejected(self):
  outside=self.root.parent/'outside.txt';outside.write_text(self.body);(self.root/'link.txt').symlink_to(outside)
  self.p['evidence'][0]['source_file']='link.txt';self.assertIn('source_path_rejected',self.codes())
 def test_duplicate_json_keys_rejected(self):
  with self.assertRaises(ValueError):self.m.load_json_bytes(b'{"scope":{},"scope":{}}')
 def test_oversize_json_rejected_before_parse(self):
  with self.assertRaises(ValueError):self.m.load_json_bytes(b' '*129,max_bytes=128)
 def test_source_changed_blocks_quote(self):
  (self.root/'notice.txt').write_text('changed');self.assertIn('source_hash_mismatch',self.codes())
 def test_repeated_quote_cannot_use_wrong_line(self):
  self.p['evidence'][0].update(quote='好的',line_start=3,line_end=3);self.assertIn('quote_line_mismatch',self.codes())
 def test_coverage_hole(self):
  self.p['sources'][0]['read_ranges']=[[1,2],[4,6]];self.assertIn('unread_units',self.codes())
 def test_overlap_does_not_compensate_for_missing_units(self):
  self.p['sources'][0]['read_ranges']=[[1,3],[3,5]];self.assertIn('overlapping_read_ranges',self.codes())
 def test_no_self_messages_not_exclusion(self):
  self.p['sources'][0].update(status='excluded',exclusion_reason='no_self_messages');self.assertIn('invalid_exclusion',self.codes())
 def test_required_channel_missing(self):
  self.p['scope']['required_channels'].append('email');self.assertIn('required_channel_missing',self.codes())
 def test_incomplete_pagination(self):
  self.p['channels'][0]['pagination_exhausted']=False;self.assertIn('channel_not_complete',self.codes())
 def test_inventory_item_dropped(self):
  self.p['channels'][0]['inventory_ids'].append('wechat:acct:quiet-group');self.assertIn('inventory_source_missing',self.codes())
 def test_selected_queue_cannot_shrink_original_directory(self):
  self.inventory['inventory_ids'].append('wechat:acct:quiet-group');self.freeze_inventory()
  self.assertIn('inventory_differs_from_receipt',self.codes())
 def test_inventory_receipt_hash_must_match(self):
  (self.root/'inventory.json').write_text('{}');self.assertIn('inventory_receipt_hash_mismatch',self.codes())
 def test_receipt_pagination_cannot_be_overridden_by_summary(self):
  self.inventory['pagination_exhausted']=False;self.freeze_inventory();self.assertIn('inventory_receipt_not_complete',self.codes())
 def test_pending_notice_attachment(self):
  self.p['followups']=[{'id':'mail','parent_source_id':self.p['sources'][0]['id'],'kind':'email','required':True,'status':'pending','resolved_source_ids':[]}];self.assertIn('followup_unresolved',self.codes())
 def test_fake_resolved_followup(self):
  self.p['followups']=[{'id':'mail','parent_source_id':self.p['sources'][0]['id'],'kind':'email','required':True,'status':'resolved','resolved_source_ids':[]}];self.assertIn('followup_resolution_missing',self.codes())
 def test_secretary_deadline_not_personal(self):
  self.p['actions'][0]['deadline_role']='secretary';self.assertIn('nonpersonal_deadline',self.codes())
 def test_everyone_without_applicability_cannot_be_open(self):
  self.p['actions'][0].update(applicability='possible',status='open');self.assertIn('unconfirmed_personal_obligation',self.codes())
 def test_approval_not_payment(self):
  self.p['actions'][0].update(status='done',required_stage='paid',completion_stage='approved',completion_scope='this payment',completion_evidence_ids=['wechat:acct:m1:3']);self.assertIn('completion_stage_mismatch',self.codes())
 def test_evidence_id_collision(self):
  self.p['evidence'].append(copy.deepcopy(self.p['evidence'][0]));self.assertIn('duplicate_evidence_id',self.codes())
 def test_future_evidence_not_historical(self):
  self.p['evidence'][0]['normalized_at']='2026-10-21T08:00:00Z';self.assertIn('evidence_after_as_of',self.codes())
 def test_filename_does_not_confirm_scope(self):
  self.p['sources'][0].update(scope_verified=False,date_basis='unknown');self.assertIn('source_scope_unconfirmed',self.codes())
 def test_dst_window_uses_local_offsets(self):
  self.p['scope'].update(source_start='2026-11-01T00:00:00-04:00',source_end_exclusive='2026-11-02T00:00:00-05:00',as_of='2026-11-02T12:00:00-05:00');self.assertTrue(self.result()['coverage_complete'])
  self.p['scope']['source_end_exclusive']='2026-11-02T00:00:00-04:00';self.assertIn('scope_timezone_offset_mismatch',self.codes())
 def test_no_argument_cli_only_shows_usage(self):
  before={p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()}
  r=subprocess.run([sys.executable,str(SCRIPT)],cwd=self.root,capture_output=True,text=True)
  self.assertEqual(r.returncode,0);self.assertIn('usage:',r.stdout.lower());self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir() if p.is_file()})
 @unittest.skipUnless(hasattr(os,'mkfifo'),'requires local FIFO support')
 def test_fifo_packet_is_rejected_without_waiting_for_writer(self):
  p=self.root/'pipe.json';os.mkfifo(p)
  r=subprocess.run([sys.executable,str(SCRIPT),str(p)],capture_output=True,text=True,timeout=1)
  self.assertEqual(r.returncode,2)

if __name__=='__main__':unittest.main()
