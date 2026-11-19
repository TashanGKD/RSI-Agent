"""Conservative native-context image reads via the existing host/UI executor.
No model, caller pointer, raw XML output, private CDN/key handling or new queue.
"""
import base64,hashlib,io,json,os,re,subprocess,time
from collections import Counter
from .runtime import BeforeEffect
from .contract import digest
from . import inbound_image

class ImageReadError(BeforeEffect):
 def __init__(self,code,message,clean=True):super().__init__(message);self.code=code;self.clean=clean

def compact(text):return ''.join(text.split())
def anchor(text):
 # Remove only explicit leading @mentions delimited in the native message.
 body=re.sub(r'^(?:@[^\s\u2005]+[\s\u2005]+)+','',text).strip()
 if not 4<=len(compact(body))<=160:raise ImageReadError('IMAGE_CONTEXT_UNSUPPORTED','Neighbor text is not a bounded distinctive anchor.')
 return {'text':text,'body':body,'hasLeadingMentions':body!=text.strip()}

def build_context(peer,server,records,resource_id=None,resources=(),inbound=False):
 selected=[(i,r) for i,r in enumerate(records) if r['id']==server and r['peer']==peer]
 if len(selected)!=1:raise ImageReadError('IMAGE_SOURCE_NOT_FOUND','Exact image source is missing or outside the bounded native window.')
 i,r=selected[0]
 if r['kind']!=3:raise ImageReadError('NOT_AN_IMAGE','The exact source is not an image message.')
 if not isinstance(r.get('sender'),str) or not r['sender']:raise ImageReadError('IMAGE_IDENTITY_MISSING','Exact native sender identity is required.')
 m=r['meta'];md5=m.get('md5','')
 if not re.fullmatch('[a-f0-9]{32}',md5):raise ImageReadError('IMAGE_IDENTITY_MISSING','A unique native image MD5 is required.')
 if any(type(m.get(k)) is not int or m[k]<=0 for k in ('length','hdlength') if k in m):raise ImageReadError('IMAGE_IDENTITY_MISSING','Positive native image length required.')
 if inbound:
  if resource_id is not None and sum(v['resourceId']==resource_id for v in resources)!=1:raise ImageReadError('IMAGE_RESOURCE_MISMATCH','Requested resource differs from the exact source.')
  return {'peer':peer,'sourceId':server,'sender':r['sender'],'time':r['time'],'localId':r['local'],'nativeMD5':md5,'resourceId':resource_id,
   'sourceMode':'inbound','thumbnailWidth':m.get('cdnthumbwidth'),'thumbnailHeight':m.get('cdnthumbheight')}
 if not 0<i<len(records)-1:raise ImageReadError('IMAGE_CONTEXT_UNSUPPORTED','Both immediate text neighbors are required.')
 before,after=records[i-1],records[i+1]
 if any(v['peer']!=peer or v['kind']!=1 or v['sender']!=r['sender'] or not v['id'].isdecimal() or int(v['id'])==0 for v in (before,after)):
  raise ImageReadError('IMAGE_CONTEXT_AMBIGUOUS','Immediate neighbors must be text from the same native sender, with no extra image between.')
 a,b=anchor(before['text']),anchor(after['text'])
 for item in (a,b):
  count=0
  for v in records:
   if v['kind']==1:
    try:count+=compact(anchor(v['text'])['body'])==compact(item['body'])
    except ImageReadError:pass
  if count!=1:raise ImageReadError('IMAGE_CONTEXT_AMBIGUOUS','Repeated native anchor text is not a unique image locator.')
 if resource_id is not None and sum(v['resourceId']==resource_id for v in resources)!=1:raise ImageReadError('IMAGE_RESOURCE_MISMATCH','Requested resource is not uniquely bound to this peer/source.')
 return {'peer':peer,'sourceId':server,'sender':r['sender'],'time':r['time'],'localId':r['local'],'nativeMD5':md5,'resourceId':resource_id,
  'before':dict(a,sourceId=before['id']),'after':dict(b,sourceId=after['id'])}

def load_context(driver,j):
 from linux_tool import native,signed,decode
 from image_client import source_info
 peer=j['peer'];server=j['payload']['source_id'];table='Msg_'+hashlib.md5(peer.encode()).hexdigest();records=[];budget=0
 with native('message/message_0.db') as (db,receipt):
  if receipt.get('consistency')!='committed':raise ImageReadError('IMAGE_SOURCE_UNAVAILABLE','Native source snapshot is not committed.')
  columns='SELECT local_id,server_id,local_type,real_sender_id,create_time,message_content FROM '+table
  if j['payload'].get('source_mode')=='inbound':
   rows=db.execute(columns+' WHERE server_id=? LIMIT 2',(signed(server),)).fetchall()
  else:
   rows=db.execute(columns+' ORDER BY local_id DESC LIMIT 200').fetchall()
  for row in reversed(rows):
   kind=int(row['local_type'])&0xffffffff;sid=str(row['server_id']&0xffffffffffffffff);sender=db.execute('SELECT user_name FROM Name2Id WHERE rowid=?',(row['real_sender_id'],)).fetchone()
   value={'peer':peer,'id':sid,'local':row['local_id'],'kind':kind,'sender':sender[0] if sender else None,'time':row['create_time']}
   if kind==1 or sid==server:
    raw=decode(row['message_content']);budget+=len(raw.encode())
    if budget>2000000:raise ImageReadError('IMAGE_OVER_BUDGET','Bounded native context exceeds its read budget.')
    if peer.endswith('@chatroom') and sender and raw.startswith(sender[0]+':\n'):raw=raw[len(sender[0])+2:]
    if kind==1:value['text']=raw
    elif kind==3:
     try:value['meta']=source_info(raw,kind)
     except ValueError:raise ImageReadError('IMAGE_IDENTITY_MISSING','Image metadata is invalid or over budget.') from None
   records.append(value)
 resources=[];rid=j['payload'].get('resource_id')
 if rid is not None:
  with native('message/message_resource.db') as (db,receipt):
   if receipt.get('consistency')!='committed':raise ImageReadError('IMAGE_SOURCE_UNAVAILABLE','Resource snapshot is not committed.')
   rows=db.execute('SELECT d.resource_id FROM MessageResourceDetail d JOIN MessageResourceInfo i ON i.message_id=d.message_id JOIN ChatName2Id n ON n.rowid=i.chat_id WHERE n.user_name=? AND i.message_svr_id=? AND d.resource_id=? LIMIT 2',(peer,signed(server),rid)).fetchall();resources=[{'resourceId':x[0]} for x in rows]
 return build_context(peer,server,records,rid,resources,inbound=j['payload'].get('source_mode')=='inbound')

def validate_payload(data,expected_md5):
 if not isinstance(data,bytes) or not data:raise ImageReadError('IMAGE_NOT_DECODABLE','Actual image bytes required.')
 if hashlib.md5(data).hexdigest()!=expected_md5:raise ImageReadError('IMAGE_MD5_MISMATCH','Exported file differs from the exact native image MD5.')
 from .assets import validate_image
 try:
  validate_image(data)
  from PIL import Image
  with Image.open(io.BytesIO(data)) as im:info={'format':im.format,'width':im.width,'height':im.height}
 except Exception:raise ImageReadError('IMAGE_NOT_DECODABLE','Export is not a complete image readable by installed decoder.') from None
 return dict(info,bytes=len(data),md5=expected_md5,sha256=hashlib.sha256(data).hexdigest())

def _components(image,region,required_pixel=None,*,diagonal=False):
 im=image.crop(tuple(region)).convert('RGB');w,h=im.size
 top=region[1]
 if w*h>500000:raise ImageReadError('IMAGE_OVER_BUDGET','Visible locator region exceeds its budget.')
 # A long outgoing bubble can cover the right edge; find the same calibrated
 # neutral color around the complete boundary instead of treating it as green.
 edge=[im.getpixel((x,y)) for x in (0,w-1) for y in range(h)]+[im.getpixel((x,y)) for y in (0,h-1) for x in range(w)]
 neutral=Counter(v for v in edge if min(v)>=245 and max(v)-min(v)<=3)
 if not neutral:raise ImageReadError('UNSUPPORTED_IMAGE_LAYOUT','The calibrated neutral message background is not visible.')
 bg=neutral.most_common(1)[0][0]
 mask=bytearray(max(abs(v[k]-bg[k]) for k in range(3))>2 for v in im.getdata())
 required_index=None if required_pixel is None else (required_pixel[1]-top)*w+required_pixel[0]-region[0]
 for idx in range(w*h):
  if not mask[idx]:continue
  mask[idx]=0;stack=[idx];x0=w;x1=0;y0=h;y1=0;n=0;contains_required=False
  while stack:
   p=stack.pop();y,x=divmod(p,w);n+=1;x0=min(x0,x);x1=max(x1,x);y0=min(y0,y);y1=max(y1,y)
   contains_required=contains_required or p==required_index
   horizontal=([-1] if x else [])+([1] if x+1<w else [])
   vertical=([-w] if y else [])+([w] if y+1<h else [])
   neighbors=horizontal+vertical
   if diagonal:neighbors.extend(dx+dy for dx in horizontal for dy in vertical)
   for offset in neighbors:
    q=p+offset
    if mask[q]:mask[q]=0;stack.append(q)
  if x1-x0>=70 and y1-y0>=35 and n>=1500:
   yield x0+region[0],y0+top,x1+region[0],y1+top,contains_required,(region[0]+idx%w,top+idx//w)

def locate_visible(image,box,rows,context,*,message_pane=None,required_pixel=None):
 if not all(type(v) is int for v in box) or not 0<=box[0]<box[2]<=image.width or not 0<=box[1]<box[3]<=image.height:raise ImageReadError('UNSUPPORTED_IMAGE_LAYOUT','Invalid calibrated message pane.')
 def match(v,a):
  text=compact(v['text']);body=compact(a['body'])
  return text==compact(a['text']) or text==body or (a['hasLeadingMentions'] and '@' in text and text.endswith(body))
 if context.get('sourceMode')=='inbound':top,bottom=box[1],box[3]
 else:
  found=[]
  for name in ('before','after'):
   candidates=[v['point'][1] for v in rows if match(v,context[name])]
   if len(candidates)!=1:raise ImageReadError('IMAGE_ANCHORS_NOT_VISIBLE','Both exact unique anchor texts must be visible in the current message pane.')
   found.append(candidates[0])
  top,bottom=found[0]+15,found[1]-15
  if not box[1]<top<bottom<box[3]:raise ImageReadError('IMAGE_CONTEXT_AMBIGUOUS','Visible anchors are reversed, clipped, or too close.')
 region=[box[0],top,box[2],bottom];candidates=[]
 for x0,y0,x1,y1,contains_required,component_start in _components(image,region,required_pixel):
  if context.get('sourceMode')=='inbound' and context.get('thumbnailWidth') and context.get('thumbnailHeight'):
   expected=context['thumbnailWidth']/context['thumbnailHeight'];actual=(x1-x0)/(y1-y0)
   if not .8*expected<=actual<=1.2*expected:continue
  if x0==region[0] or y0==top or x1==region[2]-1 or y1==bottom-1:
   if (message_pane is not None and context.get('sourceMode')=='inbound' and y0>top and y1<bottom-1
       and context.get('thumbnailWidth') and context.get('thumbnailHeight')):
    # The locator's horizontal inset can cut a card that is fully visible in
    # the calibrated pane. Re-scan only the affected edge of this same frame.
    expanded=[message_pane[0] if x0==region[0] else box[0],top,message_pane[2] if x1==region[2]-1 else box[2],bottom]
    if expanded!=region:
     return locate_visible(image,expanded,rows,context,required_pixel=component_start)
   raise ImageReadError('IMAGE_CANDIDATE_CLIPPED','Image candidate is not fully within the proven visible range.')
  candidates.append(([(x0+x1)//2,(y0+y1)//2],contains_required))
 if len(candidates)!=1 or required_pixel is not None and not candidates[0][1]:
  raise ImageReadError('IMAGE_CANDIDATE_AMBIGUOUS','Exactly one complete substantial image card must match the proven range.')
 return candidates[0][0]

MAX_INBOUND_CANDIDATES=3

def inbound_candidates(image,box,context):
 # A message at the top can still open the official viewer. Geometry only
 # selects where to click; the exported file must independently prove its source.
 l,t,r,b=box
 width,height=context.get('thumbnailWidth'),context.get('thumbnailHeight')
 expected=width/height if width and height else None
 candidates=[]
 # Pale cards can have a one-pixel outline joined only at diagonal corners.
 for x0,y0,x1,y1,_,_ in _components(image,box,diagonal=True):
  w,h=x1-x0,y1-y0
  if not (l<x0 and x1<r-1 and y1<b-1 and h>=60 and w<=4*h):continue
  # The calibrated outgoing text bubble sits beside the right avatar and
  # has a solid WeChat green fill. It is not an incoming image candidate.
  if 50<=r-x1<=90:
   bubble=image.crop((x0,y0,x1+1,y1+1)).convert('RGB')
   if sum(pixel==(157,242,159) for pixel in bubble.getdata())>bubble.width*bubble.height/2:continue
  complete=y0>t
  shape_matches=expected and .8*expected<=w/h<=1.2*expected
  if complete:
   rank=0 if shape_matches else 2
  else:
   rank=1 if expected and w/h>1.2*expected else 3
  candidates.append((rank,-w*h,-y1,[(x0+x1)//2,(y0+y1)//2]))
 if not candidates:
  raise ImageReadError('IMAGE_CANDIDATE_AMBIGUOUS','No visible image candidate within the calibrated pane.')
 return [point for _,_,_,point in sorted(candidates)[:MAX_INBOUND_CANDIDATES]]

def prepare(driver,j):
 from . import image_verified
 try:verified=image_verified.prepare(driver,j)
 except ValueError as exc:raise ImageReadError('IMAGE_SOURCE_EVIDENCE_INVALID',str(exc)[:150]) from None
 if verified is not None:return verified
 from .recipes import main_window,screen,rows
 from . import navigation
 context=load_context(driver,j);navigation.begin(driver,j);driver._select(j);w=main_window(driver)
 if (w['width'],w['height']) not in ((905,667),(623,667)):raise ImageReadError('UNSUPPORTED_IMAGE_LAYOUT','A calibrated official main or conversation window is required.')
 cfg=driver.binding(j['peer']);pane=[cfg['header_box'][0],cfg['header_box'][3]+1,cfg['header_box'][2],cfg['editor'][1]-34];body=[pane[0]+60,pane[1],pane[2]-75,pane[3]]
 preview=dict(driver.screenshot(j),imageRecipe=True,programRecipe=True,uiBinding=dict(cfg),imageContext=context,imagePane=pane,imageWindows=driver.app_windows(),context=digest(context),summary={'peer':j['peer'],'action':'save_attachment','source_id':context['sourceId'],'sender':context['sender'],'nativeMD5':context['nativeMD5'],'origin':'official-client-save-as-programmatic','cacheReused':False,'messagesSent':0})
 if context.get('sourceMode')=='inbound' and j['payload'].get('representation')=='visible':
  # Confirmation binds the source and native window. Live coordinates are
  # resolved only while executing under the original lease.
  return preview
 image=screen(driver)
 point=locate_visible(image,body,rows(driver,body,contrast=160),context,message_pane=pane)
 pane_hash=hashlib.sha256(image.crop(tuple(pane)).tobytes()).hexdigest()
 if hashlib.sha256(screen(driver).crop(tuple(pane)).tobytes()).hexdigest()!=pane_hash:raise ImageReadError('IMAGE_CONTEXT_CHANGED','Message pane changed during preparation.')
 return dict(preview,imagePoint=point,imagePaneSHA256=pane_hash)

def clean(driver,j):
 if (j.get('preview') or {}).get('verifiedImageSourceRecipe'):return True # This recipe performs no UI input/navigation.
 # Export adapter closes only its own viewer/dialog. Never close foreign windows.
 expected=(j.get('preview') or {}).get('imageWindows')
 try:return bool(expected and driver.app_windows()==expected)
 except Exception:return False

def image_navigation_matches(nav,expected):
 from .lease import birth
 from .windows import window_identity
 stable=list(nav['beforeWindows'])
 own=nav.get('ownPopout')
 if nav['state']=='ready' and own and own not in stable:
  if window_identity(own)!=nav['ownIdentity']:return False
  stable.append(own)
 elif nav['state']!='started' or own:return False
 host=nav['mainIdentity']
 return (sorted(stable,key=lambda w:w['id'])==expected and nav['main'] in stable
         and window_identity(nav['main'])==host and birth(host['pid'])==nav['processBirth'])


def scroll_inbound_history(driver,j,nav,verify_windows,expected_signature):
 # Only a popout created by this operation can move. Usual navigation
 # cleanup closes it, preserving the user's existing chat windows.
 from . import navigation
 from .recipes import activate,controls,screen
 if not nav or nav['state']!='ready' or not nav.get('ownPopout'):return False
 preview=j['preview'];window=nav['ownPopout'];pane=preview['imagePane']
 verify_windows()
 if not image_navigation_matches(nav,preview['imageWindows']):return False
 binding=preview['uiBinding']
 if binding.get('nativeTargetProof',{}).get('window')!=window:return False
 navigation.verify_session(driver,binding,j['peer'])
 left,top,right,bottom=pane
 if not (window['x']<=left<right<=window['x']+window['width']
         and window['y']<=top<bottom<=window['y']+window['height']):return False
 control=controls(driver)
 try:
  activate(control,window)
  control.require_focus(window)
  verify_windows()
  if inbound_image.screenshot(screen(driver),pane)[1]!=expected_signature:return False
  control.t.XTestFakeMotionEvent(control.d,-1,(left+right)//2,(top+bottom)//2,0)
  for _ in range(4):
   control.t.XTestFakeButtonEvent(control.d,4,1,0)
   control.t.XTestFakeButtonEvent(control.d,4,0,0)
  control.x.XFlush(control.d)
  control.wait(350)
  verify_windows()
  return True
 finally:control.close()


def restore_auxiliary_window(driver,j,require_guard,before_probe):
 """Hide only an AppEx window newly mapped during this guarded image probe."""
 from pathlib import Path
 from image_client import Controls
 from . import navigation
 expected=j['preview']['imageWindows']
 if before_probe!=expected:return False
 try:
  nav=navigation.load(driver.root,j)
  if not nav or not image_navigation_matches(nav,expected):return False
  windows=driver.app_windows()
  added=[w for w in windows if w not in expected]
  if len(added)!=1 or any(w not in windows for w in expected):return False
  window=added[0];host=nav['mainIdentity']
  if window['title']!='WeChat' or nav['main'] not in expected:return False
  def auxiliary():
   props=subprocess.run(['xprop','-id',window['id'],'WM_CLASS','_NET_WM_PID'],
                        capture_output=True,text=True,check=True,timeout=3).stdout
   match=re.fullmatch(r'WM_CLASS\(STRING\) = "com\.tencent\.wechatappex", "WeChatAppEx"\n_NET_WM_PID\(CARDINAL\) = ([1-9][0-9]{0,9})\n',props)
   if not match:return None
   pid=int(match[1]);fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
   return (pid,fields[19]) if int(fields[1])==host['pid'] else None
  identity=auxiliary()
  if not identity:return False
  control=Controls(driver.root.parent)
  try:
   require_guard()
   if (driver.app_windows()!=windows or auxiliary()!=identity
       or not image_navigation_matches(nav,expected)):return False
   control.set_mapped(window,False)
   if clean(driver,j):return True
   if auxiliary()==identity:control.set_mapped(window,True)
   return False
  finally:control.close()
 except (OSError,ValueError,IndexError,subprocess.SubprocessError):return False

def dismiss_owned_viewer(driver,j):
 """Close one official image viewer left open by this failed export.

 The viewer must be the only new window, belong to the same WeChat process
 that owned the original navigation, and have no Save dialog. One Escape is
 sent; success requires the window set to return to its pre-export state.
 """
 from image_client import Controls
 from . import navigation
 from .lease import birth
 from .windows import window_identity
 preview=j.get('preview') or {}
 expected=preview.get('imageWindows')
 if not preview.get('imageRecipe') or preview.get('verifiedImageSourceRecipe') or not expected:return False
 control=None
 try:
  nav=navigation.load(driver.root,j)
  if not nav or not image_navigation_matches(nav,expected):return False
  windows=driver.app_windows()
  added=[w for w in windows if w not in expected]
  if len(added)!=1 or any(w not in windows for w in expected):return False
  viewer=added[0];host=nav['mainIdentity']
  if viewer['title']!='Photos and Videos':return False
  identity=window_identity(viewer)
  if (identity.get('class')!=['wechat','wechat'] or identity.get('transientFor') is not None
      or any(identity.get(k)!=host.get(k) for k in ('class','pid','leader'))
      or birth(host['pid'])!=nav['processBirth']):return False
  control=Controls(driver.root.parent)
  if control.one('Save',True) or control.one('Photos and Videos')!=viewer:return False
  control.focus(viewer);control.require_focus(viewer)
  if driver.app_windows()!=windows or window_identity(viewer)!=identity:return False
  control.key(0xff1b)
  for _ in range(10):
   control.wait(150)
   if viewer['id'] not in {w['id'] for w in driver.app_windows()}:break
  return driver.app_windows()==expected
 except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError):return False
 finally:
  if control is not None:control.close()

def export_error(driver,j,error):
 stage=getattr(error,'image_export_stage',None)
 reason='Official image export did not prove the expected source.'
 if stage in ('viewer','save-control','save-dialog','filename','export','verification'):
  reason='Official image export failed at '+stage+'.'
 fingerprint=getattr(error,'image_toolbar_fingerprint',None)
 if stage=='save-control' and isinstance(fingerprint,str) and re.fullmatch('[a-f0-9]{64}',fingerprint):
  reason='Unrecognized save-control toolbar '+fingerprint+'.'
  toolbar=getattr(error,'image_toolbar',None)
  if (toolbar is not None and toolbar.mode=='RGB' and toolbar.size==(640,44)
      and hashlib.sha256(toolbar.tobytes()).hexdigest()==fingerprint):
   path=driver.previews/(j['id']+'-save-toolbar.png')
   try:
    with os.fdopen(os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'wb') as out:toolbar.save(out,format='PNG')
    reason+=' Private control evidence: '+path.name+'.'
   except OSError:
    reason+=' Control evidence could not be stored; existing evidence retained.'
 raise ImageReadError('IMAGE_EXPORT_NOT_PROVEN',reason+' No bytes returned.',clean=clean(driver,j)) from None


def export(driver,j):
 if (j.get('preview') or {}).get('verifiedImageSourceRecipe'):
  from .image_verified import export as qualified_export
  return qualified_export(driver,j)
 from . import navigation
 from .recipes import screen
 import image_client
 from sender import UI
 p=j['preview'];context=load_context(driver,j)
 if digest(context)!=p['context'] or context['peer']!=j['peer']:
  raise ImageReadError('IMAGE_CONTEXT_CHANGED','Native image context differs from the frozen request.')
 lease, fds=driver.lease, driver.fds
 def guard():
  if not fds or driver.fds is not fds:raise ValueError('Original image input guard epoch changed.')
  driver.check_lease(lease)
 def verify_windows():
  guard()
  if not clean(driver,j):
   raise ImageReadError('IMAGE_CLEANUP_UNPROVEN','Official windows differ from the original image operation.',clean=False)
 class SelectedImageUI(UI):
  def config(self,target):
   if target['username']!=j['peer']:raise ValueError('Exact selected image peer required.')
   return p['uiBinding']
  def preflight(self,request,target):
   binding=self.config(target)
   if binding.get('nativeTargetProof'):
    return navigation.verify_session(driver,binding,target['username'])
   return super().preflight(request,target)
 inbound=context.get('sourceMode')=='inbound' and j['payload'].get('representation')=='visible'
 before_probe=None
 def probe(point,signature):
  nonlocal before_probe
  if inbound:
   guard()
   before_probe=driver.app_windows()
   if before_probe!=p['imageWindows']:
    raise ImageReadError('IMAGE_CLEANUP_UNPROVEN','Official windows changed before this image probe.',clean=False)
  request={'action':'image','peer':j['peer'],'server_id':context['sourceId'],'point':point,
           'context_sha256':signature,'representation':j['payload'].get('representation','original')}
  return image_client.dispatch(driver.tool(),request,ui=SelectedImageUI(driver.root),guard=guard)
 def recover(error):
  if getattr(error,'image_export_stage',None)!='viewer' or getattr(error,'image_viewer_missing',False) is not True:return False
  if not clean(driver,j):restore_auxiliary_window(driver,j,guard,before_probe)
  return True
 if inbound:
  pane=p['imagePane']
  def points(image):
   try:return inbound_candidates(image,pane,context)
   except ImageReadError as error:
    if error.code!='IMAGE_CANDIDATE_AMBIGUOUS':raise
    return []
  try:
   nav=navigation.load(driver.root,j)
   seek=None
   if nav and nav['state']=='ready' and nav.get('ownPopout'):
    seek=lambda signature:scroll_inbound_history(driver,j,nav,verify_windows,signature)
   result=inbound_image.capture(lambda:inbound_image.screenshot(screen(driver),pane),points,probe,recover,verify_windows,seek)
  except inbound_image.UnresolvedImage as error:
   raise ImageReadError(error.code,str(error),clean=clean(driver,j)) from None
  except ImageReadError:raise
  except ValueError as error:export_error(driver,j,error)
 else:
  verify_windows()
  if hashlib.sha256(screen(driver).crop(tuple(p['imagePane'])).tobytes()).hexdigest()!=p['imagePaneSHA256']:
   raise ImageReadError('IMAGE_CONTEXT_CHANGED','Frozen manual image location changed.')
  try:result=probe(p['imagePoint'],p['imagePaneSHA256'])
  except ValueError as error:export_error(driver,j,error)
  verify_windows()
 visible=j['payload'].get('representation')=='visible'
 if result.get('peer')!=context['peer'] or result.get('serverId')!=context['sourceId'] or result.get('senderId')!=context['sender'] or not result.get('contentReady'):raise ImageReadError('IMAGE_SOURCE_MISMATCH','Official export receipt does not match the frozen native image source.')
 if not visible and not result.get('messageMd5Matched'):raise ImageReadError('IMAGE_SOURCE_MISMATCH','Native original image MD5 is not proven.')
 encoded=result.get('content_base64')
 if not isinstance(encoded,str):raise ImageReadError('IMAGE_NOT_DECODABLE','Encoded exported image required.')
 try:data=base64.b64decode(encoded,validate=True)
 except ValueError:raise ImageReadError('IMAGE_NOT_DECODABLE','Invalid exported image bytes.') from None
 actual_md5=hashlib.md5(data).hexdigest();matched=actual_md5==context['nativeMD5']
 if visible and not matched:
  if not result.get('nativeSourceIdentityVerified') or result.get('sourceLocalId')!=context['localId'] or result.get('time')!=context['time']:raise ImageReadError('IMAGE_SOURCE_MISMATCH','Official visible source identity is not proven.')
  try:image_client.verify_filename(result.get('officialDefaultFilename'),result)
  except ValueError:raise ImageReadError('IMAGE_SOURCE_MISMATCH','Official visible filename does not match the original message.') from None
 info=validate_payload(data,actual_md5 if visible else context['nativeMD5']);suffix={'JPEG':'jpg','TIFF':'tiff'}.get(info['format'],info['format'].lower())
 proof=dict(info,name='image-'+context['sourceId']+'.'+suffix,sourceId=context['sourceId'],sender=context['sender'],resourceId=context['resourceId'],nativeMessageMD5Matched=matched,sourceContextVerified=True,origin='official-client-save-as-programmatic',exportPerformedThisRequest=True,cacheReused=False,contentReady=True,businessAIReadClaimed=False,messagesSent=0)
 if visible:
  proof.update(nativeSourceIdentityVerified=True,nativeSourceMD5=context['nativeMD5'],sourceLocalId=context['localId'],sourceCreateTime=context['time'])
  if matched:proof.update(sourceIdentityMethod='native-message-md5',representation='original')
  else:proof.update(officialDefaultFilename=result['officialDefaultFilename'],sourceIdentityMethod='official-save-as-native-time-and-local-id',representation='official-visible-variant')
 if navigation.load(driver.root,j):
  if not navigation.finish(driver,j):raise ImageReadError('IMAGE_CLEANUP_UNPROVEN','Original image navigation did not return to its verified baseline.',clean=False)
  proof['navigationRestored']=True
 return data,proof
