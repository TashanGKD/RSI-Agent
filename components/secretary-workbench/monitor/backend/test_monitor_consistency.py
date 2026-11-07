# -*- coding:utf-8 -*-
import copy,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import work_observer as w
from delivery_health import build_health,receipt_ids
from send_tool_observer import project,CLIENTS
THREAD='00000000-0000-4000-8000-4e07f8267a19';HISTORY='00000000-0000-4000-8000-1b7a62c8f9fa';TURN='00000000-0000-4000-8000-4b75f5b72f75'
class ConsistencyTests(unittest.TestCase):
 def test_registered_safe_entry_updates_without_breaking_directory_other_bad_binding_is_isolated(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'PLAN.md').write_text('old');(root/'AGENTS.md').write_text('current');reg=root/'registry.json';private=root/'private';private.mkdir()
   second='00000000-0000-4000-8000-4344f0fd9daa';bindings=[{'id':'a','threadId':THREAD,'historyThreadId':THREAD,'peer':'1@chatroom','workEntry':str(root/'AGENTS.md'),'workbookDir':str(root/'workbook')},{'id':'bad','threadId':second,'historyThreadId':second,'peer':'2@chatroom','workEntry':'/etc/passwd'}];reg.write_text(json.dumps({'ownerThread':THREAD,'bindings':bindings}))
   with patch.multiple(w,METHOD=root,REGISTRY=reg,PRIVATE=private,KNOWN={THREAD:('system','system',root,root/'PLAN.md'),second:('secretary','secretary',root,root/'PLAN.md')},SUPPORT={}),patch('installation_config.identity',return_value=THREAD):
    roles,discovery=w.directory();self.assertEqual(len(roles),2);self.assertEqual(roles[0]['entry'],root/'AGENTS.md');self.assertTrue(roles[1].get('adapterGaps'));self.assertEqual(roles[1]['entry'],root/'PLAN.md')
 def test_same_native_identity_reconciles_registered_role_history_and_preserves_previous(self):
  from monitor_history_mapping import reconcile_native
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.execute('create table thread_turns(thread_id text,turn_id text,started_at int)');c.execute('insert into thread_turns values(?,?,?)',(HISTORY,TURN,100))
  role={'threadId':THREAD,'historyThreadId':THREAD};meta={'threadId':THREAD,'status':'active','turns':[{'id':TURN,'startedAt':100}]}
  with patch.object(w,'ro',return_value=c):
   history,ref,gap=reconcile_native(role,meta,None);self.assertEqual(history,HISTORY);self.assertIn(THREAD,ref['previousHistoryThreadIds']);self.assertIsNone(gap)
   history,_,gap=reconcile_native(role,dict(meta,threadId='00000000-0000-4000-8000-4344f0fd9daa'),ref);self.assertIsNotNone(gap);self.assertEqual(history,HISTORY)
  c.close()
 def test_missing_note_and_whole_folder_keep_prior_item_with_stale_evidence(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();folder=root/'workbook';folder.mkdir();p=folder/'task.md';p.write_text('- **事情**：原待交付\n- **现在怎么样**：等反馈\n- **下一步**：等准确回复')
   role={'id':'forum','threadId':THREAD,'root':root};items,cache,errs=w.notebook_items(role,{}, {},'2026-11-02T01:00:00Z');original=items[0]['id'];p.unlink();folder.rmdir()
   items,cache2,errs=w.notebook_items(role,{},cache,'2026-11-02T02:00:00Z');self.assertEqual(items[0]['id'],original);self.assertTrue(items[0]['sourceStale']);self.assertEqual(items[0]['state'],'等反馈');self.assertTrue(errs);self.assertIn(str(p),cache2)
 def test_wrapper_receipts_and_explicit_normal_get_file_index_only_real_jobs(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();p=root/'normal-get.json';job={'client':'forum_employee','request_id':'forum-fixture-65cb27cf-20260101','peer':'1@chatroom','action':'send_text'};p.write_text(json.dumps({'items':[{'job':job},{'request_id':'forum-fixture-13d31d22-20260101','phase':'queued'}]}))
   self.assertEqual(receipt_ids(str(p),'forum_employee',[root]),[job['request_id']])
 def test_partial_native_acceptance_never_becomes_verified_delivery_for_any_client(self):
  body='frozen';sha=hashlib.sha256(body.encode()).hexdigest()
  for client in CLIENTS:
   job={'client':client,'request_id':'valid','peer':('wxid_fixture_owner' if client in ['employee_method','aup_support','research_secretary'] else 'target'),'action':'send_text','payload':{'text':body},'state':'succeeded','result':{'state':'accepted','peer':('wxid_fixture_owner' if client in ['employee_method','aup_support','research_secretary'] else 'target'),'serverId':'123','nativeStatus':2,'uniqueCandidateCount':1,'nativeCreateTime':100,'textComparison':{'expectedSHA256':sha,'actualSHA256':sha}}}
   if client=='aup_support':job.update(id='a'*32,created=100,updated=110)
   if client=='research_secretary':job.update(id='a'*32,created=1793863800,updated=1793863810)
   self.assertFalse(project(job)['nativeReceiptVerified'])
   job['result'].update(senderId='wxid_fixture_bbb47eb57f',evidence='native-sender-status-and-operation-semantics');self.assertTrue(project(job)['nativeReceiptVerified'])
 def test_statement_no_longer_waiting_is_not_cross_content_replacement_proof(self):
  old='secretary-fixture-c3b00d73-20260101';new='secretary-fixture-608b7920-20260101';item={'id':'b','employee':'secretary','title':'results','state':'等反馈','commitment':'accepted'};seed={'businessId':'b','employee':'secretary','ownerThreadId':THREAD,'requestIds':[old,new],'sourceId':'note','noLongerWaitingForSend':True}
  a={'client':'secretary','employee':'secretary','request_id':old,'peer':'target','action':'send_text','created':100,'updated':101,'state':'failed','noSend':True,'contentHash':'a'*64,'nativeReceiptVerified':False};b={**a,'request_id':new,'created':200,'updated':201,'state':'succeeded','nativeReceiptVerified':True,'contentHash':'b'*64,'noSend':False}
  h=build_health(items=[item],seeds=[seed],jobs=[a,b],gaps=[],observed_at=300);self.assertEqual(len(h['incidents']),2);self.assertNotEqual(next(i for i in h['incidents'] if old in i['requestIds'])['status'],'resolved')
 def test_proven_failed_request_index_survives_note_edit_without_claiming_success(self):
  from delivery_receipt_cache import prepare_receipts
  import work_observer
  rid='secretary-fixture-62119cff-20260101';src={};op=work_observer.source(src,'原微信工具:secretary/'+rid,json.dumps({'client':'secretary','request_id':rid,'peer':'target','action':'send_text','state':'failed','created':100,'updated':101,'noSend':True,'contentHash':'a'*64,'nativeReceiptVerified':False}),'2026-11-02T00:00:00Z','failed')
  comp={'id':'delivery-abc','businessId':'b','employee':'secretary','ownerThreadId':THREAD,'client':'secretary','status':'blocked','requestIds':[rid],'evidenceRefs':[op]};work_observer.source(src,'交付组件:delivery-abc',json.dumps(comp),'2026-11-02T00:00:00Z','component')
  seed={'businessId':'b','employee':'secretary','ownerThreadId':THREAD,'requestIds':[]};ss,entries,g=prepare_receipts([{'id':'b'}],[seed],src,{});self.assertIn(rid,ss[0]['requestIds']);self.assertFalse(entries)
 def test_text_redacted_for_display_is_not_reused_as_parse_source(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'workbook').mkdir();note=root/'workbook/a.md';proof=root/'proof.json';proof.write_text(json.dumps({'client':'forum_employee','request_id':'forum-fixture-1327096c-20260101','peer':'1@chatroom','action':'send_text'}));note.write_text('- **事情**：delivery\n- **现在怎么样**：待推进\n- **过程笔记**：'+str(proof))
   role={'id':'forum','threadId':THREAD,'root':root};first,cache,_=w.notebook_items(role,{}, {},'now')
   cache[str(note)]['text']=cache[str(note)]['text'].replace(str(proof),'[display redacted path]')
   later,_,_=w.notebook_items(role,{},cache,'later');self.assertIn('forum-fixture-1327096c-20260101',later[0]['_deliverySeed']['operationEvidenceIds'])
 def test_delivery_guard_requires_scoped_checksum_bound_full_native_proof(self):
  from monitor_consistency import guard_deliveries
  from test_delivery_receipt_cache import ReceiptCacheTests
  fixture=ReceiptCacheTests();item,seed,jobs,sources,health=fixture.fixture()
  good=guard_deliveries(health,jobs,sources);self.assertEqual(good['incidents'][0]['status'],'resolved')
  for key,val in [('sourceId','missing'),('scopeBusinessId','different-business'),('contentHash','f'*64)]:
   bad=copy.deepcopy(jobs)
   for row in bad:
    if row.get('nativeReceiptVerified'):row[key]=val
   result=guard_deliveries(health,bad,sources);self.assertEqual(result['incidents'][0]['status'],'unknown');self.assertFalse(result['incidents'][0]['nativeReceiptVerified'])
 def test_professional_nested_origin_request_is_not_lost_or_converted_to_accepted_debt(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'CURRENT_RESEARCH.json').write_text(json.dumps({'latest_updated_utc':'2026-11-02T00:00:00Z','main':{'status':'in review','question':'main question'},'discussion':{'owner_request':{'status':'draft published; science remains open','source_serverId':'123','question':'requested comparison'}},'measurement':{'metric':{'status':'ok'}},'next_actions':['consider alternative']}))
   with patch.object(w,'SCI',root):rows=w.science_items({'id':'science'}, {})
   match=[r for r in rows if r['title']=='requested comparison'];self.assertEqual(len(match),1);self.assertNotEqual(match[0]['commitment'],'accepted');self.assertFalse(any(r['title']=='metric' for r in rows))
 def test_current_round_keeps_original_and_followups_instead_of_only_last_message(self):
  from inbox_reader import read_employee_inbox
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;c.executescript('create table thread_turns(thread_id text,turn_id text,status text,started_at int,rollout_ordinal int);create table thread_items(thread_id text,turn_id text,item_id text,item_type text,item_json text,created_at_ms int);create table queued_items(thread_id text,id text,queue_order int,created_at_ms int,payload_json text);')
  c.execute('insert into thread_turns values(?,?,?,?,?)',(THREAD,TURN,'inProgress',100,1))
  for k in range(4):c.execute('insert into thread_items values(?,?,?,?,?,?)',(THREAD,TURN,'u'+str(k),'userMessage',json.dumps({'content':[{'type':'text','text':'原始任务内容'+str(k)}]}),100000+k))
  c.execute('insert into thread_items values(?,?,?,?,?,?)',(THREAD,TURN,'p','agentMessage',json.dumps({'text':'正在核对本轮任务'}),100010))
  with patch.object(w,'ro',return_value=c):result=read_employee_inbox({'id':'system','name':'system','threadId':THREAD,'historyThreadId':THREAD,'channels':[{}]}, {},'now')
  active=[i for i in result['items'] if i['phase']=='processing'];self.assertEqual(len(active),1)
  for k in range(4):self.assertIn('原始任务内容'+str(k),active[0]['requestText'])
  c.close()
 def test_later_business_cancellation_does_not_erase_verified_physical_delivery(self):
  from test_delivery_receipt_cache import ReceiptCacheTests
  item,seed,jobs,sources,health=ReceiptCacheTests().fixture();item['state']='不做了'
  result=build_health(items=[item],seeds=[seed],jobs=jobs,gaps=[],observed_at=600)
  self.assertEqual(result['incidents'][0]['status'],'resolved');self.assertTrue(result['incidents'][0]['nativeReceiptVerified'])
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
