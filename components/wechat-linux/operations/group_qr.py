"""Private QR export through the same official-client executor; never sends a chat.

Identity comes from the exact native group and an owned official-window delta,
not Chinese OCR or the number printed in a group title. Public English control
labels only locate controls. Copied PNG must contain the exact displayed code.
"""
import hashlib,io,json,os,re,stat,time
from pathlib import Path
from .contract import digest
from .runtime import BeforeEffect


def relation_proof(peer,account,in_group,members):
 if not isinstance(peer,str) or not peer.endswith('@chatroom') or in_group is not True or account not in members:
  raise ValueError('exact current group and native self membership required')
 return {'peer':peer,'selfMembershipVerified':True,'memberCount':len(set(members)),
         'membershipSHA256':digest(sorted(set(members)))}


def native_relation(d,j):
 from linux_tool import native,ACCOUNT
 if ACCOUNT!=d.policy.cfg.get('account'):raise BeforeEffect('native group account changed')
 with native('contact/contact.db') as (db,r):
  if r.get('consistency')!='committed':raise BeforeEffect('group snapshot is not committed')
  rows=db.execute('SELECT is_in_chat_room FROM contact WHERE username=?',(j['peer'],)).fetchall()
  members=[v[0] for v in db.execute('SELECT c.username FROM chat_room g JOIN chatroom_member m ON g.id=m.room_id JOIN contact c ON c.id=m.member_id WHERE g.username=?',(j['peer'],))]
  return relation_proof(j['peer'],ACCOUNT,len(rows)==1 and rows[0][0]==1,members)


def owned_window(before,after,host,identity):
 if any(w not in after for w in before):raise ValueError('preexisting official window changed')
 extra=[w for w in after if w['id'] not in {v['id'] for v in before}]
 if len(extra)!=1:raise ValueError('one owned QR window required')
 w=extra[0];i=identity(w)
 if w.get('title')!='Weixin' or (w.get('width'),w.get('height'))!=(375,667) or i.get('class')!=['wechat','wechat'] or any(i.get(k)!=host.get(k) for k in ('class','pid','leader')) or i.get('transientFor') is not None or not {'_NET_WM_WINDOW_TYPE_NORMAL'}<=set(i.get('types',[]))<={'_NET_WM_WINDOW_TYPE_NORMAL','_KDE_NET_WM_WINDOW_TYPE_OVERRIDE'}:
  raise ValueError('new QR window is not the pinned official process/layout')
 return w


def qr_region(image):
 im=image.convert('RGB');w,h=im.size
 if not 200<=w<=800 or not 200<=h<=1000:raise ValueError('QR display/image geometry unsupported')
 # Sparse data rows are valid QR content. Locate its three isolated outer
 # finder rings instead of requiring every horizontal row to be dense.
 pixels=list(im.getdata());mask=bytearray(max(v)<80 for v in pixels);rings=[]
 for index in range(w*h):
  if not mask[index]:continue
  mask[index]=0;stack=[index];left=w;right=0;top=h;bottom=0;n=0
  while stack:
   p=stack.pop();y,x=divmod(p,w);n+=1;left=min(left,x);right=max(right,x);top=min(top,y);bottom=max(bottom,y)
   for q in ([p-1] if x else [])+([p+1] if x+1<w else [])+([p-w] if y else [])+([p+w] if y+1<h else []):
    if mask[q]:mask[q]=0;stack.append(q)
  bw,bh=right-left+1,bottom-top+1
  if not 20<=bw<=64 or abs(bw-bh)>1 or not .35<=n/(bw*bh)<=.7:continue
  black=lambda x,y:max(pixels[y*w+x])<80
  edges=[sum(black(x,top) for x in range(left,right+1))/bw,sum(black(x,bottom) for x in range(left,right+1))/bw,sum(black(left,y) for y in range(top,bottom+1))/bh,sum(black(right,y) for y in range(top,bottom+1))/bh]
  if min(edges)<.6:continue
  cx,cy=(left+right)//2,(top+bottom)//2
  if not black(cx,cy) or black(left+int(bw*.21),cy) or black(cx,top+int(bh*.21)):continue
  rings.append((left,top,right+1,bottom+1))
 candidates=set()
 for a in rings:
  for b in rings:
   if abs(a[1]-b[1])>1 or b[0]-a[0]<100 or abs((a[2]-a[0])-(b[2]-b[0]))>1:continue
   for c in rings:
    if abs(a[0]-c[0])>1 or c[1]-a[1]<100 or abs((a[3]-a[1])-(c[3]-c[1]))>1:continue
    box=(a[0],a[1],b[2],c[3])
    if box[2]-box[0]==box[3]-box[1] and 100<=box[2]-box[0]<=min(w,h)-20:candidates.add(box)
 if len(candidates)!=1:raise ValueError('one complete three-finder QR square not proved')
 return next(iter(candidates))


def image_proof(data,visible):
 from PIL import Image
 if not isinstance(data,bytes) or not 0<len(data)<=10000000:raise ValueError('invalid bounded clipboard PNG')
 try:
  with Image.open(io.BytesIO(data)) as source:
   if source.format!='PNG' or source.size!=(375,568):raise ValueError('unknown official QR export format/layout')
   source.load();im=source.convert('RGB')
 except Exception:raise ValueError('complete official QR PNG required') from None
 a,b=qr_region(im),qr_region(visible)
 if im.crop(a).size!=visible.crop(b).size or im.crop(a).tobytes()!=visible.convert('RGB').crop(b).tobytes():raise ValueError('clipboard code differs from the exact visible group code')
 return {'sha256':hashlib.sha256(data).hexdigest(),'md5':hashlib.md5(data).hexdigest(),'bytes':len(data),
         'width':im.width,'height':im.height,'visibleCodePixelsMatched':True,'decoded':False,
         'visibleCodeSHA256':hashlib.sha256(visible.convert('RGB').crop(b).tobytes()).hexdigest()}


def path(d,j,suffix='group-qr'):
 if not re.fullmatch('[a-f0-9]{32}',j.get('id','')):raise ValueError('internal stable job required')
 return d.root/(j['id']+'-'+suffix+'.json')


def write(d,j,value,suffix='group-qr'):
 p=path(d,j,suffix);tmp=p.with_suffix('.tmp')
 if p.is_symlink() or tmp.exists() or tmp.is_symlink():raise ValueError('QR journal path collision')
 v=dict(value,jobId=j['id'],client=j['client'],peer=j['peer'],payloadSHA256=digest(j['payload']))
 raw=json.dumps(v,ensure_ascii=False).encode()
 if len(raw)>40000:raise ValueError('QR journal over budget')
 fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as out:out.write(raw);out.flush();os.fsync(out.fileno())
 os.replace(tmp,p);return v


def read(d,j,suffix='group-qr'):
 p=path(d,j,suffix)
 if p.is_symlink():raise ValueError('QR journal symlink')
 if not p.exists():return None
 s=p.stat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>40000:raise ValueError('private regular QR journal required')
 v=json.loads(p.read_text())
 if any(v.get(k)!=expected for k,expected in [('jobId',j['id']),('client',j['client']),('peer',j['peer']),('payloadSHA256',digest(j['payload']))]):raise ValueError('QR journal request mismatch')
 return v


def controls_visible(d,w):
 from .recipes import rows
 from .selectors import unique_line
 regions={'Forward to Friends':(20,177),'Copy Image':(190,282),'Save':(302,355)}
 return {label:unique_line(rows(d,[w['x']+left,w['y']+590,w['x']+right,w['y']+635],lang='eng',psm=6),label) for label,(left,right) in regions.items()}


def sidebar_cleanup_state(v,current_hash,public_labels):
 if v.get('phase')=='sidebar-close-intent':return 'close-settled' if public_labels==0 else 'protected'
 if v.get('sidebarOpened'):return 'close-owned'
 if v.get('phase')!='sidebar-intent' or current_hash==v.get('sidebarBaselineSHA256'):return 'unchanged'
 return 'close-owned' if public_labels>=2 else 'protected'


def prepare(d,j):
 from .recipes import PreparationError
 try:return _prepare(d,j)
 except PreparationError:raise
 except (ValueError,OSError) as e:
  # The executor still requires positive owned cleanup before recording noSend.
  # A pre-input identity rejection must not become an indefinite active job.
  raise PreparationError('GROUP_QR_PREPARATION_FAILED',str(e)[:150]) from None


def _prepare(d,j):
 from . import navigation
 from .recipes import main_window,controls,activate,rows,screen,PreparationError
 from .windows import window_identity
 from .ocr import normalized
 relation=native_relation(d,j)
 navigation.begin(d,j);d._select(j);chat=main_window(d);before=d.app_windows()
 v=write(d,j,{'phase':'selected','chat':chat,'beforeWindows':before,'chatIdentity':window_identity(chat),'relation':relation,'sidebarOpened':False})
 sidebar=[chat['x']+chat['width']-250,chat['y']+82,chat['x']+chat['width']-65,chat['y']+chat['height']-12]
 v['sidebarBaselineSHA256']=hashlib.sha256(screen(d).crop(tuple(sidebar)).tobytes()).hexdigest();write(d,j,v)
 labels={'groupname','groupqrcode','myaliasingroup','searchchathistory','remark'}
 if len({normalized(r['text']) for r in rows(d,sidebar,lang='eng')}&labels)>=2:
  raise PreparationError('GROUP_INFO_PROTECTED','Existing group information panel preserved.')
 c=controls(d)
 try:
  activate(c,chat);v.update(phase='sidebar-intent');write(d,j,v)
  c.click(chat['x']+chat['width']-20,chat['y']+55);c.wait(350)
  observed=rows(d,sidebar,lang='eng')
  if len({normalized(r['text']) for r in observed}&labels)<2:raise PreparationError('GROUP_INFO_NOT_VERIFIED','Owned group information panel not proved.',clean=False)
  v.update(sidebarOpened=True);write(d,j,v);point=None
  for _ in range(6):
   found=[r['point'] for r in rows(d,sidebar,lang='eng') if normalized(r['text'])=='groupqrcode']
   if len(found)>1:raise PreparationError('GROUP_QR_CONTROL_AMBIGUOUS','Multiple QR controls.',clean=False)
   if found:point=found[0];break
   c.t.XTestFakeMotionEvent(c.d,-1,sidebar[0]+150,sidebar[3]-60,0)
   for _ in range(4):
    for down in (1,0):c.t.XTestFakeButtonEvent(c.d,5,down,0)
    c.x.XFlush(c.d);c.wait(100)
  if point is None:raise PreparationError('GROUP_QR_NOT_VISIBLE','Exact official Group QR Code control unavailable.',clean=False)
  stable=False
  for _ in range(6):
   c.wait(200);now=[r['point'] for r in rows(d,sidebar,lang='eng') if normalized(r['text'])=='groupqrcode']
   if len(now)!=1:break
   if now[0]==point:stable=True;break
   point=now[0]
  if not stable:raise PreparationError('GROUP_QR_CONTROL_MOVING','QR control has not settled; no click.',clean=False)
  v.update(phase='qr-open-intent',qrControl=point);write(d,j,v);c.click(*point)
  qr=None
  for pause in (150,250,400,800):
   c.wait(pause)
   if d.app_windows()!=before:
    qr=owned_window(before,d.app_windows(),v['chatIdentity'],window_identity);break
  if qr is None:raise PreparationError('GROUP_QR_WINDOW_MISSING','No owned QR window observed.',clean=False)
  v.update(phase='qr-open',qr=qr,qrIdentity=window_identity(qr));write(d,j,v)
  for pause in (100,200,400,800,1200):
   c.wait(pause)
   try:
    points=controls_visible(d,qr);image=screen(d).crop((qr['x'],qr['y'],qr['x']+qr['width'],qr['y']+qr['height']));region=qr_region(image);break
   except ValueError:continue
  else:raise PreparationError('GROUP_QR_NOT_LOADED','Official QR content did not load.',clean=False)
  v.update(phase='preview',qrCodeRegion=list(region),qrCodeSHA256=hashlib.sha256(image.crop(region).tobytes()).hexdigest(),copyPoint=points['Copy Image']);write(d,j,v)
  native_relation(d,j)
  return dict(d.screenshot(j),groupQRRecipe=True,programRecipe=True,context=digest(v),
              summary={'peer':j['peer'],'action':'get_group_qr','name':d.tool().resolve(j['peer'])['displayName'],'selfMembershipVerified':True,'messagesSent':0,'publishesQRCode':False})
 finally:c.close()


def execute(d,j):
 from .recipes import controls,screen,activate
 from .windows import window_identity
 v=read(d,j);native_relation(d,j)
 if not v or v['phase']!='preview' or j['preview'].get('context')!=digest(v):raise BeforeEffect('QR request/preview changed')
 qr=v['qr']
 if d.app_windows()!=sorted(v['beforeWindows']+[qr],key=lambda w:w['id']) or window_identity(qr)!=v['qrIdentity']:raise BeforeEffect('owned QR window changed')
 visible=screen(d).crop((qr['x'],qr['y'],qr['x']+qr['width'],qr['y']+qr['height']))
 if hashlib.sha256(visible.crop(tuple(v['qrCodeRegion'])).tobytes()).hexdigest()!=v['qrCodeSHA256']:raise BeforeEffect('group QR code changed since preview')
 points=controls_visible(d,qr)
 if points['Copy Image']!=v['copyPoint']:raise BeforeEffect('QR copy control changed')
 import gi
 gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk
 clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);c=controls(d)
 try:
  activate(c,qr);clip.set_text('GROUP_QR_COPY_'+j['id'],-1);c.wait(60)
  c.click(*points['Copy Image']);pix=None
  for wait in (100,200,400,800):
   c.wait(wait);pix=clip.wait_for_image()
   if pix is not None:break
  if pix is None:raise BeforeEffect('official QR clipboard image unavailable')
  data=pix.save_to_bufferv('png',[],[])[1];proof=image_proof(data,visible)
  asset=d.assets.put(j['client'],'group-qr-'+j['peer'].split('@')[0]+'.png',data,proof['sha256']);asset.pop('path',None)
  result=dict(proof,state='accepted',peer=j['peer'],asset=asset,selfMembershipVerified=True,
              origin='official-group-qr-copy-image',messagesSent=0,invitationPayloadPrivate=True,
              joinVerified=False,refreshPerformed=True,expiresAt=None,
              expirySource='official card text retained in PNG; not inferred by server')
  write(d,j,{'result':result},'group-qr-result');return result
 finally:c.close()


def verify(d,j):
 v=read(d,j,'group-qr-result')
 if not v:return {'state':'unknown','reason':'verified_qr_export_not_available','automaticReplay':False}
 result=v['result'];asset=d.assets.get(j['client'],result['asset']['id'])
 if asset['sha256']!=result['sha256']:raise ValueError('QR result asset changed')
 return result


def cleanup_failure(d,j,reason,error=None):
 try:
  value={'at':time.time(),'reason':reason,'errorType':type(error).__name__ if error else None}
  if reason=='qr-window-set':
   original=read(d,j)
   value['expectedWindowIds']=[w['id'] for w in original['beforeWindows']+[original['qr']]]
   value['observedWindows']=[dict({k:w.get(k) for k in ('id','x','y','width','height')},titleSHA256=hashlib.sha256(w.get('title','').encode()).hexdigest()) for w in d.app_windows()[:32]]
  write(d,j,value,'group-qr-cleanup')
 except Exception:pass
 return False


def wait_windows(d,c,expected):
 # Copy Image can briefly change official window visibility. Wait for the
 # exact original set, without classifying, closing or selecting the extra.
 expected=sorted(expected,key=lambda w:w['id'])
 for delay in (0,100,200,400,800,1200,2000):
  if delay:c.wait(delay)
  if d.app_windows()==expected:return True
 return False


def cleanup(d,j):
 from .recipes import controls,screen,activate,rows
 from .windows import window_identity
 from .ocr import normalized
 from . import navigation
 try:
  v=read(d,j)
  if not v:return navigation.finish(d,j)
  if v['phase']=='settled':return navigation.finish(d,j)
  c=controls(d)
  try:
   qr=v.get('qr')
   if qr and qr in d.app_windows():
    if window_identity(qr)!=v['qrIdentity']:return cleanup_failure(d,j,'qr-window-identity')
    if not wait_windows(d,c,v['beforeWindows']+[qr]):return cleanup_failure(d,j,'qr-window-set')
    if v.get('qrCodeSHA256'):
     image=screen(d).crop((qr['x'],qr['y'],qr['x']+qr['width'],qr['y']+qr['height']))
     if hashlib.sha256(image.crop(tuple(v['qrCodeRegion'])).tobytes()).hexdigest()!=v['qrCodeSHA256']:return cleanup_failure(d,j,'qr-code-pixels')
    if not v.get('qrCloseRequested'):
     v.update(qrCloseRequested=True);write(d,j,v)
     activate(c,qr);c.click(qr['x']+qr['width']-23,qr['y']+18)
    for delay in (80,160,320,500):
     c.wait(delay)
     if qr not in d.app_windows():break
   if d.app_windows()!=v['beforeWindows']:return cleanup_failure(d,j,'baseline-window-set')
   chat=v['chat'];side=[chat['x']+chat['width']-250,chat['y']+82,chat['x']+chat['width']-65,chat['y']+chat['height']-12]
   labels={'groupqrcode','groupname','myaliasingroup','searchchathistory','remark'}
   mode=sidebar_cleanup_state(v,hashlib.sha256(screen(d).crop(tuple(side)).tobytes()).hexdigest(),len({normalized(r['text']) for r in rows(d,side,lang='eng')}&labels))
   if mode=='protected':return cleanup_failure(d,j,'sidebar-transition')
   if mode=='close-owned':
    if window_identity(chat)!=v['chatIdentity']:return cleanup_failure(d,j,'chat-window-identity')
    v.update(phase='sidebar-close-intent');write(d,j,v)
    activate(c,chat);c.click(chat['x']+chat['width']-20,chat['y']+55);c.wait(350)
    if len({normalized(r['text']) for r in rows(d,side,lang='eng')}&labels)>=2:return cleanup_failure(d,j,'sidebar-close-not-yet-visible')
   v.update(phase='settled',settledAt=time.time(),sidebarOpened=False);write(d,j,v)
  finally:c.close()
  settled=navigation.finish(d,j)
  return settled or cleanup_failure(d,j,'navigation-settlement')
 except Exception as e:return cleanup_failure(d,j,'cleanup-exception',e)


def finish(d,j):
 """Retry only own non-sending settlement; no Copy Image or export replay."""
 from .recipes import controls
 for delay in (0,100,200,400):
  if delay:
   c=controls(d)
   try:c.wait(delay)
   finally:c.close()
  if cleanup(d,j):return True
 return False
