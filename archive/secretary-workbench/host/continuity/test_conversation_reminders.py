import unittest,time,json
from contextlib import ExitStack
from unittest.mock import patch
from types import SimpleNamespace
import runtime as r
from test_runtime import binding,event

class ConversationReminderTests(unittest.TestCase):
 def events(self):
  t=int(time.time());return [{**event(),'time':t,'serverId':x} for x in ['8000111409434127065','8000260726188019449','8000083247339321614']]
 def test_busy_repeated_mentions_one_conversation_latest_same_second(self):
  b=binding();l=r.Ledger(':memory:');es=self.events()
  for e in es:l.ingest(b,e)
  with patch('runtime.live',return_value={'status':'inProgress'}),patch('runtime.subprocess.run') as send:
   result=r.dispatch_role([b],l);send.assert_not_called();self.assertEqual(result['pending'],1);self.assertEqual(result['pendingEvidenceCount'],3)
  view=r.conversation_view([b],l.c);self.assertEqual(len(view),1);self.assertEqual(view[0]['latestSourceId'],es[-1]['serverId']);self.assertEqual(view[0]['reminderCount'],3)
  self.assertEqual(len(l.pending(b['id'])),3);l.close()
 def test_idle_one_wake_latest_only_all_evidence_preserved(self):
  b=binding();l=r.Ledger(':memory:');es=self.events()
  for e in es:l.ingest(b,e)
  ret=SimpleNamespace(returncode=0,stdout='Queued message 00000000-0000-4000-8000-479c4f1eb72a for thread '+b['threadId']+'.\n')
  with patch('runtime.live',return_value={'status':'completed'}),patch('runtime.queued',return_value=[]),patch('runtime.subprocess.run',return_value=ret) as send:
   r.dispatch_role([b],l);send.assert_called_once();body=send.call_args[0][0][-1]
   self.assertIn(es[-1]['serverId'],body)
   for e in es[:-1]:self.assertNotIn(e['serverId'],body)
  batch=l.inflight(b['id']);self.assertEqual(json.loads(batch['ids']),[e['serverId'] for e in es]);self.assertEqual(l.c.execute('select count(*) from events').fetchone()[0],3);l.close()
 def test_three_conversations_distinct_latest_in_one_role_wake(self):
  a=binding();routes=[a,{**a,'id':'two','peer':'21304205001@chatroom'},{**a,'id':'three','peer':'22862004294@chatroom'}];l=r.Ledger(':memory:')
  for n,b in enumerate(routes):
   for k,e in enumerate(self.events()[:2]):l.ingest(b,{**e,'peer':b['peer'],'serverId':str(8000054645942641489+n*10+k)})
  rows=r.conversation_view(routes,l.c);self.assertEqual(len(rows),3);self.assertEqual({x['peer'] for x in rows},{x['peer'] for x in routes});self.assertTrue(all(x['reminderCount']==2 for x in rows));l.close()
 def test_latest_work_acceptance_closes_old_reminders_not_business(self):
  b=binding();l=r.Ledger(':memory:');es=self.events()
  for e in es:l.ingest(b,e)
  with patch('runtime.live',return_value={'status':'completed'}),patch('runtime.queued',return_value=[]),patch('runtime.work_acceptance',side_effect=lambda b,e:'original-work' if e['serverId']==es[-1]['serverId'] else None),patch('runtime.subprocess.run') as send:
   r.dispatch_role([b],l);send.assert_not_called()
  self.assertEqual(l.pending(b['id']),[]);self.assertEqual(l.c.execute('select count(*) from events').fetchone()[0],3);l.close()
 def test_new_reminder_kept_without_editing_frozen_queued_input(self):
  b=binding();l=r.Ledger(':memory:');es=self.events();l.ingest(b,es[0]);batch=l.prepare(b,l.pending(b['id']));l.patch(batch['id'],state='queued',queue_id='existing')
  l.ingest(b,es[1]);frozen=l.inflight(b['id'])['body'];view=r.conversation_view([b],l.c);self.assertEqual(view[0]['latestSourceId'],es[1]['serverId']);self.assertEqual(frozen,batch['body'])
  with patch('runtime.live',return_value={'status':'completed'}),patch('runtime.find_native',return_value={'where':'queue','id':'existing'}),patch('runtime.subprocess.run') as send:r.dispatch_role([b],l);send.assert_not_called()
  l.close()
 def test_missing_native_batch_can_settle_only_after_all_original_work_is_accepted(self):
  for accepted_count,busy,queue_present in [(2,False,False),(1,False,False),(2,True,False),(2,False,True)]:
   with self.subTest(accepted_count=accepted_count,busy=busy,queue_present=queue_present), ExitStack() as stack:
    binding_info=binding();ledger=r.Ledger(':memory:');stack.callback(ledger.close)
    events=self.events()
    with patch('runtime.work_acceptance',return_value=None):
     for event_info in events[:2]:ledger.ingest(binding_info,event_info)
     batch=ledger.prepare(binding_info,ledger.pending(binding_info['id']))
     ledger.patch(batch['id'],state='queued',queue_id='original-queue')
     ledger.ingest(binding_info,events[2])
    accepted={e['serverId'] for e in events[:accepted_count]}
    stack.enter_context(patch('runtime.live',return_value={'status':'inProgress' if busy else 'completed'}))
    stack.enter_context(patch('runtime.find_native',return_value=None))
    stack.enter_context(patch('runtime.queued',return_value=[{'id':'some-live-queue'}] if queue_present else []))
    stack.enter_context(patch('runtime.work_acceptance',side_effect=lambda b,e:'original-work.md' if e['serverId'] in accepted else None))
    send=stack.enter_context(patch('runtime.subprocess.run'))
    result=r.dispatch_role([binding_info],ledger)
    send.assert_not_called()
    current=ledger.c.execute('select * from batches where id=?',(batch['id'],)).fetchone()
    settled=accepted_count==2 and not busy and not queue_present
    self.assertEqual(result['batchState'],'work_accepted_delivery_unverified' if settled else 'unknown_no_retry')
    self.assertEqual(current['state'],'work_accepted_delivery_unverified' if settled else 'queued')
    self.assertEqual(current['body'],batch['body'])
    self.assertEqual(current['queue_id'],'original-queue')
    self.assertIsNone(current['native_id'])
    self.assertEqual([e['serverId'] for e in ledger.pending(binding_info['id'])],[events[2]['serverId']])
    if settled:self.assertIsNone(ledger.inflight(binding_info['id']))
 def test_hourly_saw_latest_before_source_ingest_supersedes_older_reminders(self):
  b=binding();l=r.Ledger(':memory:');es=self.events();l.ingest(b,es[0]);l.ingest(b,es[1])
  with patch('runtime.work_acceptance',return_value='original-hourly-work'):l.ingest(b,es[-1])
  self.assertEqual(r.conversation_view([b],l.c),[]);self.assertEqual(l.c.execute('select count(*) from events').fetchone()[0],3);l.close()
 def test_new_mention_after_review_creates_new_conversation_reminder(self):
  b=binding();l=r.Ledger(':memory:');old=self.events()[0]
  with patch('runtime.work_acceptance',return_value='original-review'):l.ingest(b,old)
  newer={**old,'serverId':'8000280760311663203','time':old['time']+1};l.ingest(b,newer)
  view=r.conversation_view([b],l.c);self.assertEqual(len(view),1);self.assertEqual(view[0]['latestSourceId'],newer['serverId']);l.close()

if __name__=='__main__':unittest.main()
