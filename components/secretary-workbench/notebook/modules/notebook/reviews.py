"""Versioned presentation and explicit follow-up metadata, without a timer or AI."""
import hashlib,json,uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from contracts import actor,text,day,CLOSED,TIMEZONE,today
from .legacy_store import stamp,validate_id,ValidationError,ConflictError

def followup(value):
 if value is None:return None
 if not isinstance(value,dict) or set(value)-{'date','at','condition','remindEvenUnchanged'}:raise ValidationError('复看字段无效')
 d=day(value.get('date'));at=value.get('at');condition=text(value.get('condition',''),'复看条件',2000,empty=True)
 if at:
  from .journal import instant
  parsed=instant(at).astimezone(ZoneInfo(TIMEZONE))
  if d and d!=parsed.date().isoformat():raise ValidationError('复看日期与时刻不一致')
  d=parsed.date().isoformat();at=parsed.isoformat()
 elif at is not None and at!='':raise ValidationError('复看时刻无效')
 flag=value.get('remindEvenUnchanged',True)
 if type(flag) is not bool:raise ValidationError('复看选项无效')
 if not d and not condition:return None
 return dict(date=d,at=at or None,condition=condition,remindEvenUnchanged=flag)

def followup_key(t):
 return hashlib.sha256(json.dumps([t.get('followup'),t.get('reviewDate'),t.get('condition'),t.get('followupSetAt')],sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:32]

class ReviewMixin:
 def _init_reviews(self):
  with self._connect() as db:
   db.execute('CREATE TABLE IF NOT EXISTS notebook_followup_receipts(id TEXT PRIMARY KEY,object_id TEXT NOT NULL,followup_key TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(object_id,followup_key))')
  with self._connect() as db:
   db.execute('CREATE TABLE IF NOT EXISTS notebook_presentations(id TEXT PRIMARY KEY,object_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL)')
   db.execute('BEGIN IMMEDIATE')
   journal=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notebook_journal_meta'").fetchone()
   if journal and db.execute("SELECT 1 FROM notebook_journal_meta WHERE key='baseline'").fetchone():return
   ids=[r[0] for r in db.execute('SELECT id FROM tasks UNION SELECT id FROM local_items UNION SELECT id FROM local_objects')]
   for rid in ids:
    t=self._current(rid,db)
    if t.get('needsReview') and t['kind']=='action' and t['state'] not in CLOSED and not self._latest_presentation(db,rid):
     p=dict(id='PRES-'+hashlib.sha256(('legacy-review|'+rid).encode()).hexdigest()[:32],objectId=rid,version=1,status='pending',at=stamp(),actor={'name':'迁移','kind':'ai'},note='沿用既有未批阅标记；未产生新的秘书建议',acknowledgedAt=None,acknowledgedBy=None,imported=True)
     db.execute('INSERT INTO notebook_presentations VALUES(?,?,?,?)',(p['id'],rid,1,json.dumps(p,ensure_ascii=False)))

 def _latest_presentation(self,db,rid):
  row=db.execute('SELECT payload FROM notebook_presentations WHERE object_id=? ORDER BY version DESC LIMIT 1',(rid,)).fetchone()
  return json.loads(row[0]) if row else None

 def _decorate_review(self,t,db):
  p=self._latest_presentation(db,t['id'])
  if p:
   t['presentation']=p
   t['needsReview']=p['status']=='pending' and t['kind']=='action' and t['state'] not in CLOSED
  t['followupDue']=self._followup_due(t,db)
  return t

 def _followup_due(self,t,db):
  if t['state'] in CLOSED:return False
  f=t.get('followup') or {'date':t.get('reviewDate'),'at':None}
  if not f.get('date') or f['date']>today():return False
  if f.get('at'):
   from .journal import instant
   if instant(f['at'])>datetime.now(ZoneInfo(TIMEZONE)):return False
  return not db.execute('SELECT 1 FROM notebook_followup_receipts WHERE object_id=? AND followup_key=?',(t['id'],followup_key(t))).fetchone()

 def _new_presentation(self,db,rid,a,note=''):
  old=self._latest_presentation(db,rid)
  p=dict(id='PRES-'+uuid.uuid4().hex,objectId=rid,version=(old['version']+1 if old else 1),status='pending',
   at=stamp(),actor=a,note=note,acknowledgedAt=None,acknowledgedBy=None)
  db.execute('INSERT INTO notebook_presentations VALUES(?,?,?,?)',(p['id'],rid,p['version'],json.dumps(p,ensure_ascii=False)))
  self._audit(db,'presentation',p['id'],None,p)
  return p

 def _confirm_presentation(self,db,rid,body,a):
  if not body.get('confirm'):return
  if a['kind']!='human':raise ValidationError('本人批阅确认不能由AI代写')
  p=self._latest_presentation(db,rid)
  if body.get('presentationId') is not None or body.get('presentationVersion') is not None:
   if not p or p['id']!=body.get('presentationId') or p['version']!=body.get('presentationVersion'):raise ConflictError('呈报已更新，请核对本轮建议')
  t=self._current(rid,db)
  if self._followup_due(t,db):
   receipt=dict(id='FOLLOW-'+uuid.uuid4().hex,objectId=rid,followupKey=followup_key(t),at=stamp(),actor=a,note='本人确认本次复看')
   db.execute('INSERT INTO notebook_followup_receipts VALUES(?,?,?,?)',(receipt['id'],rid,receipt['followupKey'],json.dumps(receipt,ensure_ascii=False)))
   self._audit(db,'followupReceipt',receipt['id'],None,receipt)
  if p and p['status']=='pending':
   new=dict(p,status='acknowledged',acknowledgedAt=stamp(),acknowledgedBy=a)
   db.execute('UPDATE notebook_presentations SET payload=? WHERE id=?',(json.dumps(new,ensure_ascii=False),p['id']))
   self._audit(db,'presentation',p['id'],p,new)

 def present(self,rid,body):
  self._assert_writable();validate_id(rid)
  if not isinstance(body,dict) or set(body)-{'expectedRevision','note','recommendation','actor','requestId'}:raise ValidationError('呈报字段无效')
  a=actor(body.get('actor'));v=body.get('expectedRevision');key=body.get('requestId');canon=self._canonical('present',rid,body)
  if type(v) is not int or v<0:raise ValidationError('缺少对象版本')
  note=text(body.get('note',''),'呈报说明',12000,empty=True);patch={'needsReview':True}
  if 'recommendation' in body:patch['recommendation']=self._validate({'recommendation':body['recommendation']})[1]['recommendation']
  with self._transaction(a,key) as db:
   retry=self._retry(db,key,canon)
   if retry:
    r=db.execute('SELECT payload FROM notebook_presentations WHERE id=?',(retry['result_id'],)).fetchone();return json.loads(r[0])
   t=self._current(rid,db)
   if t['revision']!=v:raise ConflictError('事项有新变化，请重新读取')
   if t['kind']!='action' or t['state'] in CLOSED:raise ValidationError('已闭环或非行动对象不产生待批阅')
   self._audit(db,'object',rid,t,t)
   p=self._new_presentation(db,rid,a,note)
   self._append(db,rid,a,patch,note,[],{k:t.get(k) for k in patch})
   self._remember(db,key,canon,'presentation',p['id'])
  return p

 def due_followups(self,date=None,at=None):
  from .journal import instant
  check=instant(at) if at else (datetime.fromisoformat(day(date)+'T23:59:59.999999+08:00') if date else datetime.now(ZoneInfo(TIMEZONE)))
  d=check.astimezone(ZoneInfo(TIMEZONE)).date().isoformat();items=[];unknown=[]
  with self._connect() as db:
   for t in self.list_tasks():
    if t['state'] in CLOSED or not t.get('active',True):continue
    f=t.get('followup') or {'date':t.get('reviewDate'),'at':None,'condition':t.get('condition','')}
    key=followup_key(t)
    if db.execute('SELECT 1 FROM notebook_followup_receipts WHERE object_id=? AND followup_key=?',(t['id'],key)).fetchone():continue
    due=bool(f.get('date') and f['date']<=d and (not f.get('at') or instant(f['at'])<=check))
    item=dict(objectId=t['id'],followupKey=key,followup=f,objectRevision=t['revision'],conditionResult='unknown' if f.get('condition') else None)
    if due:items.append(item)
    elif f.get('condition'):unknown.append(item)
  return dict(items=items,conditionsUnknown=unknown,timezone=TIMEZONE,checkedAt=check.isoformat(),executed=False)

 def acknowledge_followup(self,rid,body):
  self._assert_writable();validate_id(rid)
  if not isinstance(body,dict) or set(body)-{'expectedRevision','followupKey','note','actor','requestId'}:raise ValidationError('复看回执无效')
  a=actor(body.get('actor'));key=body.get('requestId');canon=self._canonical('followup-ack',rid,body)
  note=text(body.get('note',''),'复看回执',12000,empty=True)
  with self._transaction(a,key) as db:
   retry=self._retry(db,key,canon)
   if retry:return json.loads(db.execute('SELECT payload FROM notebook_followup_receipts WHERE id=?',(retry['result_id'],)).fetchone()[0])
   t=self._current(rid,db)
   if type(body.get('expectedRevision')) is not int or t['revision']!=body['expectedRevision'] or followup_key(t)!=body.get('followupKey'):raise ConflictError('复看约定或对象已变化')
   if db.execute('SELECT 1 FROM notebook_followup_receipts WHERE object_id=? AND followup_key=?',(rid,body['followupKey'])).fetchone():raise ConflictError('本次复看已有回执')
   r=dict(id='FOLLOW-'+uuid.uuid4().hex,objectId=rid,followupKey=body['followupKey'],at=stamp(),actor=a,note=note)
   db.execute('INSERT INTO notebook_followup_receipts VALUES(?,?,?,?)',(r['id'],rid,r['followupKey'],json.dumps(r,ensure_ascii=False)))
   self._audit(db,'followupReceipt',r['id'],None,r);self._remember(db,key,canon,'followupReceipt',r['id'])
  return r
