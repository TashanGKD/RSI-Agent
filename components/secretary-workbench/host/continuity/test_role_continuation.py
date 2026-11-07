import json,time,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import runtime as r
from test_runtime import binding,event

class RoleContinuationTests(unittest.TestCase):
 def pair(self):
  a=binding();b={**a,'id':'second','peer':'21304205001@chatroom'}
  e=event();f={**e,'peer':b['peer'],'serverId':'8000105847482291211'}
  return a,b,e,f
 def test_busy_many_groups_retained_then_one_idle_queue(self):
  a,b,e,f=self.pair();l=r.Ledger(':memory:');l.ingest(a,e);l.ingest(b,f)
  ret=SimpleNamespace(returncode=0,stdout='Queued message 00000000-0000-4000-8000-479c4f1eb72a for thread '+a['threadId']+'.\n')
  with patch('runtime.live',return_value={'status':'inProgress'}),patch('runtime.subprocess.run') as send:
   r.dispatch_role([a,b],l);send.assert_not_called();self.assertIsNone(l.inflight(a['id']));self.assertEqual(len(l.pending(b['id'])),1)
  with patch('runtime.live',return_value={'status':'completed'}),patch('runtime.queued',return_value=[]),patch('runtime.subprocess.run',return_value=ret) as send:
   r.dispatch_role([a,b],l);send.assert_called_once();body=send.call_args[0][0][-1]
   for x in [e['serverId'],f['serverId'],a['peer'],b['peer']]:self.assertIn(x,body)
   self.assertNotIn('--resume',send.call_args[0][0]);self.assertEqual(l.pending(a['id'])+l.pending(b['id']),[])
   with patch('runtime.find_native',return_value={'where':'history','id':'actual','turnId':'actual-turn'}):r.dispatch_role([a,b],l)
   send.assert_called_once()
  l.close()
 def test_hourly_already_accepted_all_groups_no_new_queue(self):
  a,b,e,f=self.pair();l=r.Ledger(':memory:');l.ingest(a,e);l.ingest(b,f)
  with patch('runtime.work_acceptance',return_value='original-note'),patch('runtime.live',return_value={'status':'completed'}),patch('runtime.queued',return_value=[]),patch('runtime.subprocess.run') as send:
   r.dispatch_role([a,b],l);send.assert_not_called();self.assertEqual(l.pending(a['id'])+l.pending(b['id']),[])
  l.close()
 def test_role_conflicts_rejected(self):
  a,b,_,_=self.pair()
  for bad in [{**b,'workEntry':'/different/ROLE.md'},{**b,'historyThreadId':'00000000-0000-4000-8000-680f4dcf9cf6'},{**b,'account':'wxid_fixture_4c90539d6a'}]:
   with self.assertRaises(ValueError):r.role_groups([a,bad])
 def test_authorized_separate_work_area_and_escape_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d).resolve();cwd=base/'project';cwd.mkdir();area=base/'employee';area.mkdir();entry=area/'ENTRY.md';entry.write_text('entry')
   b={**binding(),'cwd':str(cwd),'workRoot':str(area),'workEntry':str(entry),'workbookDir':str(area/'notebook')};(area/'notebook').mkdir()
   r.validate_binding(b)
   outside=base/'outside.md';outside.write_text('private');link=area/'linked.md';link.symlink_to(outside)
   for bad in [{**b,'workEntry':str(outside)},{**b,'workEntry':str(link)},{**b,'workbookDir':str(base/'project')},{**b,'workRoot':str(area/'..')}]:
    with self.assertRaises(ValueError):r.validate_binding(bad)
 def test_native_source_identity_conflict_kept(self):
  a,_,e,_=self.pair();l=r.Ledger(':memory:');l.ingest(a,e)
  with self.assertRaises(ValueError):l.ingest(a,{**e,'senderId':'wxid_fixture_4c90539d6a'})
  self.assertEqual(len(l.pending(a['id'])),1);l.close()
 def test_saved_hourly_prompt_reused_and_target_checked(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d).resolve();p=base/'automations/role-hourly/automation.toml';p.parent.mkdir(parents=True)
   b={**binding(),'automationId':'role-hourly'};prompt='Use the original role entry; keep paused work paused.'
   def write(target):p.write_text('kind = "heartbeat"\ntarget_thread_id = '+json.dumps(target)+'\nprompt = '+json.dumps(prompt)+'\n')
   write(b['threadId'])
   with patch('runtime.HOME',base):
    self.assertEqual(r.continuation_prompt(b),prompt)
    self.assertIn(prompt,r.body_for(b,[event()],'test'))
    write('00000000-0000-4000-8000-680f4dcf9cf6')
    with self.assertRaises(ValueError):r.continuation_prompt(b)
 def test_original_secretary_notes_acceptance_not_process_reference(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d).resolve();folder=base/'notebook';folder.mkdir();b={**binding(),'workEntry':str(base/'ENTRY.md'),'workbookDir':str(folder)};e=event();note=folder/'old.md'
   prefix='<!-- secretary-work-current:start -->\n- **怎么来的**：'+e['serverId']+'\n- **现在怎么样**：等反馈\n- **下一步**：等原结果\n<!-- secretary-work-current:end -->'
   note.write_text(prefix);self.assertEqual(r.work_acceptance(b,e),str(note))
   note.write_text(prefix.replace(e['serverId'],'different')+'\nprocess '+e['serverId']);self.assertIsNone(r.work_acceptance(b,e))

if __name__=='__main__':unittest.main()
