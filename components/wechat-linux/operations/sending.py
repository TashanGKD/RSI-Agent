"""One programmatic prepare/commit/finalize path for text, image and file sends."""
import hashlib,time,os
from pathlib import Path
from . import composer
from .runtime import BeforeEffect
from .recipes import PreparationError
from .navigation import header_key

def send_button(image,point):
 x,y=point;l=max(0,x-75);t=max(0,y-45);r=min(image.width,x+75);b=min(image.height,y+28);im=image.crop((l,t,r,b)).convert('RGB');w,h=im.size
 mask=bytearray(g>100 and g>red+65 and g>blue+35 for red,g,blue in im.getdata());found=[]
 for i in range(w*h):
  if not mask[i]:continue
  mask[i]=0;stack=[i];xs=[];ys=[]
  while stack:
   p=stack.pop();yy,xx=divmod(p,w);xs.append(xx);ys.append(yy)
   for q in ([p-1] if xx else [])+([p+1] if xx+1<w else [])+([p-w] if yy else [])+([p+w] if yy+1<h else []):
    if mask[q]:mask[q]=0;stack.append(q)
  if len(xs)>200 and max(xs)-min(xs)>=20 and max(ys)-min(ys)>=15:found.append([l+(min(xs)+max(xs))//2,t+(min(ys)+max(ys))//2])
 if len(found)!=1 or abs(found[0][0]-x)>25 or abs(found[0][1]-y)>10:raise ValueError('no unique enabled Send control in the calibrated region')
 return found[0]

def adopt(driver,j):
 p=j.get('preview') or {};value=composer.load(driver.root,j)
 if value:
  driver.session_bindings[j['peer']]=value['binding'];driver.active_window=value['window']
 elif p.get('uiBinding'):driver.session_bindings[j['peer']]=p['uiBinding']

def scene(driver,j,expected=None):
 from .recipes import main_window
 main_window(driver) # known search popup only; foreign chat windows are preserved
 windows=driver.app_windows()
 if expected is not None and windows!=expected:raise BeforeEffect('official window set changed; no Send click')
 return windows

def enabled(driver,ui):
 from .recipes import screen
 from .ocr import observe
 last=None
 for pause in (0,100,200,400,700):
  if pause:ui.settle(pause)
  try:
   image=screen(driver);point=send_button(image,ui.cfg['send'])
   # OCR only the white glyphs inside the proven green button; exclude emoji icons.
   from .selectors import unique_line
   x,y=point;label=image.crop((x-25,y-11,x+26,y+12)).convert('RGB');label.putdata([(0,0,0) if v[0]>70 else (255,255,255) for v in label.getdata()]);label=label.resize((label.width*2,label.height*2))
   unique_line(observe(label,driver.previews,psm=6,lang='eng')[0],'Send')
   if last==point:return point
   last=point
  except ValueError:last=None
 raise BeforeEffect('Send control is absent, disabled, ambiguous or outside the calibrated layout')

def preview(driver,j,ui,window):
 from .recipes import screen
 image=screen(driver);box=(ui.cfg['header_box'][0],window['y']+35,window['x']+window['width'],window['y']+window['height'])
 if not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:raise BeforeEffect('target chat preview is outside the supported display')
 image=image.crop(box);path=driver.previews/(j['id']+'.png');tmp=path.with_suffix('.tmp')
 if path.is_symlink() or tmp.is_symlink():raise BeforeEffect('preview symlink refused')
 fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:image.save(f,format='PNG');f.flush();os.fsync(f.fileno())
 os.replace(tmp,path);data=path.read_bytes()
 return {'artifact':j['id'],'sha256':hashlib.sha256(data).hexdigest(),'width':image.width,'height':image.height,'screenshotBytes':len(data),'targetChatOnly':True}

def prepare(driver,j):
 from .recipes import main_window
 from .driver import preview_context
 from .visual import attachment_box
 asset=None
 if j['action']=='send_image':
  from .assets import validate_image
  asset=driver.assets.get(j['client'],j['payload']['asset'])
  if asset['bytes']>10000000:raise PreparationError('SEND_PREPARATION_FAILED','Clipboard image byte budget exceeded.')
  data=Path(asset['path']).read_bytes()
  if validate_image(data):
   raise PreparationError('ANIMATED_IMAGE_UNSUPPORTED','The image draft transport supports one frame.')
 driver._select(j);window=main_window(driver);windows=scene(driver,j)
 try:ui=driver.ui(j['peer'])
 except ValueError:raise PreparationError('RECIPIENT_NOT_VERIFIED','Target changed before input; no composer was modified.') from None
 phase='policy-and-identity'
 try:
  versions=None
  if j.get('execution_mode')=='verified_fast':
   from .fast import binding_identity
   versions=driver.fast_versions(j)
   if versions['bindingIdentitySHA256']!=binding_identity(ui.cfg):raise BeforeEffect('session identity differs from current registration')
  phase='park-draft';parked=composer.park(driver,j,ui,window);file_selection=None
  if j['action']=='send_text':
   phase='stage-text';ui.stage(j['payload']['text'],None)
  elif j['action']=='send_image':
   from . import image_draft
   from gi.repository import GdkPixbuf
   phase='image-source';loader=GdkPixbuf.PixbufLoader.new();loader.write(data);loader.close()
   identity=image_draft.pixel_identity(loader.get_pixbuf())
   # Record ownership before paste, so failure before preview can still be cleaned.
   parked.update(state='image-paste-pending',imageIdentity=identity,imageAssetSHA256=asset['sha256']);composer.save(driver.root,j,parked)
   phase='image-paste';ui.clip.set_image(loader.get_pixbuf());ui.ctrl('v');ui.settle(700)
   phase='image-copy-proof';image_draft.verify(ui,identity)
   parked.update(imagePasteVerified=True,imageCopyProbes=getattr(ui,'imageCopyProbes',None));composer.save(driver.root,j,parked)
  else:
   from .recipes import controls
   phase='file-chooser';asset=driver.assets.get(j['client'],j['payload']['asset']);ui.click([ui.cfg['header_box'][0]+105,ui.cfg['send'][1]]);ui.settle(450)
   dialogs=[w for w in driver.app_windows() if w['title']=='Select File' and (w['width'],w['height'],w['x'],w['y'])==(647,432,0,0)]
   if len(dialogs)!=1:raise BeforeEffect('one supported official file chooser required')
   parked.update(ownChooser=dialogs[0]);composer.save(driver.root,j,parked)
   ui.click([260,375]);ui.ctrl('a');ui.clip.set_text(asset['path'],-1);ui.settle(70);ui.ctrl('v');ui.settle(150);ui.ctrl('a');ui.ctrl('c');ui.settle(130)
   if ui.clip.wait_for_text()!=asset['path'] or not driver._file_helper().chooser_present():raise BeforeEffect('file chooser path differs from the frozen asset')
   ui.click([20,375]);ui.settle(100);ui.click([595,375]);ui.settle(500)
   if driver._file_helper().chooser_present():raise BeforeEffect('file chooser did not complete')
   parked.pop('ownChooser',None)
   from .fast import asset_identity
   from .contract import digest
   file_selection={'assetIdentitySHA256':digest(asset_identity(asset)),'chooserPathSHA256':hashlib.sha256(asset['path'].encode()).hexdigest(),'chooserPathVerified':True,'chooserCompleted':True}
   parked['fileSelection']=file_selection
  phase='preview';ui.check();p=dict(preview(driver,j,ui,window),senderRecipe=True,programRecipe=True,uiBinding=dict(ui.cfg),sendWindows=windows,summary={'peer':j['peer'],'action':j['action'],'text':j['payload'].get('text'),'priorTextDraftPreserved':bool(parked.get('priorText'))},text=j['payload'].get('text',''),asset=asset)
  if versions:p['fastVersions']=versions
  if j['action']=='send_image':
   p.update(imageIdentity=identity,imageDraftVerified=True)
  elif asset:
   if j['action']=='send_file':
    # Metadata-only observation, not an eligibility claim. Unknown formats
    # retain the ordinary manual workflow; no clipboard path is opened.
    from . import file_draft
    p['fileDraftObservation']=file_draft.read(ui,asset)
    native=p['fileDraftObservation'].get('nativeFileVerified') is True
    try:ocr=driver._file_helper().preview_matches(driver._file_helper().preview(ui,driver.previews/(j['id']+'-filename.png')),asset['name'])
    except Exception:ocr=False
    # The old exact OCR result remains separate. Full native single-file
    # reference is a stronger, explicit proof when the visual label ellipsizes.
    p.update(fileSelection=file_selection,filenameOCRProgramVerified=bool(ocr),nativeFileDraftVerified=native,filenameProgramVerified=bool(ocr or native),filenameVerificationMethod='native-single-file-reference' if native else 'exact-ocr' if ocr else 'unverified')
   im=ui.ui.screenshot();box=attachment_box(im,[ui.cfg['header_box'][0]+20,ui.cfg['editor'][1]-30,ui.cfg['header_box'][2]-40,ui.cfg['send'][1]-24]);p.update(attachmentBox=box,attachmentContext=hashlib.sha256(im.crop(tuple(box)).tobytes()).hexdigest())
  else:
   header=header_key(driver,ui);p['context']=preview_context(j['peer'],header,j['payload']['text'],None)
  phase='final-controls';parked.update(state='staged',preview=p);composer.save(driver.root,j,parked);enabled(driver,ui);scene(driver,j,windows)
  p.update(preview(driver,j,ui,window));return p
 except composer.DraftProtected as e:
  if composer.load(driver.root,j) and not cleanup(driver,j):raise PreparationError('DRAFT_RECOVERY_PENDING','Original text is privately preserved; cleanup/restore is not proven.',clean=False) from None
  raise PreparationError('DRAFT_PROTECTED',str(e)) from None
 except Exception as e:
  safe=cleanup(driver,j)
  # Finite operational facts only. Never persist exception text, business
  # payload, arbitrary paths or clipboard contents in diagnostic metadata.
  import json,re
  diagnostic={'phase':phase,'errorType':type(e).__name__ if re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,79}',type(e).__name__) else 'Exception','ownedCleanupVerified':bool(safe),'at':time.time()}
  try:
   composer.path(driver.root,j)
   target=driver.root/(j['id']+'-preparation-failure.json');tmp=target.with_suffix('.tmp')
   if target.exists() or target.is_symlink() or tmp.exists() or tmp.is_symlink():raise ValueError('existing preparation evidence preserved')
   fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
   with os.fdopen(fd,'wb') as out:out.write(json.dumps(diagnostic).encode());out.flush();os.fsync(out.fileno())
   os.replace(tmp,target)
  except Exception:pass
  failure=PreparationError('SEND_PREPARATION_FAILED',str(e)[:120] if isinstance(e,BeforeEffect) else 'Program could not complete its owned preparation; retained evidence.',clean=safe)
  failure.preparationPhase=phase
  raise failure from None
 finally:ui.close()

def verify_fast_payload(driver,j,ui,value):
 from .fast import asset_identity
 from .contract import digest
 from .driver import preview_context
 from .recipes import screen
 p=j['preview']
 if j['action']=='send_text':
  actual=ui.draft();header=header_key(driver,ui)
  if actual!=j['payload']['text'] or preview_context(j['peer'],header,actual,None)!=p.get('context'):raise BeforeEffect('exact final text or target changed')
  return {}
 try:asset=driver.assets.get(j['client'],j['payload']['asset']);identity=asset_identity(asset)
 except (ValueError,PermissionError,OSError):raise BeforeEffect('uploaded asset is no longer proven') from None
 if identity!=asset_identity(p.get('asset')):raise BeforeEffect('asset differs from frozen preview')
 if j['action']=='send_image':
  from . import image_draft
  if p.get('imageDraftVerified') is not True or value.get('imageIdentity')!=p.get('imageIdentity') or value.get('imageAssetSHA256')!=asset['sha256']:raise BeforeEffect('image to uploaded asset proof missing')
  try:image_draft.verify(ui,p['imageIdentity'])
  except (ValueError,OSError):raise BeforeEffect('actual unique image/RGBA reference is unproven') from None
 elif j['action']=='send_file':
  from . import file_draft
  selection=p.get('fileSelection') or {}
  if p.get('filenameProgramVerified') is not True or p.get('nativeFileDraftVerified') is not True or selection!=value.get('fileSelection') or selection.get('chooserPathVerified') is not True or selection.get('chooserCompleted') is not True or selection.get('assetIdentitySHA256')!=digest(identity) or selection.get('chooserPathSHA256')!=hashlib.sha256(asset['path'].encode()).hexdigest():raise BeforeEffect('full filename/chooser/asset proof missing')
  try:proof=file_draft.verify(ui,asset)
  except (ValueError,OSError):raise BeforeEffect('actual sole native file reference is unproven') from None
  if proof.get('nativeFileVerified') is not True or hashlib.sha256(screen(driver).crop(tuple(p['attachmentBox'])).tobytes()).hexdigest()!=p['attachmentContext']:raise BeforeEffect('native file or frozen card changed')
 else:raise BeforeEffect('unsupported fast asset kind')
 return {'assetIdentitySHA256':digest(identity)}

def certify_fast(driver,j):
 import stat
 from .fast import final_scene,binding_identity
 from .contract import digest
 p=j.get('preview') or {};versions=final_scene(j,p);driver.check_lease(driver.lease);adopt(driver,j)
 path=driver.previews/(j['id']+'.png')
 try:
  fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
  with os.fdopen(fd,'rb') as f:
   before_stat=os.fstat(f.fileno())
   if not stat.S_ISREG(before_stat.st_mode) or before_stat.st_uid!=os.getuid() or before_stat.st_mode&0o077 or not 0<before_stat.st_size<=4000000:raise BeforeEffect('unproven private preview artifact')
   data=f.read(4000001);after_stat=os.fstat(f.fileno())
  if (before_stat.st_ino,before_stat.st_size,before_stat.st_mtime_ns)!=(after_stat.st_ino,after_stat.st_size,after_stat.st_mtime_ns) or hashlib.sha256(data).hexdigest()!=p['sha256']:raise BeforeEffect('preview artifact changed')
 except OSError:raise BeforeEffect('private preview artifact unavailable') from None
 value=composer.load(driver.root,j)
 if not value or value.get('state')!='staged' or type(value.get('priorChars')) is not int or value['priorChars']!=0 or value.get('priorText')!='' or value.get('priorSHA')!=hashlib.sha256(b'').hexdigest():raise BeforeEffect('unproved or prior foreign composer')
 if driver.fast_versions(j)!=versions or binding_identity(value['binding'])!=versions['bindingIdentitySHA256']:raise BeforeEffect('native registration or scope changed')
 scene(driver,j,p['sendWindows']);ui=driver.ui(j['peer'])
 try:
  ui.check();payload_proof=verify_fast_payload(driver,j,ui,value)
  enabled(driver,ui);scene(driver,j,p['sendWindows']);ui.check();driver.check_lease(driver.lease)
  if j['action']=='send_text' and ui.draft()!=j['payload']['text']:raise BeforeEffect('final text changed during certification')
  return dict({'version':1,'eligible':True,'guardVerified':True,'peer':j['peer'],'action':j['action'],'payloadSHA256':digest(j['payload']),'previewSHA256':p['sha256'],'versions':versions},**payload_proof)
 finally:ui.close()

def cleanup(driver,j):
 value=composer.load(driver.root,j)
 if not value or value['state']=='restored':return True
 if (driver.root/(j['id']+'-attempt.json')).exists():return False
 try:
  proof=value['binding'].get('nativeTargetProof')
  if proof:
   if value.get('window')!=proof.get('window'):return False
   from .navigation import verify_session
   verify_session(driver,value['binding'],j['peer'])
  adopt(driver,j)
  own=value.get('ownChooser');windows=driver.app_windows()
  if own and own in windows:
   from .recipes import controls
   c=controls(driver)
   try:c.focus(own);c.require_focus(own);c.key(0xff1b);c.wait(120)
   finally:c.close()
   if own in driver.app_windows():return False
  scene(driver,j)
  if proof:
   from .recipes import controls,activate
   c=controls(driver)
   try:activate(c,proof['window'])
   finally:c.close()
  ui=driver.ui(j['peer'])
  try:
   if j['action']=='send_image' and value.get('imageIdentity'):
    from . import image_draft
    try:image_draft.verify(ui,value['imageIdentity'])
    except ValueError:
     # Qt may still insert a requested paste after an empty-looking frame.
     # Only an already proven paste can use the ordinary empty-editor branch.
     if value.get('state')=='image-paste-pending' and not value.get('imagePasteVerified'):return False
     driver._file_helper().require_empty_editor(ui)
    else:composer.clear(ui)
    driver._file_helper().require_empty_editor(ui)
    return composer.restore(driver.root,j,ui,lambda:driver._file_helper().require_empty_editor(ui))
   actual=ui.draft();p=value.get('preview') or {}
   if value['state']=='staged':
    if j['action']=='send_text':
     if actual and actual!=j['payload']['text']:return False
     if actual:composer.clear(ui)
    else:
     if not p:return False
     composer.deselect(ui);im=ui.ui.screenshot()
     if hashlib.sha256(im.crop(tuple(p['attachmentBox'])).tobytes()).hexdigest()!=p['attachmentContext']:return False
     composer.clear(ui)
   elif actual:return False
   driver._file_helper().require_empty_editor(ui)
   return composer.restore(driver.root,j,ui,lambda:driver._file_helper().require_empty_editor(ui))
  finally:ui.close()
 except Exception:return False

def execution_mark(driver,j,state,**extra):
 import re
 from .contract import digest
 # This is evidence for the original job, not an alternate dispatch queue.
 composer.path(driver.root,j)
 p=driver.root/(j['id']+'-execution-check.json');tmp=p.with_suffix('.tmp')
 if p.is_symlink() or tmp.exists() or tmp.is_symlink():raise BeforeEffect('execution checkpoint path is not safe')
 v={'jobId':j['id'],'peer':j['peer'],'payloadHash':digest(j['payload']),'state':state,'at':time.time(),**extra}
 if p.exists():
  if p.stat().st_mode&0o077 or p.stat().st_size>4000:raise BeforeEffect('private bounded execution checkpoint required')
  old=__import__('json').loads(p.read_text())
  if any(old.get(k)!=v[k] for k in ('jobId','peer','payloadHash')):raise BeforeEffect('execution checkpoint identity changed')
 raw=__import__('json').dumps(v,ensure_ascii=False).encode()
 if len(raw)>4000:raise BeforeEffect('execution checkpoint budget')
 fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p)

def execute(driver,j):
 attempt=driver.root/(j['id']+'-attempt.json')
 if attempt.exists() or attempt.is_symlink():raise RuntimeError('original attempt already exists; reconcile only, never execute twice')
 checkpoint=driver.root/(j['id']+'-execution-check.json')
 if checkpoint.exists() or checkpoint.is_symlink():raise RuntimeError('original execution checkpoint exists; reconcile only, never overwrite for another click')
 try:execution_mark(driver,j,'pre-send-validation')
 except Exception:
  failure=BeforeEffect('Execution checkpoint could not be recorded before entering terminal code.');failure.code='PRE_SEND_VALIDATION_FAILED';raise failure from None
 try:return _execute(driver,j)
 except Exception as error:
  prior=__import__('json').loads((driver.root/(j['id']+'-execution-check.json')).read_text())
  if attempt.exists() or attempt.is_symlink() or prior.get('state')=='terminal-boundary':
   # Even a validation-looking exception after this durable boundary is unknown.
   raise RuntimeError('terminal attempt exists; original-request reconciliation required') from error
  if isinstance(error,BeforeEffect):raise
  execution_mark(driver,j,'validation-failed',lastPhase=prior['state'],noSend=True,errorType=type(error).__name__,privateReason=str(error)[:150])
  failure=BeforeEffect('Pre-send validation failed before the terminal boundary; preserve original receipt for mechanism review.')
  failure.code='PRE_SEND_VALIDATION_FAILED';raise failure from None

def _execute(driver,j):
 from .driver import preview_context
 from sender import before
 from .recipes import screen
 adopt(driver,j);p=j['preview'];scene(driver,j,p['sendWindows']);execution_mark(driver,j,'scene-verified');ui=driver.ui(j['peer'])
 try:
  if j['action']=='send_text':
   actual=ui.draft();header=header_key(driver,ui)
   if preview_context(j['peer'],header,actual,None)!=p['context']:raise BeforeEffect('target or exact draft changed')
  elif j['action']=='send_image':
   from . import image_draft
   asset=driver.assets.get(j['client'],j['payload']['asset'])
   if asset['sha256']!=p['asset']['sha256']:raise BeforeEffect('uploaded image asset changed')
   image_draft.verify(ui,p['imageIdentity'])
  else:
   asset=driver.assets.get(j['client'],j['payload']['asset'])
   if asset['sha256']!=p['asset']['sha256'] or hashlib.sha256(screen(driver).crop(tuple(p['attachmentBox'])).tobytes()).hexdigest()!=p['attachmentContext']:raise BeforeEffect('frozen attachment changed')
  execution_mark(driver,j,'payload-verified');point=enabled(driver,ui);scene(driver,j,p['sendWindows']);ui.check()
  if j['action']=='send_text':
   if ui.draft()!=j['payload']['text']:raise BeforeEffect('exact draft changed before final Send')
  elif j['action']=='send_image':image_draft.verify(ui,p['imageIdentity'])
  elif hashlib.sha256(screen(driver).crop(tuple(p['attachmentBox'])).tobytes()).hexdigest()!=p['attachmentContext']:raise BeforeEffect('attachment changed before final Send')
  if j.get('execution_mode')=='verified_fast':
   from .fast import verify_certificate
   driver.check_lease(driver.lease)
   if driver.fast_versions(j)!=p.get('fastVersions'):raise BeforeEffect('registered identity or policy changed before Send')
   if p.get('confirmationSource')=='programmatic':verify_certificate(j,p,p.get('fastVerification'))
   ui.check()
   if p.get('confirmationSource')=='programmatic':verify_fast_payload(driver,j,ui,composer.load(driver.root,j) or {})
   elif j['action']=='send_text' and ui.draft()!=j['payload']['text']:raise BeforeEffect('fast final draft changed')
  execution_mark(driver,j,'final-validation-passed');baseline=before(j['peer']);execution_mark(driver,j,'native-baseline-read')
  started=time.time();driver._save_attempt(j,{'beforeIds':baseline,'startedAt':started,'peer':j['peer'],'action':j['action'],'text':j['payload'].get('text'),'asset':p.get('asset'),'clickScheduled':True})
  execution_mark(driver,j,'terminal-boundary')
  ui.click(point) # exactly one click; unknown never becomes an automatic second click
  for pause in (.1,.2,.4,.8,1,1,1,1,1,1,1,1):
   ui.settle(int(pause*1000));proof=driver.verify(j)
   if proof.get('state')=='accepted':return dict(proof,executionSeconds=time.time()-started,sendClicks=1)
  return {'state':'unknown','reason':'unique native receipt not yet proven','automaticReplay':False,'sendClicks':1}
 finally:ui.close()

def finalize(driver,j,proof):
 value=composer.load(driver.root,j)
 if not value:return proof
 try:
  adopt(driver,j);scene(driver,j);ui=driver.ui(j['peer'])
  try:restored=composer.restore(driver.root,j,ui,lambda:driver._file_helper().require_empty_editor(ui))
  finally:ui.close()
 except Exception:restored=False
 return dict(proof,priorTextDraftPreserved=bool(value.get('priorChars')),draftRestored=restored,draftRecoveryPending=not restored)
