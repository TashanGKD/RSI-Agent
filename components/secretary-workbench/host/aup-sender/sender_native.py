"""Native official daemon proxy. Closing a client never stops the daemon."""
import pathlib,subprocess,selectors,os,json,time,sys
ROOT=pathlib.Path(os.environ.get('SECRETARY_SENDER_WORKSPACE','var/sender')).resolve()
AUTH=pathlib.Path(os.environ['SECRETARY_CODEX_HOME']) if os.environ.get('SECRETARY_CODEX_HOME') else None
BIN=pathlib.Path(os.environ['SECRETARY_CODEX_BIN']) if os.environ.get('SECRETARY_CODEX_BIN') else None
SOCKET=AUTH/'app-server-control/app-server-control.sock' if AUTH else None
# Reuse the already verified JSON-RPC framing, without a second native model host.
class Native:
 def __init__(self):
  if AUTH is None or BIN is None:raise ValueError('Configure SECRETARY_CODEX_HOME and SECRETARY_CODEX_BIN explicitly')
  env={k:v for k,v in os.environ.items() if k in ['HOME','PATH','LANG','LC_ALL','TZ','USER']};env['CODEX_HOME']=str(AUTH)
  start_env=dict(env)
  for k in ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY']:
   if os.environ.get(k):start_env[k]=os.environ[k]
  check=subprocess.run([str(BIN),'app-server','daemon','start'],env=start_env,capture_output=True,timeout=30)
  if check.returncode:raise RuntimeError('official AUP sender daemon unavailable; no alternate sender')
  self.p=subprocess.Popen(['/usr/bin/node',str(pathlib.Path(__file__).with_name('native_ws_proxy.mjs')),'--connect'],env=env,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
  self.sel=selectors.DefaultSelector();self.sel.register(self.p.stdout,selectors.EVENT_READ);self.buf=b'';self.seq=0;self.events=[];self.completed={};self.requests=[];self.on_event=None
 def receive(self,end):
  while time.monotonic()<end:
   if b'\n' in self.buf:
    line,self.buf=self.buf.split(b'\n',1)
    try:return json.loads(line)
    except ValueError:continue
   if not self.sel.select(.3):continue
   b=os.read(self.p.stdout.fileno(),65536)
   if not b:raise RuntimeError('test appserver exited')
   self.buf+=b
   if len(self.buf)>64*1024*1024:raise RuntimeError('response bound exceeded')
  raise TimeoutError('bounded appserver wait')
 def notice(self,r):
  method=r.get('method','');v=r.get('params',{})
  if method and 'id' in r:
   # No arbitrary dynamic tools or approvals are executed by this host adapter.
   self.p.stdin.write((json.dumps({'id':r['id'],'error':{'code':-32601,'message':'not available in readonly migration acceptance'}})+'\n').encode());self.p.stdin.flush();self.events.append({'method':method,'denied':True});return
  if method in ['turn/started','item/started','thread/status/changed']:
   self.events.append({'method':method,'turnId':v.get('turnId',v.get('turn',{}).get('id')),'threadId':v.get('threadId'),'itemType':v.get('item',{}).get('type')})
  if method=='turn/completed':self.completed[v['turn']['id']]=v['turn']
  if method=='item/completed':
   i=v.get('item',{});x={'type':i.get('type'),'id':i.get('id'),'turnId':v.get('turnId')}
   if i.get('type')=='commandExecution':x.update(command=i.get('command'),exitCode=i.get('exitCode'),output=i.get('aggregatedOutput','')[:20000])
   if i.get('type')=='agentMessage' and i.get('phase') in [None,'final','final_answer']:x.update(text=i.get('text',''),phase=i.get('phase'))
   self.events.append(x)
  if method=='error':self.events.append({'error':v.get('error')})
  if self.on_event and (method in ['turn/started','item/started','thread/status/changed','turn/completed','item/completed','error']):self.on_event()
 def call(self,method,params,timeout=60):
  if method not in ['initialize','thread/read','thread/resume','thread/queue/add','thread/queue/list','thread/queue/start','thread/turns/list','thread/items/list','account/read','config/read','mcpServerStatus/list','config/mcpServer/reload']:raise ValueError('unsupported native collaboration method')
  self.seq+=1;seq=self.seq;self.requests.append({'method':method,'threadId':params.get('threadId')});self.p.stdin.write((json.dumps({'id':seq,'method':method,'params':params})+'\n').encode());self.p.stdin.flush();end=time.monotonic()+timeout
  while True:
   r=self.receive(end)
   if r.get('id')==seq:
    if 'error' in r:raise RuntimeError(method+': '+str(r['error']))
    return r.get('result',{})
   self.notice(r)

 def init(self):
  self.call('initialize',{'clientInfo':{'name':'original_wechat_sender_router','version':'1'},'capabilities':{'experimentalApi':True}});self.p.stdin.write(b'{"method":"initialized"}\n');self.p.stdin.flush()
 def close(self):
  self.sel.close();self.p.stdin.close()
  try:self.p.wait(timeout=10)
  except subprocess.TimeoutExpired:
   self.p.terminate()
   try:self.p.wait(timeout=5)
   except subprocess.TimeoutExpired:self.p.kill();self.p.wait()
