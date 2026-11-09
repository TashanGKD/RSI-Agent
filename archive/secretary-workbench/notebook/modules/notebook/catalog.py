"""Minimal online source directory. No source bodies, media or credentials."""
import json,re
from contracts import text,actor
from contracts.source_refs import source_refs
from .legacy_store import ValidationError,ConflictError,stamp

class CatalogMixin:
 def _init_catalog(self):
  with self._connect() as db:db.execute('CREATE TABLE IF NOT EXISTS notebook_source_catalog(source_id TEXT PRIMARY KEY,payload TEXT NOT NULL)')
 def source_catalog(self):
  with self._connect() as db:known={r[0]:json.loads(r[1]) for r in db.execute('SELECT * FROM notebook_source_catalog')}
  for task in self.list_tasks():
   for ref in task.get('sourceContacts',[]):
    sid=ref.get('sourceId')
    if not sid or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}:[A-Za-z0-9_-]{1,64}',sid):continue
    known.setdefault(sid,dict(id=sid,type=sid.split(':')[0],accountId=sid.split(':')[1],displayName=sid,status='not_connected',revision=0,
     coverage={'upstreamComplete':False},gaps=[{'code':'metadata_only','detail':'仅有事项来源定位；未同步读取覆盖与检查点。'}],capabilities={'liveRefresh':False}))
  return [known[k] for k in sorted(known)]
 def update_source_catalog(self,body):
  self._assert_writable()
  allowed={'sourceId','displayName','status','snapshot','recordCount','lastRetrievedAt','lastReadAt','lastAppliedAt','gaps','expectedRevision','requestId','actor'}
  if not isinstance(body,dict) or set(body)-allowed:raise ValidationError('信源目录字段无效；禁止上传原始资料')
  sid=body.get('sourceId');source_refs([{'sourceId':sid,'recordId':'catalog-validation'}])
  a=actor(body.get('actor'));key=body.get('requestId');canon=self._canonical('source-catalog',sid,body)
  if type(body.get('expectedRevision')) is not int or body['expectedRevision']<0:raise ValidationError('缺少目录版本')
  payload={}
  for k in ('displayName','snapshot'):
   if k in body:payload[k]=text(body[k],k,256)
  if 'status' in body:
   if body['status'] not in ('cached_only','not_connected','unavailable','partial'):raise ValidationError('目录不能宣称已连接未验证的上游')
   payload['status']=body['status']
  if 'recordCount' in body:
   if type(body['recordCount']) is not int or not 0<=body['recordCount']<=10**9:raise ValidationError('目录数量无效')
   payload['recordCount']=body['recordCount']
  for k in ('lastRetrievedAt','lastReadAt','lastAppliedAt'):
   if k in body:
    from .journal import instant
    if body[k] is not None:instant(body[k])
    payload[k]=body[k]
  if 'gaps' in body:
   if not isinstance(body['gaps'],list) or len(body['gaps'])>20:raise ValidationError('缺口清单无效')
   payload['gaps']=[]
   for gap in body['gaps']:
    if not isinstance(gap,dict) or set(gap)!={'code','detail'}:raise ValidationError('缺口字段无效')
    payload['gaps'].append({'code':text(gap['code'],'缺口代码',100),'detail':text(gap['detail'],'缺口说明',500)})
  with self._transaction(a,key) as db:
   retry=self._retry(db,key,canon)
   r=db.execute('SELECT payload FROM notebook_source_catalog WHERE source_id=?',(sid,)).fetchone();old=json.loads(r[0]) if r else None
   if retry:return old
   if body['expectedRevision']!=(old or {}).get('revision',0):raise ConflictError('信源目录有新版本')
   value=dict(old or {},**payload,id=sid,type=sid.split(':')[0],accountId=sid.split(':')[1],revision=body['expectedRevision']+1,updatedAt=stamp(),
    coverage={'recordCount':payload.get('recordCount',(old or {}).get('recordCount')),'upstreamComplete':False},capabilities={'liveRefresh':False})
   db.execute('INSERT INTO notebook_source_catalog VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET payload=excluded.payload',(sid,json.dumps(value,ensure_ascii=False)))
   self._audit(db,'sourceCatalog',sid,old,value);self._remember(db,key,canon,'sourceCatalog',sid)
  return value
