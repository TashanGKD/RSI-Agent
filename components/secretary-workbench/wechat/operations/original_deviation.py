"""One hash-pinned original receipt disposition; no general text normalization.

A locally reviewed, hash-pinned original case is required to use this mechanism. No UI, Send or state
writes occur here; the existing reconcile/Store and owned finalizer do those.
"""
import hashlib,json,math,os,sqlite3,stat
from pathlib import Path
from .contract import digest

MODE='explicit_specific_deviation_author_accepted'
CASE=None  # No private case is distributed or registered by this package.

def _sha(data):return hashlib.sha256(data).hexdigest()
def _need(condition,code):
 if not condition:raise ValueError(code)
def _unknown(code):return {'state':'unknown','reason':'original_deviation_'+code,'automaticReplay':False}

def load_record(root):
 if CASE is None:return None
 root=Path(root)
 _need(root.is_absolute() and root.resolve()==root,'root_identity')
 p=root/(CASE['jobId']+'-accepted-deviation.json')
 if not p.exists() and not p.is_symlink():return None
 s=p.lstat()
 _need(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and not s.st_mode&0o077 and s.st_size<=16384,'record_not_private_regular')
 data=p.read_bytes();after=p.lstat()
 _need((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns),'record_changed')
 _need(_sha(data)==CASE['recordSHA256'],'record_sha')
 r=json.loads(data);_need(r.get('version')==1 and r.get('mode')==MODE and r.get('allowGlobalNormalization') is False and r.get('ordinaryVerificationAtSend')=='unknown','record_scope')
 _need(r.get('case')=={k:v for k,v in CASE.items() if k!='recordSHA256'},'record_case')
 raw=r.get('authorAcceptanceDocumentUTF8');_need(isinstance(raw,str) and _sha(raw.encode())==CASE['authorAcceptanceDocumentSHA256'],'author_document_sha')
 doc=json.loads(raw);_need(doc==r.get('authorAcceptanceDocument'),'author_document_changed')
 for k,v in {'jobId':CASE['jobId'],'requestId':CASE['requestId'],'peer':CASE['peer'],'originalSHA256':CASE['expectedTextSHA256'],'actualSHA256':CASE['actualTextSHA256'],'nativeServerId':CASE['nativeServerId'],'originalFrozenChars':2000,'actualChars':1998}.items():_need(doc.get(k)==v,'author_'+k)
 for k in ['callerAuthorAcceptsThisActualSentVersionAsCompleteBusinessDelivery','callerAcceptanceDoesNotChangeCanonicalOrBackfillProgrammaticExactVerification','exactWholeBusinessTextMatchBeforeFinalTwoChars','send1NoReplay']:_need(doc.get(k) is True,'author_acceptance_missing')
 return r

def _original(root,j):
 _need((j.get('id'),j.get('client'),j.get('request_id'),j.get('peer'),j.get('action'))==(CASE['jobId'],CASE['client'],CASE['requestId'],CASE['peer'],'send_text'),'job_scope')
 db=sqlite3.connect((Path(root)/'queue.sqlite').as_uri()+'?mode=ro',uri=True)
 try:
  rows=db.execute('SELECT body,hash,state,result FROM jobs WHERE id=? AND client=? AND request_id=?',(CASE['jobId'],CASE['client'],CASE['requestId'])).fetchall();_need(len(rows)==1,'stored_job_unique')
  raw,h,state,result=rows[0];_need(_sha(raw.encode())==CASE['canonicalBodySHA256'] and h==CASE['canonicalContractSHA256'],'canonical_changed')
  body=json.loads(raw);_need(digest(body)==h and all(j.get(k)==v for k,v in body.items()),'job_view_changed')
  _need(state in ('unknown','succeeded'),'original_state')
  if state=='succeeded':
   old=json.loads(result or '{}');_need(old.get('state')=='accepted' and old.get('serverId')==CASE['nativeServerId'] and old.get('textComparison',{}).get('mode')==MODE,'accepted_state_conflict')
  counts=dict(db.execute("SELECT state,count(*) FROM events WHERE job_id=? AND state IN ('confirmed','executing') GROUP BY state",(CASE['jobId'],)).fetchall());_need(counts=={'confirmed':1,'executing':1},'execution_count')
  _need(db.execute("SELECT count(*) FROM events WHERE job_id=? AND state='unknown'",(CASE['jobId'],)).fetchone()[0]>=1,'unknown_history_missing')
 finally:db.close()
 expected=body['payload']['text'];_need(isinstance(expected,str) and len(expected)==2000 and _sha(expected.encode())==CASE['expectedTextSHA256'] and expected.endswith(' \n') and not expected[-3].isspace(),'expected_text')
 p=Path(root)/(CASE['jobId']+'-attempt.json');s=p.lstat();_need(stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and not s.st_mode&0o077 and s.st_size<=70000,'attempt_private')
 data=p.read_bytes();_need(_sha(data)==CASE['attemptSHA256'],'attempt_sha');a=json.loads(data)
 _need(a.get('peer')==CASE['peer'] and a.get('action')=='send_text' and a.get('text')==expected and a.get('clickScheduled') is True,'attempt_identity')
 start=a.get('startedAt');_need(type(start) in (int,float) and math.isfinite(start) and start==CASE['attemptStartedAt'],'attempt_time')
 before=a.get('beforeIds');_need(isinstance(before,list) and len(before)<=1000 and all(isinstance(v,str) for v in before) and CASE['nativeServerId'] not in before,'attempt_before_ids')
 p=Path(root)/(CASE['jobId']+'-execution-check.json');_need(not p.is_symlink() and _sha(p.read_bytes())==CASE['executionCheckSHA256'],'execution_checkpoint_changed')
 return a,expected

def _row_match(j,a,row,expected):
 return bool(row.get('peer')==CASE['peer'] and row.get('senderId')==CASE['account'] and row.get('status')==2 and row.get('kind')==1 and type(row.get('time')) in (int,float) and row['time']==CASE['nativeTime'] and row['time']>=int(a['startedAt'])-1 and row.get('serverId') not in a['beforeIds'] and isinstance(row.get('text'),str) and len(row['text'])==1998 and row['text']==expected[:-2] and _sha(row['text'].encode())==CASE['actualTextSHA256'])

def native_snapshot(j,a):
 from linux_tool import native,ACCOUNT,decode
 rows=[]
 with native('message/message_0.db') as (db,r):
  if r.get('consistency')!='committed' or r.get('integrity')!='ok':return {'account':ACCOUNT,'receipt':r,'rows':[],'truncated':True}
  me=db.execute('SELECT rowid FROM Name2Id WHERE user_name=? LIMIT 2',(ACCOUNT,)).fetchall()
  if len(me)!=1:return {'account':ACCOUNT,'receipt':r,'rows':[],'truncated':True}
  table='Msg_'+hashlib.md5(CASE['peer'].encode()).hexdigest()
  exact=db.execute('SELECT server_id FROM '+table+' WHERE server_id=? LIMIT 2',(int(CASE['nativeServerId']),)).fetchall()
  if len(exact)!=1:return {'account':ACCOUNT,'receipt':r,'rows':[],'truncated':True}
  got=db.execute('SELECT server_id,status,local_type,create_time,message_content FROM '+table+' WHERE real_sender_id=? AND create_time>=? ORDER BY create_time,local_id LIMIT 101',(me[0][0],int(a['startedAt'])-1)).fetchall()
  if len(got)>100:return {'account':ACCOUNT,'receipt':r,'rows':[],'truncated':True}
  for v in got:
   sid=str(v['server_id']&0xffffffffffffffff);kind=int(v['local_type'])&0xffffffff
   if sid=='0' or sid in a['beforeIds'] or v['status']!=2 or kind!=1:continue
   text=decode(v['message_content'])
   if text.startswith(ACCOUNT+':\n'):text=text[len(ACCOUNT)+2:]
   rows.append({'peer':CASE['peer'],'serverId':sid,'senderId':ACCOUNT,'status':v['status'],'kind':kind,'time':v['create_time'],'text':text})
  return {'account':ACCOUNT,'receipt':r,'rows':rows,'truncated':False}

def verify(root,j):
 if CASE is None:return None
 if j.get('id')!=CASE['jobId']:return None # Other jobs cannot even read this record.
 try:
  _need((j.get('client'),j.get('request_id'),j.get('peer'),j.get('action'))==(CASE['client'],CASE['requestId'],CASE['peer'],'send_text'),'job_scope')
  if load_record(root) is None:return None
  a,expected=_original(root,j);snap=native_snapshot(j,a)
  _need(snap.get('account')==CASE['account'] and snap.get('receipt',{}).get('consistency')=='committed' and snap.get('receipt',{}).get('integrity')=='ok' and not snap.get('truncated'),'native_snapshot_gap')
  _need(sum(row.get('serverId')==CASE['nativeServerId'] for row in snap.get('rows',[]))==1,'native_id_not_unique')
  # Exact, existing one-LF and this explicit two-character version compete
  # in the same original attempt window; none may be ignored as a rival.
  candidates=[row for row in snap.get('rows',[]) if row.get('peer')==CASE['peer'] and row.get('senderId')==CASE['account'] and row.get('status')==2 and row.get('kind')==1 and type(row.get('time')) in (int,float) and math.isfinite(row['time']) and row['time']>=int(a['startedAt'])-1 and row.get('serverId') not in a['beforeIds'] and row.get('text') in (expected,expected[:-1],expected[:-2])]
  _need(len(candidates)==1,'native_competing_text_candidates')
  matches=[row for row in candidates if _row_match(j,a,row,expected)]
  _need(len(matches)==1 and matches[0].get('serverId')==CASE['nativeServerId'],'native_candidate_conflict')
  proof={'state':'accepted','peer':CASE['peer'],'serverId':CASE['nativeServerId'],'senderId':CASE['account'],'nativeStatus':2,'nativeCreateTime':CASE['nativeTime'],'uniqueCandidateCount':1,'attemptAndSingleExecutionEvent':True,'evidence':'explicit-specific-native-difference-current-author-accepted','ordinaryVerificationAtSend':'unknown','automaticResend':False,'phoneReceiptConfirmed':False,'textComparison':{'mode':MODE,'exact':False,'expectedSHA256':CASE['expectedTextSHA256'],'actualSHA256':CASE['actualTextSHA256'],'expectedChars':2000,'actualChars':1998,'removedSuffixCodepoints':['U+0020','U+000A'],'globalNormalizationApplied':False},'authorAcceptance':{'verified':True,'threadId':CASE['authorThread'],'documentSHA256':CASE['authorAcceptanceDocumentSHA256'],'recordSHA256':CASE['recordSHA256'],'specificOriginalOnly':True},'canonicalAndAttemptUnchanged':True,'nativeSnapshotReceipt':snap['receipt']}
  return dict(proof,draftRestored=False,draftRecoveryPending=True,navigationRestored=False,navigationRecoveryPending=True,postActionPending=True)
 except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as e:return _unknown(str(e)[:100])

def audit_match(root,j,a,row):
 if CASE is None:return False
 if root is None or j.get('id')!=CASE['jobId']:return False
 try:
  if load_record(root) is None:return False
  saved,expected=_original(root,j);r=j.get('result') or {};t=r.get('textComparison') or {};ack=r.get('authorAcceptance') or {}
  return bool(saved==a and r.get('state')=='accepted' and r.get('serverId')==CASE['nativeServerId'] and t.get('mode')==MODE and t.get('exact') is False and t.get('expectedSHA256')==CASE['expectedTextSHA256'] and t.get('actualSHA256')==CASE['actualTextSHA256'] and ack.get('verified') is True and ack.get('recordSHA256')==CASE['recordSHA256'] and ack.get('documentSHA256')==CASE['authorAcceptanceDocumentSHA256'] and row.get('serverId')==CASE['nativeServerId'] and _row_match(j,a,row,expected))
 except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):return False
