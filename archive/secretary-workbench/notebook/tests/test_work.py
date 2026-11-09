import hashlib,json,tempfile,unittest
from pathlib import Path
from modules.notebook import NotebookService,ValidationError,ConflictError

class WorkTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.ws=Path(self.tmp.name);self.src=self.ws/'source.json';self.src.write_text('{"records":[]}')
  self.n=NotebookService(self.ws/'book.sqlite3',self.src,self.ws)
 def meta(self,**kw):return dict(start='2026-10-14',end='2026-10-14',participants=['服务对象甲'],organizations=['他山协会'],**kw)
 def message(self,ids=[]):return self.n.append_record({'text':'工作记录：材料已交，不等于付款完成','objectIds':ids,'actor':{'name':'秘书','kind':'ai'},'sourceRefs':[{'sourceId':'wechat:mine','nativeId':'real-1','sender':'服务对象甲','at':'2026-10-15','precision':'date'}]})
 def body(self,m,**kw):return dict(expectedRecordHash=self.n.work_record_hash(m),work=self.meta(),requestId='MERGE-'+m['id'],**kw)
 def test_direct_completed_preserves_record_and_idempotent(self):
  m=self.message();before=self.n.changes()['cursor'];b=self.body(m,task={'title':'交回本轮材料','state':'已完成','assignee':'服务对象甲','domain':'他山'})
  x=self.n.integrate_work_record(m['id'],b);t=x['task'];r=self.n.record_detail(m['id'])
  for key in ['id','text','at','actor','sourceRefs','receipts','processing']:self.assertEqual(r[key],m[key])
  self.assertEqual(r['objectIds'],[t['id']]);self.assertEqual(t['state'],'已完成');self.assertFalse(t['needsReview'])
  self.assertEqual(self.n.integrate_work_record(m['id'],b)['task']['id'],t['id']);self.assertEqual(len(self.n.list_tasks()),1)
  ops=self.n.changes(before)['operations'];self.assertEqual(len(ops),1);self.assertEqual({e['kind'] for e in ops[0]['effects']},{'object','record'})
  self.assertEqual(self.n.as_of(sequence=before)['records'][0]['objectIds'],[])
 def test_linked_progress_does_not_complete_parent_and_groups_one_row(self):
  t=self.n.create_task({'title':'做完一期活动','state':'待办','assignee':'待定'});m=self.message([t['id']]);b=self.body(m,objectId=t['id'],expectedRevision=t['revision']+1)
  self.n.integrate_work_record(m['id'],b)
  self.n.record(t['id'],{'expectedRevision':self.n.get_task(t['id'])['revision'],'note':'今天又补一张表','work':self.meta()})
  q=self.n.query_work(start='2026-10-14',end='2026-10-14',person='服务对象甲',organization='他山协会')
  self.assertEqual(len(q['objects']),1);self.assertEqual(len(q['objects'][0]['workEntries']),2);self.assertEqual(q['objects'][0]['state'],'待办')
  self.assertEqual(len(self.n.query_work(start='2026-10-15',end='2026-10-15')['objects']),0)
  self.assertEqual(len(self.n.query_work(person='秘书')['objects']),0)
 def test_stale_record_or_object_never_applied(self):
  t=self.n.create_task({'title':'已完成原交付','state':'已完成'});m=self.message([t['id']]);b=self.body(m,objectId=t['id'],expectedRevision=1)
  with self.assertRaises(ConflictError):self.n.integrate_work_record(m['id'],b)
  b['expectedRevision']=self.n.get_task(t['id'])['revision'];b['expectedRecordHash']='0'*64
  with self.assertRaises(ConflictError):self.n.integrate_work_record(m['id'],b)
  self.assertNotIn('work',self.n.record_detail(m['id']))
 def test_unrelated_or_duplicate_task_rejected(self):
  t=self.n.create_task({'title':'原事项'});m=self.message([t['id']])
  with self.assertRaises(ValidationError):self.n.integrate_work_record(m['id'],self.body(m,task={'title':'复制成第二份','state':'已完成'}))
 def test_ranges_unknown_and_business_time_separate_from_save(self):
  m=self.n.append_record({'text':'周内值日完成','work':{'start':'2026-10-20','end':'2026-10-26','participants':['肖明辉'],'organizations':['软物质组']},'objectIds':[self.n.create_task({'title':'本周值日','state':'已完成'})['id']]})
  self.assertEqual(len(self.n.query_work(start='2026-10-22',end='2026-10-22')['objects']),1)
  self.assertEqual(m['work']['start'],'2026-10-20')
  for work in [{'start':'2026-10-20','end':'2026-10-19'}, {'participants':['秘书']*101}, {'start':'bad'}, {'secret':'x'}]:
   with self.assertRaises(ValidationError):self.n.append_record({'text':'bad','work':work})
 def test_atomic_new_work_requires_link_and_not_raw_input_conversion(self):
  with self.assertRaises(ValidationError):self.n.append_record({'text':'全局备忘','work':self.meta()})
  m=self.message();b=self.body(m,task={'title':'不准伪造未完成','state':'待办'})
  with self.assertRaises(ValidationError):self.n.integrate_work_record(m['id'],b)
  self.assertEqual(len(self.n.list_tasks()),0)
 def test_restart_and_unknown_date_never_use_commit_day(self):
  t=self.n.create_task({'title':'不确定日期的材料','state':'已完成'})
  self.n.append_record({'text':'只知道已交','objectIds':[t['id']],'work':{'participants':[],'organizations':[]}})
  self.assertEqual(len(self.n.query_work()['objects']),1)
  self.assertEqual(len(self.n.query_work(start='2026-10-01',end='2026-10-31')['objects']),0)
  self.assertEqual(len(self.n.query_work(person='待定',organization='待定')['objects']),1)
  before=self.n.changes()['cursor'];NotebookService(self.n.db_file,self.src,self.ws)
  self.assertEqual(self.n.changes()['cursor'],before)
 def test_same_request_with_changed_meaning_rejected(self):
  m=self.message();b=self.body(m,task={'title':'交材料','state':'已完成'})
  self.n.integrate_work_record(m['id'],b)
  with self.assertRaises(ValidationError):self.n.integrate_work_record(m['id'],dict(b,work={'start':'2026-10-15'}))
 def test_pagination_rejects_changed_snapshot(self):
  for i in range(3):
   t=self.n.create_task({'title':str(i),'state':'已完成'});self.n.append_record({'text':'交付','objectIds':[t['id']],'work':self.meta()})
  q=self.n.query_work(limit=1);self.assertTrue(q['hasMore'])
  q2=self.n.query_work(limit=1,cursor=q['cursor'],snapshot=q['snapshot']);self.assertNotEqual(q['objects'][0]['id'],q2['objects'][0]['id'])
  t=q['objects'][0];self.n.record(t['id'],{'expectedRevision':t['revision'],'note':'新信息'})
  with self.assertRaises(ConflictError):self.n.query_work(limit=1,cursor=q['cursor'],snapshot=q['snapshot'])

 def test_model_can_record_completed_result_without_pending_precursor(self):
  from modules.secretary.service import SecretaryService,SecretaryValidationError
  fields={'title':'直接已交材料','state':'已完成','assignee':'服务对象甲','note':'已交，不代表已付','proposedAt':None,'work':self.meta()}
  self.assertEqual(SecretaryService._fields(fields,create=True)['state'],'已完成')
  with self.assertRaises(SecretaryValidationError):SecretaryService._fields({'title':'没有依据的完成','state':'已完成'},create=True)
 def test_explicit_attach_unlinked_record_to_existing_does_not_duplicate(self):
  t=self.n.create_task({'title':'补交完整材料','state':'待办'});m=self.message()
  self.n.integrate_work_record(m['id'],self.body(m,objectId=t['id'],expectedRevision=t['revision']))
  self.assertEqual(len(self.n.list_tasks()),1);self.assertEqual(self.n.get_task(t['id'])['state'],'待办')

 def test_secretary_work_summary_is_not_presented_as_original_quote(self):
  t=self.n.create_task({'title':'本轮已交','state':'已完成'});m=self.message([t['id']])
  evidence=self.n.get_task(t['id'])['evidence'];self.assertEqual(evidence[0].get('evidenceKind'),'summary')
