"""One committed operation across object, occurrence, review and input effects.

Additive migration establishes a truthful baseline. Earlier history stays in old
ledgers; we never invent pre-migration snapshots or backdate late source input.
"""
import json,uuid,hashlib,base64
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from contracts import actor,text,TIMEZONE
from .legacy_store import stamp,validate_id,ValidationError,ConflictError

_context=ContextVar('notebook_transaction',default=None)
def enc(x):return json.dumps(x,ensure_ascii=False,separators=(',',':'))

def instant(v):
 if not isinstance(v,str) or len(v)>60:raise ValidationError('查询时间无效')
 try:
  d=datetime.fromisoformat(v.replace('Z','+00:00'))
  if d.tzinfo is None:raise ValueError()
  return d
 except ValueError:raise ValidationError('须提供带时区的提交时间') from None

class JournalMixin:
 def _init_journal(self):
  self._journal_ready=False
  with self._connect() as db:
   db.executescript('''
    CREATE TABLE IF NOT EXISTS notebook_operations(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,at TEXT NOT NULL,actor TEXT NOT NULL,request_id TEXT);
    CREATE TABLE IF NOT EXISTS notebook_effects(operation_id TEXT NOT NULL,kind TEXT NOT NULL,id TEXT NOT NULL,before_value TEXT,after_value TEXT,PRIMARY KEY(operation_id,kind,id));
    CREATE INDEX IF NOT EXISTS notebook_effect_entity ON notebook_effects(kind,id);
    CREATE TABLE IF NOT EXISTS notebook_operation_links(operation_id TEXT NOT NULL,ledger TEXT NOT NULL,event_id TEXT NOT NULL,PRIMARY KEY(ledger,event_id));
    CREATE TABLE IF NOT EXISTS notebook_baseline(kind TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(kind,id));
    CREATE TABLE IF NOT EXISTS notebook_journal_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS notebook_presentations(id TEXT PRIMARY KEY,object_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL);
   ''')
   db.execute('BEGIN IMMEDIATE')
   if not db.execute("SELECT 1 FROM notebook_journal_meta WHERE key='baseline'").fetchone():
    ids=[r[0] for r in db.execute('SELECT id FROM tasks UNION SELECT id FROM local_items UNION SELECT id FROM local_objects')]
    for rid in ids:db.execute('INSERT INTO notebook_baseline VALUES(?,?,?)',('object',rid,enc(self._decorate_review(self._current(rid,db),db))))
    for r in db.execute('SELECT id,payload FROM notebook_presentations').fetchall():db.execute('INSERT INTO notebook_baseline VALUES(?,?,?)',('presentation',r[0],r[1]))
    for r in db.execute('SELECT id,payload FROM schedule_entries').fetchall():db.execute('INSERT INTO notebook_baseline VALUES(?,?,?)',('schedule',r[0],r[1]))
    for r in db.execute('SELECT * FROM local_records').fetchall():db.execute('INSERT INTO notebook_baseline VALUES(?,?,?)',('record',r['id'],enc(self._record_row(r))))
    db.execute('INSERT INTO notebook_journal_meta VALUES(?,?)',('baseline',enc({'at':stamp(),'sequence':0,'earlierHistory':'旧时间线保留；迁移前状态快照未知'})))

  self._journal_ready=True

 @contextmanager
 def _transaction(self,a,key=None):
  with self._connect() as db:
   db.execute('BEGIN IMMEDIATE');token=_context.set({'service':self,'db':db,'id':None,'actor':a,'requestId':key})
   try:yield db
   finally:_context.reset(token)

 def _audit(self,db,kind,rid,before,after):
  ctx=_context.get()
  if not ctx or ctx['service'] is not self or ctx['db'] is not db:return None
  if ctx['id'] is None:
   ctx['id']='OP-'+uuid.uuid4().hex
   db.execute('INSERT INTO notebook_operations(id,at,actor,request_id) VALUES(?,?,?,?)',(ctx['id'],stamp(),enc(ctx['actor']),ctx['requestId']))
  db.execute('INSERT INTO notebook_effects VALUES(?,?,?,?,?) ON CONFLICT(operation_id,kind,id) DO UPDATE SET after_value=excluded.after_value',
   (ctx['id'],kind,rid,enc(before) if before is not None else None,enc(after) if after is not None else None))
  return ctx['id']

 def _link_operation(self,db,ledger,event_id):
  ctx=_context.get()
  if ctx and ctx['service'] is self and ctx['db'] is db and ctx['id']:
   db.execute('INSERT INTO notebook_operation_links VALUES(?,?,?)',(ctx['id'],ledger,event_id))

 def _operation(self,db,row):
  return dict(id=row['id'],sequence=row['seq'],at=row['at'],actor=json.loads(row['actor']),requestId=row['request_id'],records=[dict(ledger=x['ledger'],id=x['event_id']) for x in db.execute('SELECT * FROM notebook_operation_links WHERE operation_id=?',(row['id'],))],
   effects=[dict(kind=e['kind'],id=e['id'],before=json.loads(e['before_value']) if e['before_value'] else None,
    after=json.loads(e['after_value']) if e['after_value'] else None) for e in db.execute('SELECT * FROM notebook_effects WHERE operation_id=? ORDER BY kind,id',(row['id'],))])

 def changes(self,cursor=0,limit=100,*,object_id=None,author=None,start=None,end=None):
  if type(cursor) is not int or cursor<0 or type(limit) is not int or not 1<=limit<=500:raise ValidationError('游标/页大小无效')
  if object_id is not None:validate_id(object_id)
  if author is not None:text(author,'记录人',120)
  s=instant(start) if start else None;e=instant(end) if end else None
  if s and e and s>=e:raise ValidationError('结束时间须晚于开始时间')
  with self._connect() as db:
   db.execute('BEGIN')
   high=db.execute('SELECT COALESCE(MAX(seq),0) FROM notebook_operations').fetchone()[0]
   if cursor>high:raise ValidationError('游标超出当前提交范围')
   matches=[]
   for r in db.execute('SELECT * FROM notebook_operations WHERE seq>? AND seq<=? ORDER BY seq',(cursor,high)):
    at=instant(r['at'])
    if s and at<s or e and at>=e:continue
    if author and json.loads(r['actor'])['name']!=author:continue
    op=self._operation(db,r)
    if object_id and not any(x['id']==object_id or (x.get('after') or x.get('before') or {}).get('objectId')==object_id or any(object_id in (x.get(side) or {}).get('objectIds',[]) for side in ('before','after')) for x in op['effects']):continue
    matches.append(op)
    if len(matches)>limit:break
   more=len(matches)>limit;items=matches[:limit]
   return dict(operations=items,cursor=items[-1]['sequence'] if more else high,hasMore=more,highWatermark=high,timezone=TIMEZONE,
    coverage=json.loads(db.execute("SELECT value FROM notebook_journal_meta WHERE key='baseline'").fetchone()[0]))

 def as_of(self,*,sequence=None,at=None):
  if sequence is not None and (type(sequence) is not int or sequence<0):raise ValidationError('历史提交序号无效')
  if sequence is not None and at is not None:raise ValidationError('序号和时点只能选一个')
  cutoff=instant(at) if at else None
  with self._connect() as db:
   db.execute('BEGIN')
   baseline=json.loads(db.execute("SELECT value FROM notebook_journal_meta WHERE key='baseline'").fetchone()[0])
   if cutoff and cutoff<instant(baseline['at']):raise ValidationError('该时点早于可回看迁移基线；此前请查看原时间线')
   high=db.execute('SELECT COALESCE(MAX(seq),0) FROM notebook_operations').fetchone()[0]
   if sequence is not None and sequence>high:raise ValidationError('历史序号超出当前提交范围')
   values={(r['kind'],r['id']):json.loads(r['payload']) for r in db.execute('SELECT * FROM notebook_baseline')}
   last=0
   for row in db.execute('SELECT * FROM notebook_operations ORDER BY seq'):
    if sequence is not None and row['seq']>sequence or cutoff and instant(row['at'])>cutoff:break
    last=row['seq']
    for effect in db.execute('SELECT * FROM notebook_effects WHERE operation_id=?',(row['id'],)):
     key=(effect['kind'],effect['id'])
     if effect['after_value'] is None:values.pop(key,None)
     else:values[key]=json.loads(effect['after_value'])
   receipts=[v for (k,i),v in values.items() if k=='followupReceipt']
   for (kind,rid),obj in values.items():
    if kind=='object':
     from .reviews import followup_key
     if any(r.get('objectId')==rid and r.get('followupKey')==followup_key(obj) for r in receipts):obj['followupDue']=False
   return dict(followupReceipts=receipts,objects=[v for (k,i),v in values.items() if k=='object'],schedules=[v for (k,i),v in values.items() if k=='schedule'],
    records=[v for (k,i),v in values.items() if k=='record'],presentations=[v for (k,i),v in values.items() if k=='presentation'],sequence=last,coverage=baseline)

 def restore_preview(self,rid,*,sequence,fields):
  from .service import PATCH_FIELDS
  if not isinstance(fields,list) or not fields or len(fields)>30 or len(set(fields))!=len(fields) or set(fields)-PATCH_FIELDS or set(fields)&{'needsReview','sources'}:raise ValidationError('请选择允许恢复的显式字段')
  current=self.get_task(rid);past=next((x for x in self.as_of(sequence=sequence)['objects'] if x['id']==rid),None)
  if not past:raise ValidationError('该历史时点没有此对象')
  patch={f:past.get(f) for f in fields if current.get(f)!=past.get(f)}
  if 'sourceContacts' in patch:
   from contracts.source_refs import FIELDS
   normalized=[]
   for ref in patch['sourceContacts'] or []:
    row={k:v for k,v in ref.items() if k in FIELDS and v is not None}
    if not row.get('conversation') and ref.get('conversationName'):row['conversation']=ref['conversationName']
    if not row.get('sender') and ref.get('senderName'):row['sender']=ref['senderName']
    if not row.get('sourceId') or not (row.get('recordId') or row.get('nativeId')):raise ValidationError('该旧来源没有可恢复的稳定身份；请选择其他字段，原来源仍保留')
    normalized.append(row)
   patch['sourceContacts']=normalized
  # Same validation as ordinary writes; do not bypass locators or relations.
  self._validate(dict(patch,expectedRevision=current['revision']))
  return dict(objectId=rid,sequence=sequence,expectedRevision=current['revision'],changes={f:{'before':current.get(f),'after':v} for f,v in patch.items()},patch=patch)

 def restore(self,rid,body):
  if not isinstance(body,dict) or set(body)-{'sequence','fields','expectedRevision','requestId','actor','note'}:raise ValidationError('恢复参数无效')
  canon=self._canonical('restore',rid,body)
  with self._connect() as db:
   if self._retry(db,body.get('requestId'),canon):return self._current(rid,db)
  preview=self.restore_preview(rid,sequence=body.get('sequence'),fields=body.get('fields'))
  if preview['expectedRevision']!=body.get('expectedRevision'):raise ConflictError('恢复预览后事项有新变化，请重新预览')
  return self.record(rid,dict(preview['patch'],**({'requestId':body['requestId']} if body.get('requestId') is not None else {}),expectedRevision=body['expectedRevision'],actor=body.get('actor'),
   note=body.get('note') or '恢复历史字段（提交序号 '+str(body['sequence'])+'）；后续记录保留'),_canonical_override=canon)

 def query_objects(self,**filters):
  allowed={'kind','state','domain','assignee','counterparty','start','end','keyword','cursor','limit'}
  if set(filters)-allowed:raise ValidationError('查询字段无效')
  from contracts import day,state,KINDS,DOMAINS
  f=dict(filters);limit=f.pop('limit',100);cursor=f.pop('cursor',0)
  if type(limit) is not int or not 1<=limit<=500:raise ValidationError('分页大小无效')
  if cursor not in (0,None) and (not isinstance(cursor,str) or len(cursor)>512):raise ValidationError('分页游标无效')
  if f.get('kind') and f['kind'] not in KINDS:raise ValidationError('性质无效')
  if f.get('state'):f['state']=state(f['state'])
  if f.get('domain') and f['domain'] not in DOMAINS:raise ValidationError('归属无效')
  for name in ('assignee','counterparty','keyword'):
   if name in f:text(f[name],name,1000,empty=True)
  start=day(f.get('start'));end=day(f.get('end'))
  if start and end and start>end:raise ValidationError('日期范围无效')
  tasks=[]
  for t in self.list_tasks():
   if any(v and t.get(k)!=v for k,v in f.items() if k in ('kind','state','domain','assignee')):continue
   if f.get('counterparty') and f['counterparty'] not in t.get('counterparty',''):continue
   date=t.get('planDate')
   if start and (not date or date<start) or end and (not date or date>end):continue
   if f.get('keyword') and f['keyword'].casefold() not in json.dumps(self.detail(t['id']),ensure_ascii=False).casefold():continue
   tasks.append(t)
  tasks.sort(key=lambda t:t['id'])
  with self._connect() as db:high=db.execute('SELECT COALESCE(MAX(seq),0) FROM notebook_operations').fetchone()[0]
  signature=hashlib.sha256(enc([f,limit,high,[(t['id'],t['revision']) for t in tasks]]).encode()).hexdigest()
  offset=0
  if cursor:
   try:
    value=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)));offset=value['offset']
    if value['signature']!=signature or type(offset) is not int or not 0<=offset<=len(tasks):raise ValueError()
   except (ValueError,KeyError,TypeError,UnicodeError):raise ConflictError('分页快照已变化，请从第一页重新读取') from None
  page=tasks[offset:offset+limit];next_offset=offset+len(page)
  next_cursor=base64.urlsafe_b64encode(enc(dict(signature=signature,offset=next_offset)).encode()).decode().rstrip('=') if next_offset<len(tasks) else None
  return dict(objects=page,nextCursor=next_cursor,total=len(tasks),snapshot=signature,highWatermark=high,pagination='snapshot-bound; rejects changes')
