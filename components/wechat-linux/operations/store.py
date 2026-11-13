import os,stat,json,sqlite3,time,secrets,hmac,hashlib
from pathlib import Path
from contextlib import contextmanager
from .contract import validate_job,ident,digest

ACTIVE=('preparing','awaiting_confirmation','confirmed','executing','unknown','needs_attention','needs_assistance')
TERMINAL=('succeeded','failed','cancelled','expired')
class Conflict(ValueError):pass
def private_root(root):
 root=Path(root).absolute()
 for p in [root,*root.parents]:
  if p.is_symlink():raise ValueError('symlink state path refused')
 root.mkdir(parents=True,exist_ok=True,mode=0o700)
 s=root.stat()
 if s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('owner-only state directory required')
 return root
class Store:
 def __init__(self,root):
  self.root=private_root(root);p=self.root/'queue.sqlite'
  if p.is_symlink():raise ValueError('symlink database refused')
  fd=os.open(p,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);s=os.fstat(fd);os.close(fd)
  if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077:raise ValueError('private regular database required')
  self.c=sqlite3.connect(p,timeout=15,isolation_level=None);self.c.row_factory=sqlite3.Row
  self.c.execute('PRAGMA busy_timeout=15000');self.c.execute('PRAGMA synchronous=FULL')
  self.c.executescript('CREATE TABLE IF NOT EXISTS jobs(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,client TEXT NOT NULL,request_id TEXT NOT NULL,body TEXT NOT NULL,hash TEXT NOT NULL,state TEXT NOT NULL,preview TEXT,token TEXT,expires REAL,result TEXT,created REAL NOT NULL,updated REAL NOT NULL,UNIQUE(client,request_id));CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,at REAL NOT NULL,state TEXT NOT NULL,detail TEXT);')
  self.c.executescript('BEGIN IMMEDIATE;CREATE TABLE IF NOT EXISTS dispatch_batches(client TEXT NOT NULL,batch_id TEXT NOT NULL,hash TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(client,batch_id));CREATE TABLE IF NOT EXISTS dispatch_metadata(job_id TEXT PRIMARY KEY,spec TEXT NOT NULL,hash TEXT NOT NULL);CREATE TABLE IF NOT EXISTS dispatch_supersessions(client TEXT NOT NULL,request_id TEXT NOT NULL,replacement_id TEXT NOT NULL,created REAL NOT NULL,PRIMARY KEY(client,request_id));CREATE INDEX IF NOT EXISTS events_job_state_at ON events(job_id,state,at);COMMIT;')
 def close(self):self.c.close()
 @contextmanager
 def tx(self):
  self.c.execute('BEGIN IMMEDIATE')
  try:yield;self.c.execute('COMMIT')
  except BaseException:self.c.execute('ROLLBACK');raise
 def event(self,jid,state,detail=None):self.c.execute('INSERT INTO events(job_id,at,state,detail) VALUES(?,?,?,?)',(jid,time.time(),state,json.dumps(detail,ensure_ascii=False) if detail else None))
 def decoded(self,r):
  if not r:return None
  x=dict(r);body=json.loads(x.pop('body'));x.update(body);x.pop('hash');token=x.pop('token');x['confirmation_token']=token if x['state']=='awaiting_confirmation' else None
  for k in ('preview','result'):x[k]=json.loads(x[k]) if x.get(k) else None
  meta=self.c.execute('SELECT spec,hash FROM dispatch_metadata WHERE job_id=?',(x['id'],)).fetchone()
  if meta:
   from .dispatch import decode_spec
   x['dispatch']=decode_spec(meta)
  return x
 def submit(self,body):
  body=validate_job(body);sha=digest(body);now=time.time()
  with self.tx():
   old=self.c.execute('SELECT * FROM jobs WHERE client=? AND request_id=?',(body['client'],body['request_id'])).fetchone()
   if old:
    if old['hash']!=sha:raise Conflict('request ID already has different target or content')
    return self.decoded(old)
   if self.c.execute('SELECT 1 FROM dispatch_supersessions WHERE client=? AND request_id=?',(body['client'],body['request_id'])).fetchone():raise Conflict('request explicitly superseded before admission')
   from .owner_prefix import check_new
   check_new(self.root,body)
   if self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]>=10000:raise ValueError('queue receipt quota reached')
   jid=secrets.token_hex(16);self.c.execute('INSERT INTO jobs(id,client,request_id,body,hash,state,created,updated) VALUES(?,?,?,?,?,?,?,?)',(jid,body['client'],body['request_id'],json.dumps(body,ensure_ascii=False),sha,'queued',now,now));self.event(jid,'queued')
  return self.get(body['client'],body['request_id'])
 def get(self,client,rid):
  ident(client);ident(rid);r=self.c.execute('SELECT * FROM jobs WHERE client=? AND request_id=?',(client,rid)).fetchone()
  if not r:raise KeyError('no request for this client')
  return self.decoded(r)
 def by_id(self,jid):return self.decoded(self.c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone())
 def list_jobs(self,client=None,limit=100):
  if type(limit) is not int or not 1<=limit<=1000:raise ValueError('list limit')
  if client:ident(client)
  rows=self.c.execute('SELECT * FROM jobs '+('WHERE client=? ' if client else '')+'ORDER BY seq LIMIT ?',([client] if client else [])+[limit]).fetchall()
  return [self.decoded(x) for x in rows]
 def active(self):
  r=self.c.execute('SELECT * FROM jobs WHERE state IN ('+','.join('?' for _ in ACTIVE)+') ORDER BY seq LIMIT 1',ACTIVE).fetchone();return self.decoded(r)
 def claim(self,now=None):
  from .dispatch import choose
  with self.tx():
   j=choose(self,now)
   if not j:return None
   self.c.execute("UPDATE jobs SET state='preparing',updated=? WHERE id=?",(time.time() if now is None else now,j['id']));self.event(j['id'],'preparing')
  return self.by_id(j['id'])
 def peek_ready(self):
  from .dispatch import choose
  with self.tx():return choose(self)
 def ready_business(self):
  from .dispatch import spec,waiting
  cache={}
  for row in self.c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY seq LIMIT 10000").fetchall():
   j=self.decoded(row);m=spec(self,j)
   if m['kind']!='maintenance' and not waiting(self,j,m,cache):return True
  return False
 def has_ready(self):
  from .dispatch import candidates
  return bool(candidates(self))
 def maintenance_eligibility(self):
  from .dispatch import eligibility
  return eligibility(self)
 def admit(self,client,batch_id,items,check,ordered=False):
  from .dispatch import MAX_BATCH,metadata
  from .assets import Assets
  ident(client);ident(batch_id)
  if type(ordered) is not bool or not isinstance(items,list) or not 1<=len(items)<=MAX_BATCH:raise ValueError('bounded nonempty batch required')
  validated=[];seen=[]
  for position,item in enumerate(items):
   if not isinstance(item,dict) or set(item)-{'job','dispatch'} or 'job' not in item:raise ValueError('batch item fields invalid')
   j=validate_job(item['job'])
   if j['client']!=client or j['request_id'] in seen:raise ValueError('one client and unique request IDs required')
   check(j);m=metadata(j,item.get('dispatch'),batch_id,position,seen,ordered)
   if m.get('unit') and validated and validated[-1][1].get('unit')==m['unit'] and seen[-1] not in m['after']:m['after'].append(seen[-1])
   validated.append((j,m,bool(item.get('dispatch')) or ordered));seen.append(j['request_id'])
  units={}
  for j,m,e in validated:
   if m.get('unit'):units.setdefault(m['unit'],[]).append(m)
  for group in units.values():
   if len(group)>4 or len({m['kind'] for m in group})!=1 or [m['position'] for m in group]!=list(range(group[0]['position'],group[0]['position']+len(group))):raise ValueError('unit requires at most four contiguous same-class items')
   own_ids={validated[m['position']][0]['request_id'] for m in group}
   external=[rid for m in group for rid in m['after'] if rid not in own_ids]
   for rid in external:
    if rid not in group[0]['after']:group[0]['after'].append(rid)
  all_sup=[rid for j,m,explicit in validated for rid in m['supersedes']]
  if len(set(all_sup))!=len(all_sup) or any(rid in seen for rid in all_sup):raise ValueError('overlapping batch supersession')
  batch_hash=digest([{'job':j,'dispatch':m} for j,m,e in validated])
  with self.tx():
   old_batch=self.c.execute('SELECT hash FROM dispatch_batches WHERE client=? AND batch_id=?',(client,batch_id)).fetchone()
   if old_batch and old_batch[0]!=batch_hash:raise Conflict('immutable batch membership conflict')
   pending=[];supersede=[];fresh=0
   for j,m,explicit in validated:
    old=self.c.execute('SELECT * FROM jobs WHERE client=? AND request_id=?',(client,j['request_id'])).fetchone()
    if old:
     if old['hash']!=digest(j):raise Conflict('immutable job conflict')
     meta=self.c.execute('SELECT spec,hash FROM dispatch_metadata WHERE job_id=?',(old['id'],)).fetchone()
     if meta:
      original=json.loads(meta['spec']);logical=('kind','after','expected_asset','supersedes','unit','group_reply_source')
      if digest(original)!=meta['hash'] or any(original.get(k)!=m.get(k) for k in logical) or (original.get('unit') and original['batch_id']!=m['batch_id']):raise Conflict('immutable dispatch conflict')
     elif explicit:raise Conflict('legacy scheduling cannot be retrofitted')
     pending.append((j,m,old['id']));continue
    if self.c.execute('SELECT 1 FROM dispatch_supersessions WHERE client=? AND request_id=?',(client,j['request_id'])).fetchone():raise Conflict('request explicitly superseded')
    from .owner_prefix import check_new
    check_new(self.root,j)
    if 'asset' in j['payload']:
     try:a=Assets(self.root).get(client,j['payload']['asset'])
     except PermissionError:raise
     except (ValueError,OSError):
      if m['expected_asset'] is None:raise ValueError('future asset requires exact descriptor')
     else:
      if m['expected_asset'] and any(a.get(k)!=m['expected_asset'][k] for k in ('name','bytes','sha256')):raise ValueError('asset descriptor mismatch')
    for rid in m['supersedes']:
     row=self.c.execute('SELECT * FROM jobs WHERE client=? AND request_id=?',(client,rid)).fetchone()
     if self.c.execute('SELECT 1 FROM dispatch_supersessions WHERE client=? AND request_id=?',(client,rid)).fetchone():raise Conflict('old request already superseded')
     if row:
      jid=row['id'];history=self.c.execute("SELECT 1 FROM events WHERE job_id=? AND state<>'queued' LIMIT 1",(jid,)).fetchone()
      if row['state']!='queued' or row['preview'] or row['expires'] is not None or history or (self.root/(jid+'-attempt.json')).exists() or (self.root/(jid+'-composer.json')).exists() or (self.root/(jid+'-navigation.json')).exists() or list(self.root.glob(jid+'-step-*')):raise Conflict('old request is not positively unattempted')
     supersede.append((rid,row,j['request_id']))
    pending.append((j,m,None));fresh+=1
   if self.c.execute('SELECT COUNT(*) FROM dispatch_supersessions').fetchone()[0]+len(supersede)>10000:raise ValueError('supersession receipt quota reached')
   if self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]+fresh>10000:raise ValueError('queue receipt quota reached')
   now=time.time();ids={}
   if not old_batch:
    if self.c.execute('SELECT count(*) FROM dispatch_batches').fetchone()[0]>=10000:raise ValueError('batch receipt quota reached')
    self.c.execute('INSERT INTO dispatch_batches VALUES(?,?,?,?)',(client,batch_id,batch_hash,now))
   for j,m,oldid in pending:
    if oldid:ids[j['request_id']]=oldid;continue
    jid=secrets.token_hex(16);ids[j['request_id']]=jid
    self.c.execute('INSERT INTO jobs(id,client,request_id,body,hash,state,created,updated) VALUES(?,?,?,?,?,?,?,?)',(jid,client,j['request_id'],json.dumps(j,ensure_ascii=False),digest(j),'queued',now,now))
    self.c.execute('INSERT INTO dispatch_metadata(job_id,spec,hash) VALUES(?,?,?)',(jid,json.dumps(m,ensure_ascii=False),digest(m)));self.event(jid,'queued')
   for rid,row,replacement in supersede:
    target=ids[replacement];self.c.execute('INSERT INTO dispatch_supersessions VALUES(?,?,?,?)',(client,rid,target,now))
    if row:
     result={'reason':'explicitly_superseded','replacementRequestId':replacement,'noSend':True}
     self.c.execute("UPDATE jobs SET state='cancelled',result=?,updated=? WHERE id=?",(json.dumps(result),now,row['id']));self.event(row['id'],'superseded',{'replacementRequestId':replacement})
  return [self.get(client,j['request_id']) for j,m,e in validated]
 def preview(self,jid,value,now=None,ttl=180,state='awaiting_confirmation'):
  if state not in ('awaiting_confirmation','needs_assistance'):raise ValueError('preview state')
  now=time.time() if now is None else now
  if not 10<=ttl<=300:raise ValueError('bounded preview ttl required')
  with self.tx():
   old=self.by_id(jid)
   if not old or old['state'] not in ('preparing','needs_assistance','needs_attention'):raise Conflict('job is not preparing')
   if old['state']=='preparing' and old.get('expires')==0:
    self.c.execute("UPDATE jobs SET state='needs_attention',preview=?,token=NULL,updated=? WHERE id=?",(json.dumps(value,ensure_ascii=False),now,jid));self.event(jid,'cancel-before-preview')
    return self.by_id(jid)
   token=secrets.token_urlsafe(32);self.c.execute('UPDATE jobs SET state=?,preview=?,token=?,expires=?,updated=? WHERE id=?',(state,json.dumps(value,ensure_ascii=False),token,now+ttl,now,jid));self.event(jid,state,{'previewSha256':digest(value)})
  return self.by_id(jid)
 def confirm(self,client,rid,token,now=None):
  now=time.time() if now is None else now
  with self.tx():
   row=self.c.execute('SELECT * FROM jobs WHERE client=? AND request_id=?',(ident(client),ident(rid))).fetchone()
   if not row:raise KeyError('no request')
   if row['state']!='awaiting_confirmation' or row['expires']<=now or not isinstance(token,str) or not hmac.compare_digest(row['token'],token):raise ValueError('preview is expired, changed or not confirmed by its token')
   p=json.loads(row['preview']);p['confirmationSource']='manual'
   self.c.execute("UPDATE jobs SET state='confirmed',preview=?,token=NULL,updated=? WHERE id=?",(json.dumps(p,ensure_ascii=False),now,row['id']));self.event(row['id'],'confirmed',{'source':'manual'})
  return self.get(client,rid)
 def confirm_programmatic(self,jid,certificate,now=None):
  from .fast import verify_certificate
  now=time.time() if now is None else now
  with self.tx():
   j=self.by_id(jid)
   if not j or j['state']!='awaiting_confirmation' or j['expires']<=now:return None
   p=dict(j['preview']);verify_certificate(j,p,certificate)
   p.update(confirmationSource='programmatic',fastVerification=certificate,reviewRequired=False)
   self.c.execute("UPDATE jobs SET state='confirmed',preview=?,token=NULL,updated=? WHERE id=?",(json.dumps(p,ensure_ascii=False),now,jid));self.event(jid,'confirmed',{'source':'programmatic','certificateSHA256':digest(certificate)})
  return self.by_id(jid)
 def review_fast(self,jid):
  with self.tx():
   j=self.by_id(jid)
   if not j or j['state']!='awaiting_confirmation' or j['expires']<=time.time():return j
   p=dict(j['preview']);p.update(reviewRequired=True,fastVerification={'eligible':False,'reason':'FAST_REVIEW_REQUIRED'})
   self.c.execute('UPDATE jobs SET preview=?,updated=? WHERE id=?',(json.dumps(p,ensure_ascii=False),time.time(),jid));self.event(jid,'fast-review-required')
  return self.by_id(jid)
 def begin_execution(self,jid,now=None):
  now=time.time() if now is None else now
  with self.tx():
   j=self.by_id(jid)
   if not j or j['state']!='confirmed' or j['expires']<=now:return None
   self.c.execute("UPDATE jobs SET state='executing',updated=? WHERE id=?",(now,jid));self.event(jid,'executing')
  return self.by_id(jid)
 def assist(self,client,rid,context,point):
  with self.tx():
   j=self.get(client,rid);p=j.get('preview') or {}
   if j['state']!='needs_assistance' or j['expires']<=time.time() or p.get('context')!=context:raise ValueError('assistance context expired or changed')
   if not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point):raise ValueError('two integer coordinates required')
   bounds=p.get('navigationBounds')
   if not bounds or not bounds[0]<point[0]<bounds[2] or not bounds[1]<point[1]<bounds[3]:raise ValueError('navigation must stay in frozen session list')
   p['navigationPoint']=point;self.c.execute("UPDATE jobs SET state='preparing',preview=?,updated=? WHERE id=?",(json.dumps(p,ensure_ascii=False),time.time(),j['id']));self.event(j['id'],'assisted-navigation')
  return self.get(client,rid)
 def plan_step(self,client,rid,context,step,patch):
  from .steps import validate_step
  with self.tx():
   j=self.get(client,rid);p=j.get('preview') or {}
   if j['state']!='needs_assistance' or j['expires']<=time.time() or context!=p.get('context'):raise ValueError('assistance preview changed or expired')
   validate_step(step,p['windowBounds'],list(j['payload']))
   p.update(step=step,stepPatch=patch,previousContext=context)
   token=secrets.token_urlsafe(32);self.c.execute("UPDATE jobs SET state='awaiting_confirmation',preview=?,token=?,expires=?,updated=? WHERE id=?",(json.dumps(p,ensure_ascii=False),token,time.time()+180,time.time(),j['id']));self.event(j['id'],'step-awaiting-confirmation',{'step':step,'patch':patch})
  return self.get(client,rid)
 def repreview(self,jid,preview):
  with self.tx():
   j=self.by_id(jid)
   if not j or j['state']!='needs_attention':raise ValueError('only a suspended request can receive a verified replacement preview')
   token=secrets.token_urlsafe(32);self.c.execute("UPDATE jobs SET state='awaiting_confirmation',preview=?,token=?,expires=?,updated=? WHERE id=?",(json.dumps(preview,ensure_ascii=False),token,time.time()+180,time.time(),jid));self.event(jid,'revalidated-preview')
  return self.by_id(jid)
 def set_state(self,jid,state,result=None,expected=None):
  if state not in (*ACTIVE,*TERMINAL):raise ValueError('invalid job state')
  with self.tx():
   current=self.by_id(jid)
   if not current:raise KeyError(jid)
   if expected is not None and (current['state'],current['updated'])!=expected:return current
   self.c.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',(state,json.dumps(result,ensure_ascii=False) if result is not None else None,time.time(),jid));self.event(jid,state)
  return self.by_id(jid)
 def cancel(self,client,rid,*,queued_only=False):
  with self.tx():
   j=self.get(client,rid)
   if queued_only and j['state']!='queued':return j
   if j['state']=='queued':
    if (self.root/(j['id']+'-attempt.json')).exists() or (self.root/(j['id']+'-composer.json')).exists() or (self.root/(j['id']+'-navigation.json')).exists() or list(self.root.glob(j['id']+'-step-*')):raise ValueError('queued side-effect evidence must be reconciled')
    self.c.execute("UPDATE jobs SET state='cancelled',result=?,updated=? WHERE id=?",(json.dumps({'reason':'caller_cancelled_before_preparation','noSend':True}),time.time(),j['id']));self.event(j['id'],'cancelled')
   elif j['state'] in ('preparing','awaiting_confirmation','needs_assistance') or (j['state']=='needs_attention' and not (self.root/(j['id']+'-attempt.json')).exists() and not list(self.root.glob(j['id']+'-step-*'))):self.c.execute("UPDATE jobs SET expires=0,updated=? WHERE id=?",(time.time(),j['id']));self.event(j['id'],'cancel-requested')
   elif j['state'] not in TERMINAL:raise ValueError('execution outcome must be reconciled before cancellation')
  return self.get(client,rid)
 def recover(self):
  with self.tx():
   # A crash between saved preview and native certification must not expose a
   # forever-pending fast request or silently auto-confirm its stale scene.
   for row in self.c.execute("SELECT id,body,preview FROM jobs WHERE state='awaiting_confirmation'").fetchall():
    body=json.loads(row['body']);p=json.loads(row['preview'])
    if body.get('execution_mode')=='verified_fast' and not p.get('reviewRequired'):
     p.update(reviewRequired=True,fastVerification={'eligible':False,'reason':'RESTART_REVIEW_REQUIRED'})
     self.c.execute('UPDATE jobs SET preview=?,updated=? WHERE id=?',(json.dumps(p,ensure_ascii=False),time.time(),row['id']));self.event(row['id'],'fast-restart-review-required')
   for row in self.c.execute("SELECT id,state FROM jobs WHERE state IN ('executing','preparing')").fetchall():
    state='unknown' if row['state']=='executing' else 'needs_attention';reason='execution_interrupted' if state=='unknown' else 'preparation_interrupted';self.c.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',(state,json.dumps({'reason':reason,'automaticReplay':False}),time.time(),row['id']));self.event(row['id'],state,{'recovery':'not replayed'})
