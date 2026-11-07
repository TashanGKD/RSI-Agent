"""On-demand AUP WeChat entry. JSON stdin, explicit actions, no model dispatch.

The historical fixed-pair helpers below remain for old receipt regression tests.
Production reads go through isolated snapshots in linux_tool.py, never connect().
"""
import argparse,base64,ctypes,ctypes.util,fcntl,hashlib,json,os,re,sqlite3,subprocess,sys,time
from contextlib import closing
from pathlib import Path
from receive_source import SourceInbox,sid
ROOT=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))
ACCOUNT=os.environ.get('WECHAT_ACCOUNT_ID','wxid_fixture_operator');PEER='wxid_fixture_c2253ec460'
DBROOT=Path(os.environ.get('WECHAT_PROFILE',str(ROOT/'xwechat_files/fixture-profile')))/'db_storage'
TABLE='Msg_'+hashlib.md5(PEER.encode()).hexdigest()

TEXT_BYTES=32768
class TextDecodeError(ValueError):
    """Finite safe codes, still compatible with existing ValueError consumers."""
    CODES=frozenset(('TEXT_OVER_BUDGET','TEXT_COMPRESSED_INVALID','TEXT_UTF8_INVALID','TEXT_NUL','TEXT_TYPE_INVALID'))
    def __init__(self,code):
        if code not in self.CODES:raise ValueError('unknown text decode code')
        self.code=code
        super().__init__(code)

def decode_text(v):
    if isinstance(v,bytes):
        if v[:4]==b'\x28\xb5\x2f\xfd':
            z=ctypes.CDLL(ctypes.util.find_library('zstd'))
            z.ZSTD_decompress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
            z.ZSTD_decompress.restype=ctypes.c_size_t
            z.ZSTD_isError.argtypes=[ctypes.c_size_t];z.ZSTD_isError.restype=ctypes.c_uint
            z.ZSTD_getErrorCode.argtypes=[ctypes.c_size_t];z.ZSTD_getErrorCode.restype=ctypes.c_uint
            out=ctypes.create_string_buffer(TEXT_BYTES+1);n=z.ZSTD_decompress(out,TEXT_BYTES+1,v,len(v))
            if z.ZSTD_isError(n):
                # ZSTD_error_dstSize_tooSmall=70 in the installed zstd_errors.h.
                # This is a bounded budget stop, never a claim of valid content.
                code='TEXT_OVER_BUDGET' if z.ZSTD_getErrorCode(n)==70 else 'TEXT_COMPRESSED_INVALID'
                raise TextDecodeError(code)
            if n>TEXT_BYTES:raise TextDecodeError('TEXT_OVER_BUDGET')
            v=out.raw[:n]
        if len(v)>TEXT_BYTES:raise TextDecodeError('TEXT_OVER_BUDGET')
        try:v=v.decode('utf8')
        except UnicodeError:raise TextDecodeError('TEXT_UTF8_INVALID') from None
    if not isinstance(v,str):raise TextDecodeError('TEXT_TYPE_INVALID')
    if '\0' in v:raise TextDecodeError('TEXT_NUL')
    try:size=len(v.encode('utf8'))
    except UnicodeError:raise TextDecodeError('TEXT_UTF8_INVALID') from None
    if size>TEXT_BYTES:raise TextDecodeError('TEXT_OVER_BUDGET')
    return v

def validate_request(r):
    if not isinstance(r,dict) or len(r)>6:raise ValueError('invalid request')
    if r.get('peer',PEER)!=PEER:raise ValueError('unbound recipient')
    if r.get('action')=='read':
        if type(r.get('after',0)) is not int or not 0<=r.get('after',0)<2**63:raise ValueError('invalid cursor')
    elif r.get('action')=='send':
        if not re.fullmatch('[a-f0-9]{64}',r.get('request_id','')):raise ValueError('request ID must be SHA256')
        if not decode_text(r.get('text','')).strip():raise ValueError('empty send')
    elif r.get('action')=='voice':
        sid(r.get('server_id'))
    elif r.get('action')=='ack':
        if not isinstance(r.get('ack_ids'),list) or not 1<=len(r['ack_ids'])<=128:raise ValueError('bounded exact batch ACK required')
    elif r.get('action') not in ('inspect','delivery','recover'):raise ValueError('unsupported action')
    if r.get('action')=='delivery' and not re.fullmatch('[a-f0-9]{64}',r.get('request_id','')):raise ValueError('invalid request ID')
    return r

def secret_json(path):
    if path.is_symlink() or path.stat().st_mode&0o077:raise ValueError('private regular file required')
    if path.stat().st_size>32768:raise ValueError('oversized private file')
    return json.loads(path.read_text())

def connect(rel='message/message_0.db'):
    if rel not in ('message/message_0.db','contact/contact.db','message/media_0.db'):raise ValueError('unsupported source')
    sys.path.insert(0,str(ROOT/'deps'))
    from sqlcipher3 import dbapi2
    keys=secret_json(ROOT/'db-keys.json');key=keys[rel]
    if not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('invalid key format')
    c=dbapi2.connect('file:'+str(DBROOT/rel)+'?mode=ro',uri=True,timeout=2)
    c.row_factory=dbapi2.Row
    c.execute('PRAGMA key="x\''+key+'\'"');c.execute('pragma query_only=ON')
    return c

def require_supported_sources(names):
    if {name for name in names if re.fullmatch(r'message_\d+\.db',name)}!={'message_0.db'}:
        raise ValueError('source rotation requires explicit reconciliation; refusing incomplete coverage')

def read_events(after):
    require_supported_sources([p.name for p in (DBROOT/'message').glob('message_*.db')])
    inbox=source_inbox()
    try:result=inbox.read()
    finally:inbox.close()
    return {**result,'source':'message/message_0.db','table':TABLE,'health':health()}

def source_inbox():
    def stamp():
        result=[]
        for suffix in ('','-wal','-shm'):
            p=Path(str(DBROOT/'message/message_0.db')+suffix)
            if p.exists():
                s=p.stat();result.append([suffix,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns])
            else:result.append([suffix,None])
        return result
    epoch=(DBROOT/'message/message_0.db').open('rb').read(16).hex()
    return SourceInbox(ROOT/'native-source-receipts.sqlite',connect,TABLE,ACCOUNT,PEER,decode_text,epoch,stamp,only_incoming=True)

def health():
    os.environ['XAUTHORITY']=str(ROOT/'Xauthority')
    active=False
    for unit in ['tashan-wechat-client-capture.service','tashan-wechat-native-client.service']:
        p=subprocess.run(['systemctl','--user','is-active','--quiet',unit],capture_output=True,timeout=3)
        active=active or p.returncode==0
    paired=False
    try:
        from PIL import ImageGrab
        cfg=secret_json(ROOT/'native-ui.json')
        bindings=ROOT/'tool-targets.json'
        if bindings.exists():cfg=secret_json(bindings).get(PEER,cfg)
        if cfg.get('paired_account')!=ACCOUNT or cfg.get('peer')!=PEER:raise ValueError('UI identity binding mismatch')
        check_header(ImageGrab.grab(xdisplay=':97').crop(tuple(cfg['header_box'])).tobytes(),cfg['header_sha256']);paired=True
    except Exception:pass
    return {'native_client_active':active,'paired_window_ready':paired}

def check_header(pixels,expected):
    if hashlib.sha256(pixels).hexdigest()!=expected:raise ValueError('paired chat header changed; no UI action')

def voice(server_id):
    server=int(sid(server_id));raw_server=server if server<2**63 else server-2**64
    with connect() as c:
        row=c.execute('select local_id,server_id,local_type,real_sender_id from '+TABLE+' where server_id=?',(raw_server,)).fetchone()
        peerid=c.execute('select rowid from Name2Id where user_name=?',(PEER,)).fetchone()[0]
        if not row or int(row['local_type'])&0xffffffff!=34 or row['real_sender_id']!=peerid or not row['server_id']:raise ValueError('unbound voice message')
        local_id=row['local_id']
    with connect('message/media_0.db') as c:
        ids=c.execute('select rowid from Name2Id where user_name=?',(PEER,)).fetchall()
        if len(ids)!=1:raise ValueError('ambiguous native media identity')
        rows=c.execute('select voice_data from VoiceInfo where chat_name_id=? and svr_id=?',(ids[0][0],raw_server)).fetchall()
        if len(rows)!=1:return {'state':'audio_missing','local_id':local_id,'server_id':str(server)}
        data=rows[0][0]
        if not isinstance(data,bytes) or not 0<len(data)<=2000000:raise ValueError('voice size cap')
        return {'state':'audio_ready','local_id':local_id,'server_id':str(server),'sha256':hashlib.sha256(data).hexdigest(),'audio_base64':base64.b64encode(data).decode()}

def sender_state():
    p=ROOT/'native-outbox.sqlite'
    if p.is_symlink():raise ValueError('symlink state')
    if not p.exists():
        fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    c=sqlite3.connect(p);c.row_factory=sqlite3.Row
    c.execute('create table if not exists sends(id text primary key,hash text not null,text text not null,baseline integer not null,started real not null,state text not null,local_id integer,server_id text)')
    if 'seen_servers' not in {r[1] for r in c.execute('pragma table_info(sends)')}:
        c.execute('alter table sends add column seen_servers text')
    # WCDB may reuse an outgoing local_id after server reconciliation. The server
    # message ID identifies the sent message; local_id is only a lookup coordinate.
    c.execute('BEGIN IMMEDIATE')
    try:
        normalize_legacy_receipts(c)
        c.execute("create unique index if not exists one_server_receipt_per_request on sends(server_id) where server_id is not null and server_id not in ('','0')")
        c.execute('drop index if exists one_native_receipt_per_request')
        c.commit()
    except BaseException:
        c.rollback();c.close();raise
    return c

def normalize_legacy_receipts(c):
    rows=c.execute("select id,server_id from sends where server_id is not null and server_id not in ('','0')").fetchall()
    normalized={};updates=[]
    for row in rows:
        key=sid(int(row['server_id']))
        if key in normalized and normalized[key]!=row['id']:raise ValueError('ambiguous legacy server receipts require reconciliation')
        normalized[key]=row['id']
        if row['server_id']!=key:updates.append((key,row['id']))
    for key,ident in updates:c.execute('update sends set server_id=? where id=?',(key,ident))

def reconcile(c,ident):
    r=c.execute('select rowid as attempt_seq,* from sends where id=?',(ident,)).fetchone()
    if not r:return {'state':'not_found'}
    if r['state']=='accepted':return {'state':'accepted','local_id':r['local_id'],'server_id':sid(int(r['server_id']))}
    with closing(connect()) as native:
        sender=native.execute('select rowid from Name2Id where user_name=?',(ACCOUNT,)).fetchone()[0]
        rows=native.execute('select local_id,server_id,status,message_content from '+TABLE+' where create_time>=? and real_sender_id=? and local_type=1 order by create_time,local_id limit 1025',(int(r['started'])-5,sender)).fetchall()
        if len(rows)>1024:raise ValueError('receipt candidate budget exceeded')
        next_attempt=c.execute('select * from sends where rowid>? order by rowid limit 1',(r['attempt_seq'],)).fetchone()
        claimed={sid(int(v[0])) for v in c.execute("select server_id from sends where id<>? and server_id is not null and server_id not in ('','0')",(ident,))}
        seen={sid(int(v)) for v in json.loads(r['seen_servers'])} if 'seen_servers' in r.keys() and r['seen_servers'] is not None else set()
        upper_seen=None
        if next_attempt:
            upper_seen={sid(int(v)) for v in json.loads(next_attempt['seen_servers'])} if 'seen_servers' in next_attempt.keys() and next_attempt['seen_servers'] is not None else set()
        matches=[]
        for x in rows:
            key=sid(int(x['server_id'])) if x['server_id'] else None
            if key and (key in claimed or key in seen or (upper_seen is not None and key not in upper_seen)):continue
            if canonical_send(decode_text(x['message_content']))==canonical_send(r['text']):matches.append(x)
    confirmed={sid(int(x['server_id'])):x for x in matches if x['server_id'] and x['status']==2}
    if len(confirmed)==1:
        row=next(iter(confirmed.values()));key=sid(int(row['server_id']))
        with c:c.execute("update sends set state='accepted',local_id=?,server_id=? where id=?",(row['local_id'],key,ident))
        return {'state':'accepted','local_id':row['local_id'],'server_id':key}
    if not confirmed and len(matches)==1:
        row=matches[0]
        if row['server_id'] and row['status']==2:
            with c:c.execute("update sends set state='accepted',local_id=?,server_id=? where id=?",(row['local_id'],str(row['server_id']),ident))
            return {'state':'accepted','local_id':row['local_id'],'server_id':str(row['server_id'])}
        return {'state':'awaiting_wechat_transport','local_id':row['local_id']}
    return {'state':'unknown','automatic_retry':False,'reason':'no_unique_native_receipt'}

def canonical_send(text):
    return text.replace('\r\n','\n').strip()

def unresolved_send(c):
    for row in c.execute("select id from sends where state='attempting' order by rowid").fetchall():
        result=reconcile(c,row['id'])
        if result['state']!='accepted':
            return {'state':'blocked_by_uncertain_send','request_id':row['id'],'automatic_retry':False}
    return None

def send_text(r):
    r={**r,'text':canonical_send(r['text'])}
    os.environ['DISPLAY']=':97';os.environ['XAUTHORITY']=str(ROOT/'Xauthority')
    lock=os.open(ROOT/'native-ui.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        cfg=secret_json(ROOT/'native-ui.json')
        from PIL import ImageGrab
        before=ImageGrab.grab(xdisplay=':97')
        check_header(before.crop(tuple(cfg['header_box'])).tobytes(),cfg['header_sha256'])
        c=sender_state();ident=r['request_id'];digest=hashlib.sha256(r['text'].encode()).hexdigest()
        prior=c.execute('select hash,text from sends where id=?',(ident,)).fetchone()
        if prior:
            if prior['hash']!=digest and canonical_send(prior['text'])!=r['text']:raise ValueError('request ID content conflict')
            return reconcile(c,ident)
        blocked=unresolved_send(c)
        if blocked:return blocked
        started=time.time()
        with closing(connect()) as native:
            native.execute('BEGIN')
            baseline=native.execute('select coalesce(max(local_id),0) from '+TABLE).fetchone()[0]
            sender=native.execute('select rowid from Name2Id where user_name=?',(ACCOUNT,)).fetchone()[0]
            existing=native.execute('select server_id from '+TABLE+' where real_sender_id=? and create_time>=? and server_id is not null and server_id<>0 limit 1025',(sender,int(started)-5)).fetchall()
            if len(existing)>1024:raise ValueError('pre-send snapshot exceeds bounded budget')
            seen=sorted({sid(int(x[0])) for x in existing})
        # Journal before any side effect: interruption after this point never auto-clicks again.
        with c:c.execute('insert into sends(id,hash,text,baseline,started,state,seen_servers) values(?,?,?,?,?,?,?)',(ident,digest,r['text'],baseline,started,'attempting',json.dumps(seen)))
        import gi
        gi.require_version('Gtk','3.0')
        from gi.repository import Gtk,Gdk,GLib
        x=ctypes.CDLL('libX11.so.6');t=ctypes.CDLL('libXtst.so.6')
        x.XOpenDisplay.restype=ctypes.c_void_p;x.XFlush.argtypes=[ctypes.c_void_p]
        x.XKeysymToKeycode.argtypes=[ctypes.c_void_p,ctypes.c_ulong];x.XKeysymToKeycode.restype=ctypes.c_uint
        t.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
        t.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
        t.XTestFakeKeyEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
        d=x.XOpenDisplay(None)
        if not d:raise ValueError('private display unavailable')
        def click(point):
            t.XTestFakeMotionEvent(d,-1,*point,0)
            for z in (1,0):t.XTestFakeButtonEvent(d,1,z,0)
            x.XFlush(d)
        def chord(key):
            ctrl=x.XKeysymToKeycode(d,0xffe3);code=x.XKeysymToKeycode(d,key)
            for k,z in [(ctrl,1),(code,1),(code,0),(ctrl,0)]:t.XTestFakeKeyEvent(d,k,z,0)
            x.XFlush(d)
        clip=Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD);clip.set_text(r['text'],-1)
        click(cfg['editor']);chord(0x61);chord(0x76)
        loop=GLib.MainLoop();GLib.timeout_add(1800,lambda:(loop.quit(),False)[1]);loop.run()
        check_header(ImageGrab.grab(xdisplay=':97').crop(tuple(cfg['header_box'])).tobytes(),cfg['header_sha256'])
        click(cfg['send']);time.sleep(1)
        for _ in range(8):
            result=reconcile(c,ident)
            if result['state']=='accepted':return result
            time.sleep(1)
        return result
    finally:os.close(lock)

def handle(r):
    # Phase 1: ordinary WeChat is an on-demand tool, never a model entrance.
    if isinstance(r,dict) and r.get('action')=='select_target':
        raise ValueError('select_target quarantined after a focus-related unintended message; no navigation or sending performed')
    actions={'sessions','resolve','messages','voice','attachments','attachment','image_prepare','image','target_prepare','open_target','send_text','send_image','delivery','inspect_target','bind_target','select_target'}
    if isinstance(r,dict) and r.get('action') in actions:
        from linux_tool import Tool
        from sender import dispatch
        from read_metadata import Metadata
        m=Metadata(ROOT/'tool-read-metadata.sqlite')
        try:return Tool(sender=dispatch,metadata=m).handle(r)
        finally:m.close()
    if isinstance(r,dict) and r.get('action') in ('read','ack','send'):
        return {'state':'legacy_automatic_bridge_retired','reason':'Use explicit sessions/messages/voice/send_text/send_image actions; no automatic model dispatch.'}
    if isinstance(r,dict) and r.get('action')=='inspect':
        return {'state':'on_demand_tools_ready','account':ACCOUNT,'health':health(),'automaticModelDispatch':False}
    validate_request(r)
    if r['action']=='read':return read_events(r.get('after',0))
    if r['action']=='send':return send_text(r)
    if r['action']=='delivery':return reconcile(sender_state(),r['request_id'])
    if r['action']=='voice':return voice(r['server_id'])
    if r['action']=='ack':
        inbox=source_inbox()
        try:return inbox.ack(r.get('batch_id'),r.get('batch_hash'),r['ack_ids'])
        finally:inbox.close()
    if r['action']=='recover':
        h=health()
        if h['native_client_active']:return {'state':'native_client_already_running','health':h}
        p=subprocess.run(['systemctl','--user','start','tashan-wechat-native-client.service'],capture_output=True,timeout=12)
        return {'state':'native_client_start_requested' if p.returncode==0 else 'native_client_attention'}
    with connect() as c:
        n=c.execute('select count(*) from '+TABLE).fetchone()[0]
    return {'state':'source_ready','account':ACCOUNT,'peer':PEER,'paired_messages':n,'health':health()}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');a=p.parse_args()
    if not a.execute:p.print_help()
    else:
        try:
            from linux_tool import parse_request
            raw=sys.stdin.buffer.read(1500001)
            if len(raw)>1500000:raise ValueError('request size limit')
            result=handle(parse_request(raw.decode('utf8')));output=json.dumps(result,ensure_ascii=False)
            if len(output.encode())>4000000:raise ValueError('response exceeds 4 MB; request a smaller limit')
            print(output)
        except Exception as e:
            print(json.dumps({'state':'error','error_type':type(e).__name__,'reason':str(e)[:160] if type(e) is ValueError else 'tool operation failed'}));sys.exit(2)
