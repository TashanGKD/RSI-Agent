"""Native editor primitives only; no business dispatcher or group list."""
from rsi_runtime_env import display, xauthority
import ctypes,hashlib,json,os,sys,time,secrets
from pathlib import Path
def check_prior(text,expected):
 if text and hashlib.sha256(text.encode()).hexdigest()!=expected:raise PermissionError('existing draft retained; exact owned-draft approval required')

def prior_receipt(r,prior):
 if any(prior.get(k)!=r.get(k) for k in ['peer','requestId','textSha256']):raise ValueError('request ID conflicts with prior target or content')
 return dict(prior,automaticResend=False)

def check_session(expected):
 p=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))/'desktop-control-20261026/session.json'
 if p.is_symlink() or p.stat().st_mode&0o077:raise ValueError('private desktop lease required')
 s=json.loads(p.read_text())
 if s.get('session')!=expected or s.get('mode')!='compose' or s.get('expiresAt',0)<=time.time():raise ValueError('owned compose session is unavailable; another operator may be active')

class Desktop:
 def __init__(self,peer,session):
  self.session=session;check_session(session)
  os.environ.update(DISPLAY=display(),XAUTHORITY=xauthority(Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))))
  sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
  from linux_tool import Tool,ROOT as BASE
  from sender import UI
  self.target=Tool().resolve(peer);self.ui=UI(BASE);self.cfg=self.ui.config(self.target)
  import gi
  gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk,GLib
  self.GLib=GLib;self.clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
  self.x=ctypes.CDLL('libX11.so.6');self.xt=ctypes.CDLL('libXtst.so.6');x=self.x;xt=self.xt
  x.XOpenDisplay.restype=ctypes.c_void_p;self.d=x.XOpenDisplay(None)
  if not self.d:raise ValueError('authorized display unavailable')
  x.XFlush.argtypes=[ctypes.c_void_p];x.XSync.argtypes=[ctypes.c_void_p,ctypes.c_int];x.XCloseDisplay.argtypes=[ctypes.c_void_p]
  x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XKeysymToKeycode.restype=ctypes.c_uint
  xt.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong];xt.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong];xt.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
  self.check()
 def close(self):self.x.XCloseDisplay(self.d)
 def check(self):check_session(self.session);self.ui.preflight({},self.target)
 def settle(self,ms):
  loop=self.GLib.MainLoop();self.GLib.timeout_add(ms,lambda:(loop.quit(),False)[1]);loop.run()
 def click(self,point):
  self.xt.XTestFakeMotionEvent(self.d,-1,*point,0)
  for v in [1,0]:self.xt.XTestFakeButtonEvent(self.d,1,v,0)
  self.x.XSync(self.d,False)
 def ctrl(self,ch):
  ctrl=self.x.XKeysymToKeycode(self.d,0xffe3);key=self.x.XKeysymToKeycode(self.d,ord(ch))
  if not ctrl or not key:raise ValueError('native control keys unavailable')
  for k,v in [(ctrl,1),(key,1),(key,0),(ctrl,0)]:self.xt.XTestFakeKeyEvent(self.d,k,v,0)
  self.x.XSync(self.d,False)
 def draft(self):
  self.check();self.click(self.cfg['editor']);self.settle(100)
  sentinel='GROUP_DRAFT_PROBE_'+secrets.token_hex(12);self.clip.set_text(sentinel,-1);self.settle(80)
  self.ctrl('a');self.ctrl('c');self.settle(250);value=self.clip.wait_for_text()
  self.check()
  if value is None:raise ValueError('native draft unavailable')
  return '' if value==sentinel else value
 def stage(self,text,prior):
  existing=self.draft();check_prior(existing,prior)
  self.clip.set_text(text,-1);self.settle(100);self.ctrl('v');self.settle(600);actual=self.draft()
  if actual!=text:raise ValueError('native UTF-8 draft mismatch; not sent')
  return {'state':'staged-not-sent','draftSha256':hashlib.sha256(actual.encode()).hexdigest(),'exactTextMatch':True,'peer':self.target['username']}
