"""Native favourite-sticker send through the original executor (type 47).

Selection: the official favourites order in emoticon.db puts the exact MD5 at
one grid cell, and that cell's pixels equal a private reference crop of the
same favourite. Receipt: exactly one new self type-47 message with the same
MD5 and native status 2. One click; an unproven result stays unknown.
"""
import hashlib,os,stat,time
from .contract import digest
from .runtime import BeforeEffect
from .group_qr import write,read

SUFFIX='sticker'
CHAT=(623,667)
PANEL=(466,466)
BUTTON=(31,636)          # emoji control, relative to the verified chat window
FAVOURITES_TAB=(134,442) # relative to the official sticker panel window
FIRST=(57,56)            # centre of the first favourite cell in the panel
PITCH=88
COLUMNS=5
VISIBLE_ROWS=4
HALF=34                  # private references are 68 px square crops
NO_ROW_SECONDS=60        # the client writes a local row as soon as a send starts


def favourites():
 from linux_tool import native
 with native('emoticon/emoticon.db') as (db,receipt):
  if receipt.get('consistency')!='committed':raise BeforeEffect('favourite sticker snapshot is not committed')
  rows=[v[0] for v in db.execute('SELECT md5 FROM kFavEmoticonOrderTable ORDER BY rowid LIMIT 1001')]
 rows=[v.lower() for v in rows if isinstance(v,str)]
 if len(rows)>1000 or len(set(rows))!=len(rows):raise BeforeEffect('favourite sticker order is not unique')
 return rows[::-1] # the official panel shows the newest favourite first


def cell_box(panel,index):
 if type(index) is not int or not 0<=index<COLUMNS*VISIBLE_ROWS:raise ValueError('favourite is outside the first visible page')
 row,col=divmod(index,COLUMNS);x=panel['x']+FIRST[0]+PITCH*col;y=panel['y']+FIRST[1]+PITCH*row
 return (x-HALF,y-HALF,x+HALF,y+HALF)


def reference(md5):
 from PIL import Image
 from .driver import BASE
 p=BASE/'sticker-refs'/(md5+'.png')
 if p.is_symlink() or not p.is_file():raise ValueError('private favourite reference missing')
 s=p.stat()
 if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>200000:raise ValueError('private regular favourite reference required')
 with Image.open(p) as image:
  image=image.convert('RGB')
  if image.size!=(2*HALF,2*HALF):raise ValueError('favourite reference geometry changed')
  return image.tobytes()


def owned_panel(before,after,chat_identity,identity):
 if any(w not in after for w in before):raise ValueError('preexisting official window changed')
 extra=[w for w in after if w['id'] not in {v['id'] for v in before}]
 if len(extra)!=1:raise ValueError('one owned sticker panel required')
 w=extra[0];i=identity(w)
 if (w['width'],w['height'])!=PANEL or any(i.get(k)!=chat_identity.get(k) for k in ('class','pid')):raise ValueError('new window is not the official sticker panel')
 return w


def prepare(d,j):
 from .recipes import PreparationError
 try:return _prepare(d,j)
 except PreparationError as e:
  # No favourite cell has been clicked during preparation, so nothing was
  # sent. Owned cleanup closes the panel and chat before recording noSend.
  e.clean=True;raise
 except (ValueError,OSError) as e:raise PreparationError('STICKER_PREPARATION_FAILED',str(e)[:150]) from None


def _prepare(d,j):
 from . import navigation
 from .recipes import controls,activate,screen,PreparationError
 from .windows import window_identity
 md5=j['payload']['md5'];order=favourites()
 if md5 not in order:raise PreparationError('STICKER_NOT_FAVOURITE','The exact sticker is not an official favourite.')
 index=order.index(md5)
 if index>=COLUMNS*VISIBLE_ROWS:raise PreparationError('STICKER_NOT_ON_FIRST_PAGE','The favourite is outside the first visible page.')
 expected=reference(md5)
 relation=None
 if j['peer'].endswith('@chatroom'):
  from .group_qr import native_relation
  relation=native_relation(d,j)
 navigation.begin(d,j);d._select(j)
 chat=getattr(d,'active_window',None);binding=d.session_bindings.get(j['peer'])
 if not chat or (chat['width'],chat['height'])!=CHAT or not (binding or {}).get('nativeTargetProof'):
  raise PreparationError('STICKER_CHAT_NOT_VERIFIED','A verified official chat window is required.')
 before=d.app_windows()
 v=write(d,j,{'phase':'selected','chat':chat,'chatIdentity':window_identity(chat),'beforeWindows':before,'index':index,'orderSHA256':digest(order)},SUFFIX)
 c=controls(d)
 try:
  activate(c,chat);v.update(phase='panel-intent');write(d,j,v,SUFFIX)
  c.click(chat['x']+BUTTON[0],chat['y']+BUTTON[1]);panel=None
  for pause in (150,250,400,800):
   c.wait(pause)
   if d.app_windows()!=before:panel=owned_panel(before,d.app_windows(),v['chatIdentity'],window_identity);break
  if panel is None:raise PreparationError('STICKER_PANEL_MISSING','No owned official sticker panel observed.')
  v.update(phase='panel-open',panel=panel,panelIdentity=window_identity(panel));write(d,j,v,SUFFIX)
  c.click(panel['x']+FAVOURITES_TAB[0],panel['y']+FAVOURITES_TAB[1]);box=cell_box(panel,index)
  for pause in (150,250,400,800,1200):
   c.wait(pause);seen=screen(d).crop(box).convert('RGB').tobytes()
   if seen==expected:break
  else:raise PreparationError('STICKER_CELL_NOT_VERIFIED','The favourite cell differs from its private reference; no click.')
  if favourites()!=order:raise PreparationError('STICKER_ORDER_CHANGED','Official favourite order changed; no click.')
  if relation is not None and native_relation(d,j)!=relation:raise PreparationError('GROUP_RELATION_CHANGED','Native group membership changed; no click.')
  v.update(phase='preview',cellBox=list(box),cellSHA256=hashlib.sha256(seen).hexdigest());write(d,j,v,SUFFIX)
  return dict(d.screenshot(j),stickerRecipe=True,programRecipe=True,context=digest(v),
              summary={'peer':j['peer'],'action':'send_sticker','md5':md5,'favouriteIndex':index,
                       'referencePixelsMatched':True,'messagesSent':0})
 finally:c.close()


def execute(d,j):
 from .recipes import controls,screen
 from .windows import window_identity
 from sender import before
 md5=j['payload']['md5'];v=read(d,j,SUFFIX)
 if not v or v['phase']!='preview' or j['preview'].get('context')!=digest(v):raise BeforeEffect('sticker request/preview changed')
 panel=v['panel']
 if d.app_windows()!=sorted(v['beforeWindows']+[panel],key=lambda w:w['id']) or window_identity(panel)!=v['panelIdentity'] or window_identity(v['chat'])!=v['chatIdentity']:raise BeforeEffect('owned sticker panel changed')
 order=favourites()
 if md5 not in order or order.index(md5)!=v['index'] or digest(order)!=v['orderSHA256']:raise BeforeEffect('official favourite order changed')
 seen=screen(d).crop(tuple(v['cellBox'])).convert('RGB').tobytes()
 if hashlib.sha256(seen).hexdigest()!=v['cellSHA256'] or seen!=reference(md5):raise BeforeEffect('favourite cell changed since preview')
 if j['peer'].endswith('@chatroom'):
  from .group_qr import native_relation
  native_relation(d,j)
 start=time.time();box=v['cellBox']
 d._save_attempt(j,{'beforeIds':before(j['peer']),'startedAt':start,'peer':j['peer'],'action':'send_sticker','md5':md5,'clickScheduled':True})
 v.update(phase='click-intent');write(d,j,v,SUFFIX);c=controls(d)
 try:
  c.click((box[0]+box[2])//2,(box[1]+box[3])//2)
  for pause in (100,200,400,800,1200,2000):
   c.wait(pause);proof=verify(d,j)
   if proof.get('state')=='accepted':return dict(proof,sendClicks=1,executionSeconds=time.time()-start)
 finally:c.close()
 return {'state':'unknown','reason':'native_sticker_receipt_not_yet_unique','sendClicks':1,'automaticReplay':False}


def verify(d,j):
 import json
 from linux_tool import native,ACCOUNT,decode
 from .proof import sticker_md5
 p=d.root/(j['id']+'-attempt.json')
 if not p.exists():return {'state':'unknown','reason':'no_attempt_receipt','automaticReplay':False}
 x=json.loads(p.read_text());md5=j['payload']['md5']
 if x.get('peer')!=j['peer'] or x.get('action')!='send_sticker' or x.get('md5')!=md5:return {'state':'unknown','reason':'attempt_identity_mismatch','automaticReplay':False}
 table='Msg_'+hashlib.md5(j['peer'].encode()).hexdigest();found={}
 with native('message/message_0.db') as (c,r):
  if r.get('consistency')!='committed':return {'state':'unknown','reason':'native_consistency_gap','automaticReplay':False}
  if not c.execute('select 1 from sqlite_master where name=?',(table,)).fetchone():return {'state':'unknown','reason':'target_messages_absent','automaticReplay':False}
  me=c.execute('select rowid from Name2Id where user_name=?',(ACCOUNT,)).fetchone()
  if not me:return {'state':'unknown','reason':'sender_unresolved','automaticReplay':False}
  rows=c.execute('select local_id,server_id,status,local_type,message_content,create_time from '+table+' where real_sender_id=? and create_time>=? limit 101',(me[0],int(x['startedAt'])-1)).fetchall()
  if len(rows)>100:return {'state':'unknown','reason':'candidate_budget','automaticReplay':False}
  for row in rows:
   sid=str(row['server_id']&0xffffffffffffffff)
   if (row['server_id'] and sid in x['beforeIds']) or int(row['local_type'])&0xffffffff!=47:continue
   if sticker_md5(row['message_content'],decode,ACCOUNT if j['peer'].endswith('@chatroom') else None)!=md5:continue
   found['local:'+str(row['local_id'])]=row
 if not found and time.time()-x['startedAt']>NO_ROW_SECONDS:
  # No local row at all long after the one click: the click did not start a send.
  return {'state':'not_sent','reason':'no_native_sticker_row_after_click','automaticReplay':False}
 if len(found)!=1:return {'state':'unknown','reason':'no_unique_native_sticker_receipt','candidates':len(found),'automaticReplay':False}
 row=next(iter(found.values()));sid=str(row['server_id']&0xffffffffffffffff)
 if row['status']!=2 or not row['server_id']:return {'state':'unknown','reason':'native_sticker_not_yet_sent','nativeStatus':row['status'],'automaticReplay':False}
 return {'state':'accepted','peer':j['peer'],'serverId':sid,'md5':md5,'nativeType':47,'nativeStatus':2,
         'nativeCreateTime':row['create_time'],'senderId':ACCOUNT,'evidence':'native-type47-md5-receipt',
         'phoneReceiptConfirmed':False,'automaticResend':False}


def cleanup(d,j):
 from .recipes import controls
 from .windows import window_identity
 from . import navigation
 try:
  v=read(d,j,SUFFIX)
  if v and v.get('phase')!='settled':
   panel=v.get('panel')
   if panel and panel['id'] in {w['id'] for w in d.app_windows()}:
    if window_identity(panel)!=v['panelIdentity']:return False
    c=controls(d)
    try:
     c.key(0xff1b) # Escape closes only the official sticker popup.
     for delay in (80,160,320,500,800):
      c.wait(delay)
      if panel['id'] not in {w['id'] for w in d.app_windows()}:break
    finally:c.close()
    if panel['id'] in {w['id'] for w in d.app_windows()}:return False
   v.update(phase='settled',settledAt=time.time());write(d,j,v,SUFFIX)
  return bool(navigation.finish(d,j))
 except Exception:return False


def finish(d,j):
 """Retry only own non-sending settlement; never a second sticker click."""
 from .recipes import controls
 for delay in (0,100,200,400):
  if delay:
   c=controls(d)
   try:c.wait(delay)
   finally:c.close()
  if cleanup(d,j):return True
 return False
