"""Single executor; confirmation and business decisions remain with callers."""
import time,os,fcntl
from pathlib import Path
class BeforeEffect(ValueError):pass
class Busy(Exception):pass
class Executor:
 def __init__(self,store,driver):self.s=store;self.d=driver;self.expired_cleanup_retried=set();self.accepted_cleanup_attempts={};self.image_cleanup_attempts={}
 def recover_image_attention(self,j):
  # A failed image export sends nothing. Retry only the original cleanup so a
  # leftover viewer cannot hold every later reply behind needs_attention.
  failure=j.get('result') or {};root=getattr(self.s,'root',None)
  if (j['action']!='save_attachment' or failure.get('reason')!='precondition_changed'
      or failure.get('sideEffectStarted') is not False or root is None
      or (root/(j['id']+'-export.json')).exists()):return None
  now=time.monotonic()
  if now-self.image_cleanup_attempts.get(j['id'],-float('inf'))<5:return None
  self.image_cleanup_attempts[j['id']]=now
  try:clean=self.d.cleanup(j)
  except Exception:clean=False
  if not clean:return None
  proof=dict(failure,code='IMAGE_EXPORT_NOT_PROVEN',noSend=True,messagesSent=0,contentReady=False,navigationRestored=True,navigationRecoveryPending=False,postActionPending=False,automaticReplay=False,originalFailure=failure,cleanup='executor-retried-original-cleanup')
  actual=self.s.set_state(j['id'],'failed',proof,expected=(j['state'],j['updated']))
  self.d.release();return {'state':actual['state'],'job':j['id']}
 def recover_expired_preview(self,j):
  p=j.get('preview') or {};expires=j.get('expires');root=getattr(self.s,'root',None)
  if j['state']!='needs_attention' or j['action'] not in ('send_text','send_image','send_file') or (j.get('result') or {}).get('reason')!='owned_draft_cleanup_not_proven' or not p or expires is None or expires<=0 or expires>time.time() or j['id'] in self.expired_cleanup_retried:return None
  if root is None:return None # A simplified adapter cannot prove an original journal.
  journal=root/(j['id']+'-composer.json')
  if not journal.is_file() or journal.is_symlink():return None
  evidence=[root/(j['id']+suffix) for suffix in ('-attempt.json','-execution-check.json')]
  if any(p.exists() or p.is_symlink() for p in evidence) or list(root.glob(j['id']+'-step-*')):return None
  if self.s.c.execute("SELECT 1 FROM events WHERE job_id=? AND state IN ('confirmed','executing')",(j['id'],)).fetchone() or not self.s.c.execute("SELECT 1 FROM events WHERE job_id=? AND state='awaiting_confirmation'",(j['id'],)).fetchone():return None
  self.expired_cleanup_retried.add(j['id'])
  try:clean=self.d.cleanup(j)
  except Exception:clean=False
  if not clean:return None
  current=self.s.by_id(j['id'])
  if current['state']!='needs_attention':self.d.release();return {'state':current['state'],'job':j['id']}
  terminal='cancelled' if current.get('expires')==0 else 'expired'
  reason='caller_cancelled_and_owned_draft_cleanup_verified' if terminal=='cancelled' else 'preview_expired_owned_cleanup_verified'
  self.s.set_state(j['id'],terminal,{'reason':reason,'sideEffectStarted':False,'noSend':True,'draftRestored':True,'navigationRestored':True,'draftRecoveryPending':False,'navigationRecoveryPending':False,'postActionPending':False,'automaticReplay':False});self.d.release();return {'state':terminal,'job':j['id']}
 def finalize(self,j,proof):
  try:return self.d.finalize(j,proof) if hasattr(self.d,'finalize') else proof
  except Exception:return dict(proof,postActionPending=True,draftRecoveryPending=True,draftRestored=False)
 def recover_accepted_cleanup(self):
  # Terminal acceptance and remaining UI cleanup are separate. Retry only the
  # original cleanup primitives; never prepare, execute or change its payload.
  import json
  from . import navigation,composer
  from .audit import audit_many
  candidate=None
  for row in self.s.c.execute("SELECT id,result FROM jobs WHERE state='succeeded' ORDER BY seq"):
   proof=json.loads(row['result']) if row['result'] else {}
   if proof.get('state')=='accepted' and any(proof.get(k) is True for k in ('postActionPending','draftRecoveryPending','navigationRecoveryPending')):
    original=self.s.by_id(row['id'])
    if original['action'] in ('send_text','send_image','send_file'):candidate=original;break
  if not candidate:return None
  j=candidate;now=time.monotonic()
  if now-self.accepted_cleanup_attempts.get(j['id'],-float('inf'))<5:return None
  self.accepted_cleanup_attempts[j['id']]=now
  self.d.work_class='business' # Original accepted fault cleanup, not new work.
  if not self.d.acquire():return {'state':'window_busy','job':j['id']}
  try:
   current=self.s.by_id(j['id'])
   if self.s.active() or (current['state'],current['updated'])!=(j['state'],j['updated']):return {'state':'cleanup_pending','job':j['id'],'reason':'original-state-changed'}
   proof=j['result']
   # The existing native audit proves one scheduled attempt + confirmed/executing
   # events; legacy receipts may omit the optional sendClicks summary field.
   # Fresh native audit and the original owned-window journals govern cleanup;
   # current target registration or preparation versions are not a cleanup permit.
   audit=audit_many(self.s,j['client'],[j['request_id']],account=self.d.policy.cfg['account'])
   if not audit.get('allVerified'):return {'state':'cleanup_pending','job':j['id'],'reason':'original-native-audit-unproved'}
   original_navigation=navigation.load(self.s.root,j)
   if original_navigation is None and proof.get('navigationRecoveryPending') is True:return {'state':'cleanup_pending','job':j['id'],'reason':'original-navigation-journal-missing'}
   parked=composer.load(self.s.root,j)
   if parked and parked.get('state')!='restored':
    partial=self.finalize(j,proof)
    if partial.get('draftRestored') is not True or partial.get('draftRecoveryPending') is not False:return {'state':'cleanup_pending','job':j['id'],'reason':'original-draft-cleanup-unproved'}
   elif not parked and (proof.get('draftRecoveryPending') is True or proof.get('draftRestored') is not True):
    return {'state':'cleanup_pending','job':j['id'],'reason':'original-composer-evidence-missing'}
   if not navigation.finish(self.d,j):return {'state':'cleanup_pending','job':j['id'],'reason':'original-navigation-cleanup-unproved'}
   recovered=dict(proof,draftRestored=True,draftRecoveryPending=False,navigationRestored=True,navigationRecoveryPending=False,postActionPending=False,cleanupRecoveredBy='original-executor-primitives',cleanupRecoveredAt=time.time())
   actual=self.s.set_state(j['id'],'succeeded',recovered,expected=(j['state'],j['updated']))
   if actual['result']!=recovered:return {'state':'cleanup_pending','job':j['id'],'reason':'concurrent-original-change-preserved'}
   return {'state':'cleanup_recovered','job':j['id'],'automaticReplay':False}
  except Exception as exc:return {'state':'cleanup_pending','job':j['id'],'reason':'original-cleanup-unproved','type':type(exc).__name__}
  finally:self.d.release()
 def step(self):
  active=self.s.active()
  if not active:
   recovered=self.recover_accepted_cleanup()
   if recovered:return recovered
  if not active:
   ready=self.s.peek_ready()
   if not ready:
    self.d.release();return {'state':'waiting' if self.s.c.execute("SELECT 1 FROM jobs WHERE state='queued' LIMIT 1").fetchone() else 'idle'}
   from .dispatch import spec
   self.d.work_class='maintenance' if spec(self.s,ready)['kind']=='maintenance' else 'business'
  else:self.d.work_class='business' # finish/reconcile protected current work, never preempt
  if not self.d.acquire():return {'state':'window_busy'}
  try:
   previous=self.s.active();j=previous or self.s.claim();fresh_claim=previous is None and j is not None
   if not j:self.d.release();return {'state':'idle'}
   state=j['state']
   if state in ('unknown','needs_attention'):
    from .failed_text_retry import pending
    if state=='unknown' and getattr(self.s,'root',None) is not None and pending(self.s.root,j):
     return {'state':'unknown','job':j['id'],'automaticReplay':False}
    p=j.get('preview') or {}
    if state=='needs_attention':
     recovered=self.recover_expired_preview(j)
     if recovered:return recovered
     recovered=self.recover_image_attention(j)
     if recovered:return recovered
    if state=='needs_attention' and (j.get('result') or {}).get('reason')=='preparation_failed' and not self.s.c.execute("SELECT 1 FROM events WHERE job_id=? AND state IN ('confirmed','executing')",(j['id'],)).fetchone() and hasattr(self.d,'settle_preparation_failure') and self.d.settle_preparation_failure(j):
     self.s.set_state(j['id'],'failed',{'code':'NAVIGATION_PREPARATION_FAILED','reason':'Original pre-input navigation failed and owned baseline cleanup is verified.','sideEffectStarted':False,'noSend':True,'navigationRestored':True,'automaticReplay':False});self.d.release();return {'state':'failed','job':j['id']}
    if state=='needs_attention' and j.get('expires') and j['expires']<=time.time() and p.get('navigationBounds') and self.d.cleanup(j):self.s.set_state(j['id'],'expired',{'reason':'navigation_expired_before_input','noSend':True});self.d.release();return {'state':'expired','job':j['id']}
    if state=='needs_attention' and j.get('expires')==0 and self.d.cleanup(j):self.s.set_state(j['id'],'cancelled',{'reason':'caller_cancelled_and_owned_draft_cleanup_verified','noSend':True});self.d.release();return {'state':'cancelled'}
    proof=self.d.verify(j)
    if proof.get('state')=='accepted':
     proof=self.finalize(j,proof)
     self.s.set_state(j['id'],'succeeded',proof);self.d.release();return {'state':'succeeded','job':j['id']}
    return {'state':state,'job':j['id'],'automaticReplay':False}
   if state in ('awaiting_confirmation','needs_assistance','preparing'):
    from .dispatch import spec
    if spec(self.s,j)['kind']=='maintenance' and self.s.ready_business() and not (self.s.root/(j['id']+'-attempt.json')).exists() and not list(self.s.root.glob(j['id']+'-step-*')):
     pristine=fresh_claim and state=='preparing' and not j.get('preview') and not (self.s.root/(j['id']+'-composer.json')).exists() and not (self.s.root/(j['id']+'-navigation.json')).exists()
     if pristine or self.d.cleanup(j):
      self.s.set_state(j['id'],'cancelled',{'reason':'owned_maintenance_yielded_to_ready_business','noSend':True});self.d.release();return {'state':'cancelled','reason':'maintenance_yielded'}
     self.s.set_state(j['id'],'needs_attention',{'reason':'maintenance_yield_cleanup_unproven'});return {'state':'needs_attention'}
   if state in ('awaiting_confirmation','needs_assistance'):
    if j['expires']<=time.time():
     if self.d.cleanup(j):
      terminal='cancelled' if j['expires']==0 else 'expired'
      self.s.set_state(j['id'],terminal,{'reason':'caller_cancelled' if terminal=='cancelled' else 'preview_expired','noSend':True});self.d.release();return {'state':terminal}
     self.s.set_state(j['id'],'needs_attention',{'reason':'owned_draft_cleanup_not_proven'});return {'state':'needs_attention'}
    return {'state':state,'job':j['id']}
   if state=='preparing':
    try:
     preview=self.d.prepare(j);assist=preview.get('needs_assistance',False)
     saved=self.s.preview(j['id'],preview,state='needs_assistance' if assist else 'awaiting_confirmation')
     if saved.get('expires')==0:
      if self.d.cleanup(saved):self.s.set_state(j['id'],'cancelled',{'reason':'cancelled_during_preparation','noSend':True});self.d.release();return {'state':'cancelled','job':j['id']}
      self.s.set_state(j['id'],'needs_attention',{'reason':'cancelled_owned_draft_cleanup_not_proven','code':'OPERATOR_REQUIRED'});return {'state':'needs_attention','job':j['id']}
     if saved.get('execution_mode')=='verified_fast' and not assist:
      from .fast import final_scene,verify_certificate
      try:
       final_scene(saved,saved['preview']);cert=self.d.certify_fast(saved);verify_certificate(saved,saved['preview'],cert)
      except Exception:saved=self.s.review_fast(j['id'])
      else:saved=self.s.confirm_programmatic(j['id'],cert) or self.s.by_id(j['id'])
     return {'state':saved['state'],'job':j['id']}
    except Busy:return {'state':'window_busy','job':j['id']}
    except Exception as e:
     if (getattr(e,'clean',False) or getattr(e,'code',None) in ('QUOTE_NOT_VERIFIED','FORWARD_RECIPIENT_NOT_VISIBLE','FORWARD_BUTTON_NOT_SUPPORTED')) and self.d.cleanup(j):
      failure={'code':getattr(e,'code','PREPARATION_FAILED'),'reason':str(e)[:150],'sideEffectStarted':False,'noSend':True}
      phase=getattr(e,'preparationPhase',None)
      if phase in ('policy-and-identity','park-draft','stage-text','image-source','image-paste','image-copy-proof','file-chooser','preview','final-controls'):failure['preparationPhase']=phase
      self.s.set_state(j['id'],'failed',failure);self.d.release();return {'state':'failed','job':j['id']}
     # A failed preparation may have a visible draft; do not hide it or repeat.
     self.s.set_state(j['id'],'needs_attention',{'reason':'preparation_failed','type':type(e).__name__,'detail':str(e)[:150]});return {'state':'needs_attention','job':j['id']}
   if state=='confirmed':
    if j['expires']<=time.time():
     if self.d.cleanup(j):self.s.set_state(j['id'],'expired',{'reason':'confirmation_expired_before_execution','noSend':True});self.d.release();return {'state':'expired'}
     self.s.set_state(j['id'],'needs_attention',{'reason':'expired_confirmation_with_unproven_cleanup'});return {'state':'needs_attention'}
    current=self.s.begin_execution(j['id'])
    if not current:self.d.release();return {'state':self.s.by_id(j['id'])['state'],'job':j['id']}
    j=current
    try:
     proof=self.d.execute(j)
     if proof.get('state')=='continue':
      self.s.set_state(j['id'],'preparing',{'lastStepCompleted':True});j=self.s.by_id(j['id']);preview=self.d.prepare(j);self.s.preview(j['id'],preview,state='needs_assistance' if preview.get('needs_assistance') else 'awaiting_confirmation');return {'state':'needs_assistance','job':j['id']}
     if proof.get('state')=='accepted':
      proof=self.finalize(j,proof)
      self.s.set_state(j['id'],'succeeded',proof);self.d.release();return {'state':'succeeded','job':j['id']}
     self.s.set_state(j['id'],'unknown',proof);return {'state':'unknown','job':j['id'],'automaticReplay':False}
    except BeforeEffect as e:
     if self.d.cleanup(j):self.s.set_state(j['id'],'failed',dict({'reason':str(e)[:120],'sideEffectStarted':False,'noSend':True},**({'code':e.code} if getattr(e,'code',None) else {})));self.d.release();return {'state':'failed','job':j['id']}
     self.s.set_state(j['id'],'needs_attention',{'reason':'precondition_changed','detail':str(e)[:150],'sideEffectStarted':False});return {'state':'needs_attention'}
    except Exception as e:self.s.set_state(j['id'],'unknown',{'reason':'execution_result_unknown','type':type(e).__name__,'automaticReplay':False});return {'state':'unknown','job':j['id']}
   return {'state':state,'job':j['id']}
  except BaseException:self.d.release();raise

def run(store,driver,seconds=60,once=False):
 if type(seconds) is not int or not 1<=seconds<=3600:raise ValueError('bounded run duration required')
 fd=os.open(store.root/'executor.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
 try:
  locked=False;e=Executor(store,driver);end=time.monotonic()+seconds;last=None;published=0
  while time.monotonic()<end:
   if not locked:
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
     if once:return {'state':'window_busy'}
     time.sleep(.15);continue
    locked=True;store.recover()
   result=e.step()
   if result!=last or time.monotonic()-published>5:
    p=store.root/'health.json';tmp=p.with_suffix('.tmp');import json;from .lease import birth
    policy=getattr(driver,'policy',None);extra={}
    if policy is not None:
     from .contract import digest
     extra={'dispatchVersion':1,'policyFormatVersion':policy.format_version,'policyConfigSHA256':digest(policy.cfg)}
    tmp.write_text(json.dumps(dict(result,at=time.time(),pid=os.getpid(),birth=birth(os.getpid()),modelCalls=0,**extra)));tmp.chmod(0o600);os.replace(tmp,p);last=result;published=time.monotonic()
   if once:return result
   if result['state'] in ('needs_attention','unknown','idle','waiting','window_busy','cleanup_pending','cleanup_recovered'):
    # Original job state still blocks all ordinary admission/maintenance. Let
    # its existing guarded recovery acquire these SAME locks between checks;
    # never cancel/replay the original or hold recovery out for the whole run.
    driver.release();fcntl.flock(fd,fcntl.LOCK_UN);locked=False
   time.sleep(.4 if result['state'] in ('idle','waiting') else .15)
  return last or {'state':'window_busy'}
 finally:driver.release();os.close(fd)
