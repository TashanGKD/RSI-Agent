"""Conservative native-context image reads via the existing host/UI executor.
No model, caller pointer, raw XML output, private CDN/key handling or new queue.
"""
import base64,hashlib,io,json,re,time
from collections import Counter
from contextlib import contextmanager
from .runtime import BeforeEffect
from .contract import digest

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
  return {'peer':peer,'sourceId':server,'sender':r['sender'],'time':r['time'],'nativeMD5':md5,'resourceId':resource_id,
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
 return {'peer':peer,'sourceId':server,'sender':r['sender'],'time':r['time'],'nativeMD5':md5,'resourceId':resource_id,
  'before':dict(a,sourceId=before['id']),'after':dict(b,sourceId=after['id'])}

def load_context(driver,j):
 from linux_tool import native,signed,decode
 from image_client import source_info
 peer=j['peer'];server=j['payload']['source_id'];table='Msg_'+hashlib.md5(peer.encode()).hexdigest();records=[];budget=0
 with native('message/message_0.db') as (db,receipt):
  if receipt.get('consistency')!='committed':raise ImageReadError('IMAGE_SOURCE_UNAVAILABLE','Native source snapshot is not committed.')
  rows=db.execute('SELECT local_id,server_id,local_type,real_sender_id,create_time,message_content FROM '+table+' ORDER BY local_id DESC LIMIT 200').fetchall()
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

def locate_visible(image,box,rows,context):
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
 region=[box[0],top,box[2],bottom];im=image.crop(tuple(region)).convert('RGB');w,h=im.size
 if w*h>500000:raise ImageReadError('IMAGE_OVER_BUDGET','Visible locator region exceeds its budget.')
 # A long outgoing bubble can cover the right edge; find the same calibrated
 # neutral color around the complete boundary instead of treating it as green.
 edge=[im.getpixel((x,y)) for x in (0,w-1) for y in range(h)]+[im.getpixel((x,y)) for y in (0,h-1) for x in range(w)]
 neutral=Counter(v for v in edge if min(v)>=245 and max(v)-min(v)<=3)
 if not neutral:raise ImageReadError('UNSUPPORTED_IMAGE_LAYOUT','The calibrated neutral message background is not visible.')
 bg=neutral.most_common(1)[0][0]
 mask=bytearray(max(abs(v[k]-bg[k]) for k in range(3))>2 for v in im.getdata());candidates=[]
 for idx in range(w*h):
  if not mask[idx]:continue
  mask[idx]=0;stack=[idx];x0=w;x1=0;y0=h;y1=0;n=0
  while stack:
   p=stack.pop();y,x=divmod(p,w);n+=1;x0=min(x0,x);x1=max(x1,x);y0=min(y0,y);y1=max(y1,y)
   for q in ([p-1] if x else [])+([p+1] if x+1<w else [])+([p-w] if y else [])+([p+w] if y+1<h else []):
    if mask[q]:mask[q]=0;stack.append(q)
  if x1-x0>=70 and y1-y0>=35 and n>=1500:
   if context.get('sourceMode')=='inbound' and context.get('thumbnailWidth') and context.get('thumbnailHeight'):
    expected=context['thumbnailWidth']/context['thumbnailHeight'];actual=(x1-x0)/(y1-y0)
    if not .8*expected<=actual<=1.2*expected:continue
   if x0==0 or y0==0 or x1==w-1 or y1==h-1:raise ImageReadError('IMAGE_CANDIDATE_CLIPPED','Image candidate is not fully within the proven visible range.')
   candidates.append([region[0]+(x0+x1)//2,region[1]+(y0+y1)//2])
 if len(candidates)!=1:raise ImageReadError('IMAGE_CANDIDATE_AMBIGUOUS','Exactly one complete substantial image card must be visible between the native anchors.')
 return candidates[0]

def prepare(driver,j):
 from . import image_verified
 try:verified=image_verified.prepare(driver,j)
 except ValueError as exc:raise ImageReadError('IMAGE_SOURCE_EVIDENCE_INVALID',str(exc)[:150]) from None
 if verified is not None:return verified
 if j['payload'].get('representation')=='visible':raise ImageReadError('IMAGE_VISIBLE_SOURCE_NOT_VERIFIED','No source-qualified official visible file is registered for this exact client/peer/source.')
 from .recipes import main_window,screen,rows
 context=load_context(driver,j);driver._select(j);w=main_window(driver)
 if (w['width'],w['height']) not in ((905,667),(623,667)):raise ImageReadError('UNSUPPORTED_IMAGE_LAYOUT','A calibrated official main or conversation window is required.')
 cfg=driver.binding(j['peer']);pane=[cfg['header_box'][0],cfg['header_box'][3]+1,cfg['header_box'][2],cfg['editor'][1]-34];body=[pane[0]+70,pane[1],pane[2]-75,pane[3]]
 image=screen(driver);observed=rows(driver,body,contrast=160);point=locate_visible(image,body,observed,context)
 # OCR must not race a changed message pane.
 pane_hash=hashlib.sha256(image.crop(tuple(pane)).tobytes()).hexdigest()
 if hashlib.sha256(screen(driver).crop(tuple(pane)).tobytes()).hexdigest()!=pane_hash:raise ImageReadError('IMAGE_CONTEXT_CHANGED','Message pane changed during preparation.')
 return dict(driver.screenshot(j),imageRecipe=True,programRecipe=True,uiBinding=dict(cfg),imageContext=context,imagePane=pane,imagePoint=point,imagePaneSHA256=pane_hash,imageWindows=driver.app_windows(),context=digest(context),summary={'peer':j['peer'],'action':'save_attachment','source_id':context['sourceId'],'sender':context['sender'],'nativeMD5':context['nativeMD5'],'origin':'official-client-save-as-programmatic','cacheReused':False,'messagesSent':0})

def clean(driver,j):
 if (j.get('preview') or {}).get('verifiedImageSourceRecipe'):return True # This recipe performs no UI input/navigation.
 # Export adapter closes only its own viewer/dialog. Never close foreign windows.
 expected=(j.get('preview') or {}).get('imageWindows')
 try:return bool(expected and driver.app_windows()==expected)
 except Exception:return False

def export(driver,j):
 if (j.get('preview') or {}).get('verifiedImageSourceRecipe'):
  from .image_verified import export as qualified_export
  return qualified_export(driver,j)
 from .recipes import screen
 p=j['preview'];context=load_context(driver,j)
 if digest(context)!=p['context'] or context['peer']!=j['peer']:raise ImageReadError('IMAGE_CONTEXT_CHANGED','Native image context differs from the frozen request.')
 if not clean(driver,j):raise ImageReadError('IMAGE_CONTEXT_CHANGED','Official windows changed since the final preview.',clean=False)
 if hashlib.sha256(screen(driver).crop(tuple(p['imagePane'])).tobytes()).hexdigest()!=p['imagePaneSHA256']:raise ImageReadError('IMAGE_CONTEXT_CHANGED','Frozen message pane changed; no image is opened.')
 import image_client
 @contextmanager
 def owned(root):
  held=driver.fds;expected=driver.lease
  def require_guard():
   if not held or driver.fds is not held:raise ValueError('Original image input guard epoch changed.')
   driver.check_lease(expected)
  require_guard();yield require_guard
 old=image_client.locked;image_client.locked=owned
 try:
  try:result=image_client.dispatch(driver.tool(),{'action':'image','peer':j['peer'],'server_id':context['sourceId'],'point':p['imagePoint'],'context_sha256':p['imagePaneSHA256']})
  except ValueError:
   raise ImageReadError('IMAGE_EXPORT_NOT_PROVEN','Official image export did not prove the expected source; no bytes returned.',clean=clean(driver,j)) from None
 finally:image_client.locked=old
 if not clean(driver,j):raise ImageReadError('IMAGE_CLEANUP_UNPROVEN','Image export windows did not return to the verified initial state.',clean=False)
 if result.get('peer')!=context['peer'] or result.get('serverId')!=context['sourceId'] or result.get('senderId')!=context['sender'] or not result.get('messageMd5Matched') or not result.get('contentReady'):raise ImageReadError('IMAGE_SOURCE_MISMATCH','Official export receipt does not match the frozen native image source.')
 encoded=result.get('content_base64')
 if not isinstance(encoded,str):raise ImageReadError('IMAGE_NOT_DECODABLE','Encoded exported image required.')
 try:data=base64.b64decode(encoded,validate=True)
 except ValueError:raise ImageReadError('IMAGE_NOT_DECODABLE','Invalid exported image bytes.') from None
 info=validate_payload(data,context['nativeMD5']);suffix={'JPEG':'jpg','TIFF':'tiff'}.get(info['format'],info['format'].lower())
 proof=dict(info,name='image-'+context['sourceId']+'.'+suffix,sourceId=context['sourceId'],sender=context['sender'],resourceId=context['resourceId'],nativeMessageMD5Matched=True,sourceContextVerified=True,origin='official-client-save-as-programmatic',exportPerformedThisRequest=True,cacheReused=False,contentReady=True,businessAIReadClaimed=False,messagesSent=0)
 return data,proof
