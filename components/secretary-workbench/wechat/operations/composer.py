"""Per-request draft protection; no public draft contents, no second task queue."""
import hashlib,json,os,re
from pathlib import Path
from .runtime import BeforeEffect
from .contract import digest
class DraftProtected(BeforeEffect):
 code='DRAFT_PROTECTED';clean=True

def path(root,j):
 if not re.fullmatch('[a-f0-9]{32}',j['id']):raise ValueError('internal job ID required')
 return Path(root)/(j['id']+'-composer.json')
def load(root,j):
 p=path(root,j)
 if not p.exists():return None
 if p.is_symlink() or p.stat().st_size>70000 or p.stat().st_mode&0o077:raise ValueError('private bounded composer journal required')
 x=json.loads(p.read_text())
 if x['peer']!=j['peer'] or x['payloadHash']!=digest(j['payload']):raise ValueError('composer journal identity differs')
 return x
def save(root,j,value):
 p=path(root,j);tmp=p.with_suffix('.tmp')
 if p.is_symlink() or tmp.is_symlink():raise ValueError('composer symlink refused')
 x=dict(value,peer=j['peer'],payloadHash=digest(j['payload']));raw=json.dumps(x,ensure_ascii=False).encode()
 if len(raw)>70000:raise ValueError('bounded composer journal required')
 fd=os.open(tmp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
 os.replace(tmp,p);return x

def validate_plain(text,targets,html,card,quote):
 allowed={'UTF8_STRING','TEXT','STRING','text/plain','text/plain;charset=utf-8','text/html','TIMESTAMP','TARGETS','MULTIPLE','SAVE_TARGETS','WeChat_RichEdit_Format','QQ_Unicode_RichEdit_Format','x-application-mimetype-xwechat'}
 if len(text.encode())>20000 or '@' in text or '\ufffc' in text or card or quote or targets-allowed:raise DraftProtected('Existing rich, mentioned, large or attached draft is preserved; no input was replaced.')
 if html and re.search(r'<\s*(img|object|blockquote|a)\b',html,re.I):raise DraftProtected('Existing rich draft cannot be restored losslessly; it is preserved.')

def editor_point(cfg):
 # This is inside the calibrated editor's blank right margin, not a clickable card.
 return [cfg['header_box'][2]-55,cfg['editor'][1]]

def deselect(ui):
 ui.click(editor_point(ui.cfg));ui.settle(70)

def plain_ui(driver,ui,text):
 from .recipes import screen
 from .visual import attachment_box
 from .selectors import quote_close
 # Copy result is still owned by Qt here; do not replace clipboard before proof.
 targets=set();html=''
 try:
  ok,atoms=ui.clip.wait_for_targets()
  if ok:targets={v.name() for v in atoms}
  if ui.clip.wait_for_image() is not None or ui.clip.wait_for_uris():raise DraftProtected('Existing media draft is preserved.')
  if 'text/html' in targets:
   from gi.repository import Gdk
   data=ui.clip.wait_for_contents(Gdk.Atom.intern('text/html',False));raw=bytes(data.get_data()) if data else b''
   if len(raw)>50000:raise DraftProtected('Existing rich draft exceeds its bounded proof.')
   html=raw.decode('utf-8',errors='replace')
 except DraftProtected:raise
 except Exception:raise DraftProtected('Existing draft clipboard types cannot be proven; draft preserved.') from None
 deselect(ui);im=screen(driver);cfg=ui.cfg;bounds=[cfg['header_box'][0]+20,cfg['editor'][1]-30,cfg['header_box'][2]-40,cfg['send'][1]-30]
 card=False
 try:attachment_box(im,bounds);card=True
 except ValueError as e:
  if 'no unambiguous substantial' not in str(e):card=True
 quote=False
 try:quote_close(im,[bounds[0],cfg['editor'][1],bounds[2],cfg['send'][1]-20]);quote=True
 except ValueError:pass
 validate_plain(text,targets,html,card,quote)

def clear(ui):
 from image_client import Controls
 from .driver import BASE
 ui.click(editor_point(ui.cfg));ui.ctrl('a');c=Controls(BASE)
 try:c.key(0xff08);c.wait(120)
 finally:c.close()

def park(driver,j,ui,window):
 try:old=ui.draft()
 except ValueError:raise DraftProtected('Existing composer contents cannot be proven as plain text; preserved.') from None
 if old:plain_ui(driver,ui,old)
 else:
  try:driver._file_helper().require_empty_editor(ui)
  except ValueError:raise DraftProtected('Existing non-text draft is preserved; nothing was replaced.') from None
 value=save(driver.root,j,{'priorText':old,'priorSHA':hashlib.sha256(old.encode()).hexdigest(),'priorChars':len(old),'state':'backed-up','binding':dict(ui.cfg),'window':window})
 if old:
  clear(ui)
  if ui.draft():raise DraftProtected('Draft was backed up but editor did not clear exactly; retained for maintenance.')
 driver._file_helper().require_empty_editor(ui);value['state']='parked';save(driver.root,j,value)
 return value

def restore(root,j,ui,require_empty):
 value=load(root,j)
 if not value or value['state']=='restored':return True
 text=value.get('priorText') or ''
 actual=ui.draft()
 if not text:
  if actual:return False
  try:require_empty()
  except Exception:return False
  value.update(state='restored',priorText=None);save(root,j,value);return True
 if actual!=text:
  if actual:return False
  try:require_empty();ui.stage(text,None)
  except Exception:return False
  if ui.draft()!=text:return False
 value.update(state='restored',priorText=None);save(root,j,value);return True
