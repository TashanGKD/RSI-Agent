"""Original-job native-title navigation and owned, non-sending cleanup."""
import hashlib,json,os,re,stat,time
from pathlib import Path
from .contract import digest

BASIC={'send_text','send_image','send_file'}

def path(root,j):
 if not re.fullmatch('[a-f0-9]{32}',j.get('id','')):raise ValueError('exact internal job required')
 return Path(root)/(j['id']+'-navigation.json')

def load(root,j):
 p=path(root,j)
 if p.is_symlink():raise ValueError('navigation journal symlink')
 if not p.exists():return None
 s=p.stat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>30000:raise ValueError('private bounded navigation journal required')
 v=json.loads(p.read_text())
 if v.get('jobId')!=j['id'] or v.get('peer')!=j['peer'] or v.get('payloadHash')!=digest(j['payload']):raise ValueError('navigation journal identity changed')
 return v

def save(root,j,v):
 p=path(root,j);tmp=p.with_suffix('.tmp')
 if p.is_symlink() or tmp.exists() or tmp.is_symlink():raise ValueError('navigation journal path collision')
 value=dict(v,jobId=j['id'],peer=j['peer'],payloadHash=digest(j['payload']))
 raw=json.dumps(value,ensure_ascii=False).encode()
 if len(raw)>30000:raise ValueError('navigation journal budget')
 fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p);return value

def prove_popout(w,name,identity,host):
 if w.get('title')!=name or (w.get('width'),w.get('height'))!=(623,667) or not re.fullmatch('0x[0-9a-fA-F]{1,16}',w.get('id','')):raise ValueError('exact official chat title/geometry not proven')
 if identity.get('class')!=['wechat','wechat'] or host.get('class')!=identity['class'] or identity.get('pid')!=host.get('pid') or identity.get('leader')!=host.get('leader') or identity.get('transientFor') is not None or not {'_NET_WM_WINDOW_TYPE_NORMAL'}<=set(identity.get('types',[]))<={'_NET_WM_WINDOW_TYPE_NORMAL','_KDE_NET_WM_WINDOW_TYPE_OVERRIDE'}:raise ValueError('official chat process identity not proven')
 return True

CONTROL_LABELS={'b7ed138502ad07080a7a10d9f7f6341e7c1e516da9b539b17aed7e9494eb004e':'contact','db8999af2af7c42eda70ac0250c4e1af9b21428ff456b8a6bdfe81d2f0691a2f':'group',
 # Local WSL Xephyr rendering of the same top "Group Chats" label; OCR can misread it as "GroupChat:".
 '7891899e7aa430223618803010a02ab7e4f5d87aa2f91cff84aa14d2ec136596':'group',
 # Local WSL Xephyr rendering of the top "Contacts" label.
 '5a4a4d01622c981752161880efda4a4cabb0db21f14a10acfd88ef5c6e596f6d':'contact'}

def first_native_candidate(rows,peer,box,image=None):
 from .selectors import native_search_bounds,_search_section
 kind=None
 if image is not None:
  label=image.crop((box[0]+6,box[1]+5,box[0]+115,box[1]+35)).convert('RGB');kind=CONTROL_LABELS.get(hashlib.sha256(label.tobytes()).hexdigest())
 wanted='group' if peer.endswith('@chatroom') else 'contact'
 if kind==wanted:
  start=box[1]+18;end=min((v['point'][1] for v in rows if v['point'][1]>start and _search_section(v['text'])),default=box[3])
 else:start,end=native_search_bounds(rows,peer)
 point=[box[0]+120,int(start)+45]
 if not box[1]<=start<point[1]<min(end,box[3])-12 or not box[0]<point[0]<box[2]:raise ValueError('no first native chat row inside its native section')
 return point

def title_point(point):
 if not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point) or point[1]<16:raise ValueError('calibrated selected row point required')
 return [point[0],point[1]-16]

# A freshly started client opens its first chat window at this default size and
# does not remember a resize; only the window this job just opened is adjusted.
DEFAULT_POPOUT=(598,640)

def resize_own_popout(d,own):
 import subprocess
 subprocess.run(['xdotool','windowsize',own['id'],'623','667'],capture_output=True,timeout=3)
 for delay in (0.1,0.2,0.4,0.8):
  time.sleep(delay);after=d.app_windows()
  current=next((w for w in after if w['id']==own['id']),None)
  if current and (current['width'],current['height'])==(623,667):return current,after
 return own,d.app_windows()

def refresh_own(v,windows):
 """The same owned chat window after WeChat renamed it.

 A new chat window is first mapped with the generic title and named shortly
 after. Only the title may change: the window ID, position and size must
 still match. Returns None otherwise.
 """
 own=v.get('ownPopout')
 if not own:return None
 found=[w for w in windows if w['id']==own['id']]
 if len(found)!=1:return None
 w=found[0]
 if (w['x'],w['y'],w['width'],w['height'])!=(own['x'],own['y'],own['width'],own['height']):return None
 v['ownPopout']=w
 return w

def settle_popout_title(d,v,name):
 own=v['ownPopout']
 for delay in (0.15,0.3,0.5,0.8):
  if own['title']==name:break
  time.sleep(delay)
  current=refresh_own(v,d.app_windows())
  if current is None:break
  own=current
 return own

def open_selected_popout(d,j,c,v):
 """Only bounded, pre-input navigation; an observed new window ends gestures."""
 from .recipes import screen,activate,PreparationError
 from .selectors import selected_chat_row
 main=v['main'];before=d.app_windows();ids={w['id'] for w in before}
 v.update(state='popout-opening',search=None,openAttempts=[],openBaselineWindowIds=sorted(ids));save(d.root,j,v)
 def observed():
  current=d.app_windows()
  if any(w not in current for w in before):raise PreparationError('RECIPIENT_NOT_VERIFIED','Original official window changed during navigation.',clean=False)
  added=[w for w in current if w['id'] not in ids]
  if len(added)>1:raise PreparationError('RECIPIENT_NOT_VERIFIED','Multiple new windows during navigation.',clean=False)
  return (added[0],current) if added else None
 bounds=[main['x']+70,main['y']+82,main['x']+300,main['y']+650]
 for attempt in range(2):
  found=observed()
  if found:return found
  activate(c,main);c.require_focus(main)
  last=None;stable=None
  for _ in range(6):
   found=observed()
   if found:return found
   try:point=title_point(selected_chat_row(screen(d),bounds))
   except ValueError:point=None
   if point is not None and point==last:stable=point;break
   last=point;c.wait(80)
  if stable is None:raise PreparationError('SEARCH_SELECTION_UNPROVEN','Selected conversation has not stabilized; no opening gesture.')
  # Separate a fresh pair from the previous search-selection click. Recheck
  # after this non-editing settle: a delayed window must not get another pair.
  c.wait(450 if attempt else 80)
  found=observed()
  if found:return found
  c.require_focus(main)
  try:current=title_point(selected_chat_row(screen(d),bounds))
  except ValueError:current=None
  if current!=stable:raise PreparationError('SEARCH_SELECTION_UNPROVEN','Selected conversation moved before its opening gesture.')
  v['openAttempts'].append({'index':attempt+1,'point':stable,'selectionStable':True,'beforeWindowIds':sorted(ids),'at':time.time()});save(d.root,j,v)
  # Keep the two button pairs together. XFlush queues these events without
  # waiting on Qt; no GLib pump or window subprocess may split the gesture.
  c.click(*stable);c.click(*stable)
  for pause in (150,250,400):
   c.wait(pause);found=observed()
   if found:return found
 raise PreparationError('CHAT_POPOUT_NOT_OPENED','No official chat opened after bounded stable pre-input navigation; owned scene will be settled.')

def popout_binding(cfg, window, image):
 x, y = window['x'], window['y']
 box = [x+1, y+35, x+window['width']-1, y+82]
 editor = [x+280, y+554]
 bound = dict(cfg, header_box=box, header_sha256=hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest(),
              editor=editor, editor_frame_y=y+526, send=[x+window['width']-50, y+window['height']-32])
 content_top = cfg.get('editor_content_top')
 if type(content_top) is int:
  # Keep the calibrated inset relative to the editor when its window moves.
  bound['editor_content_top'] = content_top + editor[1] - cfg['editor'][1]
 return bound

def attach(d,j,cfg,w,identity=None):
 from .windows import window_identity
 from .lease import birth
 v=load(d.root,j);identity=identity or window_identity(w);prove_popout(w,w['title'],identity,v['mainIdentity']);born=birth(identity['pid'])
 if not born:raise ValueError('official chat process birth unavailable')
 return dict(cfg,nativeTargetProof={'peer':j['peer'],'account':d.policy.cfg['account'],'window':dict(w),'identity':identity,'hostIdentity':v['mainIdentity'],'processBirth':born})

def verify_session(d,cfg,peer):
 from .windows import window_identity
 from .lease import birth
 from .runtime import BeforeEffect
 try:
  p=cfg['nativeTargetProof']
  if cfg['peer']!=peer or p['peer']!=peer or p['account']!=cfg.get('paired_account') or p['account']!=d.policy.cfg['account']:raise ValueError('account or peer changed')
  found=[w for w in d.app_windows() if w['id']==p['window']['id']]
  if found!=[p['window']] or birth(p['identity']['pid'])!=p['processBirth']:raise ValueError('exact chat window changed')
  current=window_identity(found[0])
  if current!=p['identity']:raise ValueError('native chat process changed')
  prove_popout(found[0],p['window']['title'],current,p['hostIdentity']);return digest(p)
 except Exception:raise BeforeEffect('Exact native target window/account proof changed; no Send.') from None

def header_key(d,ui):
 if ui.cfg.get('nativeTargetProof'):return verify_session(d,ui.cfg,ui.cfg['peer'])
 from .recipes import screen
 return hashlib.sha256(screen(d).crop(tuple(ui.cfg['header_box'])).tobytes()).hexdigest()

def begin(d,j):
 from .recipes import main_window,controls,activate
 from .windows import window_identity
 from .lease import birth
 if not d.fds:raise ValueError('navigation requires original held driver guard')
 if load(d.root,j):raise ValueError('existing navigation requires original cleanup, not preparation replay')
 d.fast_versions(j)
 d.active_window=None;w=main_window(d);windows=d.app_windows()
 c=controls(d)
 try:activate(c,w)
 finally:c.close()
 identity=window_identity(w)
 from .recipes import screen
 c=controls(d)
 try:c.click(w['x']+500,w['y']+55);c.wait(80)
 finally:c.close()
 field=[w['x']+78,w['y']+40,w['x']+280,w['y']+70]
 save(d.root,j,{'state':'started','main':w,'mainIdentity':identity,'processBirth':birth(identity['pid']),'beforeWindows':windows,'searchFieldBox':field,'searchFieldSHA256':hashlib.sha256(screen(d).crop(tuple(field)).tobytes()).hexdigest()})
 d.navigation_job_id=j['id']

def search_named(d,j,target,cfg,query):
 return _search_named(d,j,target,cfg,query)

def refresh_search(v,windows,main):
 """The same owned search popup after it grew to show its sections.

 Only the height may change: the window ID, title, position, width and the
 calibrated search geometry must still match. Returns None otherwise.
 """
 from .windows import search_geometry
 s=v.get('search')
 if not s:return None
 found=[w for w in windows if w['id']==s['id']]
 if len(found)!=1:return None
 w=found[0]
 if (w['title'],w['x'],w['y'],w['width'])!=(s['title'],s['x'],s['y'],s['width']) or not search_geometry(w,main):return None
 v['search']=w;return w

def _search_named(d,j,target,cfg,query):
 from .recipes import controls,activate,paste_field,rows,screen,main_window,PreparationError
 from .selectors import selected_chat_row
 from .windows import window_identity,search_parent_proof,search_geometry
 v=load(d.root,j)
 if not v or v['state']!='started':raise PreparationError('NAVIGATION_RECOVERY_PENDING','Original navigation must be settled before another selection.',clean=False)
 # Native/account/group relation proof is authoritative before any composer input.
 d.fast_versions(j);main=v['main'];c=controls(d)
 try:
  activate(c,main);v.update(state='search-intent',querySHA256=hashlib.sha256(query.encode()).hexdigest());save(d.root,j,v)
  paste_field(c,[main['x']+165,main['y']+58],query);c.wait(550)
  windows=d.app_windows();pop=[w for w in windows if w['id'] not in {x['id'] for x in v['beforeWindows']} and search_geometry(w,main)]
  if len(pop)!=1:raise PreparationError('SEARCH_RESULTS_NOT_SUPPORTED','Exact official native-search popup missing.')
  popup=pop[0];search_parent_proof(popup,main);v.update(state='search-open',search=popup);save(d.root,j,v)
  # The official popup first shows only the web-search row and grows when the
  # contact and group sections load. Re-read the same owned popup until a
  # native row is proven; never select a web result or a different window.
  point=None
  for pause in (0,300,500,800,1200):
   if pause:
    c.wait(pause);current=refresh_search(v,d.app_windows(),main)
    if current is None:raise PreparationError('SEARCH_RESULTS_NOT_SUPPORTED','Owned native-search popup changed.',clean=False)
    if current!=popup:popup=current;save(d.root,j,v)
   box=[popup['x'],popup['y'],popup['x']+popup['width'],popup['y']+popup['height']]
   image=screen(d)
   try:point=first_native_candidate([],j['peer'],box,image=image);break
   except ValueError:
    try:point=first_native_candidate(rows(d,box),j['peer'],box,image=image);break
    except ValueError:continue
  if point is None:raise PreparationError('RECIPIENT_NOT_VISIBLE','No native chat row proven; web results never selected.')
  c.click(*point);c.wait(350)
  if popup['id'] in {w['id'] for w in d.app_windows()}:raise PreparationError('SEARCH_SELECTION_UNPROVEN','Native chat selection did not dismiss its own search.')
  # Opening a chat is navigation only. Its system title must prove the recipient
  # before ui()/park()/stage() may touch any draft. Never accept a guessed name.
  before=d.app_windows();own,after=open_selected_popout(d,j,c,v);identity=window_identity(own)
  if (own['width'],own['height'])==DEFAULT_POPOUT and identity['pid']==v['mainIdentity']['pid'] and identity['transientFor'] is None:
   own,after=resize_own_popout(d,own)
  # Record a newly created normal official window even if its target is wrong,
  # so exact owned non-editing cleanup can still run. No stage has occurred.
  if (own['width'],own['height'])!=(623,667) or identity['class']!=v['mainIdentity']['class'] or identity['pid']!=v['mainIdentity']['pid'] or identity['leader']!=v['mainIdentity']['leader'] or identity['transientFor'] is not None:raise PreparationError('RECIPIENT_NOT_VERIFIED','New window identity is not the official chat.',clean=False)
  v.update(state='popout-created',ownPopout=own,ownIdentity=identity);save(d.root,j,v)
  own=settle_popout_title(d,v,target['displayName']);save(d.root,j,v)
  try:prove_popout(own,target['displayName'],identity,v['mainIdentity'])
  except ValueError:raise PreparationError('RECIPIENT_NOT_VERIFIED','Opened chat system title differs from the exact native target.') from None
  if {w['id'] for w in after}!={w['id'] for w in before}|{own['id']}:raise PreparationError('RECIPIENT_NOT_VERIFIED','Official window set drifted.',clean=False)
  d.fast_versions(j);d.active_window=own;activate(c,own)
  d.session_bindings[j['peer']]=attach(d,j,popout_binding(cfg,own,screen(d)),own,identity)
  v.update(state='ready');save(d.root,j,v)
  return None
 finally:c.close()

def restore_search(d,v,c):
 from .recipes import screen
 import secrets
 box=v.get('searchFieldBox')
 if not box:return True
 main=v['main'];c.click(main['x']+500,main['y']+55);c.wait(80)
 def restored():
  image=screen(d);current=hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest();previous=v['searchFieldSHA256']
  if current==previous:return True
  # Both complete empty-field appearances were independently observed. Never
  # apply this to an unknown query, masked region or uncalibrated geometry.
  empty={'6c8ae520a63dbbf17fb53717c0b4a2e0ad8fdb519675c96e778b79009c226b8f','f84d7f473fb161da261ffa1c755a317af78fe7082f62cbad76394fe8dd09aa3e'}
  if current in empty and previous in empty and image.mode=='RGB' and (main.get('width'),main.get('height'))==(905,667) and box==[main['x']+78,main['y']+40,main['x']+280,main['y']+70]:
   v.update(searchBaselineOutcome='both-observed-empty-field-appearances',canonicalEmptySearchVerified=True,priorSearchPixelAppearanceRestored=False);return True
  return False
 if restored():return True
 if not v.get('querySHA256'):return False
 import gi
 gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk
 clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);clip.set_text('NAVIGATION_COPY_'+secrets.token_hex(8),-1)
 c.click(main['x']+165,main['y']+58);c.key(0x61,True);c.key(0x63,True);c.wait(100)
 actual=clip.wait_for_text()
 if not isinstance(actual,str) or hashlib.sha256(actual.encode()).hexdigest()!=v['querySHA256']:return False
 c.key(0xff08);c.wait(120);c.click(main['x']+500,main['y']+55);c.wait(100)
 return restored()

def finish(d,j):
 from .recipes import controls,activate,main_window
 from .windows import window_identity
 from .lease import birth
 from . import composer
 try:
  v=load(d.root,j)
  if not v or v['state']=='settled':return True
  if birth(v['mainIdentity']['pid'])!=v['processBirth']:return False
  windows=d.app_windows();main=v['main'];own=v.get('ownPopout');retained=False
  if main not in windows or window_identity(main)!=v['mainIdentity']:return False
  search=v.get('search')
  if search and any(w['id']==search['id'] for w in windows) and search not in windows:
   # The popup grew after it was recorded; accept only the same owned window.
   if refresh_search(v,windows,main) is None:return False
   save(d.root,j,v)
  if v['state']=='popout-opening':
   # A failed double-click is navigation, not an uncertain Send. Observe its
   # bounded result under the original guard; never guess an unrelated dialog.
   before=v['beforeWindows'];ids={w['id'] for w in before};c=controls(d)
   try:
    for delay in (100,200,400,800):
     added=[w for w in windows if w['id'] not in ids]
     if added:break
     c.wait(delay);windows=d.app_windows()
   finally:c.close()
   if any(w not in windows for w in before):return False
   added=[w for w in windows if w['id'] not in ids]
   if len(added)>1:return False
   if added:
    own=added[0];name=d.tool().resolve(j['peer'])['displayName']
    if d.name_peer(name)!=j['peer']:return False
    identity=window_identity(own);prove_popout(own,name,identity,v['mainIdentity'])
    v.update(state='popout-created',ownPopout=own,ownIdentity=identity,lateWindowVerified=True)
   else:v.update(state='navigation-no-new-window-observed')
   save(d.root,j,v)
  if own and own not in windows:
   # The owned window may have been renamed after it was recorded.
   current=refresh_own(v,windows)
   if current is not None:own=current;save(d.root,j,v)
  expected=list(v['beforeWindows'])
  for w in (own,v.get('search')):
   if w and w in windows and w not in expected:expected.append(w)
  if windows!=sorted(expected,key=lambda w:w['id']):return False
  c=controls(d)
  try:
   search=v.get('search')
   if search and search in windows:
    from .windows import search_parent_proof
    search_parent_proof(search,main);activate(c,main)
    if search in d.app_windows():c.click(main['x']+500,main['y']+55)
    for delay in (80,160,320,500):
     c.wait(delay)
     if search['id'] not in {w['id'] for w in d.app_windows()}:break
    else:return False
    after=d.app_windows()
    if after!=[w for w in windows if w['id']!=search['id']]:return False
    windows=after;v.update(search=None);save(d.root,j,v)
   if own and own in windows:
    if window_identity(own)!=v['ownIdentity']:return False
    parked=composer.load(d.root,j)
    # Prior foreign drafts are restored and retained, never cleared for layout.
    if (parked and parked.get('state')!='restored'):return False
    retained=bool(v.get('protectedDraft') or (parked or {}).get('priorChars'))
    if not retained:
     # Read pixels only, including for a rejected wrong-title candidate. Never
     # copy/clear a foreign draft just to close a temporary chat.
     from types import SimpleNamespace
     from .recipes import screen
     image=screen(d)
     cfg=popout_binding({},own,image)
     d._file_helper().require_empty_editor(SimpleNamespace(cfg=cfg,ui=SimpleNamespace(screenshot=lambda:image)))
     activate(c,own)
     if d.app_windows()!=windows:return False
     c.click(own['x']+own['width']-16,own['y']+14)
     for delay in (80,160,320,500):
      c.wait(delay)
      if own['id'] not in {w['id'] for w in d.app_windows()}:break
     else:return False
     if d.app_windows()!=[w for w in windows if w['id']!=own['id']]:return False
   elif own and any(w['id']==own['id'] for w in windows):return False
   d.active_window=None;main_window(d);activate(c,main)
   if not restore_search(d,v,c):return False
   final=d.app_windows();expected=v['beforeWindows']+([own] if retained and own else [])
   if final!=sorted(expected,key=lambda w:w['id']):return False
   v.update(state='settled',settledAt=time.time(),priorDraftWindowRetained=retained);save(d.root,j,v)
   d.session_bindings.pop(j['peer'],None);d.navigation_job_id=None;return True
  finally:c.close()
 except Exception:return False

def _yield_owned_read(d,j,owned,store,force=False):
 """Private read-helper checkpoint; only exact owned non-sending windows.

 No new queue/action/lease. The caller releases its original executor/native
 guards immediately on return. False preserves unproved navigation debt.
 """
 if j.get('action')!='save_attachment' or not getattr(d,'fds',None):return False
 if not force and not store.ready_business():return None
 from .recipes import controls,activate
 from .windows import window_identity
 from .lease import birth
 from .forwarding import require_window_focus
 c=None
 try:
  active=store.active()
  if active and active['id']!=j['id']:return False
  v=load(d.root,j)
  if not v:return False
  if v['state']=='settled':return True
  host=v['mainIdentity']
  if birth(host['pid'])!=v['processBirth']:return False
  windows=d.app_windows();baseline=v['beforeWindows'];ids={w['id'] for w in baseline}
  if v['main'] not in windows or window_identity(v['main'])!=host:return False
  if set(owned)&ids:return False # Never adopt a pre-existing window as own.
  search=v.get('search')
  if search and any(w['id']==search['id'] for w in windows) and search not in windows:
   if refresh_search(v,windows,v['main']) is None:return False
   save(d.root,j,v)
  expected=list(baseline)
  for original in (v.get('ownPopout'),v.get('search')):
   if not original:continue
   if original in windows and original not in expected:expected.append(original)
   elif any(w['id']==original['id'] and w!=original for w in windows):return False
  live=[]
  for wid,item in owned.items():
   found=[w for w in windows if w['id']==wid]
   if not found:continue
   w=found[0];identity=window_identity(w)
   if w!=item['window'] or identity!=item['identity'] or identity.get('class')!=['wechat','wechat'] or identity.get('pid')!=host['pid'] or identity.get('leader')!=host.get('leader'):return False
   role='save' if w['title']=='Save' else 'viewer' if w['title']=='Photos and Videos' else 'history' if w['title'].startswith('Chat history of ') else None
   if role is None:return False
   live.append((role,w,identity));expected.append(w)
  if windows!=sorted(expected,key=lambda w:w['id']):return False
  if any(sum(role==kind for role,w,identity in live)>1 for kind in ('save','viewer','history')):return False
  viewers={item['window']['id'] for item in owned.values() if item['window']['title']=='Photos and Videos'}
  if any(role=='save' and identity.get('transientFor') not in viewers for role,w,identity in live):return False
  c=controls(d)
  for kind in ('save','viewer','history'):
   for role,w,identity in live:
    if role!=kind:continue
    before=d.app_windows()
    if w not in before or window_identity(w)!=identity or birth(host['pid'])!=v['processBirth']:return False
    activate(c,w);require_window_focus(c,w)
    if kind=='history':c.click(w['x']+w['width']-16,w['y']+14) # Existing own-history close recipe.
    else:c.key(0xff1b) # Existing own Save-cancel / viewer-dismiss recipes.
    for delay in (100,200,400):
     c.wait(delay)
     if not any(x['id']==w['id'] for x in d.app_windows()):break
    else:return False
    if d.app_windows()!=[x for x in before if x['id']!=w['id']]:return False
  return finish(d,j)
 except Exception:return False
 finally:
  if c is not None:c.close()


def _read_command(d,j,owned,store,stream,deadline):
 """Same-process nonblocking framed input; partial lines cannot hold the UI.

 Check ready/deadline before every complete command and every bounded read.
 Persistent raw-byte buffering avoids TextIO prefetch hiding queued commands.
 """
 import select
 while True:
  settled=_yield_owned_read(d,j,owned,store,force=time.monotonic()>=deadline)
  if settled is not None:return None,settled
  state=getattr(d,'_read_pipe_state',None)
  if state is None:
   fd=stream.fileno();state={'stream':stream,'fd':fd,'buffer':bytearray(),'eof':False,'blocking':os.get_blocking(fd)}
   os.set_blocking(fd,False);d._read_pipe_state=state
  elif state['stream'] is not stream:raise ValueError('original read input stream changed')
  pending=state['buffer'];end=pending.find(b'\n')
  if end>=0:
   line=bytes(pending[:end+1]);del pending[:end+1]
   return line.decode('utf-8'),None
  if state['eof']:
   if pending:
    line=bytes(pending);pending.clear();return line.decode('utf-8'),None
   return None,_yield_owned_read(d,j,owned,store,force=True)
  if select.select([state['fd']],[],[],1)[0]:
   try:data=os.read(state['fd'],65536)
   except BlockingIOError:continue
   if data:pending.extend(data)
   else:state['eof']=True
