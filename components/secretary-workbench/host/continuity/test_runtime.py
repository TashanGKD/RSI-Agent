import unittest,tempfile,sqlite3,time
from unittest.mock import patch
from types import SimpleNamespace
from pathlib import Path
from runtime import validate_binding,validate_event,Ledger,body_for,work_acceptance,extend_bindings

ACCOUNT='wxid_fixture_operator'
def binding():
 return dict(id='forum',account=ACCOUNT,peer='21993263679@chatroom',threadId='00000000-0000-4000-8000-1f937c412a00',historyThreadId='00000000-0000-4000-8000-58d5abcc6b58',cwd=str(Path(__file__).resolve().parent),workEntry=str(Path(__file__).resolve()),since=int(time.time())-60,handledSources=['8000115792974558290','8000268335426123501'])
def event():
 return dict(account=ACCOUNT,peer='21993263679@chatroom',serverId='8000002710771205891',senderId='wxid_fixture_owner',time=int(time.time()),kind=1,atUserIds=[ACCOUNT],nativeSourceVerified=True)

class RuntimeTests(unittest.TestCase):
 def test_cross_group_rejected(self):
  e=event();e['peer']='21557886000@chatroom'
  with self.assertRaises(ValueError):validate_event(binding(),e)
 def test_body_at_is_not_native(self):
  e=event();e['atUserIds']=[];e['text']='@吾愿'
  with self.assertRaises(ValueError):validate_event(binding(),e)
 def test_unsafe_binding_rejected(self):
  for field,value in [('peer','1@chatroom; touch /tmp/unsafe'),('threadId','--resume'),('workEntry','/tmp/../../etc/passwd')]:
   b=binding();b[field]=value
   with self.assertRaises(ValueError):validate_binding(b)
 def test_self_and_imprecise_ids_rejected(self):
  for field,value in [('senderId',ACCOUNT),('serverId',8000002710771205891),('nativeSourceVerified',False)]:
   e=event();e[field]=value
   with self.assertRaises(ValueError):validate_event(binding(),e)
 def test_event_once_across_reopen(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'ledger.sqlite';l=Ledger(p);self.assertTrue(l.ingest(binding(),event()));self.assertFalse(l.ingest(binding(),event()));l.close()
   l=Ledger(p);self.assertEqual(len(l.pending('forum')),1);self.assertFalse(l.ingest(binding(),event()));l.close()
 def test_handled_source_does_not_dispatch(self):
  l=Ledger(':memory:');e=event();e['serverId']='8000268335426123501';l.ingest(binding(),e);self.assertEqual(l.pending('forum'),[]);l.close()
 def test_frozen_submission_and_unknown_no_retry(self):
  l=Ledger(':memory:');b=binding();l.ingest(b,event());batch=l.prepare(b,l.pending('forum'));self.assertEqual(batch['state'],'prepared')
  l.patch(batch['id'],state='submitting');l.patch(batch['id'],state='unknown');self.assertEqual(l.inflight('forum')['state'],'unknown');self.assertEqual(l.pending('forum'),[])
  with self.assertRaises(ValueError):l.prepare(b,[event()])
  l.close()
 def test_body_has_real_sources_and_no_fake_content(self):
  s=body_for(binding(),[event()],'stable-test');self.assertIn(event()['serverId'],s);self.assertIn('原生@',s);self.assertNotIn('你好我是教授',s)
 def test_busy_retains_no_batch_no_external_call(self):
  from runtime import dispatch
  l=Ledger(':memory:');b=binding();l.ingest(b,event())
  with patch('runtime.live',return_value={'status':'inProgress'}),patch('runtime.subprocess.run') as send:
   result=dispatch(b,l);self.assertTrue(result['waitingForIdle']);self.assertEqual(len(l.pending('forum')),1);self.assertIsNone(l.inflight('forum'));send.assert_not_called()
  l.close()
 def test_idle_submits_once_and_reconciles_without_resend(self):
  from runtime import dispatch
  l=Ledger(':memory:');b=binding();l.ingest(b,event())
  result=SimpleNamespace(returncode=0,stdout='Queued message 00000000-0000-4000-8000-479c4f1eb72a for thread '+b['threadId']+'.\n')
  with patch('runtime.live',return_value={'status':'completed'}),patch('runtime.queued',return_value=[]),patch('runtime.subprocess.run',return_value=result) as send:
   dispatch(b,l);send.assert_called_once();self.assertNotIn('--resume',send.call_args[0][0])
   with patch('runtime.find_native',return_value={'where':'history','id':'item-real','turnId':'turn-real'}):dispatch(b,l)
   send.assert_called_once();self.assertIsNone(l.inflight('forum'))
  l.close()
 def test_submission_timeout_never_retries_new_id(self):
  from runtime import dispatch
  l=Ledger(':memory:');b=binding();l.ingest(b,event())
  with patch('runtime.live',return_value={'status':'completed'}),patch('runtime.queued',return_value=[]),patch('runtime.find_native',return_value=None),patch('runtime.subprocess.run',side_effect=TimeoutError) as send:
   with self.assertRaises(TimeoutError):dispatch(b,l)
   self.assertEqual(l.inflight('forum')['state'],'unknown');dispatch(b,l);send.assert_called_once()
  l.close()
 def test_original_workbook_acceptance_and_candidates(self):
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d)/'workbook';folder.mkdir();b=binding();b['workEntry']=str(Path(d)/'ROLE.md');e=event()
   note=folder/'existing.md';prefix='<!-- employee-work:start -->\n- **事情**：原业务\n- **怎么来的**：'
   suffix='\n- **现在怎么样**：待推进\n- **下一步**：准备原方案\n<!-- employee-work:end -->'
   note.write_text(prefix+'本人原群消息'+e['serverId']+suffix)
   self.assertEqual(work_acceptance(b,e),str(note))
   note.write_text(prefix+'主动发现，尚未承接，引用'+e['serverId']+suffix)
   self.assertIsNone(work_acceptance(b,e))
   note.write_text(prefix+'另一条消息'+suffix+'\n过程里仅提及'+e['serverId'])
   self.assertIsNone(work_acceptance(b,e))
 def test_additive_registration_preserves_existing_routes(self):
  old=binding();new={**binding(),'id':'pilot','peer':'23167690015@chatroom'}
  self.assertEqual(extend_bindings([old],[old,new]),[old,new])
  for rows in [[new],[{**old,'since':old['since']+1},new],[old,{**new,'peer':old['peer']}]]:
   with self.assertRaises(ValueError):extend_bindings([old],rows)

if __name__=='__main__':unittest.main()
