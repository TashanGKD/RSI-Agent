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
  return x
 def submit(self,body):
  body=validate_job(body);sha=digest(body);now=time.time()
  with self.tx():
   old=self.c.execute('SELECT * FROM jobs WHERE client=? AND request_id=?',(body['client'],body['request_id'])).fetchone()
   if old:
    if old['hash']!=sha:raise Conflict('request ID already has different target or content')
    return self.decoded(old)
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
 def claim(self):
  with self.tx():
   if self.active():return None
   r=self.c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY seq LIMIT 1").fetchone()
   if not r:return None
   self.c.execute("UPDATE jobs SET state='preparing',updated=? WHERE id=?",(time.time(),r['id']));self.event(r['id'],'preparing')
  return self.by_id(r['id'])
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
   self.c.execute("UPDATE jobs SET state='confirmed',token=NULL,updated=? WHERE id=?",(now,row['id']));self.event(row['id'],'confirmed')
  return self.get(client,rid)
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
 def set_state(self,jid,state,result=None):
  if state not in (*ACTIVE,*TERMINAL):raise ValueError('invalid job state')
  with self.tx():
   if not self.by_id(jid):raise KeyError(jid)
   self.c.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',(state,json.dumps(result,ensure_ascii=False) if result is not None else None,time.time(),jid));self.event(jid,state)
  return self.by_id(jid)
 def cancel(self,client,rid):
  with self.tx():
   j=self.get(client,rid)
   if j['state']=='queued':self.c.execute("UPDATE jobs SET state='cancelled',updated=? WHERE id=?",(time.time(),j['id']));self.event(j['id'],'cancelled')
   elif j['state'] in ('preparing','awaiting_confirmation','needs_assistance') or (j['state']=='needs_attention' and not (self.root/(j['id']+'-attempt.json')).exists() and not list(self.root.glob(j['id']+'-step-*'))):self.c.execute("UPDATE jobs SET expires=0,updated=? WHERE id=?",(time.time(),j['id']));self.event(j['id'],'cancel-requested')
   elif j['state'] not in TERMINAL:raise ValueError('execution outcome must be reconciled before cancellation')
  return self.get(client,rid)
 def recover(self):
  with self.tx():
   for row in self.c.execute("SELECT id,state FROM jobs WHERE state IN ('executing','preparing')").fetchall():
    state='unknown' if row['state']=='executing' else 'needs_attention';reason='execution_interrupted' if state=='unknown' else 'preparation_interrupted';self.c.execute('UPDATE jobs SET state=?,result=?,updated=? WHERE id=?',(state,json.dumps({'reason':reason,'automaticReplay':False}),time.time(),row['id']));self.event(row['id'],state,{'recovery':'not replayed'})
