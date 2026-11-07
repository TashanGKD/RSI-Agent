import tempfile,unittest
from pathlib import Path
from inbox_reader import read_document,describe_request,meaningful_summary,queue_rows

class InboxTests(unittest.TestCase):
 def test_public_activity_has_titles_without_tool_arguments_or_reasoning(self):
  from inbox_reader import visible_activity
  rows=[{'type':'reasoning','text':'HIDDEN'},{'type':'subAgentActivity','agentPath':'/root/front_draft_review','kind':'completed'},{'type':'commandExecution','command':'SECRET_COMMAND','aggregatedOutput':'SECRET_OUTPUT','status':'completed'}]
  s=visible_activity(rows);self.assertIn('Front draft review',s);self.assertIn('已结束',s);self.assertNotIn('HIDDEN',s);self.assertNotIn('SECRET',s)
 def test_heartbeat_time_and_xml_are_not_the_work_summary(self):
  raw='<heartbeat>\n<automation_id>science-group-halfhour</automation_id>\n<current_time_iso>2026-10-31T13:32:04.819Z</current_time_iso>\n<instructions>参与科研交流，推进原研究。</instructions>\n</heartbeat>'
  x=meaningful_summary(raw)
  self.assertEqual(x,'定时工作接续');self.assertNotIn('2026',x);self.assertNotIn('<',x)
 def test_confirmation_wrapper_is_not_shown_as_raw_json(self):
  raw='<send_user_message_question_reply>[{"questionItemId":"opaque-id","question":"明早九点在协会骨干群发接龙？","answer":"确认"}]</send_user_message_question_reply>'
  s=meaningful_summary(raw);self.assertIn('确认',s);self.assertIn('明早九点',s);self.assertNotIn('questionItemId',s)
 def test_native_current_and_queue_are_separate_and_readonly(self):
  import sqlite3,json
  from unittest.mock import patch
  import work_observer as m
  from inbox_reader import read_employee_inbox
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  c.executescript('create table thread_turns(thread_id text,turn_id text,status text,started_at int,rollout_ordinal int);create table thread_items(thread_id text,turn_id text,item_id text,item_type text,item_json text,created_at_ms int);create table queued_items(thread_id text,id text,queue_order int,created_at_ms int,payload_json text);')
  c.execute('insert into thread_turns values(?,?,?,?,?)',('t','turn','inProgress',100,1))
  msg={'content':[{'type':'text','text':'核对课程师资后给出意见'}]}
  c.execute('insert into thread_items values(?,?,?,?,?,?)',('t','turn','user','userMessage',json.dumps(msg),100000))
  c.execute('insert into thread_items values(?,?,?,?,?,?)',('t','turn','private','reasoning',json.dumps({'text':'DO_NOT_READ_PRIVATE_REASONING'}),100002))
  c.execute('insert into thread_items values(?,?,?,?,?,?)',('t','turn','progress','agentMessage',json.dumps({'text':'正在核对师资，随后给出意见'}),100001))
  for ident,order,ts in [('b',8,1000),('a',4,2000)]:c.execute('insert into queued_items values(?,?,?,?,?)',('t',ident,order,ts,json.dumps({'UserInput':msg})))
  changes=c.total_changes
  with patch.object(m,'ro',return_value=c):x=read_employee_inbox({'id':'actor','name':'员工','threadId':'t','historyThreadId':'t','channels':[{}]}, {},'2026-10-31T10:00:00Z')
  self.assertEqual(x['queueCount'],2);self.assertEqual([r['phase'] for r in x['items']],['processing','queued','queued']);self.assertEqual([r['queuePosition'] for r in x['items']],[0,1,2]);self.assertIn('给出意见',x['items'][0]['progress']);self.assertNotIn('DO_NOT_READ',str(x));self.assertEqual(c.total_changes,changes);c.close()
 def test_foreign_file_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):read_document('/etc/passwd',[Path(d).resolve()])
 def test_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve();(p/'real.txt').write_text('hello');(p/'link.txt').symlink_to(p/'real.txt')
   with self.assertRaises(ValueError):read_document(p/'link.txt',[p])
 def test_secret_reference_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve();f=p/'password.txt';f.write_text('private')
   with self.assertRaises(ValueError):read_document(f,[p])
 def test_secretary_is_not_a_secret_filename(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d).resolve();f=p/'secretary-owner-reply.md';f.write_text('业务回复')
   self.assertEqual(read_document(f,[p]),'业务回复')
 def test_brief_resolves_target_and_actual_body(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();body=root/'M521地点进展.txt';body.write_text('我来核对已发通知的群，补充中关村线下地点：物理所M521。线上时间和会议入口保持。')
   brief=root/'assignment.md';brief.write_text('发送交办，secretary/吾愿→24117802867@chatroom。最终全文'+str(body)+'，request_id=example-fixture-f26f2dc2-20260101。')
   x=describe_request('发送交办example-fixture-f26f2dc2-20260101，自然新来源真实核后有具体工作在做，原关系进展定稿见'+str(brief),roots=[root])
   self.assertEqual(x['peer'],'24117802867@chatroom');self.assertIn('M521',x['summary']);self.assertNotIn('自然新来源',x['summary']);self.assertIn('会议入口保持',x['body'])
 def test_file_delivery_title_names_the_actual_result(self):
  x=meaningful_summary('发送交办abc-fixture-75a713fd-20260101','', ['缅怀钱学森_纪念单页.png','缅怀钱学森_纪念单页.pptx'])
  self.assertIn('钱学森',x);self.assertNotIn('发送交办',x)
 def test_queue_rank_preserves_native_order(self):
  rows=[{'id':'b','queue_order':7,'created_at_ms':10,'payload_json':'{}'},{'id':'a','queue_order':4,'created_at_ms':20,'payload_json':'{}'}]
  x=queue_rows(rows);self.assertEqual([r['id'] for r in x],['a','b']);self.assertEqual([r['queuePosition'] for r in x],[1,2])
 def test_absent_substance_remains_unknown(self):
  self.assertEqual(meaningful_summary('发送交办foo-fixture-48699ddc-20260101，自然新来源真实核后有具体工作在做，原关系进展定稿见[Mac原件]','',[]),'交办内容待提取')

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
