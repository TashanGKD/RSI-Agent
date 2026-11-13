"""Bounded scheduling metadata for the original jobs table, not another queue."""
import json,time,os,stat,hashlib,re
from .contract import ident,validate_job,digest
MAX_BATCH=20
MAX_GET=50
KINDS=('reply','delivery','maintenance')

def identifiers(xs,limit=MAX_BATCH):
 if not isinstance(xs,list) or len(xs)>limit:raise ValueError('bounded identifier list required')
 for x in xs:ident(x)
 if len(set(xs))!=len(xs):raise ValueError('duplicate request identifiers')
 return xs

def metadata(j,raw,batch_id,position,seen,ordered):
 from .assets import descriptor,INLINE_BYTES
 if raw is None:raw={}
 if not isinstance(raw,dict) or set(raw)-{'kind','after','expected_asset','supersedes','unit','group_reply_source'}:raise ValueError('unsupported dispatch fields')
 unit=raw.get('unit')
 if unit is not None:ident(unit)
 kind=raw.get('kind','delivery')
 if kind not in KINDS:raise ValueError('bounded dispatch kind required')
 after=list(identifiers(raw.get('after',[])));sup=list(identifiers(raw.get('supersedes',[])))
 if any(x not in seen for x in after) or j['request_id'] in sup or any(x in seen for x in sup):raise ValueError('only backward same-batch dependencies and distinct old supersession IDs allowed')
 if ordered and seen and seen[-1] not in after:after.append(seen[-1])
 expected=raw.get('expected_asset')
 if expected is not None:
  if j['action'] not in ('send_image','send_file') or not isinstance(expected,dict) or set(expected)!={'name','bytes','sha256'}:raise ValueError('exact future asset descriptor required')
  descriptor(j['client'],expected['name'],expected['bytes'],expected['sha256'])
  # Frozen asset ID and actual name/bytes/SHA are checked when it is present;
  # its uploader attribution need not be the submitting employee label.
 value={'kind':kind,'after':after,'expected_asset':expected,'supersedes':sup,'batch_id':batch_id,'position':position,'unit':unit}
 if 'group_reply_source' in raw:
  source=raw['group_reply_source']
  if (j['client']!='rsi-group' or not j['peer'].endswith('@chatroom') or j['action']!='send_text' or not ordered
      or not isinstance(source,str) or len(source.encode())>6000 or source==j['payload']['text']
      or source.strip()!=j['payload']['text']):raise ValueError('exact group reply slice with boundary whitespace required')
  value['group_reply_source']=source
 return value

def decode_spec(row):
 value=json.loads(row['spec'])
 if digest(value)!=row['hash']:raise ValueError('immutable dispatch metadata changed')
 return value

def spec(store,j):
 if 'dispatch' in j:return j['dispatch']
 r=store.c.execute('SELECT spec,hash FROM dispatch_metadata WHERE job_id=?',(j['id'],)).fetchone()
 return decode_spec(r) if r else {'kind':'delivery','after':[],'expected_asset':None,'supersedes':[]}

def historical_empty_text_backup(store,p,value):
 # Compatibility only: accepted old text with no original draft to restore.
 # Do not alter that historical record or certify any current UI contents.
 jid=p.name[:-len('-composer.json')]
 if not re.fullmatch('[a-f0-9]{32}',jid) or value.get('state')!='staged':return False
 if type(value.get('priorChars')) is not int or value['priorChars']!=0 or value.get('priorText')!='' or value.get('priorSHA')!=hashlib.sha256(b'').hexdigest():return False
 try:j=store.by_id(jid)
 except KeyError:return False
 result=j.get('result') or {}
 return bool(j.get('action')=='send_text' and j.get('state')=='succeeded' and result.get('state')=='accepted' and not result.get('draftRecoveryPending') and not result.get('postActionPending') and value.get('peer')==j.get('peer') and value.get('payloadHash')==digest(j['payload']))

def artifact_barrier(store):
 # Bounded existing private journals; a missing optional sendClicks is NOT a barrier.
 for r in store.c.execute("SELECT result FROM jobs WHERE state='succeeded' AND result IS NOT NULL"):
  result=json.loads(r[0])
  if result and result.get('navigationRecoveryPending'):return 'NAVIGATION_RECOVERY_PENDING'
  if result and (result.get('draftRecoveryPending') or result.get('postActionPending')):return 'DRAFT_RECOVERY_PENDING'
 for i,p in enumerate(store.root.glob('*-composer.json')):
  if i>=10000:return 'DRAFT_BUDGET'
  try:
   s=p.lstat()
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>70000:return 'DRAFT_UNVERIFIED'
   value=json.loads(p.read_text())
   if value.get('state')!='restored' and not historical_empty_text_backup(store,p,value):return 'DRAFT_RECOVERY_PENDING'
  except (OSError,ValueError):return 'DRAFT_UNVERIFIED'
 for i,p in enumerate(store.root.glob('*-navigation.json')):
  if i>=10000:return 'NAVIGATION_BUDGET'
  try:
   s=p.lstat()
   if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>30000:return 'NAVIGATION_UNVERIFIED'
   if json.loads(p.read_text()).get('state')!='settled':return 'NAVIGATION_RECOVERY_PENDING'
  except (OSError,ValueError):return 'NAVIGATION_UNVERIFIED'
 return None

def asset_state(store,j,m,cache):
 from .assets import Assets
 aid=j['payload'].get('asset')
 if not aid:return None
 key=(j['client'],aid)
 if key not in cache:
  try:cache[key]=Assets(store.root).get(*key)
  except (OSError,ValueError,PermissionError):cache[key]=None
 a=cache[key]
 if a is None:return 'ASSET_UNAVAILABLE'
 expected=m.get('expected_asset')
 if expected and any(a.get(k)!=expected[k] for k in ('name','bytes','sha256')):return 'ASSET_IDENTITY_MISMATCH'
 return None

def unit_asset_barrier(store,j,m,cache):
 unit=m.get('unit')
 if unit is None:return None
 key=('unit',j['client'],m['batch_id'],unit)
 if key in cache:return cache[key]
 cache[key]=None
 rows=store.c.execute("SELECT j.* FROM jobs j JOIN dispatch_metadata d ON d.job_id=j.id WHERE j.client=? AND j.state='queued' ORDER BY j.seq LIMIT 10000",(j['client'],)).fetchall()
 for row in rows:
  other=store.decoded(row);meta=other['dispatch']
  if meta.get('batch_id')==m['batch_id'] and meta.get('unit')==unit and asset_state(store,other,meta,cache):cache[key]='UNIT_ASSET_UNAVAILABLE';break
 return cache[key]

def waiting(store,j,m,cache):
 for rid in m['after']:
  try:dep=store.get(j['client'],rid)
  except KeyError:return 'DEPENDENCY_MISSING'
  if dep['state']!='succeeded' or (dep.get('result') or {}).get('state')!='accepted':return 'DEPENDENCY_NOT_ACCEPTED'
  if (dep.get('result') or {}).get('draftRecoveryPending') or (dep.get('result') or {}).get('postActionPending'):return 'DRAFT_RECOVERY_PENDING'
 return asset_state(store,j,m,cache) or unit_asset_barrier(store,j,m,cache)

def candidates(store,now=None):
 if store.active() or artifact_barrier(store):return []
 now=time.time() if now is None else now;cache={};ready=[]
 for row in store.c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY seq LIMIT 10000").fetchall():
  j=store.decoded(row);m=spec(store,j)
  if not waiting(store,j,m,cache):ready.append((j,m))
 return ready

def choose(store,now=None):
 now=time.time() if now is None else now;ready=candidates(store,now)
 if not ready:return None
 business=[x for x in ready if x[1]['kind']!='maintenance']
 if not business:return ready[0][0]
 last=store.c.execute("SELECT j.id FROM events e JOIN jobs j ON j.id=e.job_id WHERE e.state='preparing' ORDER BY e.seq DESC LIMIT 1").fetchone()
 if last:
  previous=store.by_id(last['id']);pm=spec(store,previous)
  if pm.get('unit') and previous['state']=='succeeded' and (previous.get('result') or {}).get('state')=='accepted':
   same=[x for x in business if x[0]['client']==previous['client'] and x[1].get('batch_id')==pm.get('batch_id') and x[1].get('unit')==pm['unit']]
   if same:return same[0][0]
 # Fixed class hints are capped; aging and a three-claim burst cap bound starvation.
 recent=store.c.execute("SELECT j.id,j.client FROM events e JOIN jobs j ON j.id=e.job_id WHERE e.state='preparing' ORDER BY e.seq DESC LIMIT 3").fetchall()
 delivery=[x for x in business if x[1]['kind']=='delivery']
 replies=[x for x in business if x[1]['kind']=='reply']
 aged_delivery=[x for x in delivery if now-x[0]['created']>=120]
 if aged_delivery:
  # Aging must reserve progress, not let an old backlog consume every class
  # share. Alternate at safe unit boundaries using the existing claim history.
  last_kind=spec(store,store.by_id(recent[0]['id']))['kind'] if recent else None
  pool=replies if replies and last_kind=='delivery' else sorted(aged_delivery,key=lambda x:(x[0]['created'],x[0]['seq']))
 else:
  reply_burst=len(recent)==3 and all(spec(store,store.by_id(r['id']))['kind']=='reply' for r in recent)
  pool=delivery if reply_burst and delivery else sorted(business,key=lambda x:(0 if x[1]['kind']=='reply' else 1,x[0]['seq']))
 if len(recent)==3 and len({r['client'] for r in recent})==1:
  other=[x for x in pool if x[0]['client']!=recent[0]['client'] and x[1]['kind']==pool[0][1]['kind']]
  if other:return other[0][0]
 return pool[0][0]

def eligibility(store):
 if store.active():return {'eligible':False,'reason':'ACTIVE_OR_UNKNOWN','isLease':False}
 barrier=artifact_barrier(store)
 if barrier:return {'eligible':False,'reason':barrier,'isLease':False}
 if any(m['kind']!='maintenance' for j,m in candidates(store)):return {'eligible':False,'reason':'READY_BUSINESS','isLease':False}
 return {'eligible':True,'reason':'NO_READY_BUSINESS','isLease':False}
