"""Thin original-thread collaboration adapter: native queue remains the sole queue."""
import pathlib,json,hashlib,sqlite3,os,fcntl,sys,time
from sender_native import Native,ROOT
from sender_protocol import validate,SID
RECEIPTS=ROOT/'receipts/assignments'
def digest(s):return hashlib.sha256(s.encode()).hexdigest()
def path_for(rid):return RECEIPTS/(digest(rid)+'.json')
def save(p,d):
 p.parent.mkdir(mode=0o700,parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp-'+str(os.getpid()));fd=os.open(t,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'w') as f:json.dump(d,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(t,p)
def native_items(rpc,tid,turn_id,direction='asc'):
 return [x.get('item',x) for x in rpc.call('thread/items/list',{'threadId':tid,'turnId':turn_id,'limit':100,'sortDirection':direction})['data']]
def exact_user(rpc,cid,body):
 c=sqlite3.connect('file:'+str(ROOT/'state/thread_history_1.sqlite')+'?mode=ro',uri=True);c.execute('pragma query_only=1')
 rows=c.execute("select turn_id,item_id from thread_items where thread_id=? and item_type='userMessage' and json_extract(item_json,'$.clientId')=?",(SID,cid)).fetchall();c.close()
 if len(rows)>1:raise RuntimeError('multiple native user identities; no new submission')
 if not rows:return None
 for x in native_items(rpc,SID,rows[0][0]):
  if x.get('type')=='userMessage' and x.get('clientId')==cid:
   text=''.join(a['text'] for a in x.get('content',[]) if a.get('type')=='text')
   if text!=body:raise ValueError('native client ID content conflict')
   return {'turnId':rows[0][0],'nativeUserMessageId':x['id'],'inputExact':True}
 raise RuntimeError('native projection exists but original API input not verified')
def queue(rpc,tid=SID):
 out=[];cursor=None
 for i in range(20):
  p=rpc.call('thread/queue/list',{'threadId':tid,'limit':100,**({'cursor':cursor} if cursor else {})});out+=p['data'];cursor=p.get('nextCursor')
  if not cursor:return out
 raise RuntimeError('queue coverage incomplete')
def status(rpc,d):
 found=exact_user(rpc,d['clientMessageId'],d['text'])
 if found:
  d.update(found);c=sqlite3.connect('file:'+str(ROOT/'state/thread_history_1.sqlite')+'?mode=ro',uri=True);row=c.execute('select status from thread_turns where thread_id=? and turn_id=?',(SID,found['turnId'])).fetchone();c.close()
  d['turnStatus']=row[0] if row else 'unknown';last=native_items(rpc,SID,found['turnId'],'desc');d['final']='\n'.join(x['text'] for x in reversed(last) if x.get('type')=='agentMessage' and x.get('phase') in ['final','final_answer']);d['phase']='completed' if d['turnStatus']=='completed' else 'delivered'
 else:
  q=next((x for x in queue(rpc) if x.get('clientUserMessageId')==d['clientMessageId']),None)
  if q:
   body=''.join(x['text'] for x in q['input'] if x['type']=='text')
   if body!=d['text']:raise ValueError('queued body conflict')
   d.update(phase='queued',queueId=q['id'],inputExact=True)
 # Always return original state if execution is initializing; never infer absent/unsent.
 return d
def context():
 c=sqlite3.connect('file:'+str(ROOT/'state/thread_history_1.sqlite')+'?mode=ro',uri=True);c.execute('pragma query_only=1');row=c.execute("select item_json from thread_items where thread_id=? and item_type='userMessage' order by rollout_ordinal desc limit 1",(SID,)).fetchone();c.close()
 if not row:return {'registeredRequest':False}
 item=json.loads(row[0]);cid=item.get('clientId')
 for p in RECEIPTS.glob('*.json'):
  d=json.load(open(p))
  if d.get('clientMessageId')==cid:
   body=''.join(x['text'] for x in item.get('content',[]) if x.get('type')=='text')
   if body!=d['text']:raise ValueError('native context content conflict')
   return {'registeredRequest':True,'request_id':d['request_id'],'caller':d['caller'],'nativeClientId':cid,'replyMode':'report_to_origin','originBodySha256':digest(d['text'])}
 return {'registeredRequest':False,'note':'historical/native direct input; keep original role and do not invent a recipient'}
def run(r):
 validate(r);RECEIPTS.mkdir(mode=0o700,parents=True,exist_ok=True)
 if r['op']=='context':return context()
 rpc=Native()
 try:
  rpc.init()
  if r['op']=='inspect':
   t=rpc.call('thread/read',{'threadId':SID,'includeTurns':False})['thread'];return {k:t.get(k) for k in ['id','cwd','status']}|{'owner':json.load(open(ROOT/'OWNER.json')),'queued':len(queue(rpc))}
  if r['op']=='read':
   p=rpc.call('thread/turns/list',{'threadId':SID,'limit':r.get('limit',3),'sortDirection':'desc','itemsView':'notLoaded'});return {'threadId':SID,'turns':[{'id':x['id'],'status':x['status'],'final':[i.get('text','') for i in native_items(rpc,SID,x['id'],'desc') if i.get('type')=='agentMessage' and i.get('phase') in ['final','final_answer']]} for x in p['data']]}
  f=path_for(r['request_id']);lock=f.with_suffix('.lock');fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX);d=json.load(open(f)) if f.exists() else None
   if r['op']=='status':
    if not d:raise ValueError('unknown original request')
    d=status(rpc,d);save(f,d);return d
   if r['op']=='report':
    if not d:raise ValueError('reply requires an original registered assignment')
    return _report(d,r['text'],f,rpc)
   owner=json.load(open(ROOT/'OWNER.json'))
   if owner['phase']!='active' and r['caller']['threadId'] not in owner.get('verificationCallers',[]):raise RuntimeError('AUP owner not activated; preserve draft without submission')
   t=rpc.call('thread/read',{'threadId':SID,'includeTurns':False})['thread']
   if t['status']['type']=='notLoaded':rpc.call('thread/resume',{'threadId':SID,'excludeTurns':True,'cwd':str(ROOT/'work'),'sandbox':'danger-full-access','approvalPolicy':'never','config':json.load(open(ROOT/'thread-config.json'))})
   cid=r.get('client_message_id') or 'sender-task-'+digest(r['request_id'])
   if d and (d['text']!=r['text'] or d['caller']!=r['caller'] or d['clientMessageId']!=cid):raise ValueError('request body/origin conflict')
   if d:
    d=status(rpc,d);save(f,d);return d
   d={'request_id':r['request_id'],'text':r['text'],'caller':r['caller'],'clientMessageId':cid,'threadId':SID,'host':'aup','phase':'prepared','at':time.time()}
   found=exact_user(rpc,cid,r['text'])
   q=next((x for x in queue(rpc) if x.get('clientUserMessageId')==cid),None)
   save(f,d)
   if not found and not q:
    d['phase']='submitting';save(f,d);a=rpc.call('thread/queue/add',{'threadId':SID,'clientUserMessageId':cid,'input':[{'type':'text','text':r['text'],'text_elements':[]}]});d['queueId']=a['queuedSubmission']['id'];d['phase']='queued';save(f,d)
   d=status(rpc,d)
   q=queue(rpc);mine=next((x for x in q if x.get('clientUserMessageId')==cid),None)
   t=rpc.call('thread/read',{'threadId':SID,'includeTurns':False})['thread']
   if mine and t['status']['type']=='notLoaded':
    # Same canonical host and original ID; no second model process.
    t=rpc.call('thread/resume',{'threadId':SID,'excludeTurns':True,'cwd':str(ROOT/'work'),'sandbox':'danger-full-access','approvalPolicy':'never','config':json.load(open(ROOT/'thread-config.json'))})['thread']
   q=queue(rpc);t=rpc.call('thread/read',{'threadId':SID,'includeTurns':False})['thread']
   if mine and q and q[0]['id']==mine['id'] and t['status']['type']=='idle' and not d.get('startAttempted'):
    d['startAttempted']=True;save(f,d)
    try:d['startedTurnId']=rpc.call('thread/queue/start',{'threadId':SID,'queuedSubmissionId':mine['id']})['turn']['id']
    except RuntimeError as e:d['startOutcomeUnknown']=str(e)
   d=status(rpc,d);save(f,d);return d
  finally:fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)
 finally:rpc.close()
def _report(d,text,f,rpc):
 if d.get('reportText'):
  if d['reportText']!=text:raise ValueError('report content conflict; original report retained')
  if d.get('reportReceipt') and d['reportReceipt'].get('phase')!='pending_native_callback':return d['reportReceipt']
  if d['caller']['host']!='mac':return {'phase':'unknown','note':'original native return needs reconciliation; do not re-add'}
 d['reportText']=text;d['reportPhase']='submitting';save(f,d)
 if d['caller'].get('replyMode','native' if d['caller']['host']=='mac' else 'inline')=='inline':
  rec={'phase':'available_to_original_caller','delivery':'inline tool response/status','nativeCallbackClaimed':False}
 elif d['caller']['host']=='mac':
  sys.path.insert(0,os.environ.get('SECRETARY_MAC_GATEWAY_TOOLS',str(pathlib.Path(__file__).resolve().parent)));from mac_files_client import call
  try:rec=call({'op':'sender.report','sourceRequestId':d['request_id'],'text':text})
  except Exception as e:rec={'phase':'pending_native_callback','reason':str(e)[:300],'resultAvailableViaSameStatus':True,'wechatMustNotBeRepeated':True}
 else:
  tid=d['caller']['threadId'];rid='sender-return-'+digest(d['request_id']);body='【发送员工回报 '+d['request_id']+'】\n'+text
  existing=next((x for x in queue(rpc,tid) if x.get('clientUserMessageId')==rid),None)
  if existing:rec={'phase':'queued','queueId':existing['id']}
  else:
   a=rpc.call('thread/queue/add',{'threadId':tid,'clientUserMessageId':rid,'input':[{'type':'text','text':body,'text_elements':[]}]});rec={'phase':'queued','queueId':a['queuedSubmission']['id']}
 d['reportPhase']='returned';d['reportReceipt']=rec;save(f,d);return rec
def unique(ps):
 d={}
 for k,v in ps:
  if k in d:raise ValueError('duplicate JSON key')
  d[k]=v
 return d
if __name__=='__main__':
 if sys.argv[1:]!=['--request']:print('Usage: sender_api.py --request < explicit-request.json. No default action.');sys.exit(0)
 try:
  raw=sys.stdin.read(70001)
  if len(raw.encode())>70000:raise ValueError('request too large')
  print(json.dumps({'ok':True,'result':run(json.loads(raw,object_pairs_hook=unique))},ensure_ascii=False))
 except Exception as e:print(json.dumps({'ok':False,'error':type(e).__name__,'reason':str(e)[:1200]},ensure_ascii=False));sys.exit(2)
