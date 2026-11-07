import tempfile,unittest
from pathlib import Path
from work_observer import bounded_text,public_text,receipt_state,commitment,project_note,group_bindings

class ObserverTests(unittest.TestCase):
 def test_sender_latest_turn_and_maintenance_are_separate(self):
  import sqlite3,json
  from unittest.mock import patch
  import work_observer as m
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  c.executescript('create table thread_turns(thread_id text,turn_id text,status text,started_at int,completed_at int,rollout_ordinal int);create table thread_items(thread_id text,turn_id text,item_id text,item_type text,item_json text,created_at_ms int);create table queued_items(thread_id text,id text,payload_json text,created_at_ms int,queue_order int);')
  c.execute('insert into thread_turns values(?,?,?,?,?,?)',(m.SENDER,'old','inProgress',1,None,9999));c.execute('insert into thread_turns values(?,?,?,?,?,?)',(m.SENDER,'new','inProgress',2,None,5))
  for turn,body in [('old','解决发送工具的大文件传输问题'),('new','发送交办 secretary-fixture-21ccf3c3-20260101：给人才群发送本轮结果，目标24070781937@chatroom')]:
   c.execute('insert into thread_items values(?,?,?,?,?,?)',(m.SENDER,turn,turn,'userMessage',json.dumps({'content':[{'type':'text','text':body}]}),1000 if turn=='old' else 2000))
  with tempfile.TemporaryDirectory() as d,patch.object(m,'SEC',Path(d).resolve()),patch.object(m,'ro',return_value=c):
   j=m.sender_inbox({},'2026-10-31T10:00:00Z');current=[x for x in j['items'] if x['phase']=='processing']
   self.assertEqual(len(current),1);self.assertEqual(current[0]['employee'],'secretary');self.assertEqual(current[0]['destination'],'fixture target')
  c.close()
 def test_normal_note_change_updates_without_worker_reporting(self):
  from unittest.mock import patch
  import work_observer as m
  with tempfile.TemporaryDirectory() as d:
   root=Path(d).resolve();(root/'workbook').mkdir();entry=root/'ROLE.md';entry.write_text('负责会务。图文结合，方案用Word。')
   note=root/'workbook/a.md';note.write_text('- **事情**：独立交付\n- **怎么来的**：本人交办\n- **现在怎么样**：待推进\n- **下一步**：完成它')
   (root/'registry.json').write_text('{"bindings": []}')
   role={'id':'forum','name':'论坛会务','threadId':'a','historyThreadId':'a','root':root,'entry':entry,'category':'business','channels':[]}
   snap={'tasks':[],'employees':[],'profiles':{}}
   with patch.object(m,'PRIVATE',root/'cache'),patch.object(m,'REGISTRY',root/'registry.json'),patch.object(m,'METHOD',root),patch.object(m,'directory',return_value=([role],{})),patch.object(m,'runtime',return_value={'state':'空闲','queueCount':0}),patch.object(m,'safe_coverage',return_value={'readThrough':None,'note':'fixture read boundary'}),patch.object(m,'sender_inbox',return_value={'items':[]}),patch.object(m,'enrich_sending',side_effect=lambda s,rs,t:s),patch('inbox_reader.read_employee_inbox',return_value={'items':[],'queueCount':0,'runtimeState':'unknown'}),patch.object(m,'read_modes',return_value={}),patch.object(m,'system_observation',return_value={}):
    s,rs=m.refresh_work(snap,{},'2026-10-31T10:00:00Z');ident=s['workOverview']['items'][0]['id']
    self.assertEqual(s['workOverview']['items'][0]['state'],'待推进');self.assertEqual(len(s['employees']),1)
    note.write_text(note.read_text().replace('待推进','已办好'));before=note.read_bytes()
    s,rs=m.refresh_work(s,rs,'2026-10-31T10:05:00Z')
    self.assertEqual(s['workOverview']['items'][0]['id'],ident);self.assertEqual(s['workOverview']['items'][0]['state'],'已办好');self.assertEqual(note.read_bytes(),before);self.assertEqual(s['tasks'][0]['state'],'已办好')
 def test_new_projection_validates_sources(self):
  from work_contract import validate_work
  w={'version':1,'readOnly':True,'employees':[],'items':[{'id':'a','sourceId':'s','evidence':[{'id':'s','quote':'actual'}]}],'sending':{'items':[]},'modes':{'sourceId':'s'}}
  validate_work(w,{'s':{'text':'actual'}})
  with self.assertRaises(ValueError):validate_work(w,{})
  with self.assertRaises(ValueError):validate_work({**w,'access_token':'secret'},{'s':{'text':'actual'}})
 def test_outside_refused(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(ValueError):bounded_text(Path('/etc/passwd'),[Path(d)])
 def test_symlink_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'real.md').write_text('x');(p/'link.md').symlink_to(p/'real.md')
   with self.assertRaises(ValueError):bounded_text(p/'link.md',[p])
 def test_restricted_refused(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'.restricted-archive';p.mkdir();f=p/'note.md';f.write_text('x')
   with self.assertRaises(ValueError):bounded_text(f,[Path(d)])
 def test_secrets_not_exported(self):
  for raw in ['password=abcdefg','口令：abcdefg','eyJabcdefg.abcdefghijk.abcdefghijk','sk-'+('z'*30)]:
   self.assertNotIn(raw,public_text(raw))
 def test_success_not_native_proof(self):self.assertEqual(receipt_state({'state':'succeeded'}),'unknown')
 def test_native_summary(self):
  self.assertEqual(receipt_state({'state':'succeeded','serverId':'123','independentNativeExactText':True}),'sent')
 def test_pending_does_not_close(self):self.assertEqual(receipt_state({'state':'pending'}),'pending')
 def test_candidate_separate(self):
  self.assertEqual(commitment('主动发现，尚未承接','待推进'),'candidate')
  self.assertEqual(commitment('本人交办','待推进'),'accepted')
  self.assertEqual(commitment('尚未承接；后来本人确认交办','待推进'),'unknown')
 def test_current_head_not_old_history(self):
  raw='<!-- employee-work:start -->\n- **事情**：本轮交付\n- **怎么来的**：本人交办\n- **现在怎么样**：已办好\n- **下一步**：保留回执\n<!-- employee-work:end -->\n旧状态：未完成'
  x=project_note('forum','/a.md',raw,'source1','2026-10-31')
  self.assertEqual(x['state'],'已办好');self.assertEqual(x['commitment'],'accepted')
 def test_channels_not_people(self):
  b=[{'threadId':'x','id':'a'},{'threadId':'x','id':'b'},{'threadId':'y','id':'c'}]
  self.assertEqual(len(group_bindings(b)),2)

if __name__=='__main__':unittest.main()

def setUpModule():
 from unittest.mock import patch
 import contextlib,collect,send_tool_observer,delivery_obligations,employee_profiles,account_contract,model_accounts
 global _portable_patches
 _portable_patches=contextlib.ExitStack()
 import work_observer
 _portable_patches.enter_context(patch.object(work_observer,'SENDER','00000000-0000-4000-8000-111111111111'))
 _portable_patches.enter_context(patch.object(work_observer,'PEERS',{'24070781937@chatroom':'fixture target'}))
 import work_observer

 clients={'secretary':'secretary','science':'science','organoid_bp':'organoid','forum_employee':'forum','employee_pilot':'employee-pilot','employee_method':'system','aup_support':'aup-support','research_secretary':'research-secretary'}
 ids={'secretary':'00000000-0000-4000-8000-4344f0fd9daa','science':'00000000-0000-4000-8000-37b7cd446cba','organoid':'00000000-0000-4000-8000-f709f264f942'}
 emails=tuple('fixture'+str(i)+'@example.invalid' for i in range(3))
 for mod,key,value in [(send_tool_observer,'CLIENTS',clients),(collect,'IDS',ids),(delivery_obligations,'CLIENTS',clients),(delivery_obligations,'OWNERS',ids),(employee_profiles,'IDS',ids),(account_contract,'EMAILS',emails),(model_accounts,'EMAILS',emails)]:
  _portable_patches.enter_context(patch.object(mod,key,value))
def tearDownModule():
 _portable_patches.close()
