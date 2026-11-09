"""Business-time views of the SAME notebook objects; original notes remain evidence."""
import hashlib,json
from zoneinfo import ZoneInfo
from contracts import day,text,actor,TIMEZONE
from .legacy_store import ValidationError,ConflictError,validate_id,stamp

from contracts.work import work_metadata

class WorkMixin:
 @staticmethod
 def work_record_hash(record):
  return hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

 def integrate_work_record(self,rid,body):
  """Explicit, CAS-protected promotion. Never infer work from a raw message."""
  self._assert_writable();validate_id(rid)
  allowed={'expectedRecordHash','work','objectId','expectedRevision','task','actor','requestId'}
  if not isinstance(body,dict) or set(body)-allowed or not body.get('requestId'):raise ValidationError('并入参数无效')
  if ('objectId' in body)==('task' in body):raise ValidationError('请选择原事项或独立已完成事项')
  work=work_metadata(body.get('work'));a=actor(body.get('actor'));key=body['requestId'];validate_id(key)
  canon=self._canonical('integrate-work',rid,body)
  with self._transaction(a,key) as db:
   retry=self._retry(db,key,canon)
   if retry:return {'task':self._current(retry['result_id'],db),'record':self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone())}
   old=self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone())
   if body.get('expectedRecordHash')!=self.work_record_hash(old):raise ConflictError('原记录已变化，需重新预览')
   if old.get('work') is not None:raise ValidationError('该记录已并入；请勿重复建事项')
   if 'task' in body:
    if old['objectIds']:raise ValidationError('已有事项关联，不得复制成第二份')
    task=body['task']
    if not isinstance(task,dict) or set(task)-{'title','state','assignee','domain','counterparty','completionCriterion','relatedRecordIds'} or task.get('state')!='已完成':raise ValidationError('独立结果须直接建已完成事项')
    task=dict(task,actor=a,requestId=key,assignee=task.get('assignee') or '待定',proposedAt=None)
    _,p,note,sources=self._validate(task,True)
    t=self._create_task(db,task,a,p,note,sources);oid=t['id'];refs=[oid]
   else:
    oid=validate_id(body['objectId']);t=self._current(oid,db)
    if old['objectIds'] and oid not in old['objectIds']:raise ValidationError('不能替换原事项关联；其他更正请单独记录')
    if type(body.get('expectedRevision')) is not int or body['expectedRevision']!=t['revision']:raise ConflictError('事项已变化')
    refs=old['objectIds'] or [oid]
   db.execute('UPDATE local_records SET object_ids=?,work=? WHERE id=?',(json.dumps(refs),json.dumps(work,ensure_ascii=False),rid))
   updated=self._record_row(db.execute('SELECT * FROM local_records WHERE id=?',(rid,)).fetchone())
   self._audit(db,'record',rid,old,updated)
   # Record linkage is visible in every affected object's revision, never its business state.
   for linked in refs:
    current=self._current(linked,db)
    self._append(db,linked,a,{'updatedAt':stamp()},None,[],{'updatedAt':current.get('updatedAt')})
   self._remember(db,key,canon,'task',oid)
  return {'task':self.get_task(oid),'record':self.record_detail(rid)}

 def query_work(self,*,start=None,end=None,person='',organization='',keyword='',cursor=0,limit=100,snapshot=''):
  start=day(start);end=day(end)
  if start and end and start>end:raise ValidationError('结束日期早于开始日期')
  if type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=500:raise ValidationError('页大小/游标无效')
  for v in (person,organization,keyword):text(v,'筛选',1000,empty=True)
  # A single SQLite read snapshot keeps grouped notes and current objects consistent.
  with self._connect() as db:
   db.execute('BEGIN');grouped={};people=set();orgs=set()
   def include(ids,entry):
    w=entry['work'];people.update(w['participants']);orgs.update(w['organizations'])
    if start and (not w['end'] or w['end']<start) or end and (not w['start'] or w['start']>end):return
    if person and person not in (w['participants'] or ['待定']):return
    if organization and organization not in (w['organizations'] or ['待定']):return
    for oid in ids:grouped.setdefault(oid,[]).append(entry)
   for row in db.execute('SELECT * FROM local_records WHERE work IS NOT NULL'):
    r=self._record_row(row)
    include(r['objectIds'],dict(id=r['id'],body=r['text'],at=r['at'],actor=r['actor'],work=r['work'],sourceRefs=r['sourceRefs'],attachments=r['attachments']))
   for row in db.execute('SELECT * FROM local_changes ORDER BY seq'):
    p=json.loads(row['payload'])
    if p.get('work'):include([row['id']],dict(id=row['event_id'],body=p.get('note',''),at=row['at'],actor=json.loads(row['actor']),work=p['work'],sources=p.get('sources',[]),sourceTime=p.get('sourceTime')))
   objects=[]
   for oid,entries in grouped.items():
    t=self._decorate_review(self._current(oid,db),db)
    entries.sort(key=lambda e:(e['work']['end'] or '',e['work']['start'] or '',e['id']),reverse=True)
    if keyword and keyword.casefold() not in '\n'.join([t['title'],t.get('summary',''),*(e['body'] for e in entries)]).casefold():continue
    objects.append(dict(t,workEntries=entries,workParticipants=sorted({x for e in entries for x in e['work']['participants']}),workOrganizations=sorted({x for e in entries for x in e['work']['organizations']})))
   objects.sort(key=lambda t:(t['workEntries'][0]['work']['end'] or '',t['id']),reverse=True)
   signature=hashlib.sha256(json.dumps([start,end,person,organization,keyword,limit,objects],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
   if cursor and snapshot!=signature:raise ConflictError('工作分页已变化，请从第一页重读')
   return dict(snapshot=signature,objects=objects[cursor:cursor+limit],cursor=cursor+min(limit,max(0,len(objects)-cursor)),hasMore=cursor+limit<len(objects),total=len(objects),people=sorted(people),organizations=sorted(orgs),timezone=TIMEZONE)
