"""Schedule invariants; synthetic isolated data, never the live notebook.
Reject: malformed interval/date, >42-day query, unknown fields and stale versions.
"""
import json, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
from modules.notebook import NotebookService, ValidationError, ConflictError

class ScheduleTests(unittest.TestCase):
 def setUp(self):
  clock=patch("modules.notebook.schedule.today",return_value="2026-10-24");clock.start();self.addCleanup(clock.stop)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.ws=Path(self.tmp.name);self.src=self.ws/'source.json';self.src.write_text('{"records":[]}')
  self.n=NotebookService(self.ws/'book.sqlite3',self.src,self.ws)
 def task(self,**kw):return self.n.create_task(dict(title='核对本轮方案',state='待办',planDate='2026-10-23',confirm=True,**kw))
 def entry(self,t):return next(e for e in self.n.query_schedule('2026-10-23','2026-10-23')['entries'] if e['objectId']==t['id'])
 def save(self,e,**patch):
  return self.n.schedule_record(e['id'],dict(expectedRevision=e['revision'],expectedObjectRevision=self.n.get_task(e['objectId'])['revision'],**patch))
 def test_schedule_port_exists(self):self.assertTrue(callable(getattr(self.n,'query_schedule',None)),'missing schedule query')
 def test_invalid_inputs_rejected_without_records(self):
  t=self.task();e=self.entry(t)
  for p in [{'startTime':'14:00','endTime':'13:00'},{'date':'bad'},{'state':'hacked'},{'postponeTo':{'date':'2026-02-30'}},{'startTime':'24:00'},{'postponeTo':{'date':'2026-10-23'}}]:
   with self.assertRaises(ValidationError):self.save(e,**p)
  self.assertEqual(self.n.get_schedule(e['id'])['revision'],e['revision'])
  for start,end in [('2026-10-24','2026-10-23'),('2026-10-01','2026-12-01'),('2026-99-01','2026-10-23')]:
   with self.assertRaises(ValidationError):self.n.query_schedule(start,end)
 def test_complete_stays_on_day_and_future_is_not_changed(self):
  t=self.task();e=self.entry(t);done=self.save(e,state='已完成',note='已核对并答复')
  self.assertEqual(done['state'],'已完成');self.assertEqual(self.n.get_task(t['id'])['state'],'已完成')
  self.assertEqual(self.entry(t)['id'],e['id']);self.assertEqual(self.entry(t)['state'],'已完成')
  self.assertTrue(any(x['note']=='已核对并答复' for x in self.n.schedule_history(e['id'])))
 def test_postpone_is_atomic_linked_and_history_kept(self):
  t=self.task();e=self.entry(t);old=self.save(e,state='暂缓',postponeTo={'date':'2026-10-25','startTime':'14:00','endTime':'15:00'},note='等材料到齐')
  new=self.n.get_schedule(old['nextEntryId'])
  self.assertEqual(old['state'],'暂缓');self.assertEqual(new['state'],'待办');self.assertEqual(new['date'],'2026-10-25')
  self.assertEqual(new['previousEntryId'],old['id']);self.assertEqual(new['startTime'],'14:00')
  t=self.n.get_task(t['id']);self.assertEqual(t['planDate'],'2026-10-25')
  self.save(new,state='已完成');self.assertEqual(self.n.get_schedule(e['id'])['state'],'暂缓')
 def test_note_only_is_not_ack_or_state_change(self):
  t=self.task();e=self.entry(t);a=self.save(e,note='还差收费依据')
  self.assertEqual(a['state'],e['state']);self.assertEqual(self.n.get_task(t['id'])['needsReview'],t['needsReview'])
 def test_repeat_retry_and_conflict(self):
  t=self.task();e=self.entry(t);body=dict(expectedRevision=e['revision'],expectedObjectRevision=t['revision'],state='等对方',requestId='REQ-ONCE')
  a=self.n.schedule_record(e['id'],body);b=self.n.schedule_record(e['id'],body)
  self.assertEqual(a['revision'],b['revision']);self.assertEqual(a['objectRevision'],b['objectRevision'])
  with self.assertRaises(ConflictError):self.save(e,state='已完成')
  with self.assertRaises(ValidationError):self.n.schedule_record(e['id'],dict(body,note='different'))
 def test_legacy_api_updates_only_current_entry(self):
  t=self.task();e=self.entry(t);a=self.save(e,state='暂缓',postponeTo={'date':'2026-10-25'})
  t=self.n.get_task(t['id']);self.n.record(t['id'],dict(expectedRevision=t['revision'],state='已完成'))
  self.assertEqual(self.n.get_schedule(a['nextEntryId'])['state'],'已完成');self.assertEqual(self.n.get_schedule(e['id'])['state'],'暂缓')
 def test_restarts_and_empty_notes_do_not_duplicate(self):
  t=self.task();e=self.entry(t)
  n=NotebookService(self.n.db_file,self.src,self.ws)
  self.assertEqual(len(n.query_schedule('2026-10-23','2026-10-23')['entries']),1)
  self.assertEqual(n.get_schedule(e['id'])['revision'],e['revision'])
 def test_explicit_new_date_without_review_and_time_optional(self):
  t=self.task(eventWindow={'start':'2026-10-23T14:00:00+08:00','end':None})
  e=self.entry(t);self.assertEqual(e['startTime'],'14:00');self.assertIsNone(e['endTime']);self.assertFalse(t['needsReview'])
 def test_domain_owner_and_group_order(self):
  a=self.task(domain='他山');b=self.task(domain='科研');self.task(domain='他山',assignee='AI')
  es=self.n.query_schedule('2026-10-23','2026-10-23')['entries'];self.assertEqual([e['objectId'] for e in es],[b['id'],a['id']])
  self.assertEqual(len(self.n.query_schedule('2026-10-23','2026-10-23',domain='他山')['entries']),1)
 def test_invalid_timewindow_rejected_at_task_boundary(self):
  for w in [{'start':'2026-10-23T14:00:00','end':None},{'start':'2026-10-23T14:00:00+00:00'},{'start':'2026-10-23T14:00:00+08:00','end':'2026-10-23T13:00:00+08:00'}]:
   with self.assertRaises(ValidationError):self.task(eventWindow=w)
 def test_transaction_failure_rolls_back_task_and_both_entries(self):
  t=self.task();e=self.entry(t)
  with self.n._connect() as db:db.execute("CREATE TRIGGER fail_schedule_insert BEFORE INSERT ON schedule_entries WHEN NEW.date='2026-10-25' BEGIN SELECT RAISE(ABORT,'injected'); END")
  import sqlite3
  with self.assertRaises(sqlite3.IntegrityError):self.save(e,state='暂缓',postponeTo={'date':'2026-10-25'})
  self.assertEqual(self.n.get_schedule(e['id'])['state'],'待办');self.assertEqual(self.n.get_task(t['id'])['revision'],t['revision'])

 def test_note_after_postpone_does_not_change_future_pending(self):
  t=self.task();e=self.entry(t);old=self.save(e,state='暂缓',postponeTo={'date':'2026-10-25'})
  t=self.n.get_task(t['id']);self.n.record(t['id'],dict(expectedRevision=t['revision'],note='补充一条备注'))
  self.assertEqual(self.n.get_schedule(old['nextEntryId'])['state'],'待办')
 def test_object_conflict_and_note_history_survive(self):
  t=self.task();e=self.entry(t)
  self.n.record(t['id'],dict(expectedRevision=t['revision'],note='另一设备补充信息'))
  with self.assertRaises(ConflictError):self.n.schedule_record(e['id'],dict(expectedRevision=e['revision'],expectedObjectRevision=t['revision'],state='已完成'))
  self.assertEqual(self.n.get_schedule(e['id'])['state'],'待办')
 def test_migration_preserves_all_original_tables(self):
  import sqlite3
  t=self.task();tables=['local_objects','local_changes','local_records','local_requests','tasks','notebook_events']
  def contents():
   with self.n._connect() as db:return {table:[tuple(r) for r in db.execute('SELECT * FROM '+table+' ORDER BY 1')] for table in tables}
  before=contents();self.n._init_schedule();self.assertEqual(contents(),before)
 def test_invalid_domain_and_owner_rejected(self):
  for kw in [dict(domain='invalid'),dict(assignee=['我'])]:
   with self.assertRaises(ValidationError):self.n.query_schedule('2026-10-23','2026-10-23',**kw)

 def test_restart_does_not_refresh_empty_legacy_source_over_cloud_objects(self):
  t=self.task()
  with self.n._connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM metadata ORDER BY key')]
  NotebookService(self.n.db_file,self.src,self.ws)
  with self.n._connect() as db:after=[tuple(r) for r in db.execute('SELECT * FROM metadata ORDER BY key')]
  self.assertEqual(before,after)

 def test_summary_is_returned_without_rewriting_legacy_schedule(self):
  t=self.task(summary='先核对课程、师资和收费，再形成反馈。');e=self.entry(t)
  self.assertEqual(e.get('summary'),t['summary'])
  with self.n._connect() as db:
   raw=json.loads(db.execute('SELECT payload FROM schedule_entries WHERE id=?',(e['id'],)).fetchone()[0]);raw.pop('summary',None)
   db.execute('UPDATE schedule_entries SET payload=? WHERE id=?',(json.dumps(raw),e['id']))
  with self.n._connect() as db:before=db.execute('SELECT payload FROM schedule_entries WHERE id=?',(e['id'],)).fetchone()[0]
  self.assertEqual(self.n.get_schedule(e['id']).get('summary'),t['summary'])
  self.assertEqual(self.entry(t).get('summary'),t['summary'])
  with self.n._connect() as db:self.assertEqual(db.execute('SELECT payload FROM schedule_entries WHERE id=?',(e['id'],)).fetchone()[0],before)

if __name__=='__main__':unittest.main()
