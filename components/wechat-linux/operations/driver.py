"""Backend native input. Existing official client, no vision/model API or VNC."""
from rsi_runtime_env import display, xauthority
import sys,os,json,time,fcntl,hashlib,io,base64,re
from pathlib import Path
from .contract import digest
from .assets import Assets
from .runtime import BeforeEffect,Busy

BASE=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))
NATIVE=Path(os.environ.get('WECHAT_NATIVE_CODE',str(Path(__file__).resolve().parents[1])))
COMMON=Path(os.environ.get('WECHAT_HOST_SUPPORT_CODE',str(NATIVE/'host_support')))
SERVICE=COMMON
def preview_context(peer,header,text,asset):return digest({'peer':peer,'header':header,'text':text,'asset':asset})
class PolicyConfigError(ValueError):pass
class Policy:
 format_version=2
 def __init__(self,cfg):
  from .contract import ident,peer,ACTIONS
  from copy import deepcopy
  if not isinstance(cfg,dict) or not isinstance(cfg.get('account'),str) or not cfg['account']:raise PolicyConfigError('native account configuration required')
  if 'clients' in cfg and not isinstance(cfg['clients'],dict):raise PolicyConfigError('client attribution metadata must be an object')
  self.cfg=deepcopy(cfg)
  self.cfg.setdefault('clients',{})
 @staticmethod
 def allowed(p,target):
  from .contract import ACTIONS
  return list(ACTIONS)
 def check(self,j):
  # Owner-authorized work uses client as attribution, never as an ACL tenant.
  # Actual recipient/source/native result checks remain in the action recipe.
  from .contract import ident
  ident(j['client'])
  return self.cfg.get('clients',{}).get(j['client'],{})

class NativeDriver:
 def __init__(self,root,policy):
  self.root=Path(root);self.policy=Policy(policy);self.fds=[];self.session_bindings={};self.active_window=None;self.assets=Assets(root);self.previews=self.root/'previews';self.previews.mkdir(mode=0o700,exist_ok=True)
  if self.previews.is_symlink():raise ValueError('preview symlink')
  for p in [str(NATIVE),str(COMMON)]:
   if p not in sys.path:sys.path.insert(0,p)
  self.lease=hashlib.sha256((str(root)+':'+str(os.getpid())).encode()).hexdigest()[:32];self.last_publish=0
 def acquire(self):
  from .lease import publish,MaintenanceDeferred
  if self.fds:
   if time.time()-self.last_publish>1:publish(self.root);self.last_publish=time.time()
   return True
  guard=os.open(BASE/'desktop-control-20261026/session.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
  try:
   fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
   session=BASE/'desktop-control-20261026/session.json'
   if session.exists():
    x=json.loads(session.read_text())
    from .lease import desktop_busy
    if desktop_busy(x,time.time()):return False
   from contextlib import ExitStack
   from .lease import maintenance_guard
   with ExitStack() as reservation:
    if getattr(self,'work_class','maintenance')=='maintenance':reservation.enter_context(maintenance_guard(self.root))
    for p in [BASE/'native-control.lock',BASE/'native-ui.lock',self.root/'display-guard.lock']:
     fd=os.open(p,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
     try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
     except BaseException:os.close(fd);raise
     self.fds.append(fd)
    publish(self.root);self.last_publish=time.time();return True
  except (BlockingIOError,MaintenanceDeferred):self.release();return False
  finally:os.close(guard)
 def release(self):
  from .lease import release
  release(self.root)
  for fd in self.fds:os.close(fd)
  self.fds=[]
 def check_lease(self,s):
  if not self.fds or s!=self.lease:raise BeforeEffect('executor display lease unavailable')
 def tool(self):
  from linux_tool import Tool
  return Tool()
 def binding(self,peer):
  if peer in getattr(self,'session_bindings',{}):return self.session_bindings[peer]
  return self.registered_binding(peer)
 def registered_binding(self,peer):
  from linux_tool import secret
  cfg=json.loads(secret(BASE/'native-ui.json'));bindings=json.loads(secret(BASE/'tool-targets.json')) if (BASE/'tool-targets.json').exists() else {}
  if peer in bindings:return bindings[peer]
  if peer==cfg.get('peer'):return cfg
  # Research adapter keeps its checked three-member title separately.
  p=BASE/'fixture-request-7ec3111a9cbdf1fc/ui-binding.json'
  if p.exists():
   b=json.loads(secret(p))
   if b.get('peer')==peer:return b
  raise BeforeEffect('target has no previously verified native/UI binding')
 def fast_versions(self,j):
  from linux_tool import secret,native,ACCOUNT
  from .fast import binding_identity
  latest=self.check_current_policy(j)
  if latest.get('account')!=ACCOUNT or self.policy.cfg.get('account')!=ACCOUNT:raise BeforeEffect('native account changed')
  cfg=self.registered_binding(j['peer']);target=self.tool().resolve(j['peer'])
  if target.get('username')!=j['peer'] or target.get('contactEvidence',{}).get('consistency')!='committed' or cfg.get('peer')!=j['peer'] or cfg.get('displayName')!=target['displayName'] or cfg.get('paired_account')!=ACCOUNT:raise BeforeEffect('registered native identity changed')
  if target['displayName']!=j['peer'] and self.name_peer(target['displayName'])!=j['peer']:raise BeforeEffect('native name is not unique')
  if j['peer'].endswith('@chatroom'):
   with native('contact/contact.db') as (c,r):
    if r.get('consistency')!='committed':raise BeforeEffect('native membership snapshot gap')
    member=c.execute('SELECT 1 FROM chat_room r JOIN chatroom_member m ON m.room_id=r.id JOIN contact s ON s.id=m.member_id JOIN contact g ON g.username=r.username WHERE r.username=? AND s.username=? AND g.is_in_chat_room=1',(j['peer'],ACCOUNT)).fetchone()
    if not member:raise BeforeEffect('native self membership not proven')
   if target['displayName']==j['peer']:
    from .recipes import search_identity
    members=self.group_identity(j['peer'],cfg);base=re.sub(r'[(（]\d+[)）]$','',cfg.get('observedTitle',''));names={v:self.name_peer(v) for v in base.split('、')};search_identity(target,cfg,members,names)
  elif j['client']=='rsi-friend':
   from .proof import friend
   with native('contact/contact.db') as (c,r):
    rows=c.execute('SELECT local_type,flag,delete_flag FROM contact WHERE username=? LIMIT 2',(j['peer'],)).fetchall()
    if r.get('consistency')!='committed' or r.get('gap') or len(rows)!=1 or not friend(dict(rows[0])):
     raise BeforeEffect('current native friendship not proven')
  return {'registeredBindingSHA256':digest(cfg),'bindingIdentitySHA256':binding_identity(cfg),'scopeSHA256':digest({'account':latest['account'],'client':j['client'],'authorization':'owner-authorized-work'})}
 def certify_fast(self,j):
  from .sending import certify_fast
  return certify_fast(self,j)
 def name_peer(self,name):
  from linux_tool import native
  if not isinstance(name,str) or not 1<=len(name)<=200 or '\0' in name:raise ValueError('bounded native display name required')
  with native('contact/contact.db') as (c,r):
   if r.get('consistency')!='committed':raise ValueError('contact snapshot gap')
   values={v[0] for v in c.execute('SELECT username FROM contact WHERE username=? OR remark=? OR nick_name=? OR alias=? LIMIT 3',(name,name,name,name))}
   if len(values)!=1:raise ValueError('native display name is absent or ambiguous')
   return next(iter(values))
 def group_identity(self,peer,cfg):
  from linux_tool import native
  expected=cfg.get('nativeMemberIds')
  if not expected or len(expected)>200:raise ValueError('bounded original member proof required')
  with native('contact/contact.db') as (c,r):
   if r.get('consistency')!='committed':raise ValueError('contact snapshot gap')
   sql='SELECT s.username FROM chat_room r JOIN chatroom_member m ON m.room_id=r.id JOIN contact s ON s.id=m.member_id WHERE r.username=?'
   actual={v[0] for v in c.execute(sql,(peer,))}
   if actual!=set(expected):raise ValueError('group membership changed')
   marks=','.join('?' for _ in actual)
   peers=c.execute('SELECT r.username FROM chat_room r JOIN chatroom_member m ON m.room_id=r.id JOIN contact s ON s.id=m.member_id GROUP BY r.username HAVING COUNT(DISTINCT s.username)=? AND SUM(s.username IN ('+marks+'))=COUNT(*) LIMIT 2',[len(actual),*sorted(actual)]).fetchall()
   if [v[0] for v in peers]!=[peer]:raise ValueError('same-member group is not a unique UI identity')
   return sorted(actual)
 def known_chat_window(self,title):
  try:
   if self.name_peer(title):return True
  except ValueError:pass
  if title=='File Transfer':
   from sender import visual_title
   try:
    target=self.tool().resolve('filehelper')
    if target.get('contactEvidence',{}).get('consistency')=='committed' and visual_title(target,title)==title:return True
   except ValueError:pass
  # A registered unnamed-group popout is not a foreign modal. Prove its exact
  # native member set and every displayed name; never accept a similar title.
  try:
   from linux_tool import secret
   from .recipes import search_identity
   registry=BASE/'tool-targets.json'
   bindings=json.loads(secret(registry)) if registry.exists() else {}
   matches=[]
   for peer,cfg in bindings.items():
    observed=cfg.get('observedTitle','')
    if not cfg.get('nativeMemberIds') or title not in (observed,re.sub(r'[(（]\d+[)）]$','',observed)):continue
    target=self.tool().resolve(peer)
    if target['displayName']!=peer:continue
    members=self.group_identity(peer,cfg)
    names={part:self.name_peer(part) for part in re.sub(r'[(（]\d+[)）]$','',observed).split('、')}
    _,labels=search_identity(target,cfg,members,names)
    if title in labels:matches.append(peer)
   if len(matches)==1:return True
  except (ValueError,OSError,KeyError,TypeError):pass
  p=BASE/'fixture-request-7ec3111a9cbdf1fc/ui-binding.json'
  try:
   from linux_tool import secret
   cfg=json.loads(secret(p))
   return title==cfg.get('observedTitle') and bool(self.group_identity(cfg['peer'],cfg))
  except (ValueError,OSError):return False
 def ui(self,peer):
  import native_text,sender
  driver=self;Original=sender.UI;cfg=dict(self.binding(peer))
  from .composer import editor_point
  cfg['editor']=editor_point(cfg)
  class Bound(Original):
   def config(self,target):
    if target['username']!=peer:raise BeforeEffect('wrong native identity')
    return cfg
   def preflight(self,r,target):
    if cfg.get('nativeTargetProof'):
     from .navigation import verify_session
     return verify_session(driver,cfg,target['username'])
    return Original.preflight(self,r,target)
  # These dependency bindings are confined to this single executor process.
  sender.UI=Bound;native_text.check_session=self.check_lease
  try:return native_text.Desktop(peer,self.lease)
  finally:sender.UI=Original
 def screenshot(self,j):
  from sender import UI
  im=UI(BASE).screenshot();p=self.previews/(j['id']+'.png');temp=p.with_suffix('.tmp');im.save(temp,format='PNG');temp.chmod(0o600);os.replace(temp,p)
  data=p.read_bytes();return {'artifact':j['id'],'sha256':hashlib.sha256(data).hexdigest(),'width':im.width,'height':im.height,'screenshotBytes':len(data)}
 def app_windows(self):
  os.environ.update(DISPLAY=display(),XAUTHORITY=xauthority(BASE))
  from .windows import visible
  rows=visible()
  if not rows:raise BeforeEffect('no visible official WeChat window')
  return rows
 def generic_preview(self,j):
  windows=self.app_windows();bounds=[min(w['x'] for w in windows),min(w['y'] for w in windows),max(w['x']+w['width'] for w in windows),max(w['y']+w['height'] for w in windows)]
  source=self._native_source(j) if 'source_id' in j['payload'] and j['action']!='accept_friend' else None
  return dict(self.screenshot(j),context=digest({'windows':windows,'source':source,'peer':j['peer'],'action':j['action']}),windowBounds=bounds,windows=windows,workflow=True,needs_assistance=True,action=j['action'],target=j['peer'],sourceAvailable=source is not None,reason='plan a bounded official-client step from this screenshot, then confirm; no model runs in this tool')
 def _window(self):
  from image_client import Controls
  c=Controls(BASE)
  try:
   windows=self.app_windows()
   if len(windows)!=1 or windows[0]['title']!='Weixin':raise BeforeEffect('unexpected modal/viewer, preserve current UI')
   return windows[0]
  finally:c.close()
 def _select_legacy(self,j):
  from sender import UI,validate_binding
  cfg=self.binding(j['peer']);ui=UI(BASE)
  try:validate_binding(cfg,{'username':j['peer']},ui.screenshot().crop(tuple(cfg['header_box'])).tobytes());return None
  except ValueError:pass
  main=self._window();bounds=[main['x']+134,main['y']+82,main['x']+314,main['y']+min(650,main['height']-10)];im=ui.screenshot();raw=im.crop(tuple(bounds))
  from PIL import Image
  names=Image.new('RGB',raw.size,'white');names.putdata([(0,0,0) if max(px[:3])<70 else (255,255,255) for px in raw.convert('RGB').getdata()]);sha=hashlib.sha256(names.tobytes()).hexdigest();old=j.get('preview') or {}
  point=old.get('navigationPoint')
  if point:
   if old.get('context')!=sha:return dict(self.screenshot(j),needs_assistance=True,context=sha,navigationBounds=bounds,reason='session names changed; inspect a fresh navigation preview')
   from image_client import Controls
   c=Controls(BASE)
   try:c.focus(main);c.click(*point);c.wait(450)
   finally:c.close()
   validate_binding(cfg,{'username':j['peer']},ui.screenshot().crop(tuple(cfg['header_box'])).tobytes())
   nav=self.root/'navigation';nav.mkdir(mode=0o700,exist_ok=True);top=max(0,point[1]-bounds[1]-12);bottom=min(names.height,top+24);names.crop((0,top,names.width,bottom)).save(nav/(hashlib.sha256(j['peer'].encode()).hexdigest()+'.png'))
   return None
  # Use a previously calibrated exact name template if available; ambiguity stops.
  template=self.root/'navigation'/(hashlib.sha256(j['peer'].encode()).hexdigest()+'.png')
  if j['method']=='native' and template.is_file() and not template.is_symlink():
   from PIL import Image
   needle=Image.open(template).convert('L');hay=names.convert('L');matches=[]
   for y in range(hay.height-needle.height+1):
    if hay.crop((0,y,needle.width,y+needle.height)).tobytes()==needle.tobytes():matches.append(y)
   if len(matches)==1:
    from image_client import Controls
    c=Controls(BASE)
    try:c.focus(main);c.click(bounds[0]+needle.width//2,bounds[1]+matches[0]+needle.height//2);c.wait(450)
    finally:c.close()
    validate_binding(cfg,{'username':j['peer']},ui.screenshot().crop(tuple(cfg['header_box'])).tobytes());return None
  return dict(self.screenshot(j),needs_assistance=True,context=sha,navigationBounds=bounds,expectedPeer=j['peer'],expectedTitle=self.tool().resolve(j['peer'])['displayName'],reason='select exact visible conversation; target will be independently checked before input')
 def _select(self,j):
  from .recipes import selected
  return selected(self,j)
 def _file_helper(self):
  if str(SERVICE) not in sys.path:sys.path.append(str(SERVICE))
  import file_transport
  return file_transport
 def _native_source(self,j):
  from linux_tool import native,signed,decode
  import xml.etree.ElementTree as ET
  peer=j['payload'].get('inviter',j['payload'].get('source_peer',j['peer']));table='Msg_'+hashlib.md5(peer.encode()).hexdigest()
  with native('message/message_0.db') as (c,r):
   if r.get('consistency')!='committed':raise BeforeEffect('source snapshot incomplete')
   rows=c.execute('SELECT local_type,message_content,server_id,real_sender_id,create_time FROM '+table+' WHERE server_id=?',(signed(j['payload']['source_id']),)).fetchall()
   if len(rows)!=1:raise BeforeEffect('unique source message not found')
   text=decode(rows[0]['message_content'])
   sender=c.execute('SELECT user_name FROM Name2Id WHERE rowid=?',(rows[0]['real_sender_id'],)).fetchone()
   if peer.endswith('@chatroom') and sender and text.startswith(sender[0]+':\n'):text=text[len(sender[0])+2:]
   if len(text.encode())>100000 or re.search(r'<!\s*(DOCTYPE|ENTITY)',text,re.I):raise BeforeEffect('source XML over budget or unsafe')
   source={'kind':int(rows[0]['local_type'])&0xffffffff,'text':text}
   if source['kind'] in (1,49):
    from .recipes import source_label,PreparationError
    from .ocr import normalized
    try:wanted=normalized(source_label(source))
    except PreparationError:return source
    matches=0;budget=0;includes=False;unparsed=False
    for v in c.execute('SELECT server_id,local_type,message_content FROM '+table+' ORDER BY local_id DESC LIMIT 200'):
     raw=decode(v['message_content']);budget+=len(raw.encode())
     if budget>2000000:raise BeforeEffect('source-locator window exceeds its bounded budget')
     if peer.endswith('@chatroom') and ':\n' in raw:raw=raw.split(':\n',1)[1]
     candidate={'kind':int(v['local_type'])&0xffffffff,'text':raw}
     try:label=source_label(candidate)
     except PreparationError:continue
     except (ValueError,ET.ParseError):unparsed=True;continue
     if normalized(label)==wanted:matches+=1
     if v['server_id']==rows[0]['server_id']:includes=True
    source['sourceLocatorUnique']=includes and matches==1 and not unparsed
    if source['kind']==49 and sender:
     from .proof import xml
     card=xml(source['text'])
     if card.findtext('.//appmsg/type')=='5' and card.findtext('.//appmsg/url'):
      from datetime import datetime,timedelta
      from zoneinfo import ZoneInfo
      from .forwarding import date_labels
      day=datetime.fromtimestamp(rows[0]['create_time'],ZoneInfo('Asia/Shanghai')).replace(hour=0,minute=0,second=0,microsecond=0)
      # UI truncates long link titles. A deterministic prefix is allowed only
      # when it identifies exactly one native article in the entire source day,
      # across all senders, not just a recent visible subset.
      import xml.etree.ElementTree as ET
      prefix=wanted[:21];count=0;used=0;day_rows=c.execute('SELECT local_type,message_content,real_sender_id FROM '+table+' WHERE create_time>=? AND create_time<? AND (local_type & 4294967295)=49 LIMIT 201',(int(day.timestamp()),int((day+timedelta(days=1)).timestamp()))).fetchall()
      if len(day_rows)<=200:
       for candidate in day_rows:
        raw=decode(candidate['message_content']);used+=len(raw.encode())
        if used>2000000:break
        native_sender=c.execute('SELECT user_name FROM Name2Id WHERE rowid=?',(candidate['real_sender_id'],)).fetchone()
        if peer.endswith('@chatroom') and native_sender and raw.startswith(native_sender[0]+':\n'):raw=raw[len(native_sender[0])+2:]
        if int(candidate['local_type'])&0xffffffff!=49:continue
        try:
         other=xml(raw)
         if other.findtext('.//appmsg/type')=='5' and normalized(other.findtext('.//appmsg/title') or '').startswith(prefix):count+=1
        except (ValueError,ET.ParseError):count=-1;break
       if used<=2000000 and count==1:
        person=self.tool().resolve(sender[0])
        if person.get('username')==sender[0] and person.get('displayName'):
         source['historyLocator']={'title':card.findtext('.//appmsg/title'),'titlePrefix':prefix,'senderId':sender[0],'senderName':person['displayName'],'createdAt':rows[0]['create_time'],'dateLabels':date_labels(rows[0]['create_time']),'sameDatePrefixCount':1,'sourcePeer':peer,'sourceId':j['payload']['source_id']}
   return source
 def prepare_join_native(self,j):
  from .ocr import observe,find_line
  from sender import UI
  from image_client import Controls
  import xml.etree.ElementTree as ET
  source=self._native_source(j);raw=source['text'];root=ET.fromstring(raw[raw.find('<'):]);description=root.findtext('.//des') or '';m=re.search('群聊["“](.+?)["”]',description)
  if not m:raise BeforeEffect('invitation group name not unambiguous in native source')
  name=m.group(1);nav=dict(j,peer=j['payload']['inviter']);pending=self._select(nav)
  if pending:return pending
  cfg=self.binding(j['payload']['inviter']);box=[cfg['header_box'][0],cfg['header_box'][3],cfg['header_box'][2]-8,cfg['editor'][1]-34];image=UI(BASE).screenshot();rows,t1=observe(image,self.previews,box)
  # Opening a card has no outward effect. Final Join requires full-name verification.
  point=find_line(rows,name[-10:] if len(name)>=10 else name)
  c=Controls(BASE)
  try:
   c.click(*point)
   for delay in [150,250,450,800]:
    c.wait(delay);rows,t=observe(UI(BASE).screenshot(),self.previews)
    try:find_line(rows,name);join=find_line(rows,'Join group');break
    except ValueError:continue
   else:return self.generic_preview(j)
  finally:c.close()
  image=UI(BASE).screenshot();patch={'box':[join[0]-65,join[1]-23,join[0]+65,join[1]+23]};patch['sha256']=hashlib.sha256(image.crop(tuple(patch['box'])).tobytes()).hexdigest()
  return dict(self.screenshot(j),context=digest({'source':j['payload']['source_id'],'group':name,'peer':j['peer'],'patch':patch}),joinRecipe=True,groupName=name,joinPoint=join,joinPatch=patch,target=j['peer'],action=j['action'],modelCalls=0,ocrCardSeconds=t1,windows=self.app_windows())
 def _relation(self,j):
  from linux_tool import native
  with native('contact/contact.db') as (c,r):
   x=c.execute('SELECT username,is_in_chat_room,local_type FROM contact WHERE username=?',(j['peer'],)).fetchone()
   if not x:return None
   if j['action']=='join_group' and x['is_in_chat_room']==1:
    # Also prove our native account is a member.
    yes=c.execute('SELECT 1 FROM chat_room r JOIN chatroom_member m ON m.room_id=r.id JOIN contact s ON s.id=m.member_id WHERE r.username=? AND s.username=?',(j['peer'],self.policy.cfg['account'])).fetchone()
    if yes:return {'state':'accepted','currentlyMember':True,'selfMembershipVerified':True,'peer':j['peer'],'newActionInThisRead':False}
   if j['action'] in ('accept_friend','request_friend'):
    from .proof import friend
    row=c.execute('SELECT username,local_type,flag,delete_flag,alias FROM contact WHERE username=?',(j['peer'],)).fetchone()
    if friend(dict(row) if row else None):return {'state':'accepted','currentlyFriend':True,'peer':j['peer'],'nativeContactFlagsVerified':True,'newActionInThisRead':False}
  return None
 def check_current_policy(self,j):
  # Intersection: a disk-only grant cannot broaden this running executor;
  # disk revocation or malformed/unsupported config must stop before any UI.
  from .cli import load_config
  try:
   self.policy.check(j);latest=load_config(self.root/'config.json');Policy(latest).check(j)
   if latest.get('account')!=self.policy.cfg.get('account'):raise PolicyConfigError('configured account changed')
   return latest
  except (PermissionError,ValueError,OSError) as exc:
   e=BeforeEffect('current client/peer/action policy is not valid for this operation');e.code='OUTSIDE_SCOPE' if isinstance(exc,PermissionError) else 'POLICY_CONFIG_INVALID';e.clean=True;raise e from None
 def prepare(self,j):
  self.check_current_policy(j)
  if j['action']=='invite_members':
   from .group_invites import prepare
   return prepare(self,j)
  if j['action']=='create_group':
   from .groups import prepare
   return prepare(self,j)
  if j['action']=='get_group_qr':
   from .group_qr import prepare
   return prepare(self,j)
  if j['action'] in ('send_text','send_image','send_file'):
   try:self.registered_binding(j['peer'])
   except BeforeEffect:
    from .recipes import PreparationError
    raise PreparationError('TARGET_NOT_CALIBRATED','Target has no verified native/UI binding; no UI input was attempted.') from None
  from .recipes import prepare
  from . import navigation
  try:return prepare(self,j)
  except Exception as e:
   if getattr(e,'code',None)=='DRAFT_PROTECTED':
    v=navigation.load(self.root,j)
    if v:v.update(protectedDraft=True);navigation.save(self.root,j,v)
   raise
 def prepare_basic(self,j):
  from .sending import prepare
  return prepare(self,j)
 def execute(self,j):
  self.check_current_policy(j);p=j['preview'];a=j['action']
  if a=='invite_members':
   from .group_invites import execute
   return execute(self,j)
  if a=='create_group':
   from .groups import execute
   return execute(self,j)
  if a=='get_group_qr':
   from .group_qr import execute
   return execute(self,j)
  if p.get('senderRecipe'):
   from .sending import execute
   return execute(self,j)
  if p.get('uiBinding'):self.session_bindings[j['peer']]=p['uiBinding']
  if a=='join_group':
   current=self._relation(j)
   if current:return current
  if p.get('already'):
   current=self._relation(j)
   if not current:raise BeforeEffect('native membership changed')
   return current
  if p.get('joinRecipe'):
   from .ocr import observe,find_line
   from sender import UI
   from image_client import Controls
   if self.app_windows()!=p['windows']:raise BeforeEffect('join dialog windows changed')
   image=UI(BASE).screenshot();patch=p['joinPatch']
   if hashlib.sha256(image.crop(tuple(patch['box'])).tobytes()).hexdigest()!=patch['sha256']:raise BeforeEffect('join control changed')
   rows,_=observe(image,self.previews);find_line(rows,p['groupName']);point=find_line(rows,'Join group')
   if point!=p['joinPoint']:raise BeforeEffect('join button moved')
   self._save_attempt(j,{'action':'join_group','peer':j['peer'],'startedAt':time.time(),'groupName':p['groupName']})
   c=Controls(BASE)
   try:
    c.click(*point)
    for wait in [100,200,400,700,1000]:
     c.wait(wait);relation=self._relation(j)
     if relation:return dict(relation,alreadyMember=False,newActionPerformed=True,method='offline-ocr-native-input',modelCalls=0)
   finally:c.close()
   return {'state':'unknown','reason':'join_clicked_membership_not_yet_proven','automaticReplay':False}
  if p.get('step'):return self.execute_step(j)
  if a=='save_attachment':return self.save_attachment(j)
  ui=self.ui(j['peer'])
  try:
   if a=='open_chat':ui.check();return {'state':'accepted','peer':j['peer'],'visibleTargetVerified':True,'newMessageSent':False}
   if a=='send_text':
    actual=ui.draft();header=hashlib.sha256(ui.ui.screenshot().crop(tuple(ui.cfg['header_box'])).tobytes()).hexdigest()
    if preview_context(j['peer'],header,actual,None)!=p['context']:raise BeforeEffect('target or actual draft changed since preview')
   elif a in ('send_file','send_image'):
    asset=self.assets.get(j['client'],j['payload']['asset'])
    if asset['sha256']!=p['asset']['sha256']:raise BeforeEffect('asset changed')
    im=ui.ui.screenshot().crop(tuple(p['attachmentBox']))
    if hashlib.sha256(im.tobytes()).hexdigest()!=p['attachmentContext']:raise BeforeEffect('actual attachment preview changed')
   else:raise BeforeEffect('no verified execution recipe')
   from sender import before
   start=time.time();meta={'beforeIds':before(j['peer']),'startedAt':start,'peer':j['peer'],'action':a,'text':j['payload'].get('text'),'asset':p.get('asset')}
   self._save_attempt(j,meta);ui.check();ui.click(ui.cfg['send'])
   # Adaptive native-receipt waiting, not a fixed one-second delay.
   for pause in [.05,.1,.2,.4,.8,1.2]:
    ui.settle(int(pause*1000));proof=self.verify(j)
    if proof.get('state')=='accepted':return dict(proof,executionSeconds=time.time()-start)
   return {'state':'unknown','reason':'native_receipt_not_yet_unique','automaticReplay':False}
  finally:ui.close()
 def _save_attempt(self,j,value):
  p=self.root/(j['id']+'-attempt.json');tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False));tmp.chmod(0o600);os.replace(tmp,p)
 def save_attachment(self,j):
  source=self._native_source(j)
  if source['kind']==3:
   if not (j.get('preview') or {}).get('imageRecipe'):raise BeforeEffect('image export requires a frozen programmatic source preview')
   from .images import export
   data,proof=export(self,j)
  elif source['kind']==49:
   from .exports import cached
   try:data,proof=cached(j['peer'],j['payload']['source_id'],j['payload'].get('resource_id'),source['text'])
   except ValueError as e:raise BeforeEffect(str(e)) from None
  else:raise BeforeEffect('exact source is not a supported attachment')
  asset=self.assets.put(j['client'],proof['name'],data,hashlib.sha256(data).hexdigest());asset.pop('path',None)
  result=dict(proof,state='accepted',asset=asset,sourcePeer=j['peer'],messagesSent=0)
  path=self.root/(j['id']+'-export.json');tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(result));tmp.chmod(0o600);os.replace(tmp,path);return result
 def finalize(self,j,proof):
  from . import navigation
  if j['action']=='invite_members':
   from .group_invites import finish
   settled=finish(self,j)
   return dict(proof,navigationRestored=settled,navigationRecoveryPending=not settled,postActionPending=not settled)
  if j['action']=='create_group':
   from .groups import finish
   settled=finish(self,j)
   return dict(proof,navigationRestored=settled,navigationRecoveryPending=not settled,postActionPending=not settled)
  if j['action']=='get_group_qr':
   from .group_qr import finish
   settled=finish(self,j)
   return dict(proof,navigationRestored=settled,navigationRecoveryPending=not settled,postActionPending=not settled)
  if j['action']=='forward':
   if proof.get('state')!='accepted':return proof
   from .forwarding import finish_accepted
   settled=finish_accepted(self,j)
   return dict(proof,navigationRestored=settled,navigationRecoveryPending=not settled,draftRestored=settled,draftRecoveryPending=False,postActionPending=not settled)
  result=self._finalize_original(j,proof)
  if j['action'] not in navigation.BASIC:return result
  settled=bool(not result.get('draftRecoveryPending') and navigation.finish(self,j))
  return dict(result,navigationRestored=settled,navigationRecoveryPending=not settled,postActionPending=bool(result.get('postActionPending') or not settled))
 def _finalize_original(self,j,proof):
  if (j.get('preview') or {}).get('senderRecipe'):
   from .sending import finalize
   return finalize(self,j,proof)
  return proof
 def verify(self,j):
  if j['action']=='invite_members':
   from .group_invites import verify
   return verify(self,j)
  if j['action']=='create_group':
   from .groups import verify
   return verify(self,j)
  if j['action']=='get_group_qr':
   from .group_qr import verify
   return verify(self,j)
  if j['action']=='request_friend':
   receipt=self.root/(j['id']+'-friend-result.json')
   if receipt.exists():return json.loads(receipt.read_text())
  if j['action'] in ('join_group','accept_friend','request_friend'):return self._relation(j) or {'state':'unknown','reason':'native_relation_not_established','automaticReplay':False}
  if j['action']=='save_attachment':
   receipt=self.root/(j['id']+'-export.json')
   if receipt.exists():
    v=json.loads(receipt.read_text());self.assets.get(j['client'],v['asset']['id']);return v
   return {'state':'unknown','reason':'verified_export_not_available'}
  p=self.root/(j['id']+'-attempt.json')
  if not p.exists():return {'state':'unknown','reason':'no_attempt_receipt','automaticReplay':False}
  x=json.loads(p.read_text())
  if x['action'] in ('send_text','reply','mention','forward'):
   from .proof import native_message
   return native_message(j,x)
  if x['action']=='send_file':return self._file_helper().native_receipt(dict(x,**x['asset'],size=x['asset']['bytes']))
  if x['action']=='send_image':
   from sender import lookup
   # A unique new native image plus prepared, verified bytes; raw image hash needs separate receipt.
   return lookup({'peer':j['peer'],'kind':'send_image','started':x['startedAt'],'payload':'','seen':json.dumps(x['beforeIds']),'hash':x['asset']['sha256']})
  return {'state':'unknown','automaticReplay':False}
 def execute_step(self,j):
  from .steps import validate_step
  from sender import UI
  from image_client import Controls
  p=j['preview'];step=validate_step(p['step'],p['windowBounds'],list(j['payload']));windows=self.app_windows()
  if windows!=p['windows']:raise BeforeEffect('official windows changed since step preview')
  im=UI(BASE).screenshot();patch=p['stepPatch']
  if hashlib.sha256(im.crop(tuple(patch['box'])).tobytes()).hexdigest()!=patch['sha256']:raise BeforeEffect('target control region changed since preview')
  if step['kind']=='finish':
   if j['action'] in ('join_group','accept_friend','request_friend'):return self.verify(j)
   if j['action'] in ('open_chat','open_message'):return {'state':'accepted','peer':j['peer'],'sourceId':j['payload'].get('source_id'),'evidence':'requester-confirmed-official-client-visible-range','semanticReadingClaimed':False,'newMessageSent':False}
   return {'state':'unknown','reason':'operation-specific_native_result_required','automaticReplay':False}
  if step['kind']=='check_target':return {'state':'continue'}
  if step['kind']=='commit_friend_request':
   if j['action']!='request_friend':raise BeforeEffect('friend-request commit requires the frozen friend action')
   from linux_tool import native
   from .ocr import observe,find_line
   alias=j['payload']['alias'];identities=set()
   with native('contact/contact.db') as (db,receipt):
    if receipt.get('consistency')!='committed':raise BeforeEffect('friend identity snapshot gap')
    for table in ('contact','stranger'):
     identities.update(x[0] for x in db.execute('SELECT username FROM '+table+' WHERE alias=? OR username=?',(alias,alias)))
   if identities!={j['peer']}:raise BeforeEffect('searched WeChat alias is not uniquely bound to the frozen native peer')
   rows,_=observe(im,self.previews)
   try:find_line(rows,alias)
   except ValueError:raise BeforeEffect('friend profile alias is not uniquely visible') from None
   receipts=[json.loads(x.read_text()) for x in sorted(self.root.glob(j['id']+'-step-*.json'))]
   pasted=[v for v in receipts if v.get('state')=='step_observed' and v['step'].get('kind')=='paste' and v['step'].get('field')=='greeting']
   if not pasted:raise BeforeEffect('verification greeting has not been staged and copied back')
   c=Controls(BASE)
   try:
    import gi
    gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk
    clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);c.click(*pasted[-1]['step']['point']);c.wait(80)
    import secrets
    clip.set_text('FRIEND_GREETING_PROBE_'+secrets.token_hex(12),-1);c.wait(60);c.key(0x61,True);c.key(0x63,True);c.wait(200)
    if clip.wait_for_text()!=j['payload']['greeting']:raise BeforeEffect('actual greeting differs from frozen request')
    self._save_attempt(j,{'action':j['action'],'peer':j['peer'],'alias':alias,'startedAt':time.time(),'friendshipEstablished':False})
    c.click(*step['point'])
    for delay in (200,400,800):
     c.wait(delay);image=UI(BASE).screenshot();rows,_=observe(image,self.previews)
     for text in ('Request sent','等待验证','发送成功'):
      try:find_line(rows,text)
      except ValueError:continue
      path=self.previews/(j['id']+'-friend-result.png');image.save(path);path.chmod(0o600)
      proof={'state':'accepted','peer':j['peer'],'friendRequestSubmitted':True,'friendshipEstablished':False,'evidence':'official-client-visible-submission-confirmation','proofSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'automaticResend':False}
      pth=self.root/(j['id']+'-friend-result.json');pth.write_text(json.dumps(proof));pth.chmod(0o600);return proof
    return self._relation(j) or {'state':'unknown','reason':'friend_request_confirmation_not_proven','automaticReplay':False}
   finally:c.close()
  if step['kind']=='export_image':
   if j['action']!='save_attachment' or self._native_source(j)['kind']!=3:raise BeforeEffect('image export requires an exact image source')
   import image_client
   from contextlib import contextmanager
   @contextmanager
   def owned(root):
    self.check_lease(self.lease);yield
   old=image_client.locked;image_client.locked=owned
   try:
    cfg=self.binding(j['peer']);box=image_client.viewport(cfg);context=UI(BASE).screenshot().crop(tuple(box))
    result=image_client.dispatch(self.tool(),{'action':'image','peer':j['peer'],'server_id':j['payload']['source_id'],'point':step['point'],'context_sha256':hashlib.sha256(context.tobytes()).hexdigest()})
    data=base64.b64decode(result['content_base64'],validate=True);asset=self.assets.put(j['client'],'image.'+result['format'].lower(),data,result['sha256']);asset.pop('path',None)
    proof={'state':'accepted','sourcePeer':j['peer'],'sourceId':j['payload']['source_id'],'asset':asset,'nativeMessageMD5Matched':result['messageMd5Matched'],'origin':result['origin'],'messagesSent':0}
    path=self.root/(j['id']+'-export.json');path.write_text(json.dumps(proof));path.chmod(0o600);return proof
   finally:image_client.locked=old
  if step['kind']=='commit':
   if j['action'] not in ('reply','mention','forward'):raise BeforeEffect('this action has no message commit step')
   from sender import before
   ui=self.ui(j['peer'])
   try:
    draft=ui.draft()
    if j['action'] in ('reply','mention') and draft!=j['payload']['text']:raise BeforeEffect('actual editable text differs from frozen request')
    source=self._native_source(j) if j['action'] in ('reply','forward') else None
    if j['action']=='reply':
     from .recipes import verify_quote
     verify_quote(self,ui.cfg,source)
    self._save_attempt(j,{'action':j['action'],'peer':j['peer'],'startedAt':time.time(),'beforeIds':before(j['peer']),'nativeSource':source})
    ui.check();ui.click(ui.cfg['send']);ui.settle(600);return self.verify(j)
   finally:ui.close()
  if step['kind']=='commit_forward':
   if j['action']!='forward':raise BeforeEffect('forward commit is only for a frozen forward request')
   from .ocr import observe,find_line
   from sender import before
   target=self.tool().resolve(j['peer'])
   if self.tool().resolve(target['displayName'])['username']!=j['peer']:raise BeforeEffect('forward target name is ambiguous')
   from .forwarding import verify_commit
   if not verify_commit(self,j,im):
    b=p['windowBounds'];rows,_=observe(im,self.previews,[b[0]+469,b[1]+108,b[2]-146,b[1]+144])
    try:find_line(rows,target['displayName'])
    except ValueError:raise BeforeEffect('frozen forward recipient is not uniquely visible in selected recipients') from None
    rest=im.crop((b[0]+420,b[1]+155,b[2]-105,b[1]+380)).convert('RGB')
    if len(rows)!=1 or sum(min(v)<100 for v in rest.getdata())>30:raise BeforeEffect('unexpected additional selected-recipient content')
   self._save_attempt(j,{'action':'forward','peer':j['peer'],'startedAt':time.time(),'beforeIds':before(j['peer']),'nativeSource':self._native_source(j)})
  x,y=step['point'];cfg=None
  try:cfg=self.binding(j['peer'])
  except BeforeEffect:
   try:cfg=self.binding(j['payload'].get('inviter',j['payload'].get('source_peer','wxid_fixture_c2253ec460')))
   except BeforeEffect:
    from linux_tool import secret
    cfg=json.loads(secret(BASE/'native-ui.json'))
  # A generic navigation click must never become a shortcut around native send.
  if cfg and abs(x-cfg['send'][0])<60 and abs(y-cfg['send'][1])<28:raise BeforeEffect('main Send requires an operation-specific commit')
  if not any(w['x']<x<w['x']+w['width'] and w['y']<y<w['y']+w['height'] for w in windows):raise BeforeEffect('point outside official-client windows')
  c=Controls(BASE)
  try:
   # A mouse click sets focus itself. Explicit XSetInputFocus(main) here would
   # dismiss an owned context menu before its frozen item can be clicked.
   w=next(w for w in reversed(windows) if w['x']<x<w['x']+w['width'] and w['y']<y<w['y']+w['height'])
   step_receipt=self.root/(j['id']+'-step-'+str(int(time.time()*1000000))+'.json');v={'state':'attempting','job':j['id'],'step':step,'patch':patch,'at':time.time()};step_receipt.write_text(json.dumps(v));step_receipt.chmod(0o600)
   if step['kind'] in ('click','commit_forward'):c.click(x,y)
   elif step['kind']=='double_click':c.click(x,y);c.wait(100);c.click(x,y)
   elif step['kind']=='right_click':
    c.t.XTestFakeMotionEvent(c.d,-1,x,y,0)
    for down in (1,0):c.t.XTestFakeButtonEvent(c.d,3,down,0)
    c.x.XFlush(c.d)
   elif step['kind']=='scroll':
    c.t.XTestFakeMotionEvent(c.d,-1,x,y,0);c.x.XFlush(c.d)
    for _ in range(abs(step['amount'])):
     button=4 if step['amount']>0 else 5
     for down in [1,0]:c.t.XTestFakeButtonEvent(c.d,button,down,0)
     c.x.XFlush(c.d)
   elif step['kind']=='paste':
    c.click(x,y);c.wait(100)
    import gi
    gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk
    clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);text=j['payload'][step['field']]
    if not isinstance(text,str):raise BeforeEffect('paste field is not frozen text')
    clip.set_text(text,-1);c.wait(70)
    if j['action']!='reply':c.key(0x61,True)
    c.key(0x76,True);c.wait(300)
    import secrets
    clip.set_text('OPERATIONS_COPY_PROBE_'+secrets.token_hex(12),-1);c.wait(50);c.key(0x61,True);c.key(0x63,True);c.wait(150)
    if clip.wait_for_text()!=text:raise ValueError('actual assistance field differs; no automatic repeat')
   c.wait(350);v.update(state='step_observed',completedAt=time.time());step_receipt.write_text(json.dumps(v));step_receipt.chmod(0o600)
  finally:c.close()
  if j['action'] in ('join_group','accept_friend','request_friend'):
   relation=self._relation(j)
   if relation:return relation
  if step['kind']=='commit_forward':return self.verify(j)
  return {'state':'continue'}
 def cleanup(self,j):
  from . import navigation,composer
  if j['action']=='invite_members':
   from .group_invites import finish
   return finish(self,j)
  if j['action']=='create_group':
   from .groups import cleanup
   return cleanup(self,j)
  if j['action']=='get_group_qr':
   from .group_qr import cleanup
   return cleanup(self,j)
  if j['action']=='forward':
   from .forwarding import finish
   return finish(self,j)
  if navigation.load(self.root,j) and not composer.path(self.root,j).exists():return navigation.finish(self,j)
  if j['action'] in navigation.BASIC and not composer.path(self.root,j).exists() and not j.get('preview'):return True
  safe=self._cleanup_original(j)
  return bool(safe and navigation.finish(self,j))
 def settle_preparation_failure(self,j):
  from . import navigation,composer
  if j['action']=='forward' and not j.get('preview') and (j.get('result') or {}).get('reason')=='preparation_failed':
   from .forwarding import finish
   return finish(self,j)
  if j['action'] not in navigation.BASIC or j.get('preview') or (j.get('result') or {}).get('reason')!='preparation_failed':return False
  if composer.path(self.root,j).exists() or (self.root/(j['id']+'-attempt.json')).exists() or (self.root/(j['id']+'-execution-check.json')).exists() or list(self.root.glob(j['id']+'-step-*')):return False
  return bool(navigation.load(self.root,j) and self.cleanup(j))
 def _cleanup_original(self,j):
  p=j.get('preview') or {}
  from . import composer
  if p.get('senderRecipe') or composer.path(self.root,j).exists():
   from .sending import cleanup
   return cleanup(self,j)
  if p.get('uiBinding'):self.session_bindings[j['peer']]=p['uiBinding']
  if j['action']=='forward':
   try:
    from .recipes import cleanup_forward
    return cleanup_forward(self,j)
   except Exception:return False
  if j['action']=='reply':
   try:
    from .recipes import cleanup_reply
    return cleanup_reply(self,j)
   except Exception:return False
  if p.get('navigationBounds') and not (self.root/(j['id']+'-attempt.json')).exists() and not list(self.root.glob(j['id']+'-step-*')):return True
  if j['action']=='save_attachment' and p.get('imageRecipe'):
   from .images import clean
   return clean(self,j)
  if j['action'] in ('open_chat','save_attachment'):return True
  if (j.get('preview') or {}).get('workflow'):
   # Do not close somebody else's dialog or clear an unverified field.
   return False
  if j['preview'] and j['preview'].get('already'):return True
  try:
   ui=self.ui(j['peer'])
   try:
    if j['action']=='send_text':
     actual=ui.draft()
     if not actual:return True
     if actual!=j['payload']['text']:return False
     ui.ctrl('a')
     from image_client import Controls
     c=Controls(BASE)
     try:c.key(0xff08);c.wait(100)
     finally:c.close()
     return not ui.draft()
    if j['action']=='open_chat':return True
    if j['action'] in ('send_image','send_file') and j.get('preview'):
     # Only the exact unsent attachment belonging to this request can be removed.
     self.revalidate_asset(j);ui.click(ui.cfg['editor']);ui.ctrl('a')
     from image_client import Controls
     c=Controls(BASE)
     try:c.key(0xff08);c.wait(150)
     finally:c.close()
     self._file_helper().require_empty_editor(ui)
     return not ui.draft()
    # Never silently clear an unknown attachment or a foreign modal.
    return False
   finally:ui.close()
  except Exception:return False
 def revalidate_asset(self,j):
  if j['action'] not in ('send_image','send_file') or (self.root/(j['id']+'-attempt.json')).exists():raise BeforeEffect('only an unattempted attachment can be revalidated')
  from .visual import attachment_box
  from PIL import Image
  from sender import UI,validate_binding
  cfg=self.binding(j['peer']);image=UI(BASE).screenshot();validate_binding(cfg,{'username':j['peer']},image.crop(tuple(cfg['header_box'])).tobytes());bounds=[cfg['header_box'][0],cfg['editor'][1]-70,cfg['header_box'][2],cfg['send'][1]-20]
  with Image.open(self.previews/(j['id']+'.png')) as old:oldbox=attachment_box(old,bounds);expected=hashlib.sha256(old.crop(tuple(oldbox)).tobytes()).hexdigest()
  box=attachment_box(image,bounds)
  if hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest()!=expected:raise BeforeEffect('attachment card content differs from the original prepared preview')
  p=dict(j['preview'],**self.screenshot(j),attachmentBox=box,attachmentContext=expected);return p
