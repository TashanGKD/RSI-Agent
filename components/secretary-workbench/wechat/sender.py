"""Explicit, target-bound GUI sending with durable before-click journaling."""
from rsi_runtime_env import display, xauthority
import base64,ctypes,fcntl,hashlib,io,json,os,re,sqlite3,time
from pathlib import Path

def body(r):
    kind=r.get('action')
    if kind=='send_text':
        value=r.get('text')
        if not isinstance(value,str) or not value.strip() or '\0' in value or len(value.encode())>30000:raise ValueError('bounded nonempty text required')
        return value.replace('\r\n','\n').strip(),None
    if kind=='send_image':
        try:data=base64.b64decode(r.get('image_base64',''),validate=True)
        except Exception:raise ValueError('invalid image encoding') from None
        if not 0<len(data)<=1000000:raise ValueError('image limit is 1 MB')
        try:
            from PIL import Image
            with Image.open(io.BytesIO(data)) as im:
                if im.format not in ('PNG','JPEG') or im.width*im.height>4000000:raise ValueError('bounded PNG/JPEG required')
                im.verify()
        except Exception:raise ValueError('invalid bounded image') from None
        return hashlib.sha256(data).hexdigest(),data
    raise ValueError('unsupported send kind')

class Sender:
    def __init__(self,path,ui,lookup,before=lambda peer:[]):
        path=Path(path)
        if path.is_symlink():raise ValueError('symlink sender ledger')
        if not path.exists():fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        if path.stat().st_mode&0o077:raise ValueError('private sender ledger required')
        self.c=sqlite3.connect(path,timeout=5);self.c.row_factory=sqlite3.Row;self.ui=ui;self.lookup=lookup;self.before=before
        self.c.executescript('''CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY,peer TEXT NOT NULL,kind TEXT NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,started REAL NOT NULL,state TEXT NOT NULL,receipt TEXT);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY,request_id TEXT,state TEXT,receipt TEXT,at REAL);''')
        columns={x[1] for x in self.c.execute('pragma table_info(sends)')}
        for col in ('seen','server_id'):
            if col not in columns:self.c.execute('alter table sends add column '+col+' text')
        self.c.execute('create unique index if not exists server_identity on sends(server_id) where server_id is not null')
    def delivery(self,ident):
        if not re.fullmatch('[a-f0-9]{64}',ident or ''):raise ValueError('SHA256 request ID required')
        row=self.c.execute('select * from sends where id=?',(ident,)).fetchone()
        if not row:return {'state':'not_found','requestId':ident}
        if row['state']=='accepted':return json.loads(row['receipt'])
        result=self.lookup(dict(row));result.update(requestId=ident,automaticResend=False)
        claimed=self.c.execute('select id from sends where server_id=? and id<>?',(result.get('serverId'),ident)).fetchone()
        if claimed:result={'state':'unknown','requestId':ident,'reason':'native_receipt_already_claimed','automaticResend':False}
        state='accepted' if result.get('state')=='accepted' else 'unknown'
        with self.c:
            self.c.execute('update sends set state=?,receipt=? where id=?',(state,json.dumps(result),ident))
            if state=='accepted':self.c.execute('update sends set server_id=? where id=?',(result['serverId'],ident))
            self.c.execute('insert into history(request_id,state,receipt,at) values(?,?,?,?)',(ident,state,json.dumps(result),time.time()))
        return result
    def send(self,r,target):
        value,data=body(r);ident=r.get('request_id');peer=target['username']
        if not re.fullmatch('[a-f0-9]{64}',ident or ''):raise ValueError('SHA256 request ID required')
        digest=hashlib.sha256(json.dumps([peer,r['action'],value],ensure_ascii=False).encode()).hexdigest()
        prior=self.c.execute('select * from sends where id=?',(ident,)).fetchone()
        if prior:
            if prior['hash']!=digest:raise ValueError('request ID content/target conflict')
            return self.delivery(ident)
        unresolved=self.c.execute("select id from sends where state!='accepted' limit 1").fetchone()
        if unresolved:return {'state':'blocked_by_uncertain_send','requestId':unresolved[0],'automaticResend':False}
        # UI preflight executes before journaling, but has no sending side effects.
        preflight=getattr(self.ui,'preflight',None)
        if preflight:preflight(r,target)
        seen=self.before(peer)
        with self.c:
            self.c.execute('insert into sends(id,peer,kind,payload,hash,started,state,seen) values(?,?,?,?,?,?,?,?)',(ident,peer,r['action'],value,digest,time.time(),'attempting',json.dumps(seen)))
            self.c.execute('insert into history(request_id,state,at) values(?,?,?)',(ident,'attempting',time.time()))
        try:self.ui({**r,'decoded_image':data},target)
        except Exception:
            return self.delivery(ident)
        for _ in range(10):
            result=self.delivery(ident)
            if result['state']=='accepted':return result
            time.sleep(.5)
        return result

def validate_binding(cfg,target,pixels):
    if cfg.get('peer')!=target['username'] or hashlib.sha256(pixels).hexdigest()!=cfg.get('header_sha256'):raise ValueError('target binding mismatch; inspect and bind actual chat first')

class UI:
    def __init__(self,root):self.root=Path(root)
    def config(self,target):
        from linux_tool import secret
        path=self.root/'tool-targets.json'
        if path.exists():configs=json.loads(secret(path));cfg=configs.get(target['username'])
        else:cfg=None
        if not cfg:
            old=json.loads(secret(self.root/'native-ui.json'))
            if old.get('peer')==target['username']:cfg={**old,'displayName':target['displayName']}
        if not cfg:raise ValueError('target is not UI-bound; use inspect_target and bind_target')
        return cfg
    def screenshot(self):
        from PIL import ImageGrab
        os.environ['XAUTHORITY']=xauthority(self.root);return ImageGrab.grab(xdisplay=display())
    def preflight(self,r,target):
        cfg=self.config(target);validate_binding(cfg,target,self.screenshot().crop(tuple(cfg['header_box'])).tobytes())
    def select(self,target):
        """Retired keyboard navigation. Use the mouse-only target picker."""
        raise ValueError('select_target is quarantined; use target_prepare/open_target; navigation never types or presses Enter')
    def __call__(self,r,target):
        cfg=self.config(target);self.preflight(r,target)
        os.environ['DISPLAY']=display();os.environ['XAUTHORITY']=xauthority(self.root)
        import gi
        gi.require_version('Gtk','3.0');from gi.repository import Gtk,Gdk,GLib,GdkPixbuf
        x=ctypes.CDLL('libX11.so.6');t=ctypes.CDLL('libXtst.so.6');x.XOpenDisplay.restype=ctypes.c_void_p;d=x.XOpenDisplay(None)
        if not d:raise ValueError('private display unavailable')
        x.XFlush.argtypes=[ctypes.c_void_p];x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XKeysymToKeycode.restype=ctypes.c_uint
        t.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong];t.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong];t.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
        def click(pos):
            t.XTestFakeMotionEvent(d,-1,*pos,0)
            for z in (1,0):t.XTestFakeButtonEvent(d,1,z,0)
            x.XFlush(d)
        def key(symbol,ctrl=False):
            code=x.XKeysymToKeycode(d,symbol);cc=x.XKeysymToKeycode(d,0xffe3)
            seq=([(cc,1)] if ctrl else [])+[(code,1),(code,0)]+([(cc,0)] if ctrl else [])
            for k,z in seq:t.XTestFakeKeyEvent(d,k,z,0)
            x.XFlush(d)
        def settle(ms):
            loop=GLib.MainLoop();GLib.timeout_add(ms,lambda:(loop.quit(),False)[1]);loop.run()
        clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        click(cfg['editor']);key(0x61,True)
        if r['action']=='send_text':clip.set_text(r['text'],-1)
        else:
            loader=GdkPixbuf.PixbufLoader.new();loader.write(r['decoded_image']);loader.close();clip.set_image(loader.get_pixbuf())
        key(0x76,True);settle(1800)
        self.preflight(r,target)
        if r['action']=='send_text':click(cfg['send'])
        else:
            # WeChat's native image preview requires explicit Enter confirmation.
            key(0xff0d)
        settle(1000)
        x.XCloseDisplay.argtypes=[ctypes.c_void_p];x.XCloseDisplay(d)

def lookup(row):
    from linux_tool import native,ACCOUNT,decode,signed
    table='Msg_'+hashlib.md5(row['peer'].encode()).hexdigest()
    with native('message/message_0.db') as (c,receipt):
        if receipt.get('consistency')!='committed':return {'state':'unknown','reason':'source_consistency_gap'}
        if not c.execute('select 1 from sqlite_master where name=?',(table,)).fetchone():return {'state':'unknown'}
        sender=c.execute('select rowid from Name2Id where user_name=?',(ACCOUNT,)).fetchone()
        if not sender:return {'state':'unknown'}
        kind=1 if row['kind']=='send_text' else 3
        rows=c.execute('select server_id,local_id,status,message_content from '+table+' where real_sender_id=? and create_time>=? and local_type=? order by create_time,local_id limit 101',(sender[0],int(row['started'])-1,kind)).fetchall()
        if len(rows)>100:return {'state':'unknown','reason':'candidate_budget'}
        if kind==1:rows=[x for x in rows if decode(x['message_content']).replace('\r\n','\n').strip()==row['payload']]
        seen=set(json.loads(row.get('seen') or '[]'))
        rows=[x for x in rows if x['server_id'] and x['status']==2 and str(x['server_id']&0xffffffffffffffff) not in seen]
        unique={str(x['server_id']&0xffffffffffffffff):x for x in rows}
        if len(unique)!=1:return {'state':'unknown','reason':'no_unique_native_receipt'}
        sid,x=next(iter(unique.items()))
        return {'state':'accepted','peer':row['peer'],'serverId':sid,'localId':x['local_id'],'evidence':'sender-native-committed','payloadSha256':row['hash'],'phoneReceiptConfirmed':False}

def before(peer):
    from linux_tool import native
    table='Msg_'+hashlib.md5(peer.encode()).hexdigest()
    with native('message/message_0.db') as (c,r):
        if r['consistency']!='committed':raise ValueError('cannot establish a consistent pre-send snapshot')
        if not c.execute('select 1 from sqlite_master where name=?',(table,)).fetchone():return []
        rows=c.execute('select server_id from '+table+' where create_time>=? and server_id<>0 limit 1001',(int(time.time())-5,)).fetchall()
        if len(rows)>1000:raise ValueError('pre-send snapshot budget exceeded')
        return [str(x[0]&0xffffffffffffffff) for x in rows]

def inspect_target(r,target):
    """Read current header only; caller must inspect this image before binding."""
    from linux_tool import ROOT,secret
    cfg=json.loads(secret(ROOT/'native-ui.json'));ui=UI(ROOT);im=ui.screenshot().crop(tuple(cfg['header_box']))
    b=io.BytesIO();im.save(b,format='PNG')
    return {'state':'visual_verification_required','peer':target['username'],'expectedTitle':target['displayName'],'headerSha256':hashlib.sha256(im.tobytes()).hexdigest(),'header_png_base64':base64.b64encode(b.getvalue()).decode(),'instruction':'Inspect the image. Bind only if its title exactly matches the unique resolved contact. No send occurs.'}

def bind_target(r,target):
    from linux_tool import ROOT,secret,Tool
    if r.get('execute') is not True or r.get('observed_title')!=target['displayName']:raise ValueError('explicit visually observed exact title required')
    # All display-name matches must identify this same peer.
    if Tool().resolve(target['displayName'])['username']!=target['username']:raise ValueError('ambiguous target title')
    cfg=json.loads(secret(ROOT/'native-ui.json'));cfg={**cfg,'peer':target['username'],'displayName':target['displayName'],'header_sha256':r.get('header_sha256')}
    validate_binding(cfg,target,UI(ROOT).screenshot().crop(tuple(cfg['header_box'])).tobytes())
    p=ROOT/'tool-targets.json';allcfg=json.loads(secret(p)) if p.exists() else {};allcfg[target['username']]=cfg
    tmp=p.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as out:json.dump(allcfg,out,ensure_ascii=False)
    os.replace(tmp,p);return {'state':'bound','peer':target['username'],'headerSha256':cfg['header_sha256']}

def legacy_receipt(root,ident,request=None,target=None):
    """Read historical fixed-pair receipts, never re-send or open live databases."""
    p=Path(root)/'native-outbox.sqlite'
    if not p.exists():return None
    if p.is_symlink() or p.stat().st_mode&0o077:raise ValueError('private legacy receipts required')
    with sqlite3.connect(p.as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row;row=c.execute('select * from sends where id=?',(ident,)).fetchone()
        if not row:return None
        if request is not None:
            # This identity restriction describes the historical ledger only.
            if target['username']!='wxid_fixture_c2253ec460' or request.get('action')!='send_text' or body(request)[0]!=row['text'].replace('\r\n','\n').strip():raise ValueError('legacy request identity conflicts with new target/content')
        result={'state':'accepted' if row['state']=='accepted' else 'unknown','requestId':ident,'serverId':row['server_id'],'localId':row['local_id'],'legacyReceipt':True,'evidence':'preserved-legacy-ledger','automaticResend':False}
        if c.execute('select 1 from sqlite_master where name="external_receipts"').fetchone():
            ext=c.execute('select evidence from external_receipts where request_id=?',(ident,)).fetchone()
            if ext:
                proof=json.loads(ext[0])
                if proof.get('exactTextMatch') and proof.get('senderAndConversationMatched') and proof.get('serverId')==row['server_id'] and proof.get('textSha256')==hashlib.sha256(row['text'].encode()).hexdigest():result.update(evidence='recipient-native-exact-match',recipientNativeVerified=True)
        return result

def dispatch(r,target):
    from linux_tool import ROOT
    if r['action']=='inspect_target':return inspect_target(r,target)
    if r['action']=='delivery':
        old=legacy_receipt(ROOT,r.get('request_id'))
        if old:return old
        s=Sender(ROOT/'tool-sends.sqlite',UI(ROOT),lookup,before)
        try:return s.delivery(r.get('request_id'))
        finally:s.c.close()
    from image_client import locked
    with locked(ROOT):
        if r['action']=='select_target':
            UI(ROOT).select(target)
            return inspect_target(r,target)
        if r['action']=='bind_target':return bind_target(r,target)
        old=legacy_receipt(ROOT,r.get('request_id'),r,target)
        if old:return old
        s=Sender(ROOT/'tool-sends.sqlite',UI(ROOT),lookup,before)
        try:
            return s.send(r,target)
        finally:s.c.close()
