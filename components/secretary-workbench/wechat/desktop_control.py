#!/usr/bin/env python3
"""Bounded AUP desktop sessions. No arguments do nothing; no WeChat business actions."""
import argparse, base64, contextlib, fcntl, hashlib, hmac, http.client, json, os, re, secrets
import select, signal, socket, socketserver, stat, subprocess, sys, threading, time
from pathlib import Path

ROOT=Path(os.environ.get('WECHAT_TOOL_ROOT','/var/lib/secretary-wechat'))/'desktop-control-20261026'
REMOTE=os.environ.get('WECHAT_DESKTOP_REMOTE_CODE','/opt/secretary-workbench/wechat/desktop_control.py')
HOST=os.environ.get('WECHAT_DESKTOP_BIND','127.0.0.1')
SSH=['/usr/bin/ssh','-oBatchMode=yes','-oConnectTimeout=10',os.environ.get('WECHAT_SSH_HOST','secretary-wechat-host')]
MODES=('view','navigate','compose')

class DesktopCleanupRequired(ValueError):
    code='DESKTOP_CLEANUP_REQUIRED'

def official_scene():
    """Private window identity/geometry only. Never chat, draft or title text."""
    package=str(Path(__file__).resolve().parent)
    if package not in sys.path:sys.path.insert(0,package)
    from operations.driver import NativeDriver
    from operations.cli import load_config
    from operations.windows import window_identity
    state=ROOT.parent/'operations-state'
    driver=NativeDriver(state,load_config(state/'config.json'))
    windows=driver.app_windows()
    if len(windows)>32:raise ValueError('official window snapshot is not bounded')
    out=[]
    for w in windows:
        identity=window_identity(w);role='other'
        if identity['class']==['wechat','wechat']:
            if w['title']=='Weixin' and (w['width'],w['height'])==(905,667):role='main'
            elif (w['width'],w['height'])==(623,667) and driver.known_chat_window(w['title']):role='chat'
        out.append({**{k:w[k] for k in ('id','x','y','width','height')},
                    'titleSHA256':hashlib.sha256(w['title'].encode()).hexdigest(),
                    'identity':identity,'role':role})
    return out

def _checked_scene(values):
    if not isinstance(values,list) or len(values)>32:raise ValueError('bounded window scene required')
    if len(json.dumps(values).encode())>12000:raise ValueError('window metadata exceeds private session receipt budget')
    result={}
    for w in values:
        required={'id','x','y','width','height','titleSHA256','identity','role'}
        if not isinstance(w,dict) or set(w)!=required or not isinstance(w['id'],str) or not re.fullmatch(r'0x[0-9a-fA-F]{1,16}',w['id']) or w['id'] in result:raise ValueError('unique exact window identity required')
        if any(type(w[k]) is not int for k in ('x','y','width','height')) or not 0<w['width']<=10000 or not 0<w['height']<=10000 or w['role'] not in ('main','chat','other') or not re.fullmatch('[a-f0-9]{64}',str(w['titleSHA256'])) or not isinstance(w['identity'],dict):raise ValueError('invalid native scene fields')
        result[w['id']]=w
    return result

def scene_restored(baseline,current):
    before=_checked_scene(baseline);after=_checked_scene(current)
    for wid,old in before.items():
        now=after.get(wid)
        if now is None or any(now[k]!=old[k] for k in ('x','y','width','height','identity')):return False
        # Native-verified existing chat titles can change with membership/name;
        # never treat OCR punctuation/count pixels as an added permission gate.
        if now['titleSHA256']!=old['titleSHA256'] and not (old['role']=='chat' and now['role']=='chat'):return False
    # Registered native chat popouts may intentionally be retained. New
    # viewer/history/dialog/unknown windows cannot be ignored or closed here.
    return all(w['role']=='chat' for wid,w in after.items() if wid not in before)

def stop_scene_evidence(state):
    """Observe real scene delta; stopping transport never restores WeChat UI."""
    if state.get('mode') not in ('navigate','compose') or 'windowBaseline' not in state:
        return {'available':False,'reason':'no-input-baseline','sceneRestored':None}
    try:
        current=official_scene();before=_checked_scene(state['windowBaseline']);after=_checked_scene(current)
        fields=('x','y','width','height','titleSHA256','identity','role')
        return {'available':True,'sceneRestored':scene_restored(state['windowBaseline'],current),
                'missingWindowIds':sorted(set(before)-set(after)),
                'addedWindowIds':sorted(set(after)-set(before)),
                'changedWindows':[{'id':wid,'fields':[k for k in fields if before[wid][k]!=after[wid][k]]}
                                  for wid in sorted(set(before)&set(after)) if before[wid]!=after[wid]],
                'currentSceneSHA256':hashlib.sha256(json.dumps(current,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    except Exception as exc:
        return {'available':False,'errorType':type(exc).__name__,'sceneRestored':None}

def session_fingerprint(state):
    return hashlib.sha256(json.dumps(state,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def _replace_session(state):
    import tempfile
    path=ROOT/'session.json'
    if path.is_symlink():raise ValueError('session symlink refused')
    fd,name=tempfile.mkstemp(prefix='.continuation-',dir=ROOT)
    try:
        with os.fdopen(fd,'w') as f:json.dump(state,f);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        with contextlib.suppress(FileNotFoundError):os.unlink(name)

@contextlib.contextmanager
def _native_control(session,operation_id,expected_state_sha256,driver,cleanup_owned,recovery_only=False):
    """Maintenance-only Python entry; no new public RPC/action or lock.

    Keep the original desktop alive while native work and the caller's
    exact-owned-window cleanup run under the original guards. A cleanup
    failure retains that session and a recovery receipt; never replay work.
    This is cooperative same-account control, not a security-tenant token.
    """
    if not isinstance(session,str) or not re.fullmatch('[a-f0-9]{32}',session) or not isinstance(operation_id,str) or not re.fullmatch('[A-Za-z0-9][A-Za-z0-9._-]{0,95}',operation_id) or not isinstance(expected_state_sha256,str) or not re.fullmatch('[a-f0-9]{64}',expected_state_sha256) or not callable(cleanup_owned):raise ValueError('exact owned session, operation, state and cleanup callback required')
    if Path(driver.root).resolve()!=ROOT.parent/'operations-state' or getattr(driver,'fds',None) or getattr(driver,'work_class','maintenance')!='maintenance':raise ValueError('idle original maintenance driver required')
    lock=os.open(ROOT/'session.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    held=[];assigned=False
    try:
        info=os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o077:raise ValueError('private original session lock required')
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state=read_private(ROOT/'session.json')
        if not hmac.compare_digest(state.get('session',''),session) or session_fingerprint(state)!=expected_state_sha256:raise ValueError('owned session/state changed; inspect instead of taking control')
        if state.get('mode') not in ('navigate','compose') or state.get('expiresAt',0)<=time.time() or not state.get('processes') or any(p.get('birth') is None or birth(p.get('pid'))!=p['birth'] for p in state['processes']):raise ValueError('live original input-capable session required')
        _checked_scene(state.get('windowBaseline'))
        prior=state.get('nativeContinuation',{})
        if recovery_only:
            if prior.get('phase')!='cleanup-unproven' or prior.get('operationId')!=operation_id:raise ValueError('exact pending cleanup recovery required')
        elif prior:raise ValueError('original continuation already entered; work cannot be repeated')
        package=str(Path(__file__).resolve().parent)
        if package not in sys.path:sys.path.insert(0,package)
        from operations.lease import maintenance_guard,publish,active
        if active(driver.root):raise ValueError('existing native control is protected')
        # Only the acquisition/publication is a Store transaction. New ready
        # business can enqueue during bounded maintenance, not be SQL-blocked.
        with maintenance_guard(driver.root):
            for path in (Path(os.environ.get('WECHAT_HOST_SUPPORT_CODE',str(Path(__file__).resolve().parent/'host_support')))/'native-control.lock',ROOT.parent/'native-ui.lock',Path(driver.root)/'display-guard.lock'):
                path.parent.mkdir(mode=0o700,exist_ok=True)
                fd=os.open(path,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);held.append(fd)
                value=os.fstat(fd)
                if not stat.S_ISREG(value.st_mode) or value.st_uid!=os.getuid() or value.st_mode&0o077:raise ValueError('private original native guard required')
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            driver.fds=held;held=[];assigned=True
            publish(driver.root);driver.last_publish=time.time()
        state['nativeContinuation']={'operationId':operation_id,'phase':'working','cleanupOnly':recovery_only,'startedAt':time.time()}
        _replace_session(state)
        work_error=None
        try:
            yield driver
        except BaseException as exc:
            work_error=type(exc).__name__
            raise
        finally:
            cleanup_error=None;proved=False
            try:proved=cleanup_owned(driver) is True and scene_restored(state['windowBaseline'],official_scene())
            except BaseException as exc:cleanup_error=type(exc).__name__
            state['nativeContinuation'].update(workErrorType=work_error,cleanupErrorType=cleanup_error,endedAt=time.time())
            if not proved:
                state['nativeContinuation']['phase']='cleanup-unproven';_replace_session(state)
                raise DesktopCleanupRequired('Owned cleanup is unproven; original desktop retained, inspect the same operation without replay.') from None
            # Native + session guards are still held before, during and after
            # the desktop stop. Stop itself never closes any WeChat window.
            state['nativeContinuation']['phase']='stopping';_replace_session(state)
            try:
                stop_processes(state,session)
                if not wait_stopped(state):raise DesktopCleanupRequired('desktop process termination unproven')
                cleanup(state)
            except BaseException:
                state['nativeContinuation'].update(phase='cleanup-unproven',cleanupErrorType='DesktopStopUnproven')
                _replace_session(state)
                raise DesktopCleanupRequired('Original desktop stop is unproven; inspect the same operation without replay.') from None
            if not scene_restored(state['windowBaseline'],official_scene()):
                state['nativeContinuation']['phase']='cleanup-unproven';_replace_session(state)
                raise DesktopCleanupRequired('Post-stop scene changed; preserve exact recovery evidence, do not replay work.')
            state['nativeContinuation']['phase']='settled';_replace_session(state)
    finally:
        if assigned:driver.release()
        for fd in held:os.close(fd)
        os.close(lock)

def protected_native_control(session,operation_id,expected_state_sha256,driver,cleanup_owned):
    """Existing maintenance session -> native work -> exact owned cleanup -> stop.
    The original desktop is not stopped before work/cleanup. Ordinary business
    calls have no access to this private Python entry and remain unchanged.
    """
    return _native_control(session,operation_id,expected_state_sha256,driver,cleanup_owned)

def recover_native_control(session,expected_state_sha256,driver,cleanup_owned):
    """Recover the one original cleanup only. No work callback or work replay."""
    state=read_private(ROOT/'session.json')
    operation=state.get('nativeContinuation',{}).get('operationId')
    with _native_control(session,operation,expected_state_sha256,driver,cleanup_owned,True):
        pass

def parse_request(raw):
    if not isinstance(raw,str) or len(raw.encode())>4096:raise ValueError('request size')
    def unique(pairs):
        d={}
        for k,v in pairs:
            if k in d:raise ValueError('duplicate field')
            d[k]=v
        return d
    try:r=json.loads(raw,object_pairs_hook=unique)
    except (ValueError,RecursionError):raise ValueError('invalid JSON') from None
    if not isinstance(r,dict):raise ValueError('object required')
    action=r.get('action');allowed={'start':{'action','mode','ttl'},'status':{'action'},'stop':{'action','session'}}
    if action not in allowed or set(r)-allowed[action]:raise ValueError('unsupported action or field')
    if action=='start':
        if r.get('mode') not in MODES:raise ValueError('explicit supported mode required')
        if type(r.get('ttl')) is not int or not 60<=r['ttl']<=1800:raise ValueError('TTL must be 60..1800 seconds')
    if action=='stop' and not re.fullmatch('[a-f0-9]{32}',r.get('session','')):raise ValueError('exact session required')
    return r

def input_flags(mode):
    if mode=='view':return ['-viewonly','-nosel']
    if mode=='navigate':return ['-input','MB','-nosel']
    if mode=='compose':return ['-input','KMBC','-remap','Return-None,KP_Enter-None','-seldir','recv']
    raise ValueError('unknown mode')

def ensure_operation_window_free(mode,lease_root=None):
    if mode=='view':return
    if str(ROOT.parent/'operations-20261027') not in sys.path:sys.path.insert(0,str(ROOT.parent/'operations-20261027'))
    from operations.lease import active
    if active(lease_root or ROOT.parent/'operations-state'):raise ValueError('shared display is reserved by the serial operations executor; use its queue or wait')

def read_private(path):
    path=Path(path)
    for p in [path,*path.parents]:
        if p.is_symlink():raise ValueError('symlink private path')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        s=os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=os.getuid() or s.st_mode&0o077 or s.st_size>16384:raise ValueError('private regular file required')
        return json.loads(os.read(fd,16385))
    finally:os.close(fd)

def write_private(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())

def birth(pid):
    try:return Path('/proc/'+str(pid)+'/stat').read_text().rsplit(')',1)[1].split()[19]
    except (FileNotFoundError,ProcessLookupError):return None

def stop_processes(state,session,birth=birth,kill=lambda p:os.killpg(p,signal.SIGTERM)):
    if not hmac.compare_digest(state['session'],session):raise ValueError('session mismatch')
    for p in state['processes']:
        if p['birth'] is not None and birth(p['pid'])==p['birth']:
            try:kill(p['pid'])
            except ProcessLookupError:pass

def wait_stopped(state,seconds=2):
    """Bounded proof of original PID birth termination; never kill another PID."""
    end=time.monotonic()+seconds
    while True:
        # A desktop started and stopped in this same Python process is our
        # child. Reap only that exact recorded birth; a zombie still has a
        # /proc birth value although it can no longer receive or supply input.
        for p in state['processes']:
            if p.get('birth') is not None and birth(p['pid'])==p['birth']:
                with contextlib.suppress(ChildProcessError):os.waitpid(p['pid'],os.WNOHANG)
        if not any(p.get('birth') is not None and birth(p['pid'])==p['birth'] for p in state['processes']):return True
        if time.monotonic()>=end:return False
        time.sleep(.025)

class FileAuth:
    """Websockify auth plugin. Secret is a private file, never an argv value."""
    def __init__(self,src):self.expected=read_private(Path(src))['credential']
    def authenticate(self,headers,target_host,target_port):
        value=headers.get('Authorization','');ok=False
        if value.startswith('Basic '):
            try:ok=hmac.compare_digest(base64.b64decode(value[6:],validate=True).decode('ascii'),self.expected)
            except (ValueError,UnicodeError):pass
        if not ok:
            try:from websockify.auth_plugins import AuthenticationError
            except ImportError:raise PermissionError('desktop authentication required') from None
            raise AuthenticationError(response_code=401,response_headers={'WWW-Authenticate':'Basic realm="Private AUP desktop"'})

def inject_auth(raw,host,credential):
    if len(raw)>32768 or not raw.endswith(b'\r\n\r\n'):raise ValueError('bounded complete HTTP header required')
    try:lines=raw[:-4].decode('ascii').split('\r\n');method,target,version=lines[0].split(' ')
    except (ValueError,UnicodeError):raise ValueError('invalid request line') from None
    if method not in ('GET','HEAD') or version!='HTTP/1.1' or not target.startswith('/') or target.startswith('//'):raise ValueError('read/upgrade requests only')
    headers={}
    for line in lines[1:]:
        if not line or line[0].isspace() or ':' not in line:raise ValueError('invalid header')
        k,v=line.split(':',1);k=k.lower()
        if not re.fullmatch('[a-z0-9-]+',k) or k in headers:raise ValueError('duplicate/invalid header')
        headers[k]=v.strip()
    if headers.get('host')!=host or headers.get('origin','http://'+host)!='http://'+host:raise ValueError('local desktop origin required')
    if headers.get('sec-fetch-site')=='cross-site' or 'transfer-encoding' in headers or headers.get('content-length','0')!='0':raise ValueError('cross-site/request body refused')
    headers['authorization']='Basic '+credential
    if headers.get('upgrade','').lower()!='websocket':headers['connection']='close'
    return (lines[0]+'\r\n'+'\r\n'.join(k.title()+': '+v for k,v in headers.items())+'\r\n\r\n').encode('ascii')

def rpc(request):
    parse_request(json.dumps(request))
    r=subprocess.run([*SSH,'python3 '+REMOTE+' --remote-request'],input=json.dumps(request),text=True,capture_output=True,timeout=35)
    if len(r.stdout)>16384:raise ValueError('remote output bound')
    if r.returncode:
        try:value=json.loads(r.stdout)
        except ValueError:value={}
        if isinstance(value,dict) and value.get('code')=='DESKTOP_CLEANUP_REQUIRED':raise DesktopCleanupRequired('Original desktop cleanup is unproven; inspect its recorded session without replay.')
        raise RuntimeError('desktop remote operation failed; no automatic retry')
    return json.loads(r.stdout)

def verify_web_auth(host,port,credential,expected_hash):
    for auth,expected_status in [(None,401),(base64.b64encode(credential.encode()).decode(),200)]:
        c=http.client.HTTPConnection(host,port,timeout=3)
        try:
            headers={'Connection':'close'}
            if auth:headers['Authorization']='Basic '+auth
            c.request('GET','/index.html',headers=headers);r=c.getresponse();data=r.read(32769)
            if r.status!=expected_status or len(data)>32768:raise ValueError('desktop HTTP authentication/readiness failed')
            if auth and hashlib.sha256(data).hexdigest()!=expected_hash:raise ValueError('desktop session page mismatch')
        finally:c.close()

def remote(request):
    request=parse_request(json.dumps(request));ROOT.mkdir(exist_ok=True,mode=0o700)
    if ROOT.is_symlink() or ROOT.stat().st_uid!=os.getuid():raise ValueError('private toolkit root required')
    lock=os.open(ROOT/'session.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    reservation=contextlib.ExitStack()
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        statepath=ROOT/'session.json';s=read_private(statepath) if statepath.exists() else None
        active=bool(s and any(p['birth'] is not None and birth(p['pid'])==p['birth'] for p in s['processes']))
        if request['action']=='status':return {'state':'active' if active else 'stopped','session':s['session'] if s else None,'mode':s['mode'] if s else None,'expiresAt':s['expiresAt'] if s else None,'controlTransferVersion':1,'settledStopSupported':bool(s and 'windowBaseline' in s),'nativeContinuation':s.get('nativeContinuation') if s else None}
        if request['action']=='stop':
            if not s:raise ValueError('no recorded session')
            if not hmac.compare_digest(s['session'],request['session']):raise ValueError('session mismatch')
            # A scene difference is evidence, not a prerequisite for stopping
            # this exact session's transport. No WeChat window is closed here.
            evidence={'at':time.time(),'before':stop_scene_evidence(s)}
            stop_processes(s,request['session'])
            if not wait_stopped(s):raise DesktopCleanupRequired('Original desktop termination is unproven; inspect the same recorded session.')
            cleanup(s)
            evidence['after']=stop_scene_evidence(s);s['stopEvidence']=evidence
            # Transport termination and matching windows do not prove the
            # caller's owned draft cleanup. Preserve nativeContinuation as-is.
            _replace_session(s)
            return {'state':'stopped','session':s['session'],'sceneSettled':evidence['after']['sceneRestored'],'sceneEvidence':evidence}
        if active:raise ValueError('existing desktop session must be stopped first')
        if request['mode']!='view':
            package_path=str(ROOT.parent/'operations-20261027')
            if package_path not in sys.path:sys.path.insert(0,package_path)
            from operations.lease import maintenance_guard
            # Hold original session.lock AND the original Store transaction until
            # this exact maintenance session is published. Admission linearises
            # before (and denies maintenance) or after publication, never between.
            reservation.enter_context(maintenance_guard(ROOT.parent/'operations-state'))
        ensure_operation_window_free(request['mode'])
        if s:cleanup(s)
        mode=request['mode'];ttl=request['ttl'];ident=secrets.token_hex(16)
        baseline=official_scene() if mode!='view' else None
        if baseline is not None:_checked_scene(baseline)
        work=ROOT/('session-'+ident)
        work.mkdir(mode=0o700);web=work/'web';web.mkdir(mode=0o700)
        package=ROOT/'root';env={k:v for k,v in os.environ.items() if k in ('HOME','USER','LANG','PATH')}
        env.update(LD_LIBRARY_PATH=str(package/'usr/lib/x86_64-linux-gnu'),PYTHONPATH=str(ROOT)+':'+str(package/'usr/lib/python3/dist-packages'))
        secret='desktop:'+secrets.token_urlsafe(32);pw=secrets.token_urlsafe(6)
        write_private(work/'auth.json',{'credential':secret})
        for name in ('core','vendor'):(web/name).symlink_to(package/'usr/share/novnc'/name,target_is_directory=True)
        html='<meta charset="utf-8"><title>AUP WeChat — '+mode+'</title><style>body{margin:0}#state{height:24px}#screen{width:100vw;height:calc(100vh - 24px)}</style><div id="state">Connecting — '+mode+'</div><div id="screen"></div><script type="module">import RFB from "./core/rfb.js";const r=new RFB(document.querySelector("#screen"),"ws://"+location.host+"/websockify",{credentials:{password:'+json.dumps(pw)+'}});r.scaleViewport=true;r.viewOnly='+('true' if mode=='view' else 'false')+';r.addEventListener("connect",()=>document.querySelector("#state").textContent="Connected — '+mode+' — Enter disabled");r.addEventListener("disconnect",()=>document.querySelector("#state").textContent="Disconnected");</script>'
        (web/'index.html').write_text(html);(web/'index.html').chmod(0o600)
        processes=[];s={'session':ident,'mode':mode,'expiresAt':time.time()+ttl,'processes':processes}
        if baseline is not None:s['windowBaseline']=baseline
        try:
            x11=package/'usr/bin/x11vnc'
            subprocess.run([str(x11),'-storepasswd',pw,str(work/'vnc.pass')],env=env,capture_output=True,check=True,timeout=5);(work/'vnc.pass').chmod(0o600)
            commands=[['timeout','-k','5',str(ttl),str(x11),'-display',':97','-auth','/var/lib/secretary-wechat/Xauthority','-localhost','-rfbport','15997','-rfbauth',str(work/'vnc.pass'),'-forever','-shared','-noxdamage',*input_flags(mode)],['timeout','-k','5',str(ttl),sys.executable,'-m','websockify','--web',str(web),'--web-auth','--auth-plugin','desktop_control.FileAuth','--auth-source',str(work/'auth.json'),'--heartbeat','15',HOST+':16997','127.0.0.1:15997']]
            for i,cmd in enumerate(commands):
                log=work/('process-'+str(i)+'.log');fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(fd,'wb') as output:
                    p=subprocess.Popen(cmd,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=output,start_new_session=True)
                processes.append({'pid':p.pid,'birth':birth(p.pid)})
            time.sleep(.5)
            if any(p['birth'] is None or birth(p['pid'])!=p['birth'] for p in processes):raise RuntimeError('desktop child startup failed')
            for host,port in [('127.0.0.1',15997),(HOST,16997)]:
                with socket.create_connection((host,port),timeout=3):pass
            verify_web_auth(HOST,16997,secret,hashlib.sha256(html.encode()).hexdigest())
            if statepath.exists():statepath.unlink()
            write_private(statepath,s)
            # Ephemeral HTTP credential crosses SSH into the local process memory only.
            return {**s,'credential':base64.b64encode(secret.encode()).decode()}
        except BaseException:
            stop_processes(s,ident);cleanup(s);raise
    finally:
        try:reservation.__exit__(*sys.exc_info())
        finally:os.close(lock)

def cleanup(state):
    ident=state['session']
    if not re.fullmatch('[a-f0-9]{32}',ident):raise ValueError('invalid recorded session')
    work=ROOT/('session-'+ident)
    if work.is_symlink():raise ValueError('session symlink refused')
    for p in (work/'auth.json',work/'vnc.pass',work/'web/index.html'):
        if p.is_symlink():raise ValueError('session secret symlink refused')
        p.unlink(missing_ok=True)

class Relay(socketserver.ThreadingTCPServer):
    daemon_threads=True;allow_reuse_address=False
    def __init__(self,state):
        self.state=state;self.connections=set();self.guard=threading.Lock()
        super().__init__(('127.0.0.1',0),RelayHandler)
    def release(self):
        with self.guard:
            for sock in list(self.connections):
                with contextlib.suppress(OSError):sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            self.connections.clear()

class RelayHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client=self.request;remote_socket=None
        try:
            client.settimeout(8);data=b''
            while b'\r\n\r\n' not in data:
                part=client.recv(4096)
                if not part:return
                data+=part
                if len(data)>32768:raise ValueError('header bound')
            head,extra=data.split(b'\r\n\r\n',1)
            if extra:raise ValueError('request pipelining/body refused')
            host='127.0.0.1:'+str(self.server.server_address[1]);packet=inject_auth(head+b'\r\n\r\n',host,self.server.state['credential'])
            remote_socket=socket.create_connection((HOST,16997),timeout=5)
            with self.server.guard:self.server.connections.update([client,remote_socket])
            remote_socket.sendall(packet);socks=[client,remote_socket]
            while time.time()<self.server.state['expiresAt']:
                ready,_,_=select.select(socks,[],[],20)
                for src in ready:
                    chunk=src.recv(65536)
                    if not chunk:return
                    (remote_socket if src is client else client).sendall(chunk)
        except (OSError,ValueError):pass
        finally:
            with self.server.guard:
                self.server.connections.discard(client);self.server.connections.discard(remote_socket)
            if remote_socket:remote_socket.close()

def main(argv=None,rpc=rpc):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',nargs='?',choices=['start','status','stop']);p.add_argument('--execute',action='store_true');p.add_argument('--mode',choices=MODES,default='view');p.add_argument('--ttl',type=int,default=600);p.add_argument('--session')
    a=p.parse_args(argv)
    if not a.action:p.print_help();return
    r={'action':a.action}
    if a.action=='start':r.update(mode=a.mode,ttl=a.ttl)
    if a.action=='stop':r['session']=a.session
    parse_request(json.dumps(r))
    if not a.execute:print(json.dumps({'state':'dry_run','request':r}));return
    if a.action!='start':print(json.dumps(rpc(r)));return
    s=rpc(r);server=None
    try:
        server=Relay(s);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        print(json.dumps({'state':'active','session':s['session'],'mode':a.mode,'url':'http://127.0.0.1:'+str(server.server_address[1])+'/index.html','expiresAt':s['expiresAt']}),flush=True)
        while time.time()<s['expiresAt']:time.sleep(.5)
    except KeyboardInterrupt:pass
    finally:
        if server:server.release();server.shutdown();server.server_close()
        try:print(json.dumps(rpc({'action':'stop','session':s['session']})),flush=True)
        except Exception as e:print(json.dumps({'state':'cleanup_unknown','session':s['session'],'remoteTTLStillEnforced':True,'code':getattr(e,'code',None)}),flush=True)

if __name__=='__main__':
    if sys.argv[1:]==['--remote-request']:
        os.umask(0o077)
        try:print(json.dumps(remote(parse_request(sys.stdin.read(4097)))))
        except Exception as e:print(json.dumps({'state':'error','type':type(e).__name__,'code':getattr(e,'code',None)}));sys.exit(2)
    else:main()
