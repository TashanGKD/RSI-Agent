"""Portable client for the one original AUP sending conversation. No model/timer."""
import pathlib,json,os,sys,subprocess,hashlib,time,re
SID=os.environ.get('SECRETARY_SENDER_THREAD_ID','00000000-0000-4000-8000-000000000000')
MAC_RECEIPTS=pathlib.Path(os.environ.get('SECRETARY_SENDER_RECEIPTS','var/sender-caller-receipts')).resolve()
def _hash(s):return hashlib.sha256(s.encode()).hexdigest()
def call(request):
 if not isinstance(request,dict):raise ValueError('request object required')
 if sys.platform=='darwin':
  from sender_protocol import validate
  validate(request)
  if request['op']=='assign':
   if request['caller']['host']!='mac':raise ValueError('Mac caller host mismatch')
   actual=os.environ.get('CODEX_THREAD_ID')
   if actual and actual!=request['caller']['threadId']:raise ValueError('claimed caller differs from executing original chat')
   MAC_RECEIPTS.mkdir(mode=0o700,parents=True,exist_ok=True);p=MAC_RECEIPTS/(_hash(request['request_id'])+'.json')
   data={'request_id':request['request_id'],'caller':request['caller'],'bodySha256':_hash(request['text']),'at':time.time()}
   if p.exists():
    old=json.load(open(p))
    if any(old[k]!=data[k] for k in ['request_id','caller','bodySha256']):raise ValueError('original Mac request conflict')
   else:
    with p.open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2)
    os.chmod(p,0o600)
  import shlex
  target=os.environ.get('SECRETARY_SENDER_SSH_HOST');endpoint=os.environ.get('SECRETARY_SENDER_REMOTE_API')
  if not target or not re.fullmatch(r'[A-Za-z0-9_.-]+',target) or not endpoint or not pathlib.Path(endpoint).is_absolute():raise ValueError('configure original sender SSH alias and API path')
  cmd=['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=15',target,'python3 '+shlex.quote(endpoint)+' --request']
  p=subprocess.run(cmd,input=json.dumps(request,ensure_ascii=False),capture_output=True,text=True,timeout=90)
  try:r=json.loads(p.stdout)
  except ValueError:raise RuntimeError('AUP collaboration outcome unknown; query the same request ID')
  if not r.get('ok'):raise RuntimeError(r.get('reason','AUP unavailable'))
  result=r['result']
  if request['op']=='status' and result.get('reportText') and result.get('caller',{}).get('host')=='mac' and result.get('caller',{}).get('replyMode','native')!='inline':
   # The existing authenticated outbound RPC can return a result even while reverse connectivity is down.
   q=subprocess.run(['node','/var/lib/secretary-workspace/tools/mac-host/mac_sender_report.mjs','--serve'],input=json.dumps({'op':'sender.report','sourceRequestId':request['request_id'],'text':result['reportText']},ensure_ascii=False),capture_output=True,text=True,timeout=60)
   try:result['localNativeReturn']=json.loads(q.stdout)
   except ValueError:result['localNativeReturn']={'ok':False,'reason':'original report not yet reconciled'}
  return result
 if sys.platform.startswith('linux'):
  from sender_api import run
  return run(request)
 raise RuntimeError('unsupported host; no fallback to Mac sender')
def assign(request_id,text,caller_thread_id=None,caller_host=None,wait_seconds=0,reply_mode=None):
 caller={'host':caller_host or ('mac' if sys.platform=='darwin' else 'aup'),'threadId':caller_thread_id or os.environ.get('CODEX_THREAD_ID')}
 if reply_mode:caller['replyMode']=reply_mode
 result=call({'op':'assign','request_id':request_id,'text':text,'caller':caller})
 end=time.monotonic()+min(max(wait_seconds,0),600)
 while time.monotonic()<end and result.get('phase') not in ['completed','failed','interrupted']:
  time.sleep(1);result=status(request_id)
 return result
def status(request_id):return call({'op':'status','request_id':request_id})
if __name__=='__main__':
 if sys.argv[1:]!=['--request']:print('Usage: wechat_sender.py --request < explicit-request.json. No default action.');sys.exit(0)
 try:print(json.dumps(call(json.load(sys.stdin)),ensure_ascii=False))
 except Exception as e:print(json.dumps({'state':'attention','reason':str(e)[:1000]},ensure_ascii=False));sys.exit(2)
