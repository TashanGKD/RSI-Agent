"""Read a bound image through official WeChat Save As, then prove message MD5.

No image keys, process access, automatic replies, or screenshot-as-original.
The caller must inspect prepare's chat context and choose the image bubble.
"""
from rsi_runtime_env import display, xauthority
import base64,ctypes,fcntl,hashlib,io,json,os,re,subprocess,sys,tempfile,time
from pathlib import Path
import xml.etree.ElementTree as ET
from contextlib import contextmanager

def source_info(raw,kind):
    if kind!=3 or not isinstance(raw,str) or len(raw.encode())>32768 or re.search(r'<!\s*(DOCTYPE|ENTITY)',raw,re.I):raise ValueError('bounded native image XML required')
    try:nodes=list(ET.fromstring(raw).iter('img'))
    except ET.ParseError:raise ValueError('invalid image XML') from None
    if len(nodes)!=1 or not re.fullmatch('[a-fA-F0-9]{32}',nodes[0].get('md5','')):raise ValueError('unambiguous native image MD5 required')
    out={'md5':nodes[0].get('md5').lower()}
    for key in ('length','hdlength','cdnthumbwidth','cdnthumbheight'):
        value=nodes[0].get(key)
        if value and value.isdecimal() and len(value)<=10:out[key]=int(value)
    return out

def validate_point(point,viewport):
    if not isinstance(point,list) or len(point)!=2 or any(type(x) is not int for x in point):raise ValueError('image point must be two integers')
    l,t,r,b=viewport
    if not l<point[0]<r or not t<point[1]<b:raise ValueError('point must stay inside chat message pane, away from editor and controls')
    return point

def check_context(pixels,wanted):
    if not isinstance(wanted,str) or not re.fullmatch('[a-f0-9]{64}',wanted) or hashlib.sha256(pixels).hexdigest()!=wanted:raise ValueError('chat context changed; inspect a fresh image_prepare result')

def verify_export(path,expected,root):
    from attachments import read_bound
    data=read_bound(root,path)
    if hashlib.md5(data).hexdigest()!=expected:raise ValueError('official export does not match requested image message MD5; not accepted')
    from PIL import Image
    Image.MAX_IMAGE_PIXELS=None
    with Image.open(io.BytesIO(data)) as im:
        info={'width':im.width,'height':im.height,'format':im.format};im.verify()
    with Image.open(io.BytesIO(data)) as im:im.load()
    return data,{**info,'bytes':len(data),'md5':expected,'sha256':hashlib.sha256(data).hexdigest()}

def parse_windows(text):
    pattern=r'(0x[0-9a-fA-F]+) "([^"]*)": \("wechat" "wechat"\)\s+(\d+)x(\d+)\+(-?\d+)\+(-?\d+)'
    return [{'id':a,'title':b,'x':int(e),'y':int(f),'width':int(c),'height':int(d)} for a,b,c,d,e,f in re.findall(pattern,text)]

# Exact existing official toolbar renderings; these pixels contain controls only,
# never image content or a QR payload. Unknown/active/hovered layouts defer.
SAVE_TOOLBARS={
    '17859a966e88f7191d19397c9476a0d2e21ba0c047e5e2cee16d812f1b4bf956':('without-qr',540),
    # Same inactive Save controls; original forum next-image arrow is enabled.
    '22754d0fea83ce24040b5cd8566cdfeb0e99779b3548e20bfdfadac832ae89d7':('without-qr',540),
    '6a899c59fd8029a1c46945873e8ad5a86caf1cdc7fa126c85bdb2e2f40b4ba13':('with-qr',582),
}

def viewer_save_proof(viewer,image):
    if (not isinstance(viewer,dict) or viewer.get('title')!='Photos and Videos'
        or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}',viewer.get('id',''))
        or any(type(viewer.get(k)) is not int for k in ('x','y','width','height'))):
        raise ValueError('exact official image viewer required before Save')
    x,y,w,h=(viewer[k] for k in ('x','y','width','height'))
    if (not 700<=w<=8192 or not 44<h<=8192 or min(x,y)<0 or image.mode!='RGB'
        or x+w>image.width or y+h>image.height):
        raise ValueError('unsupported complete viewer geometry/rendering; no toolbar input')
    prefix=hashlib.sha256(image.crop((x,y,x+640,y+44)).tobytes()).hexdigest()
    layout=SAVE_TOOLBARS.get(prefix)
    if layout is None:raise ValueError('current Save/QR toolbar is not a calibrated inactive layout')
    box=[x,y,x+w,y+44]
    return {'point':[x+layout[1],y+21],'layout':layout[0],'prefixSHA256':prefix,
            'toolbarBox':box,'toolbarSHA256':hashlib.sha256(image.crop(tuple(box)).tobytes()).hexdigest()}

def prove_viewer_save_input(control,viewer,capture,require_guard,point=None):
    from operations.windows import window_identity
    from operations.lease import birth
    if not callable(require_guard) or not callable(capture):raise ValueError('original input guard and capture required')
    require_guard()
    if control.one('Photos and Videos')!=viewer or control.one('Save',True):
        raise ValueError('viewer changed or a Save dialog already exists')
    identity=window_identity(viewer);host=window_identity(control.one('Weixin'))
    if (identity.get('class')!=['wechat','wechat'] or identity.get('class')!=host.get('class')
        or identity.get('pid')!=host.get('pid') or identity.get('leader')!=host.get('leader')
        or identity.get('transientFor') is not None
        or not {'_NET_WM_WINDOW_TYPE_NORMAL'}<=set(identity.get('types',[]))<={'_NET_WM_WINDOW_TYPE_NORMAL','_KDE_NET_WM_WINDOW_TYPE_OVERRIDE'}):
        raise ValueError('official viewer process/parent identity is not proven')
    born=birth(identity['pid'])
    if born is None:raise ValueError('official viewer process birth unavailable')
    control.require_focus(viewer)
    proof=viewer_save_proof(viewer,capture())
    if point is not None and (not isinstance(point,(list,tuple)) or len(point)!=2
        or any(type(v) is not int for v in point) or list(point)!=proof['point']):
        raise ValueError('requested toolbar point is not the current proved Save; no input')
    require_guard();control.require_focus(viewer)
    if viewer_save_proof(viewer,capture())!=proof:
        raise ValueError('full current toolbar changed before Save; no input')
    require_guard();control.require_focus(viewer)
    if (control.one('Photos and Videos')!=viewer or window_identity(viewer)!=identity
        or birth(identity['pid'])!=born):
        raise ValueError('viewer geometry/identity/process changed before Save; no input')
    require_guard()
    return dict(proof,viewerIdentity=identity,processBirth=born)

def open_viewer_save(control,viewer,capture,require_guard):
    from operations.windows import window_identity
    proof=prove_viewer_save_input(control,viewer,capture,require_guard)
    require_guard();control.click(*proof['point']);control.wait(600);require_guard()
    dialog=control.one('Save');identity=window_identity(dialog);owner=proof['viewerIdentity']
    if (not 550<=dialog['width']<=800 or not 380<=dialog['height']<=600
        or identity.get('class')!=owner['class'] or identity.get('pid')!=owner['pid']
        or identity.get('leader')!=owner['leader'] or identity.get('transientFor')!=viewer['id']):
        raise ValueError('new Save dialog ownership/layout is not proven; no filename input')
    return {'dialog':dialog,'dialogIdentity':identity,'proof':proof}

class Controls:
    def __init__(self,root):
        os.environ['DISPLAY']=display();os.environ['XAUTHORITY']=xauthority(root)
        self.x=ctypes.CDLL('libX11.so.6');self.t=ctypes.CDLL('libXtst.so.6');self.x.XOpenDisplay.restype=ctypes.c_void_p;self.d=self.x.XOpenDisplay(None)
        if not self.d:raise ValueError('private display unavailable')
        self.x.XFlush.argtypes=[ctypes.c_void_p];self.x.XCloseDisplay.argtypes=[ctypes.c_void_p]
        self.x.XSetInputFocus.argtypes=[ctypes.c_void_p,ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong]
        self.x.XGetInputFocus.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong),ctypes.POINTER(ctypes.c_int)]
        self.x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];self.x.XKeysymToKeycode.restype=ctypes.c_uint
        self.t.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
        self.t.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
        self.t.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
    def close(self):self.x.XCloseDisplay(self.d)
    def windows(self):
        r=subprocess.run(['xwininfo','-root','-tree'],capture_output=True,text=True,timeout=3)
        if r.returncode or len(r.stdout)>100000:raise ValueError('cannot inspect native windows')
        result=[]
        for w in parse_windows(r.stdout):
            info=subprocess.run(['xwininfo','-id',w['id']],capture_output=True,text=True,timeout=3)
            if info.returncode==0 and 'Map State: IsViewable' in info.stdout:result.append(w)
        return result
    def one(self,title,optional=False):
        rows=[w for w in self.windows() if w['title']==title]
        if not rows and optional:return None
        if len(rows)!=1:raise ValueError('required unique native window missing: '+title)
        return rows[0]
    def focus(self,w):self.x.XSetInputFocus(self.d,int(w['id'],16),1,0);self.x.XFlush(self.d)
    def require_focus(self,w):
        current=self.one(w['title']);focus=ctypes.c_ulong();revert=ctypes.c_int()
        self.x.XGetInputFocus(self.d,ctypes.byref(focus),ctypes.byref(revert))
        if current['id']!=w['id'] or focus.value!=int(w['id'],16):raise ValueError('native save dialog lost focus; no further keys sent')
    def click(self,x,y):
        self.t.XTestFakeMotionEvent(self.d,-1,x,y,0)
        for z in (1,0):self.t.XTestFakeButtonEvent(self.d,1,z,0)
        self.x.XFlush(self.d)
    def key(self,symbol,ctrl=False):
        key=self.x.XKeysymToKeycode(self.d,symbol);cc=self.x.XKeysymToKeycode(self.d,0xffe3)
        for k,z in (([(cc,1)] if ctrl else [])+[(key,1),(key,0)]+([(cc,0)] if ctrl else [])):self.t.XTestFakeKeyEvent(self.d,k,z,0)
        self.x.XFlush(self.d)
    def wait(self,ms):
        import gi
        gi.require_version('Gtk','3.0');from gi.repository import GLib
        loop=GLib.MainLoop();GLib.timeout_add(ms,lambda:(loop.quit(),False)[1]);loop.run()
    def paste(self,text):
        import gi
        gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk
        self.clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);self.clip.set_text(text,-1)
        self.key(0x61,True);self.key(0x76,True);self.wait(900)

@contextmanager
def locked(root):
    fd=os.open(Path(root)/'native-ui.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    held=False
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        held=True;original=os.fstat(fd)
        package=str(Path(root)/'operations-20261027')
        if package not in sys.path:sys.path.insert(0,package)
        from operations.lease import active,maintenance_guard
        state_root=Path(root)/'operations-state'
        if active(state_root):raise ValueError('Original queued operation protects this scene; use its original recovery, not legacy UI.')
        if (state_root/'queue.sqlite').exists():
            # Reuse the same accepted-cleanup/journal/ready-business barrier;
            # do not hold its DB transaction during UI work. native-ui.lock
            # already prevents a queued worker from claiming this scene.
            with maintenance_guard(state_root):pass
        def require_guard():
            if not held:raise ValueError('original native image guard released')
            current=os.fstat(fd)
            if (current.st_dev,current.st_ino)!=(original.st_dev,original.st_ino):raise ValueError('original native image guard changed')
        yield require_guard
    finally:held=False;os.close(fd)

def source(tool,r):
    from linux_tool import signed,beijing,decode
    from receive_source import sid
    target=tool.resolve(r['peer']);peer=target['username'];server=sid(r['server_id']);table='Msg_'+hashlib.md5(peer.encode()).hexdigest()
    with tool.open('message/message_0.db') as (c,receipt):
        if receipt.get('consistency')!='committed':raise ValueError('image source snapshot is not committed')
        rows=c.execute('select local_type,message_content,create_time,real_sender_id from '+table+' where server_id=?',(signed(server),)).fetchall()
        if len(rows)!=1:raise ValueError('image message is missing or ambiguous')
        x=rows[0]
        sender=c.execute('select user_name from Name2Id where rowid=?',(x['real_sender_id'],)).fetchone()
        raw=decode(x['message_content'])
        if peer.endswith('@chatroom') and sender and raw.startswith(sender[0]+':\n'):raw=raw[len(sender[0])+2:]
        meta=source_info(raw,int(x['local_type'])&0xffffffff)
        return target,{'peer':peer,'serverId':str(server),'senderId':sender[0] if sender else None,'time':x['create_time'],'timeBeijing':beijing(x['create_time']),'imageMetadata':meta,'sourceReceipt':receipt}

def viewport(cfg):return [cfg['header_box'][0],cfg['header_box'][3]+1,cfg['header_box'][2],cfg['editor'][1]-34]

def restore_main_focus(control):
    # Private Xvfb has no window manager to restore keyboard focus after closing
    # a Qt viewer. Never steal focus from an existing modal/read window.
    if control.one('Save',True) or control.one('Photos and Videos',True):return
    main=control.one('Weixin',True)
    if main:control.focus(main)

def dispatch(tool,r):
    from linux_tool import ROOT
    from sender import UI
    target,metadata=source(tool,r);ui=UI(ROOT)
    with locked(ROOT) as require_guard:
        ui.preflight(r,target);cfg=ui.config(target);box=viewport(cfg);im=ui.screenshot();context=im.crop(tuple(box))
        if r['action']=='image_prepare':
            b=io.BytesIO();context.save(b,format='PNG')
            return {'state':'image_context_ready',**metadata,'expectedTitle':target['displayName'],'viewport':box,'context_sha256':hashlib.sha256(context.tobytes()).hexdigest(),'context_png_base64':base64.b64encode(b.getvalue()).decode(),'contextIsOriginalImage':False,'instruction':'Inspect this message pane and select the requested image bubble; pass point and context_sha256 to image. Export will be rejected unless native message MD5 matches.'}
        point=validate_point(r.get('point'),box);check_context(context.tobytes(),r.get('context_sha256'))
        export_root=ROOT/'tool-image-scratch'
        if export_root.is_symlink():raise ValueError('symlink export root')
        export_root.mkdir(mode=0o700,exist_ok=True)
        if export_root.stat().st_mode&0o077:raise ValueError('private export root required')
        control=Controls(ROOT);viewer=None;dialog=None;viewer_identity=None;dialog_identity=None;viewer_birth=None
        try:
            if control.one('Save',True) or control.one('Photos and Videos',True):raise ValueError('close an existing native image/save window before this read')
            control.click(*point);control.wait(120);control.click(*point);control.wait(800)
            viewer=control.one('Photos and Videos')
            from operations.windows import window_identity
            from operations.lease import birth
            viewer_identity=window_identity(viewer);viewer_birth=birth(viewer_identity['pid'])
            control.focus(viewer)
            opened=open_viewer_save(control,viewer,ui.screenshot,require_guard)
            dialog=opened['dialog'];dialog_identity=opened['dialogIdentity']
            with tempfile.TemporaryDirectory(prefix='image-',dir=export_root) as td:
                folder=Path(td);out=folder/'image'
                control.focus(dialog);control.click(dialog['x']+int(dialog['width']*.45),dialog['y']+dialog['height']-56)
                control.require_focus(dialog);control.paste(str(out));control.require_focus(dialog);control.key(0xff0d);control.wait(800)
                files=[p for p in folder.iterdir() if p.name.startswith('image') and not p.name.endswith('.tmp')]
                if len(files)!=1:raise ValueError('official client did not export a unique image')
                data,info=verify_export(files[0],metadata['imageMetadata']['md5'],folder);files[0].chmod(0o600)
                result={'state':'image_ready',**metadata,**info,'origin':'official-client-save-as','messageMd5Matched':True,'contentReady':True,'wholeScreenScreenshot':False,'messageImageFileObtained':True,'rawCameraOriginalClaimed':False,'content_base64':base64.b64encode(data).decode(),'temporaryExportCleaned':True,'messagesSent':0}
            return result
        finally:
            try:
                if dialog and (w:=control.one('Save',True))==dialog and window_identity(w)==dialog_identity:
                    require_guard();control.focus(w);control.require_focus(w);control.key(0xff1b);control.wait(200)
                if (viewer and not control.one('Save',True) and (w:=control.one('Photos and Videos',True))==viewer
                    and window_identity(w)==viewer_identity and birth(viewer_identity['pid'])==viewer_birth):
                    # A rejected narrow/unknown layout is not authority for the
                    # old Close offset: width-24 could itself be Save or QR.
                    try:viewer_save_proof(w,ui.screenshot())
                    except ValueError:pass # Leave it protected for original-owner recovery.
                    else:
                        require_guard();control.focus(w);control.require_focus(w);control.click(w['x']+w['width']-24,w['y']+21);control.wait(200)
            finally:
                try:
                    if viewer:restore_main_focus(control)
                finally:control.close()
