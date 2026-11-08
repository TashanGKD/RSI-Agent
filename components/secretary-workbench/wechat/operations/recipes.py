"""Deterministic UI recipes behind the business API. No model or caller plans."""
import hashlib,json,time,os,tempfile
from pathlib import Path
from .runtime import BeforeEffect
from .selectors import unique_line
from .ocr import observe

class PreparationError(BeforeEffect):
 def __init__(self,code,message,clean=True):super().__init__(message);self.code=code;self.clean=clean

def _modal_record(driver,state,reason,windows,offending=(),**proof):
 # One bounded last-result receipt, never chat/draft text or private titles.
 root=getattr(driver,'root',None)
 if root is None:return
 temp=None
 try:
  path=Path(root)/'modal-check.json'
  if path.is_symlink():return
  data={'at':time.time(),'pid':os.getpid(),'state':state,'reason':reason,'activeWindowId':(getattr(driver,'active_window',None) or {}).get('id'),'offendingWindowIds':list(offending)[:32],
   'windows':[dict({k:w.get(k) for k in ('id','x','y','width','height')},titleSHA256=hashlib.sha256(w.get('title','').encode()).hexdigest()) for w in windows[:32]],'truncated':len(windows)>32,**proof}
  fd,temp=tempfile.mkstemp(dir=root,prefix='.modal-',suffix='.tmp')
  with os.fdopen(fd,'w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
  os.replace(temp,path);temp=None
 except (OSError,ValueError,TypeError):pass # Diagnostics must never turn rejection into permission.
 finally:
  if temp:
   try:os.unlink(temp)
   except OSError:pass

def _search_scene(driver,popup):
 from .selectors import _search_section
 from .ocr import normalized
 box=[popup['x'],popup['y'],popup['x']+popup['width'],popup['y']+popup['height']];image=screen(driver)
 if not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:raise ValueError('official search scene is outside display')
 # Empty global search has only public navigation labels, not a native
 # contact/group result. Inspect the header only: private recent terms below
 # it are neither needed for classification nor copied into diagnostics.
 if popup['width']==333 and popup['height']>=104:
  labels=('searchresults','articlesofficialaccountsandchannels','recentsearches');areas=([52,9,270,36],[52,33,325,61],[8,66,220,104]);matches=[]
  # Exclude the icon/chevron/ellipsis, rather than tolerating their OCR noise.
  for label,area in zip(labels,areas):
   region=[box[0]+area[0],box[1]+area[1],box[0]+area[2],box[1]+area[3]];header,_=observe(image,driver.previews,region,psm=6,lang='eng')
   matches.append([v for v in header if normalized(v['text'])==label and region[0]<v['point'][0]<region[2] and region[1]<v['point'][1]<region[3]])
  if all(len(v)==1 for v in matches):
   points=[v[0]['point'] for v in matches]
   if all(box[0]<x<box[2] and box[1]<y<box[1]+104 for x,y in points) and points[0][1]<points[1][1]<points[2][1]:
    return {'box':box,'pixelsSHA256':hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest(),'variant':'empty-recent-searches','sections':[{'kind':'web','y':points[0][1]},{'kind':'recent-searches','y':points[2][1]}]}
 values,_=observe(image,driver.previews,box);sections=[(v['point'][1],'history' if normalized(v['text']) in ('chathistory','聊天记录') else _search_section(v['text'])) for v in values if _search_section(v['text'])]
 kinds=[kind for _,kind in sections]
 if kinds.count('web')!=1 or not 1<=sum(kind in ('group','contact') for kind in kinds)<=2 or len(kinds)!=len(set(kinds)) or any(kind not in ('web','group','contact','history') for kind in kinds) or len({y for y,_ in sections})!=len(sections):raise ValueError('exact official search sections are not proven')
 if 'history' in kinds:
  history=next(y for y,kind in sections if kind=='history');web=next(y for y,kind in sections if kind=='web')
  if not max(y for y,kind in sections if kind in ('group','contact'))<history<web:raise ValueError('official history section order is not proven')
 return {'box':box,'pixelsSHA256':hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest(),'sections':[{'kind':kind,'y':y} for y,kind in sorted(sections)]}

def main_window(driver):
 windows=[]
 def deny(message,reason,offending=(),clean=True):
  _modal_record(driver,'rejected',reason,windows,offending)
  raise PreparationError('UNSUPPORTED_LAYOUT',message,clean=clean)
 try:
  windows=driver.app_windows();active=getattr(driver,'active_window',None);main=[v for v in windows if v['id']==active['id']] if active else [v for v in windows if v['title']=='Weixin']
  if len(main)!=1:raise ValueError('main window not unique')
  w=main[0]
 except ValueError:deny('A unique official main window is required; existing modal left unchanged.','ACTIVE_WINDOW_MISSING_OR_AMBIGUOUS')
 if (w['width'],w['height']) not in ((905,667),(623,667)):deny('The current official-client geometry is not a supported calibrated layout.','ACTIVE_GEOMETRY_UNSUPPORTED',[w['id']])
 extras=[v for v in windows if v['id']!=w['id'] and not (v['title']=='Weixin' and (v['width'],v['height'])==(905,667)) and not ((v['width'],v['height'])==(623,667) and getattr(driver,'known_chat_window',lambda title:False)(v['title']))]
 if extras:
  # The search popup belongs to the host main, even while a verified popout is active.
  hosts=[v for v in windows if v['title']=='Weixin' and (v['width'],v['height'])==(905,667)]
  if len(hosts)!=1 or len(extras)!=1:deny('An unrelated or ambiguous official modal is visible; it was left unchanged.','MODAL_OR_HOST_AMBIGUOUS',[v['id'] for v in extras])
  host=hosts[0];popup=extras[0]
  from .windows import search_parent_proof,search_geometry
  if not search_geometry(popup,host):deny('An unrelated official modal is visible; it was left unchanged.','MODAL_GEOMETRY_UNSUPPORTED',[popup['id']])
  try:
   identity=search_parent_proof(popup,host);scene=_search_scene(driver,popup)
   if driver.app_windows()!=windows or search_parent_proof(popup,host)!=identity or hashlib.sha256(screen(driver).crop(tuple(scene['box'])).tobytes()).hexdigest()!=scene['pixelsSHA256']:raise ValueError('search scene changed')
  except ValueError:deny('Official search parent or exact scene is unproven; it was left unchanged.','SEARCH_PARENT_OR_SCENE_UNPROVEN',[popup['id']])
  c=controls(driver)
  try:c.click(host['x']+500,host['y']+55);c.wait(120)
  finally:c.close()
  after=driver.app_windows()
  for delay in (80,160,320,500):
   if popup['id'] not in {v['id'] for v in after}:break
   c=controls(driver)
   try:c.wait(delay)
   finally:c.close()
   after=driver.app_windows()
  if popup['id'] in {v['id'] for v in after}:deny('Search popup could not be dismissed by its supported non-editing action.','SEARCH_DISMISS_NOT_PROVEN',[popup['id']])
  if after!=[v for v in windows if v['id']!=popup['id']]:deny('Official window set changed during search cleanup; preserve the scene.','WINDOW_SET_CHANGED_AFTER_DISMISS',clean=False)
  _modal_record(driver,'search_dismissed','OFFICIAL_SEARCH_PARENT_AND_SCENE_VERIFIED',windows,(),**identity,sceneSHA256=scene['pixelsSHA256'],sections=scene['sections'])
 return w

def activate(c,w):
 import ctypes
 c.x.XRaiseWindow.argtypes=[ctypes.c_void_p,ctypes.c_ulong];c.x.XRaiseWindow(c.d,int(w['id'],16));c.focus(w);c.wait(100)

def controls(driver):
 # All maintenance/read callers use this existing factory. A failed acquire,
 # release, or new guard epoch must stop input even after a REPL assertion.
 held=getattr(driver,'fds',None);expected=getattr(driver,'lease',None)
 def require_guard():
  if not held or getattr(driver,'fds',None) is not held or not callable(getattr(driver,'check_lease',None)):raise BeforeEffect('Original native input guard unavailable; no UI input.')
  driver.check_lease(expected)
 require_guard()
 from image_client import Controls
 from .driver import BASE
 raw=Controls(BASE)
 class GuardedFunction:
  def __init__(self,target):object.__setattr__(self,'_target',target)
  def __call__(self,*args,**kwargs):require_guard();return self._target(*args,**kwargs)
  def __getattr__(self,name):require_guard();return getattr(self._target,name)
  def __setattr__(self,name,value):require_guard();setattr(self._target,name,value)
 class GuardedLibrary:
  def __init__(self,target):self._target=target
  def __getattr__(self,name):
   require_guard();value=getattr(self._target,name)
   return GuardedFunction(value) if callable(value) else value
 class GuardedControls:
  def __getattr__(self,name):
   if name=='close':return raw.close # Closing this connection is always safe.
   require_guard()
   if name=='open_viewer_save':
    def open_save(viewer):
     require_guard()
     from image_client import open_viewer_save
     return open_viewer_save(self,viewer,lambda:screen(driver),require_guard)
    return open_save
   value=getattr(raw,name)
   if name in ('x','t'):return GuardedLibrary(value)
   if not callable(value):return value
   if name=='click':
    def guarded_click(x,y):
     require_guard()
     viewer=raw.one('Photos and Videos',True)
     if (viewer and viewer['x']+518<=x<viewer['x']+640
         and viewer['y']<=y<viewer['y']+44):
      from image_client import prove_viewer_save_input
      prove_viewer_save_input(raw,viewer,lambda:screen(driver),require_guard,point=[x,y])
     require_guard();return value(x,y)
    return guarded_click
   def guarded(*args,**kwargs):require_guard();return value(*args,**kwargs)
   return guarded
 return GuardedControls()

def screen(driver):
 from sender import UI
 from .driver import BASE
 return UI(BASE).screenshot()

def rows(driver,box,contrast=False,psm=11,lang="chi_sim+eng"):
 image=screen(driver)
 if contrast:
  threshold=210 if contrast is True else int(contrast)
  image=image.convert('L').point(lambda p:0 if p<threshold else 255).convert('RGB')
 return observe(image,driver.previews,box,psm=psm,lang=lang)[0]

def paste_field(c,point,text,replace=True):
 import gi,secrets
 gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk
 clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);c.click(*point);c.wait(100)
 if replace:c.key(0x61,True)
 clip.set_text(text,-1);c.wait(80);c.key(0x76,True);c.wait(250)
 clip.set_text('WRITE_COPY_PROBE_'+secrets.token_hex(12),-1);c.wait(60);c.key(0x61,True);c.key(0x63,True);c.wait(180)
 if clip.wait_for_text()!=text:raise PreparationError('INPUT_MISMATCH','Actual editable text differs from the frozen business request.',clean=False)
 return text

def search_identity(target,cfg,members=(),resolved_names=None):
 name=target['displayName'];peer=target['username']
 if name!=peer:
  title=name
  if peer=='filehelper' and cfg.get('observedTitle'):
   from sender import visual_title
   title=visual_title(target,cfg['observedTitle'])
  return target.get('alias') or name,[title]
 if not peer.endswith('@chatroom'):raise ValueError('native contact has no searchable verified name')
 expected=cfg.get('nativeMemberIds');title=cfg.get('observedTitle','')
 import re
 parsed=re.fullmatch(r'(.+)[(（](\d+)[)）]',title)
 if not expected or set(expected)!=set(members) or not parsed or int(parsed[2])!=len(set(members)):raise ValueError('unnamed group membership/title is not independently verified')
 base=parsed[1];names=resolved_names or {};parts=base.split('、');account=cfg.get('paired_account')
 if account not in members or len(parts)!=len(set(members))-1 or {names.get(v) for v in parts}!=set(members)-{account}:raise ValueError('all displayed member names must independently resolve to the complete remaining member set')
 query=next((v for v in parts if names.get(v) in set(members)),None)
 if not query:raise ValueError('no unique verified member name for unnamed-group search')
 return query,[base,title]

def selected(driver,j,force_search=False):
 """Cached title/template first; exact official search plus header proof otherwise."""
 from sender import validate_binding
 target=driver.tool().resolve(j['peer']);windows=driver.app_windows()
 try:cfg=getattr(driver,'binding',lambda peer:{})(j['peer'])
 except ValueError:cfg={}
 try:
  if target['displayName']!=j['peer'] and getattr(driver,'name_peer',lambda name:driver.tool().resolve(name)['username'])(target['displayName'])!=j['peer']:raise ValueError('native name is not globally unique')
  members=driver.group_identity(j['peer'],cfg) if target['displayName']==j['peer'] and j['peer'].endswith('@chatroom') else []
  resolved={}
  if members:
   import re
   base=re.sub(r'[(（]\d+[)）]$','',cfg.get('observedTitle',''))
   for name in base.split('、'):
    try:resolved[name]=getattr(driver,'name_peer',lambda value:driver.tool().resolve(value)['username'])(name)
    except ValueError:pass
  query,search_names=search_identity(target,cfg,members,resolved)
 except ValueError:raise PreparationError('TARGET_NAME_UNAVAILABLE','Target name or complete native-member/title proof is unavailable or ambiguous.') from None
 popouts=[v for v in windows if v['title'] in search_names and (v['width'],v['height'])==(623,667)]
 if len(popouts)>1:raise PreparationError('RECIPIENT_NOT_VERIFIED','Multiple same-title chat windows are ambiguous.')
 if popouts:
  if not members and getattr(driver,'name_peer',lambda name:driver.tool().resolve(name)['username'])(target['displayName'])!=j['peer']:raise PreparationError('RECIPIENT_NOT_VERIFIED','Chat window title does not uniquely map to the native peer.')
  w=popouts[0]
  if j.get('id') and getattr(driver,'navigation_job_id',None)==j['id']:
   from .navigation import load,prove_popout
   from .windows import window_identity
   prove_popout(w,w['title'],window_identity(w),load(driver.root,j)['mainIdentity'])
  driver.active_window=w;main_window(driver);c=controls(driver)
  try:activate(c,w)
  finally:c.close()
  box=[w['x']+1,w['y']+35,w['x']+w['width']-1,w['y']+82]
  # Geometry adapts to this window; keep the verified native identity for the
  # next request and for cleanup/adoption in this same long-lived driver.
  driver.session_bindings[j['peer']]=dict(cfg,peer=j['peer'],displayName=target['displayName'],header_box=box,header_sha256=hashlib.sha256(screen(driver).crop(tuple(box)).tobytes()).hexdigest(),editor=[w['x']+280,w['y']+554],send=[w['x']+w['width']-50,w['y']+w['height']-32])
  if j.get('id') and getattr(driver,'navigation_job_id',None)==j['id']:
   from .navigation import attach
   driver.session_bindings[j['peer']]=attach(driver,j,driver.session_bindings[j['peer']],w)
  return None
 driver.active_window=None;driver.session_bindings.pop(j['peer'],None)
 w=main_window(driver)
 c=controls(driver)
 try:activate(c,w)
 finally:c.close()
 try:cfg=driver.binding(j['peer'])
 except ValueError:raise PreparationError('TARGET_NOT_CALIBRATED','This target has no verified client binding.') from None
 image=screen(driver)
 if j.get('id') and getattr(driver,'navigation_job_id',None)==j['id'] and target['displayName']!=j['peer']:
  from .navigation import search_named
  return search_named(driver,j,target,cfg,query)
 try:
  if force_search:raise ValueError('refresh through verified native search')
  validate_binding(cfg,{'username':j['peer']},image.crop(tuple(cfg['header_box'])).tobytes())
  return None
 except ValueError:pass
 w=main_window(driver);target=driver.tool().resolve(j['peer']);c=controls(driver)
 try:
  # Reuse previously calibrated exact sidebar name glyphs before trying search.
  box=[w['x']+134,w['y']+82,w['x']+314,w['y']+min(650,w['height']-10)]
  from PIL import Image
  raw=image.crop(tuple(box)).convert('RGB');names=Image.new('RGB',raw.size,'white');names.putdata([(0,0,0) if max(px)<70 else (255,255,255) for px in raw.getdata()])
  p=driver.root/'navigation'/(hashlib.sha256(j['peer'].encode()).hexdigest()+'.png')
  if not force_search and p.is_file() and not p.is_symlink():
   with Image.open(p) as source:needle=source.convert('L')
   hay=names.convert('L');matches=[y for y in range(hay.height-needle.height+1) if hay.crop((0,y,needle.width,y+needle.height)).tobytes()==needle.tobytes()]
   if len(matches)==1:
    c.click(box[0]+needle.width//2,box[1]+matches[0]+needle.height//2);c.wait(350)
    try:validate_binding(cfg,{'username':j['peer']},screen(driver).crop(tuple(cfg['header_box'])).tobytes());return None
    except ValueError:raise PreparationError('RECIPIENT_NOT_VERIFIED','Selected conversation did not match its frozen binding.') from None
  # This is a calibrated search box outside the composer; never press Enter.
  point=[w['x']+165,w['y']+58]
  owned_navigation=None
  if j.get('id') and getattr(driver,'navigation_job_id',None)==j['id']:
   from .navigation import load,save
   owned_navigation=load(driver.root,j)
   if not owned_navigation or owned_navigation['state']!='started' or owned_navigation['main']!=w:raise PreparationError('NAVIGATION_RECOVERY_PENDING','Original navigation must be settled before another search.',clean=False)
   owned_navigation.update(state='search-intent',querySHA256=hashlib.sha256(query.encode()).hexdigest());save(driver.root,j,owned_navigation)
  paste_field(c,point,query);c.wait(550)
  popups=[v for v in driver.app_windows() if v['id']!=w['id'] and v['title'].lower()=='wechat' and v['x']==w['x']+76 and v['y']==w['y']+75 and v['width']==333]
  if len(popups)!=1:raise PreparationError('SEARCH_RESULTS_NOT_SUPPORTED','No supported official contact search result popup.')
  popup=popups[0];box=[popup['x'],popup['y'],popup['x']+popup['width'],popup['y']+popup['height']]
  if owned_navigation is not None:
   from .windows import search_parent_proof
   search_parent_proof(popup,w)
   owned_navigation.update(state='search-open',search=popup);save(driver.root,j,owned_navigation)
  candidates=rows(driver,box)
  from .selectors import native_search_bounds,native_search_result
  try:
   top,bottom=native_search_bounds(candidates,j['peer'])
   # Retain full-width section evidence, but exclude avatar/icon glyphs from names.
   name_box=[box[0]+55,max(box[1],int(top)),box[2]-8,int(min(box[3],bottom))]
   if name_box[1]>=name_box[3]:raise ValueError('native section has no visible result range')
   point=native_search_result(candidates,search_names,j['peer'],name_rows=rows(driver,name_box))
  except ValueError:raise PreparationError('RECIPIENT_NOT_VISIBLE','Native contact result is absent or ambiguous; internet search is never selected.') from None
  c.click(*point);c.wait(500)
  if owned_navigation is not None and popup['id'] not in {x['id'] for x in driver.app_windows()}:
   owned_navigation.update(state='legacy-selected',search=None);save(driver.root,j,owned_navigation)
  main_window(driver)
  try:validate_binding(cfg,{'username':j['peer']},screen(driver).crop(tuple(cfg['header_box'])).tobytes())
  except ValueError:raise PreparationError('RECIPIENT_NOT_VERIFIED','Search result failed the independent target-title binding.') from None
  return None
 finally:c.close()

def source_label(source):
 if source.get('sourceLocatorUnique') is False:raise PreparationError('SOURCE_AMBIGUOUS','Repeated native labels or an out-of-range source cannot be mapped safely to one visible message.')
 if source['kind']==1:
  text=source['text']
  if not text.strip() or len(text)>160:raise PreparationError('SOURCE_NOT_LOCATABLE','This source needs a supported unambiguous visible-text locator.')
  return text
 if source['kind']==49:
  from .proof import xml
  label=xml(source['text']).findtext('.//appmsg/title')
  if label and len(label)<=140:return label
 raise PreparationError('SOURCE_NOT_LOCATABLE','No supported deterministic visible locator for this message kind.')

def locate_source(driver,j,source):
 """Bounded visible-range match. Ambiguous repeated cards are never guessed."""
 cfg=driver.binding(j['peer']);label=source_label(source);box=[cfg['header_box'][0]+70,cfg['header_box'][3]+1,cfg['header_box'][2]-75,cfg['editor'][1]-35]
 c=controls(driver)
 try:
  def recent():
   from .selectors import scroll_thumb,selected_chat_row
   w=main_window(driver);rail=[w['x']+w['width']-14,box[1],w['x']+w['width']-3,box[3]]
   # Native WeChat exposes a direct "Go to the latest message" control when
   # its current history slice is older than the latest synchronized record.
   try:
    from .ocr import find_line
    latest=find_line(rows(driver,[cfg['header_box'][0]+80,cfg['editor'][1]-100,cfg['header_box'][2]-8,cfg['editor'][1]-20]),'Go to the latest message')
   except ValueError:latest=None
   if latest:c.click(*latest);c.wait(550);return
   c.t.XTestFakeMotionEvent(c.d,-1,rail[0]+5,(rail[1]+rail[3])//2,0);c.x.XFlush(c.d);c.wait(200)
   try:point=scroll_thumb(screen(driver),rail)
   except ValueError:return
   c.t.XTestFakeMotionEvent(c.d,-1,*point,0);c.t.XTestFakeButtonEvent(c.d,1,1,0);c.x.XFlush(c.d);c.wait(180)
   for step in range(1,7):
    y=int(point[1]+((rail[3]-2)-point[1])*step/6);c.t.XTestFakeMotionEvent(c.d,-1,point[0],y,0);c.x.XFlush(c.d);c.wait(60)
   c.t.XTestFakeButtonEvent(c.d,1,0,0);c.x.XFlush(c.d);c.wait(300)
  from .ocr import normalized
  initial=[v for v in rows(driver,box,contrast=160) if normalized(v['text'])==normalized(label)]
  if len(initial)>1:raise PreparationError('SOURCE_AMBIGUOUS','Repeated visible source labels cannot be safely mapped to one server ID.')
  if len(initial)==1:return initial[0]['point']
  recent()
  observation=screen(driver);observed=driver.previews/'program-locate-current.png';observation.save(observed);observed.chmod(0o600)
  debug={'requestedLabel':label,'firstRows':rows(driver,box,contrast=160),'at':time.time()};trace=driver.root/'program-locate-current.json';trace.write_text(json.dumps(debug,ensure_ascii=False));trace.chmod(0o600)
  # Reach the recent tail first, then inspect a bounded older range. These are
  # read/navigation events in the message pane, never composer keys.
  for amount in [0]+[-20]*10+[10]*12:
   if amount:
    c.t.XTestFakeMotionEvent(c.d,-1,(box[0]+box[2])//2,(box[1]+box[3])//2,0)
    for _ in range(abs(amount)):
     for down in (1,0):c.t.XTestFakeButtonEvent(c.d,4 if amount>0 else 5,down,0)
     c.x.XFlush(c.d);c.wait(40)
    c.wait(100)
   found=rows(driver,box,contrast=160)
   from .ocr import normalized
   matches=[v for v in found if normalized(v['text'])==normalized(label)]
   if len(matches)>1:raise PreparationError('SOURCE_AMBIGUOUS','Repeated visible source labels cannot be safely mapped to one server ID.')
   if len(matches)==1:return matches[0]['point']
  raise PreparationError('SOURCE_NOT_VISIBLE','Original message was not found in the bounded supported range; no caller pointer input is accepted.')
 finally:c.close()

def context_menu(driver,c,point,item):
 c.t.XTestFakeMotionEvent(c.d,-1,*point,0);c.x.XFlush(c.d);c.wait(100)
 c.t.XTestFakeButtonEvent(c.d,3,1,0);c.x.XFlush(c.d);c.wait(80)
 c.t.XTestFakeButtonEvent(c.d,3,0,0);c.x.XFlush(c.d);c.wait(300)
 # OCR only the area around this source card. Preserve menu focus.
 image=screen(driver);x,y=point;box=[max(0,x-45),max(0,y-240),min(image.width,x+230),min(image.height,y+450)]
 try:target=unique_line(rows(driver,box),item)
 except ValueError:
  windows=driver.app_windows();active=getattr(driver,'active_window',None);mains=[w for w in windows if (active and w['id']==active['id']) or (not active and w['title']=='Weixin')]
  if len(mains)==1:c.click(mains[0]['x']+400,mains[0]['y']+55);c.wait(100)
  raise PreparationError('MENU_NOT_SUPPORTED','The expected official context-menu item was not uniquely found.') from None
 c.click(*target);c.wait(350)

def final_step_preview(driver,j,step,**extra):
 from .contract import digest
 from .steps import step_patch
 windows=driver.app_windows();bounds=[min(x['x'] for x in windows),min(x['y'] for x in windows),max(x['x']+x['width'] for x in windows),max(x['y']+x['height'] for x in windows)]
 image=screen(driver);patch=step_patch(image,step,bounds)
 return dict(driver.screenshot(j),programRecipe=True,workflow=True,context=digest({'job':j['id'],'windows':windows,'patch':patch,'payload':j['payload']}),windows=windows,windowBounds=bounds,step=step,stepPatch=patch,summary={'peer':j['peer'],'action':j['action'],'text':j['payload'].get('text'),'source_id':j['payload'].get('source_id')},**extra)

def verify_quote(driver,cfg,source):
 """Read the lower quote strip, keeping faint filename glyphs intact first."""
 from .ocr import find_line
 label=source_label(source);box=[cfg['header_box'][0]+12,cfg['editor'][1],cfg['header_box'][2]-12,cfg['send'][1]-20]
 for contrast in (False,True):
  try:
   find_line(rows(driver,box,contrast=contrast),label if source['kind']==49 else label[:24]);return
  except ValueError:pass
 raise PreparationError('QUOTE_NOT_VERIFIED','Original quote is not reliably visible in the composer; not sent.',clean=False)

def remember_reply(driver,j,cfg):
 from .selectors import quote_close
 box=[cfg['header_box'][0]+12,cfg['editor'][1],cfg['header_box'][2]-12,cfg['send'][1]-20]
 image=screen(driver);point=quote_close(image,box)
 value={'peer':j['peer'],'binding':cfg,'box':box,'sha256':hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest(),'point':point}
 path=driver.root/(j['id']+'-owned-reply.json');tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));tmp.chmod(0o600);tmp.replace(path)

def cleanup_reply(driver,j):
 """Clear only this exact unattempted text plus frozen quote, never a foreign draft."""
 if (driver.root/(j['id']+'-attempt.json')).exists():return False
 path=driver.root/(j['id']+'-owned-reply.json')
 if path.is_symlink():return False
 if not path.is_file():
  driver._select(j);ui=driver.ui(j['peer'])
  try:
   if ui.draft():return False
   driver._file_helper().require_empty_editor(ui);return True
  finally:ui.close()
 marker=json.loads(path.read_text())
 if marker['peer']!=j['peer']:return False
 driver.session_bindings[j['peer']]=marker['binding'];ui=driver.ui(j['peer'])
 try:
  if ui.draft()!=j['payload']['text']:return False
  image=screen(driver)
  if hashlib.sha256(image.crop(tuple(marker['box'])).tobytes()).hexdigest()!=marker['sha256']:return False
  from .selectors import quote_close
  if quote_close(image,marker['box'])!=marker['point']:return False
  c=controls(driver)
  try:c.click(*marker['point']);c.wait(100);ui.click(ui.cfg['editor']);ui.ctrl('a');c.key(0xff08);c.wait(150)
  finally:c.close()
  if ui.draft():return False
  driver._file_helper().require_empty_editor(ui);return True
 finally:ui.close()

def prepare_reply(driver,j):
 driver._select(j);source=driver._native_source(j);point=locate_source(driver,j,source);ui=driver.ui(j['peer'])
 try:
  if ui.draft():raise PreparationError('FOREIGN_DRAFT','Existing draft is retained.')
  driver._file_helper().require_empty_editor(ui)
 finally:ui.close()
 c=controls(driver)
 try:
  context_menu(driver,c,point,'Quote')
  cfg=driver.binding(j['peer']);paste_field(c,cfg['editor'],j['payload']['text'],replace=False)
  remember_reply(driver,j,cfg)
  verify_quote(driver,cfg,source)
  return final_step_preview(driver,j,{'kind':'commit'},ownedReply=True,uiBinding=dict(cfg))
 finally:c.close()

def remember_forward(driver,j):
 dialogs=[w for w in driver.app_windows() if w['title']=='WeixinSend To' and (w['width'],w['height'])==(752,586)]
 if len(dialogs)!=1:raise PreparationError('FORWARD_DIALOG_NOT_SUPPORTED','No unique supported official forward picker.',clean=False)
 w=dialogs[0];box=[w['x']+540,w['y']+w['height']-75,w['x']+w['width']-35,w['y']+w['height']-12]
 point=unique_line(rows(driver,box,psm=6),'Cancel')
 marker={'dialog':w,'cancelBox':box,'point':point};path=driver.root/(j['id']+'-owned-forward.json');tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(marker));tmp.chmod(0o600);tmp.replace(path);return w

def cleanup_forward(driver,j):
 if (driver.root/(j['id']+'-attempt.json')).exists():return False
 path=driver.root/(j['id']+'-owned-forward.json')
 if path.is_symlink() or not path.is_file():return False
 marker=json.loads(path.read_text());w=marker['dialog'];windows=driver.app_windows()
 if w not in windows:return not any(v['id']==w['id'] for v in windows)
 point=unique_line(rows(driver,marker['cancelBox'],psm=6),'Cancel')
 if point!=marker['point']:return False
 c=controls(driver)
 try:c.click(*point);c.wait(150)
 finally:c.close()
 return not any(v['id']==w['id'] for v in driver.app_windows())

def prepare_forward(driver,j):
 from .forwarding import prepare
 return prepare(driver,j)

def prepare(driver,j):
 action=j['action']
 if action=='reply':return prepare_reply(driver,j)
 if action=='forward':return prepare_forward(driver,j)
 if action=='open_message':
  driver._select(j);source=driver._native_source(j);locate_source(driver,j,source)
  return final_step_preview(driver,j,{'kind':'finish'},sourceLocated=True)
 if action=='join_group':
  relation=driver._relation(j)
  if relation:return dict(driver.screenshot(j),already=relation,context='already-member',summary={'peer':j['peer'],'action':action,'already_member':True})
  p=driver.prepare_join_native(j)
  if p.get('needs_assistance'):raise PreparationError('INVITATION_NOT_VERIFIED','Invitation card or complete group/join control could not be verified.',clean=False)
  return dict(p,programRecipe=True,summary={'peer':j['peer'],'action':action,'groupName':p['groupName']})
 if action=='save_attachment':
  kind=driver._native_source(j)['kind']
  if (j['payload'].get('representation')=='visible' or j['payload'].get('source_mode')=='inbound') and kind!=3:raise PreparationError('NOT_AN_IMAGE','Image representation requires an exact native image source.')
  if kind==3:
   from .images import prepare
   return prepare(driver,j)
  if kind!=49:raise PreparationError('UNSUPPORTED_ATTACHMENT','Only exact ordinary-file or supported native-image exports are available.')
  return dict(driver.screenshot(j),context='cache-read',cacheReadOnly=True,summary={'peer':j['peer'],'action':action,'source_id':j['payload']['source_id']})
 if action not in ('send_text','send_image','send_file','open_chat'):raise PreparationError('UNSUPPORTED_ACTION','This action has no public deterministic recipe.')
 return driver.prepare_basic(j)
