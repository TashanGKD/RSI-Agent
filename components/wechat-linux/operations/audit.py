"""One bounded committed native snapshot; no UI, Send or request-state writes."""
import json,re,hashlib,os,stat,math
from xml.etree import ElementTree as ET
from .dispatch import identifiers,MAX_BATCH
from .proof import matches,xml
from .contract import digest

def attempt_evidence(store,j):
 if j['state']!='succeeded' or (j.get('result') or {}).get('state')!='accepted':return None,'NOT_ACCEPTED'
 if j['action'] not in ('send_text','send_file','send_image'):return None,'AUDIT_ACTION_UNSUPPORTED'
 result=j['result'];sid=result.get('serverId')
 if not isinstance(sid,str) or not re.fullmatch('[0-9]{1,20}',sid) or not 0<int(sid)<2**64:return None,'NATIVE_ID_MISSING'
 if 'sendClicks' in result and result['sendClicks']!=1:return None,'CLICK_EVIDENCE_CONFLICT'
 p=store.root/(j['id']+'-attempt.json')
 try:
  st=p.lstat()
  if not stat.S_ISREG(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or st.st_size>70000:return None,'ATTEMPT_UNVERIFIED'
  a=json.loads(p.read_text())
 except (OSError,ValueError):return None,'ATTEMPT_MISSING'
 counts=dict(store.c.execute("SELECT state,count(*) FROM events WHERE job_id=? AND state IN ('confirmed','executing') GROUP BY state",(j['id'],)).fetchall())
 if counts!={'confirmed':1,'executing':1} or a.get('clickScheduled') is not True or a.get('peer')!=j['peer'] or a.get('action')!=j['action']:return None,'ATTEMPT_EVENT_MISMATCH'
 if type(a.get('startedAt')) not in (int,float) or not math.isfinite(a['startedAt']) or not 0<=a['startedAt']<=2**53 or not isinstance(a.get('beforeIds'),list) or len(a['beforeIds'])>1000 or any(not isinstance(v,str) or not re.fullmatch('[0-9]{1,20}',v) for v in a['beforeIds']) or sid in a['beforeIds']:return None,'ATTEMPT_BASELINE_INVALID'
 if j['action']=='send_text' and a.get('text')!=j['payload']['text']:return None,'ATTEMPT_PAYLOAD_MISMATCH'
 if j['action']!='send_text':
  asset=a.get('asset') or {}
  if asset.get('id')!=j['payload']['asset'] or not re.fullmatch('[a-f0-9]{64}',asset.get('sha256','')):return None,'ATTEMPT_ASSET_MISMATCH'
  from .assets import descriptor
  try:valid=descriptor(asset.get('client'),asset.get('name'),asset.get('bytes'),asset.get('sha256'))==asset['id']
  except ValueError:valid=False
  if not valid:return None,'ATTEMPT_ASSET_MISMATCH'
 return a,None

def native_snapshot(requests):
 import sys
 from .driver import NATIVE
 if str(NATIVE) not in sys.path:sys.path.insert(0,str(NATIVE))
 from linux_tool import native,ACCOUNT,decode
 rows=[]
 with native('message/message_0.db') as (db,receipt):
  if receipt.get('consistency')!='committed' or receipt.get('integrity')!='ok':return {'account':ACCOUNT,'receipt':{'consistency':receipt.get('consistency'),'integrity':receipt.get('integrity')},'rows':[],'truncated':True}
  peers={j['peer'] for j in requests}
  if len(peers)>MAX_BATCH:raise ValueError('batch audit peer budget')
  sender=db.execute('SELECT rowid FROM Name2Id WHERE user_name=?',(ACCOUNT,)).fetchone()
  for peer in peers:
   table='Msg_'+hashlib.md5(peer.encode()).hexdigest()
   if not sender or not db.execute('SELECT 1 FROM sqlite_master WHERE name=?',(table,)).fetchone():continue
   ids=[j['result']['serverId'] for j in requests if j['peer']==peer]
   signed=[int(s) if int(s)<2**63 else int(s)-2**64 for s in ids]
   sql='SELECT server_id,real_sender_id,status,local_type,create_time,message_content FROM '+table+' WHERE server_id IN ('+','.join('?' for _ in ids)+') LIMIT 41'
   got=db.execute(sql,signed).fetchall()
   if len(got)>40:return {'account':ACCOUNT,'receipt':{'consistency':'committed','integrity':'ok'},'rows':[],'truncated':True}
   if len(rows)+len(got)>40:return {'account':ACCOUNT,'receipt':{'consistency':'committed','integrity':'ok'},'rows':[],'truncated':True}
   for r in got:
    text=decode(r['message_content']);kind=int(r['local_type'])&0xffffffff
    if peer.endswith('@chatroom') and text.startswith(ACCOUNT+':\n'):text=text[len(ACCOUNT)+2:]
    rows.append({'peer':peer,'serverId':str(r['server_id']&0xffffffffffffffff),'senderId':ACCOUNT if r['real_sender_id']==sender[0] else None,'kind':kind,'status':r['status'],'time':r['create_time'],'text':text})
  return {'account':ACCOUNT,'receipt':{'consistency':'committed','integrity':'ok'},'rows':rows,'truncated':False}

def receipt_match(j,a,row,root=None):
 if j['action']=='send_text':
  if (j.get('result') or {}).get('textComparison',{}).get('mode')=='explicit_specific_deviation_author_accepted':
   from .original_deviation import audit_match
   return audit_match(root,j,a,row)
  return matches(j,row['kind'],row.get('text',''),'')
 asset=a['asset']
 if j['action']=='send_image':
  # Native WeChat may recompress images. This audits message + frozen preparation,
  # not native-original byte equality or a new image export.
  p=j.get('preview') or {}
  identity=p.get('imageIdentity') or {}
  valid=identity.get('pixelFormat')=='RGBA8' and re.fullmatch('[a-f0-9]{64}',identity.get('pixelsSHA256','')) and type(identity.get('width')) is int and type(identity.get('height')) is int and identity['width']>0 and identity['height']>0
  return bool(valid and row['kind']==3 and (p.get('asset') or {}).get('id')==asset['id'] and (p.get('asset') or {}).get('sha256')==asset['sha256'])
 if row['kind']!=49:return False
 try:
  r=xml(row.get('text',''));apps=[r] if r.tag=='appmsg' else r.findall('.//appmsg')
  if len(apps)!=1:return False
  app=apps[0];sizes=[x.text or '' for x in app.findall('.//totallen')];hashes=[x.text or '' for x in app.findall('.//filemd5')+app.findall('.//md5')]
  return app.findtext('type')=='6' and app.findtext('title')==asset.get('name') and bool(sizes) and all(re.fullmatch('[0-9]{1,20}',v) and int(v)==asset.get('bytes') for v in sizes) and bool(hashes) and all(re.fullmatch('[a-fA-F0-9]{32}',v) and v.lower()==asset.get('md5') for v in hashes)
 except (ValueError,ET.ParseError):return False

def audit_many(store,client,ids,account=None):
 identifiers(ids,MAX_BATCH);eligible=[];items=[];attempts={}
 for rid in ids:
  try:j=store.get(client,rid)
  except KeyError:items.append({'request_id':rid,'status':'unknown','reason':'REQUEST_NOT_FOUND'});continue
  a,reason=attempt_evidence(store,j)
  if reason:items.append({'request_id':rid,'status':'unknown','reason':reason});continue
  attempts[j['id']]=a;eligible.append(j)
 counts={}
 for j in eligible:
  key=(j['peer'],j['result']['serverId']);counts[key]=counts.get(key,0)+1
 unique=[]
 for j in eligible:
  if counts[(j['peer'],j['result']['serverId'])]!=1:items.append({'request_id':j['request_id'],'status':'unknown','reason':'DUPLICATE_NATIVE_RECEIPT_ID'})
  else:unique.append(j)
 eligible=unique
 if len({j['peer'] for j in eligible})>MAX_BATCH:raise ValueError('batch audit peer budget')
 snap=None
 if eligible:
  try:snap=native_snapshot(eligible)
  except (OSError,ValueError,RuntimeError):snap=None
 used=set()
 for j in eligible:
  result={'request_id':j['request_id'],'status':'unknown','reason':'NATIVE_SNAPSHOT_GAP'};a=attempts[j['id']]
  if snap and snap.get('receipt',{}).get('consistency')=='committed' and snap.get('receipt',{}).get('integrity')=='ok' and not snap.get('truncated') and (account is None or snap.get('account')==account):
   rows=[r for r in snap['rows'] if r.get('peer')==j['peer'] and r.get('serverId')==j['result']['serverId']]
   key=(j['peer'],j['result']['serverId'])
   good=len(rows)==1 and key not in used
   if good:
    row=rows[0];good=row.get('senderId')==snap['account'] and row.get('status')==2 and type(row.get('time')) in (int,float) and math.isfinite(row['time']) and row['time']>=int(a['startedAt'])-1 and receipt_match(j,a,row,store.root)
   if good:
    used.add(key);result={'request_id':j['request_id'],'status':'verified','peer':j['peer'],'serverId':j['result']['serverId'],'nativeKind':rows[0]['kind'],'nativeCreateTime':rows[0]['time'],'attemptStartedAt':a['startedAt'],'attemptAndSingleExecutionEvent':True,'optionalSendClicksPresent':'sendClicks' in j['result'],'imageAuditScope':'message-and-frozen-preparation' if j['action']=='send_image' else None}
    if (j.get('result') or {}).get('textComparison',{}).get('mode')=='explicit_specific_deviation_author_accepted':result.update(textComparisonMode='explicit_specific_deviation_author_accepted',canonicalTextExact=False,authorAcceptanceVerified=True)
   else:result['reason']='NATIVE_IDENTITY_OR_SEMANTICS_MISMATCH'
  items.append(result)
 order={rid:i for i,rid in enumerate(ids)};items.sort(key=lambda x:order[x['request_id']])
 return {'items':items,'allVerified':bool(items) and all(x['status']=='verified' for x in items),'nativeSnapshotCalls':1 if eligible else 0,'nativeSnapshotReads':1 if snap and snap.get('receipt',{}).get('consistency')=='committed' and snap.get('receipt',{}).get('integrity')=='ok' else 0,'stateWrites':0,'newSends':0}
