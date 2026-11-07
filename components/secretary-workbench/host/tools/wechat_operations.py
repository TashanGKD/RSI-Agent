#!/usr/bin/env python3
"""Independent queued WeChat operations client; no model and no default network action."""
import argparse,subprocess,json,sys,base64,hashlib,os,stat,re,time,select
from pathlib import Path
_host=os.environ.get('WECHAT_SSH_HOST','secretary-wechat-host')
_code=os.environ.get('WECHAT_REMOTE_CODE_ROOT','/opt/secretary-workbench/wechat')
_state=os.environ.get('WECHAT_REMOTE_STATE_ROOT','/var/lib/secretary-wechat/operations-state')
import re,shlex
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,128}',_host):raise ValueError('explicit SSH alias/host required')
_remote='cd '+shlex.quote(_code)+' && python3 -m operations.cli request --execute --root '+shlex.quote(_state)+' --config '+shlex.quote(_state+'/config.json')
COMMAND=['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=10',_host,_remote]
class ToolError(RuntimeError):
 def __init__(self,error):
  self.code=error.get('code','TOOL_ERROR');self.details=error.get('details',{});self.error=error
  super().__init__(self.code+': '+error.get('message','Tool request failed.'))

MAX_FILE_BYTES=None
CHUNK_BYTES=1048576

def _stamp(s):return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)

def _stream_upload(client,path,f,metadata):
 """Fixed authenticated SSH endpoint; only JSON metadata + raw bytes, never a server path."""
 cmd=list(COMMAND);cmd[-1]=cmd[-1].replace('operations.cli request --execute','operations.cli upload-stream --execute')
 proc=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 deadline=time.monotonic()+30
 def write(data):
  nonlocal deadline
  value=memoryview(data)
  while value:
   left=deadline-time.monotonic()
   if left<=0:raise TimeoutError('bounded file upload deadline')
   if not select.select([], [proc.stdin], [], min(left,10))[1]:continue
   try:n=os.write(proc.stdin.fileno(),value)
   except BlockingIOError:continue
   if n<=0:raise ConnectionError('upload pipe closed')
   deadline=time.monotonic()+30
   value=value[n:]
 try:
  os.set_blocking(proc.stdin.fileno(),False)
  write(json.dumps(metadata,ensure_ascii=False).encode()+b'\n')
  sent=0;h=hashlib.sha256()
  while sent<metadata['bytes']:
   chunk=f.read(min(CHUNK_BYTES,metadata['bytes']-sent))
   if not chunk:raise ValueError('local file truncated during upload')
   write(chunk);h.update(chunk);sent+=len(chunk)
  if f.read(1) or h.hexdigest()!=metadata['sha256']:raise ValueError('local file changed during upload')
  proc.stdin.close();proc.stdin=None
  out,err=proc.communicate(timeout=240)
  if len(out)>65536:raise ConnectionError('upload response cap')
  try:x=json.loads(out)
  except ValueError:raise ConnectionError('upload result unknown; same client/name/hash is content-addressed, inspect before retry') from None
  if proc.returncode or x.get('state')=='error':raise ToolError(x.get('error') or {'code':'UPLOAD_FAILED','message':'Upload was rejected; no sending operation was created.'})
  if x.get('client')!=client or x.get('name')!=path.name or x.get('bytes')!=metadata['bytes'] or x.get('sha256')!=metadata['sha256']:raise ConnectionError('upload result identity mismatch')
  return x
 except BrokenPipeError:
  # An early server budget/validation rejection closes stdin before body upload.
  # Drain that SAME process once; never turn it into a replay or raise a limit.
  try:
   if proc.stdin:
    try:proc.stdin.close()
    except BrokenPipeError:pass
    proc.stdin=None
   out,err=proc.communicate(timeout=min(10,max(.1,deadline-time.monotonic())))
   if len(out)>65536:raise ConnectionError('upload rejection response cap')
   try:x=json.loads(out)
   except ValueError:raise ConnectionError('upload pipe closed without a verifiable result; inspect same asset identity') from None
   if x.get('state')=='error' and isinstance(x.get('error'),dict):raise ToolError(x['error'])
   raise ConnectionError('upload pipe closed; no verified completed upload, inspect same asset')
  finally:
   if proc.poll() is None:
    proc.terminate()
    try:proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=5)
 except BaseException:
  if proc.poll() is None:proc.terminate()
  try:proc.communicate(timeout=5)
  except subprocess.TimeoutExpired:proc.kill();proc.communicate(timeout=5)
  raise

def upload_file(client,path):
 if not isinstance(client,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}',client):raise ValueError('stable client required')
 p=Path(path).expanduser().absolute()
 fd=os.open(p,os.O_RDONLY|os.O_NONBLOCK)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('regular file required')
 except BaseException:os.close(fd);raise
 with os.fdopen(fd,'rb') as f:
  before=os.fstat(f.fileno())
  if not stat.S_ISREG(before.st_mode) or before.st_size<=0:raise ValueError('nonempty regular file required')
  if before.st_size<=10000000:
   data=f.read(10000001);after=os.fstat(f.fileno())
   if _stamp(before)!=_stamp(after) or len(data)!=before.st_size:raise ValueError('file changed during upload read')
   return call({'op':'upload','client':client,'name':p.name,'sha256':hashlib.sha256(data).hexdigest(),'data':base64.b64encode(data).decode()})
  h=hashlib.sha256();n=0
  while True:
   chunk=f.read(CHUNK_BYTES)
   if not chunk:break
   h.update(chunk);n+=len(chunk)
   if n>before.st_size:raise ValueError('local file grew while hashing')
  if _stamp(before)!=_stamp(os.fstat(f.fileno())) or n!=before.st_size:raise ValueError('file changed during hash')
  metadata={'client':client,'name':p.name,'bytes':n,'sha256':h.hexdigest()};f.seek(0)
  result=_stream_upload(client,p,f,metadata)
  if _stamp(before)!=_stamp(os.fstat(f.fileno())):raise ValueError('local file changed during transfer; uploaded hash remains frozen')
  return result

def call(request):
 raw=json.dumps(request,ensure_ascii=False)
 p=subprocess.run(COMMAND,input=raw,capture_output=True,text=True,timeout=45)
 try:x=json.loads(p.stdout)
 except ValueError:raise ConnectionError('operations transport result unknown; query stable request before retry') from None
 if p.returncode or x.get('state')=='error':raise ToolError(x.get('error') or {'code':'TOOL_ERROR','message':str(x.get('reason') or 'request failed')})
 return x
def _file_expectation(client,path):
 """Freeze a local regular file. The server receives only descriptor metadata."""
 if not isinstance(client,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}',client):raise ValueError('configured client required')
 p=Path(path).expanduser().absolute()
 fd=os.open(p,os.O_RDONLY|os.O_NONBLOCK)
 try:
  if not stat.S_ISREG(os.fstat(fd).st_mode):raise ValueError('regular file required')
 except BaseException:os.close(fd);raise
 with os.fdopen(fd,'rb') as f:
  st=os.fstat(f.fileno());stamp=_stamp(st)
  if not stat.S_ISREG(st.st_mode) or st.st_size<=0:raise ValueError('nonempty regular file required')
  h=hashlib.sha256();count=0
  while True:
   data=f.read(CHUNK_BYTES)
   if not data:break
   count+=len(data);h.update(data)
   if count>st.st_size:raise ValueError('file changed while freezing')
  if stamp!=_stamp(os.fstat(f.fileno())) or count!=st.st_size:raise ValueError('file changed while freezing')
 sha=h.hexdigest();identity={'client':client,'name':p.name,'sha256':sha}
 aid=hashlib.sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return {'id':aid,'name':p.name,'bytes':count,'sha256':sha}

def dispatch_batch(client,batch_id,items,*,ordered=False,wait_seconds=0,audit=True):
 """Admit ready, frozen work only. One normal call, at most one read-only recovery.
 Upload local originals first with upload_file, then perform the business's final
 source/cancellation check, and pass ready asset IDs here. This function never
 publishes a future asset or automatically retries an uncertain admission.
 """
 import copy
 started=time.time();clock=time.monotonic()
 if not isinstance(items,list) or not 1<=len(items)<=20:raise ValueError('1..20 explicit jobs required')
 if type(ordered) is not bool or type(audit) is not bool or type(wait_seconds) not in (int,float) or not 0<=wait_seconds<=20:raise ValueError('bounded dispatch options required')
 prepared=[];ids=[]
 for original in items:
  if not isinstance(original,dict) or set(original)-{'job','dispatch'}:raise ValueError('ready jobs only: upload originals and complete final context check before dispatch_batch')
  value=copy.deepcopy(original);j=value.get('job')
  if not isinstance(j,dict) or j.get('client')!=client:raise ValueError('one client per batch')
  rid=j.get('request_id')
  if not isinstance(rid,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}',rid) or rid in ids:raise ValueError('unique stable original request IDs required')
  if 'expected_asset' in value.get('dispatch',{}):raise ValueError('future assets are not accepted by the ready SDK')
  prepared.append(value);ids.append(rid)
 prepared_at=time.time();prepared_after=time.monotonic()-clock;admission_at=None;admission_after=None
 def timing():return {'startedAt':started,'preparedAt':prepared_at,'admissionResponseAt':admission_at,'returnedAt':time.time(),'preparedAfterSeconds':prepared_after,'admissionAfterSeconds':admission_after,'totalClientSeconds':time.monotonic()-clock,'maxSynchronousTransportCalls':2}
 request={'op':'admit','client':client,'batch_id':batch_id,'items':prepared,'ordered':ordered,'wait_seconds':wait_seconds,'audit':audit}
 try:
  result=call(request);admission_at=time.time();admission_after=time.monotonic()-clock
  return dict(result,sdkTiming=timing())
 except (ToolError,OSError,ConnectionError,TimeoutError,subprocess.TimeoutExpired) as exc:
  if isinstance(exc,ToolError) and exc.code!='INTERNAL_ERROR':raise
  # The original admission may have committed. Query those exact IDs once.
  # No second admission, new ID, cancellation, asset upload or Send is issued.
  try:
   current=call({'op':'get_many','client':client,'request_ids':ids,'wait_seconds':0,'audit':False})
  except (ToolError,OSError,ConnectionError,TimeoutError,subprocess.TimeoutExpired):
   current={'jobs':[{'request_id':rid,'state':'unknown','outcome':{'status':'unknown','next_action':'reconcile_same_request'}} for rid in ids]}
  return dict(current,transport={'code':'ADMISSION_RESPONSE_UNCERTAIN','originalRequestIds':ids,'readOnlyRecoveryAttempted':True,'admissionRetries':0},sdkTiming=timing())

def save_output(result,path):
 q=Path(path).expanduser().absolute()
 data=base64.b64decode(result['data'],validate=True)
 if hashlib.sha256(data).hexdigest()!=result['sha256']:raise ValueError('output checksum mismatch')
 fd=os.open(q,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(data)
 return dict({k:v for k,v in result.items() if k!='data'},output_path=str(q))

def save_preview(client,request_id,path):
 return save_output(call({'op':'preview','client':client,'request_id':request_id}),path)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');p.add_argument('--request-file');p.add_argument('--preview-output');p.add_argument('--asset-output');p.add_argument('--upload-file');p.add_argument('--client');a=p.parse_args()
 if not a.execute:p.print_help();return
 if a.upload_file:
  if a.request_file or not a.client:p.error('upload needs --client and cannot combine --request-file')
  print(json.dumps(upload_file(a.client,a.upload_file),ensure_ascii=False));return
 if not a.request_file:p.error('explicit request file or - required')
 raw=sys.stdin.read() if a.request_file=='-' else Path(a.request_file).read_text()
 # Strict duplicate keys are checked again by the source endpoint.
 def unique(rows):
  x={}
  for k,v in rows:
   if k in x:raise ValueError('duplicate JSON key')
   x[k]=v
  return x
 x=call(json.loads(raw,object_pairs_hook=unique))
 if a.preview_output or a.asset_output:
  if a.preview_output and a.asset_output:raise ValueError('choose one explicit output')
  x=save_output(x,a.preview_output or a.asset_output)
 elif 'data' in x:raise ValueError('use --preview-output or --asset-output to save bytes; raw data is not printed')
 print(json.dumps(x,ensure_ascii=False))
if __name__=='__main__':
 try:main()
 except ToolError as e:print(json.dumps({'state':'error','error':e.error},ensure_ascii=False));raise SystemExit(2)
