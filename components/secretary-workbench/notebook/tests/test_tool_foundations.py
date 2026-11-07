import json,tempfile,unittest
from pathlib import Path
from modules.notebook import NotebookService,ValidationError,ConflictError

class ToolFoundationsTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.ws=Path(self.tmp.name)
  self.src=self.ws/'source.json';self.src.write_text('{"records":[]}')
  self.n=NotebookService(self.ws/'book.sqlite3',self.src,self.ws)
 def task(self,**kw):return self.n.create_task(dict(title='复核培训方案',**kw))
 def record(self,t,**kw):return self.n.record(t['id'],dict(expectedRevision=t['revision'],**kw))
 def test_deadline_explicit_and_not_inferred(self):
  t=self.task(timeRequirement='2026年10月28日18点晚餐');self.assertIsNone(t['deadlineDate'])
  t=self.record(t,deadlineDate='2026-10-27');t=self.record(t,timeRequirement='约定已补充');self.assertEqual(t['deadlineDate'],'2026-10-27')
  t=self.record(t,deadlineDate=None);self.assertIsNone(t['deadlineDate'])
 def test_source_locator_without_quote_and_private_fields_rejected(self):
  ref={'sourceId':'wechat:mine','recordId':'message-1','nativeId':'100','conversation':'软物质组','sender':'通知者甲','at':'2026-10-16T16:21:00+08:00','precision':'second','version':'v2'}
  t=self.task(sourceContacts=[ref]);self.assertEqual(t['sourceContacts'],[ref])
  for bad in [dict(ref,path='/etc/passwd'),dict(ref,key='secret'),dict(ref,quote='raw text')]:
   with self.assertRaises(ValidationError):self.record(t,sourceContacts=[bad])
 def test_unified_operation_and_cursor_include_independent_notes(self):
  before=self.n.changes()['cursor'];t=self.task(state='待办',planDate='2026-10-24',confirm=True,note='同一事务')
  events=self.n.changes(before)['operations'];self.assertEqual(len(events),1)
  self.assertTrue({'object','schedule'}<={e['kind'] for e in events[0]['effects']})
  cursor=self.n.changes()['cursor'];m=self.n.append_record({'text':'全局留言'})
  self.assertEqual(self.n.changes(cursor)['operations'][0]['effects'][0]['id'],m['id'])
 def test_history_asof_restore_preview_and_preserve_later_records(self):
  t=self.task(summary='旧摘要');seq=self.n.changes()['cursor'];t=self.record(t,summary='新摘要',note='不能删的记录')
  past=self.n.as_of(sequence=seq);self.assertEqual(next(x for x in past['objects'] if x['id']==t['id'])['summary'],'旧摘要')
  preview=self.n.restore_preview(t['id'],sequence=seq,fields=['summary']);self.assertEqual(preview['changes']['summary']['after'],'旧摘要')
  restored=self.n.restore(t['id'],{'sequence':seq,'fields':['summary'],'expectedRevision':t['revision'],'requestId':'RESTORE-one'})
  self.assertEqual(restored['summary'],'旧摘要');self.assertTrue(any(x.get('note')=='不能删的记录' for x in self.n.detail(t['id'])['timeline']))
  with self.assertRaises(ConflictError):self.n.restore(t['id'],{'sequence':seq,'fields':['summary'],'expectedRevision':t['revision']})
 def test_review_version_cannot_swallow_later_proposal(self):
  t=self.task();p=self.n.present(t['id'],{'expectedRevision':t['revision'],'note':'请看本轮','requestId':'P-one','actor':{'name':'AI','kind':'ai'}})
  t=self.n.get_task(t['id']);self.assertTrue(t['needsReview'])
  self.record(t,note='只是备注');self.assertTrue(self.n.get_task(t['id'])['needsReview'])
  t=self.n.get_task(t['id']);q=self.n.present(t['id'],{'expectedRevision':t['revision'],'note':'第二轮','actor':{'name':'AI','kind':'ai'}})
  t=self.n.get_task(t['id'])
  with self.assertRaises(ConflictError):self.record(t,confirm=True,presentationId=p['id'],presentationVersion=p['version'])
  t=self.record(t,confirm=True,presentationId=q['id'],presentationVersion=q['version']);self.assertFalse(t['needsReview'])
 def test_followup_is_not_reschedule_or_deadline(self):
  t=self.task(state='待办',planDate='2026-10-24',deadlineDate='2026-10-25',confirm=True)
  e=self.n.query_schedule('2026-10-24','2026-10-24')['entries'][0]
  self.n.schedule_record(e['id'],{'expectedRevision':e['revision'],'expectedObjectRevision':t['revision'],'state':'暂缓','followup':{'date':'2026-10-26'}})
  t=self.n.get_task(t['id']);self.assertEqual(t['planDate'],'2026-10-24');self.assertEqual(t['deadlineDate'],'2026-10-25')
  self.assertEqual(len(self.n.query_schedule('2026-10-26','2026-10-26')['entries']),0)
  self.assertEqual(len(self.n.due_followups('2026-10-26')['items']),1)
  self.assertEqual(len(self.n.query('review',date='2026-10-25')),0)
  self.assertEqual(len(self.n.query('review',date='2026-10-26')),1)
 def test_migration_and_restarts_do_not_rewrite_business_tables(self):
  t=self.task();before=self.n.changes()['cursor']
  NotebookService(self.n.db_file,self.src,self.ws)
  self.assertEqual(self.n.get_task(t['id']),t);self.assertEqual(self.n.changes()['cursor'],before)
 def test_transaction_failure_rolls_back_journal(self):
  t=self.task();seq=self.n.changes()['cursor']
  with self.n._connect() as db:db.execute("CREATE TRIGGER fail_entry BEFORE INSERT ON schedule_entries BEGIN SELECT RAISE(ABORT,'injected'); END")
  import sqlite3
  with self.assertRaises(sqlite3.IntegrityError):self.record(t,planDate='2026-10-24')
  self.assertEqual(self.n.changes()['cursor'],seq);self.assertEqual(self.n.get_task(t['id'])['revision'],t['revision'])

 def test_recurring_occurrence_completion_does_not_close_definition(self):
  t=self.task(recurrence={'frequency':'daily','startDate':'2026-10-24'})
  a=self.n.create_schedule({'objectId':t['id'],'date':'2026-10-24','expectedObjectRevision':t['revision']})
  t=self.n.get_task(t['id']);b=self.n.create_schedule({'objectId':t['id'],'date':'2026-10-25','expectedObjectRevision':t['revision']})
  t=self.n.get_task(t['id']);self.n.schedule_record(a['id'],{'expectedRevision':a['revision'],'expectedObjectRevision':t['revision'],'state':'已完成'})
  self.assertEqual(self.n.get_task(t['id'])['state'],'其他');self.assertEqual(self.n.get_schedule(b['id'])['state'],'待办')
  self.assertEqual(self.n.get_schedule(a['id'])['definitionId'],t['id'])
 def test_query_pagination_rejects_snapshot_change(self):
  self.task();self.task();page=self.n.query_objects(limit=1);self.assertIsNotNone(page['nextCursor'])
  self.assertEqual(len(self.n.query_objects(limit=1,cursor=page['nextCursor'])['objects']),1)
  self.n.append_record({'text':'游标期间有新信息'})
  with self.assertRaises(ConflictError):self.n.query_objects(limit=1,cursor=page['nextCursor'])
 def test_restore_retry_is_idempotent(self):
  t=self.task(summary='old');seq=self.n.changes()['cursor'];t=self.record(t,summary='new')
  body={'sequence':seq,'fields':['summary'],'expectedRevision':t['revision'],'requestId':'REST-repeat'}
  a=self.n.restore(t['id'],body);b=self.n.restore(t['id'],body);self.assertEqual(a['revision'],b['revision'])

 def test_known_overlap_and_deadline_warnings_do_not_rewrite_dates(self):
  for title,start,end in [('first','10:00','11:00'),('second','10:30','11:30')]:
   self.n.create_task(dict(title=title,state='待办',planDate='2026-10-24',deadlineDate='2026-10-23',confirm=True,eventWindow={'start':'2026-10-24T'+start+':00+08:00','end':'2026-10-24T'+end+':00+08:00'}))
  result=self.n.query_schedule('2026-10-24','2026-10-24');self.assertEqual(len(result['conflicts']),1)
  self.assertTrue(all(e['warnings'] for e in result['entries']));self.assertTrue(all(t['deadlineDate']=='2026-10-23' for t in self.n.list_tasks()))

 def test_restore_without_optional_request_key(self):
  t=self.task(summary='old');seq=self.n.changes()['cursor'];t=self.record(t,summary='new')
  result=self.n.restore(t['id'],{'sequence':seq,'fields':['summary'],'expectedRevision':t['revision']})
  self.assertEqual(result['summary'],'old')
