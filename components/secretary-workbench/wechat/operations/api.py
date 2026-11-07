import base64,json,re,os
from pathlib import Path
from .store import Store
from .assets import Assets
from .driver import Policy
from .contract import ACTIONS,ident

class API:
 def __init__(self,root,config):self.policy=Policy(config);self.s=Store(root);self.assets=Assets(root)
 def close(self):self.s.close()
 def call(self,r):
  fields={'capabilities':set(),'submit':{'job'},'get':{'client','request_id'},'list':{'client'},'confirm':{'client','request_id','token'},'cancel':{'client','request_id'},'assist':{'client','request_id','context','point'},'plan_step':{'client','request_id','context','step'},'refresh':{'client','request_id'},'retry_native':{'client','request_id'},'reconcile':{'client','request_id'},'upload':{'client','name','sha256','data'},'preview':{'client','request_id'}}
  fields['repreview']={'client','request_id'}
  fields['download']={'client','asset'}
  fields['events']={'client','request_id'}
  fields['status']=set()
  op=r.get('op')
  if op not in fields or set(r)-fields[op]-{'op'} or fields[op]-set(r):raise ValueError('unsupported operation or fields')
  if op=='capabilities':
   return {'version':1,'modelRequired':False,'account':self.policy.cfg['account'],'actions':list(ACTIONS),'methods':{'native':'previously verified binding and deterministic native input; no model or VNC','visual':'caller-guided screenshot navigation, same native input backend'},'acceptance':{'send_text':'live-native-receipt','send_image':'live-native-receipt-and-exported-message-image-MD5','send_file':'live-TXT-PDF-PPTX-DOCX-name-size-MD5','open_chat':'live-exact-title-binding','save_attachment':'live-native-cache-file-and-official-image-export','join_group':'two-live-new-memberships-confirmed-steps; full-OCR-final-join-not-yet-accepted','reply':'live-specific-original-server-ID','forward':'live-exact-file-identity','open_message':'assisted-visible-range; exact-source-location-not-automatically-proven','mention':'software-semantic-verifier; no-controlled-live-group-test','request_friend':'assisted-interface; fresh-request-not-accepted','accept_friend':'native-friend-verifier; fresh-acceptance-not-accepted'},'authBoundary':'existing authenticated SSH and owner OS user; client labels are not separate security tenants','guiDependency':'ordinary official WeChat client remains required; backend does not mean direct private-network API'}
  if op=='status':
   p=self.s.root/'health.json';health=json.loads(p.read_text()) if p.is_file() and not p.is_symlink() else None
   import time
   from .lease import birth
   live=bool(health and type(health.get('pid')) is int and health.get('birth') is not None and birth(health['pid'])==health['birth'])
   from .lease import active
   return {'uiBusy':active(self.s.root),'worker':health,'workerLive':live,'heartbeatFresh':bool(live and time.time()-health.get('at',0)<15),'active':self.s.active(),'counts':dict(self.s.c.execute('SELECT state,count(*) FROM jobs GROUP BY state').fetchall())}
  if op=='submit':
   from .contract import validate_job
   j=validate_job(r['job']);self.policy.check(j)
   if 'asset' in j['payload']:self.assets.get(j['client'],j['payload']['asset'])
   return self.s.submit(j)
  client=ident(r['client'])
  if op=='download':
   v=self.assets.get(client,r['asset'])
   data=Path(v.pop('path')).read_bytes();return dict(v,data=base64.b64encode(data).decode())
  if op=='upload':
   if not isinstance(r['data'],str):raise ValueError('encoded asset input required')
   try:data=base64.b64decode(r['data'],validate=True)
   except ValueError:raise ValueError('valid base64 required') from None
   x=self.assets.put(client,r['name'],data,r['sha256']);x.pop('path',None);return x
  if op=='list':return {'jobs':self.s.list_jobs(client)}
  rid=ident(r['request_id'])
  if op in ('confirm','assist','plan_step','refresh','repreview','retry_native'):self.policy.check(self.s.get(client,rid))
  if op=='get':return self.s.get(client,rid)
  if op=='events':
   j=self.s.get(client,rid);rows=self.s.c.execute('SELECT seq,at,state,detail FROM events WHERE job_id=? ORDER BY seq LIMIT 1001',(j['id'],)).fetchall()
   return {'jobId':j['id'],'events':[dict(x) for x in rows[:1000]],'truncated':len(rows)>1000}
  if op=='confirm':return self.s.confirm(client,rid,r['token'])
  if op=='cancel':return self.s.cancel(client,rid)
  if op=='assist':return self.s.assist(client,rid,r['context'],r['point'])
  if op=='repreview':
   j=self.s.get(client,rid)
   if j['state']!='needs_attention':raise ValueError('request is not suspended')
   from .driver import NativeDriver
   preview=NativeDriver(self.s.root,self.policy.cfg).revalidate_asset(j);return self.s.repreview(j['id'],preview)
  if op=='retry_native':
   j=self.s.get(client,rid)
   if j['state'] not in ('needs_assistance','needs_attention') or j['action']!='join_group' or list(self.s.root.glob(j['id']+'-step-*')) or (self.s.root/(j['id']+'-attempt.json')).exists():raise ValueError('native preparation can resume only before any side-effect step')
   p=dict(j['preview'],retryNative=True)
   with self.s.tx():self.s.c.execute("UPDATE jobs SET state='preparing',preview=? WHERE id=?",(json.dumps(p),j['id']));self.s.event(j['id'],'native-recipe-requested')
   return self.s.get(client,rid)
  if op=='reconcile':
   j=self.s.get(client,rid)
   if j['state'] in ('confirmed','executing','preparing'):raise ValueError('executor is active; wait for its outcome')
   from .driver import NativeDriver
   proof=NativeDriver(self.s.root,self.policy.cfg).verify(j)
   from .original_deviation import verify as verify_original_deviation
   adopted=verify_original_deviation(self.s.root,j)
   if adopted is not None:
    if adopted.get('state')=='accepted':
     if j['state']=='succeeded':return self.s.by_id(j['id'])
     return self.s.set_state(j['id'],'succeeded',adopted,expected=(j['state'],j['updated']))
    proof=adopted
   if proof.get('state')=='accepted':return self.s.set_state(j['id'],'succeeded',proof)
   return dict(j,readOnlyReconciliation=proof)
  if op=='refresh':
   j=self.s.get(client,rid)
   if j['state'] not in ('needs_assistance','needs_attention') or not (j.get('preview') or {}).get('workflow') or (self.s.root/(j['id']+'-attempt.json')).exists():raise ValueError('only an unattempted visible-assistance observation can refresh')
   from .driver import NativeDriver
   d=NativeDriver(self.s.root,self.policy.cfg);preview=d.generic_preview(j);return self.s.preview(j['id'],preview,state='needs_assistance')
  if op=='plan_step':
   j=self.s.get(client,rid);p=j.get('preview') or {};from .steps import validate_step,step_patch
   step=validate_step(r['step'],p.get('windowBounds',[0,0,0,0]),list(j['payload']))
   image=self.s.root/'previews'/(j['id']+'.png')
   if image.is_symlink():raise ValueError('preview symlink')
   from PIL import Image
   with Image.open(image) as im:patch=step_patch(im,step,p['windowBounds'])
   return self.s.plan_step(client,rid,r['context'],step,patch)
  if op=='preview':
   j=self.s.get(client,rid);p=self.s.root/'previews'/(j['id']+'.png')
   if not j.get('preview') or p.is_symlink() or not p.is_file() or p.stat().st_size>4000000:raise ValueError('no verified preview asset')
   data=p.read_bytes();import hashlib
   if hashlib.sha256(data).hexdigest()!=j['preview']['sha256']:raise ValueError('preview asset changed')
   return {'mime':'image/png','sha256':j['preview']['sha256'],'jobState':j['state'],'expires':j['expires'],'data':base64.b64encode(data).decode()}
