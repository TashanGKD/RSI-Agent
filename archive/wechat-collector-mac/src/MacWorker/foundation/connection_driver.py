"""Owned --connect stdio driver. No Library initialization or root commands.

C9 Native owns authorization and privileged bootstrap. This driver accepts only
start/cancel for its relay nonce; a root done receipt is a C3 candidate, never an
import or media-completeness claim. All public failures are fixed non-secret codes.
"""
import json
import os
from pathlib import Path
import pwd
import queue
import selectors
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import connection as c
import helper_payload

LIMIT = 4096
TERMINALS = {'published','published_partial','cache_reused','cancelled','repair_required','failed','cleanup_unconfirmed'}
CANCEL_CODES = {'cancelled','owner_lost','timeout','invalid_request'}
WORK_CODES = {'work_failed','publish_failed','invalid_request'}
TRANSITIONS = {'': {'authorizing'}, 'authorizing': {'bound','cancel_requested','cleaning'},
               'bound': {'running','cancel_requested','cleaning'}, 'running': {'cancel_requested','cleaning'},
               'cancel_requested': {'cleaning'}, 'cleaning': {'done','cancelled','failed'}}

class DriverError(Exception):
    def __init__(self, code='invalid_request'):
        self.code=code
        super().__init__(code)

def reserved(args):
    return any(arg == '--connect' or arg.startswith('--connect=') for arg in args)

def validate_mode(args):
    if args != ['--connect']: raise DriverError()

def _object(raw):
    try: return c._json(raw,LIMIT,16)
    except Exception: raise DriverError() from None

def parse_request(raw):
    value=_object(raw)
    if (set(value)!={'v','account','archive'} or type(value['v']) is not int or value['v']!=1
            or not isinstance(value['account'],str) or not c._ACCOUNT.fullmatch(value['account'])
            or not isinstance(value['archive'],str)):
        raise DriverError()
    try: c._absolute(value['archive'])
    except Exception: raise DriverError() from None
    return value

def parse_control(raw,nonce,account,started):
    value=_object(raw)
    command=value.get('command')
    expected={'v','operation','command'} | ({'account'} if command=='start' else set())
    if (set(value)!=expected or type(value.get('v')) is not int or value['v']!=1
            or value.get('operation')!=nonce or command not in ('start','cancel')
            or command=='start' and (started or value['account']!=account)):
        raise DriverError()
    return command

def parse_receipt(raw,nonce,previous,started,previous_code='',ran=False,cancelled=False):
    value=_object(raw)
    if (set(value)!={'v','operation','state','cleanup','code'}
            or type(value['v']) is not int or value['v']!=1
            or not isinstance(value['operation'],str) or not c._NONCE.fullmatch(value['operation'])
            or nonce is not None and value['operation']!=nonce): raise DriverError()
    state,cleanup,code=value['state'],value['cleanup'],value['code']
    if not all(isinstance(x,str) for x in (state,cleanup,code)): raise DriverError()
    valid=False
    if state in ('authorizing','bound','running'): valid=cleanup=='pending' and code==''
    elif state=='cancel_requested': valid=cleanup=='pending' and code in CANCEL_CODES
    elif state=='cleaning': valid=cleanup=='pending' and code in ({''}|CANCEL_CODES|WORK_CODES)
    elif state=='done': valid=cleanup=='complete' and code=='' and ran
    elif state=='cancelled': valid=cleanup=='complete' and code in CANCEL_CODES and (cancelled or not started)
    elif state=='failed': valid=(cleanup=='complete' and code in WORK_CODES or cleanup=='unconfirmed' and code=='cleanup_unconfirmed')
    # Before start the relay itself confirms local cleanup directly (no root).
    own_terminal=not started and previous=='authorizing' and state in ('cancelled','failed')
    if (not valid or not (state in TRANSITIONS.get(previous,set()) or own_terminal)
            or state=='bound' and not started or code=='publish_failed' and not ran
            or previous=='cancel_requested' and state=='cleaning' and code!=previous_code
            or previous=='cleaning' and state in ('done','failed','cancelled') and cleanup=='complete' and code!=previous_code):
        raise DriverError()
    return value

def _archive(home,value):
    source=home+'/'+c._SOURCE; handoff=home+'/'+c._HANDOFF
    cache=home+'/'+helper_payload.CACHE_RELATIVE
    if any(c._overlap(value,p) for p in (source,handoff,cache)):
        raise DriverError('invalid_archive')
    uid=c._uid(); parent=None; archive=None
    try:
        # A selected existing parent is inspected first; no arbitrary ancestry
        # is created or chmodded. Only its missing selected leaf may be made.
        parent=c._Chain(str(Path(value).parent),uid)
        anchor=home+'/Library/Application Support'
        for index,(fd,_,_) in enumerate(parent.nodes):
            info=os.fstat(fd)
            if stat.S_IMODE(info.st_mode)&0o022 and not (info.st_uid==0 and info.st_mode&stat.S_ISVTX):
                raise DriverError('invalid_archive')
            node='/'+'/'.join(Path(parent.path).parts[1:index+1])
            # Existing OS-home anchors commonly carry a restrictive deny-delete
            # ACL. Leaf no-ACL policy starts at application/selected directories.
            if os.path.commonpath([node,anchor])!=node:c._no_acl(fd)
        info=os.fstat(parent.fd)
        if stat.S_IMODE(info.st_mode)&0o022: raise DriverError('invalid_archive')
        c._no_acl(parent.fd); parent.check()
        try: os.mkdir(Path(value).name,0o700,dir_fd=parent.fd)
        except FileExistsError: pass
        archive=c._Chain(value,uid)
        info=os.fstat(archive.fd)
        if stat.S_IMODE(info.st_mode)&0o022: raise DriverError('invalid_archive')
        c._no_acl(archive.fd); archive.check(); parent.check()
        return SimpleNamespace(state=Path(value),source=Path(source))
    except Exception:
        raise DriverError('invalid_archive') from None
    finally:
        if archive: archive.close()
        if parent: parent.close()

def _write(fd,value,timeout=.25):
    raw=(json.dumps(value,separators=(',',':'),ensure_ascii=True)+'\n').encode('ascii')
    if len(raw)>LIMIT: raise DriverError()
    deadline=time.monotonic()+timeout
    while raw:
        try:
            count=os.write(fd,raw)
            if count<=0: raise DriverError('owner_lost')
            raw=raw[count:]
        except BlockingIOError:
            with selectors.DefaultSelector() as selector:
                selector.register(fd,selectors.EVENT_WRITE)
                if not selector.select(max(0,deadline-time.monotonic())): raise DriverError('owner_lost')
        if time.monotonic()>=deadline and raw: raise DriverError('owner_lost')

def _command(owner,nonce,account,command):
    value={'v':1,'operation':nonce,'command':command}
    if command=='start': value['account']=account
    _write(owner._process.stdin.fileno(),value)

class _Monitor:
    """One joined reader monitors stdin and actual parent even during C3 work."""
    def __init__(self,input_fd,observe,deadline):
        self.input=input_fd; self.observe=observe; self.deadline=deadline
        self.parent=observe(os.getppid())
        uid=c._uid()
        if self.parent[2:4]!=(uid,uid): raise DriverError('owner_lost')
        self.events=queue.Queue(16); self.revoked=threading.Event(); self.stop=threading.Event()
        self.reason=''; self.owner=None; self.nonce=None; self.account=None
        self.lock=threading.Lock(); self.cancel_sent=False
        self.controls_enabled=False;self.start_pending=False
        self._close_lock=threading.Lock();self._wake_closed=False
        self.wake_r,self.wake_w=os.pipe()
        for fd in (self.wake_r,self.wake_w): os.set_blocking(fd,False)
        self.thread=threading.Thread(target=self._run,name='connection-owner-monitor',daemon=True)
        self.thread.start()
    def attach(self,owner,account):
        with self.lock:
            self.owner=owner;self.account=account
            os.set_blocking(owner._process.stdin.fileno(),False)
        try: os.write(self.wake_w,b'w')
        except OSError: pass
    def bind(self,nonce):
        with self.lock: self.nonce=nonce
        if self.revoked.is_set(): self._cancel()
    def _cancel(self):
        with self.lock:
            if self.cancel_sent or self.owner is None or self.nonce is None: return
            self.cancel_sent=True
            try: _command(self.owner,self.nonce,self.account,'cancel')
            except Exception:
                try: self.owner._process.stdin.close()
                except Exception: pass
    def revoke(self,reason):
        if not self.revoked.is_set():
            self.reason=reason;self.revoked.set()
        self._cancel()
    def checkpoint(self,point=None):
        if self.revoked.is_set(): raise c.ConnectionError('cancelled')
    def _put(self,kind,line):
        if kind=='input' and self.nonce is not None:
            try:
                if not self.controls_enabled: raise DriverError()
                command=parse_control(line,self.nonce,self.account,self.start_pending)
                if command=='cancel':
                    self.revoke('cancelled')
                    return
                self.start_pending=True
            except DriverError:
                self.revoke('invalid_request')
                return
        try:self.events.put_nowait((kind,line))
        except queue.Full:self.revoke('invalid_request')
    def _run(self):
        buffers={}; registered=False
        try:
            with selectors.DefaultSelector() as selector:
                os.set_blocking(self.input,False)
                selector.register(self.input,selectors.EVENT_READ,'input');buffers['input']=bytearray()
                selector.register(self.wake_r,selectors.EVENT_READ,'wake')
                while not self.stop.is_set():
                    try:
                        if os.getppid()!=self.parent[0] or self.observe(self.parent[0])!=self.parent:
                            self.revoke('owner_lost')
                    except Exception:self.revoke('owner_lost')
                    if time.monotonic()>=self.deadline:self.revoke('timeout')
                    with self.lock:owner=self.owner
                    if owner is not None and not registered:
                        os.set_blocking(owner._process.stdout.fileno(),False)
                        selector.register(owner._process.stdout.fileno(),selectors.EVENT_READ,'relay')
                        buffers['relay']=bytearray();registered=True
                    for key,_ in selector.select(.04):
                        kind=key.data
                        if kind=='wake':
                            try:os.read(self.wake_r,1024)
                            except OSError:pass
                            continue
                        try:raw=os.read(key.fd,4097)
                        except BlockingIOError:continue
                        if not raw:
                            selector.unregister(key.fd)
                            self._put(kind+'_eof',b'')
                            if kind=='input':self.revoke('cancelled')
                            continue
                        buf=buffers[kind];buf.extend(raw)
                        while b'\n' in buf:
                            at=buf.index(10)
                            line=bytes(buf[:at]);del buf[:at+1]
                            if len(line)+1>LIMIT:self.revoke('invalid_request');break
                            self._put(kind,line)
                        if len(buf)>=LIMIT:
                            self.revoke('invalid_request');selector.unregister(key.fd)
        except Exception:
            self.revoke('owner_lost')
        finally:
            self._put('monitor_stopped',b'')
            if self.stop.is_set():
                # Selector/read loop has ended; a timed-out join must never
                # recycle descriptors while that loop can still use them.
                self._close_wake()
                if self.owner is not None:
                    try:self.owner._process.stdout.close()
                    except Exception:pass
    def _close_wake(self):
        with self._close_lock:
            if not self._wake_closed:
                os.close(self.wake_r);os.close(self.wake_w);self._wake_closed=True
    def close(self):
        self.stop.set()
        try:os.write(self.wake_w,b's')
        except OSError:pass
        self.thread.join(.75)
        if self.thread.is_alive():return False
        self._close_wake()
        return True

def run(input_fd=None,output_fd=None,*,_home_lookup=None,_materialize=None,_launch=None,
        _observe=None,_budget=360,_cleanup_budget=5):
    """Private in-process fixture seams never come from CLI/env/JSON."""
    input_fd=sys.stdin.fileno() if input_fd is None else input_fd
    output_fd=sys.stdout.fileno() if output_fd is None else output_fd
    owner=ticket=monitor=None; account='';nonce='';state='failed';code='invalid_request'
    verified=missing=0;started=ran=cancelled=False;relay_terminal=None;clean=True
    deadline=time.monotonic()+min(360,max(.1,_budget)); grace=None
    previous=previous_code='';authorize=False
    old_output=os.get_blocking(output_fd);os.set_blocking(output_fd,False)
    def emit(event,state,cleanup='pending',code=''):
        _write(output_fd,dict(v=1,event=event,account=account,operation=nonce,state=state,
                             cleanup=cleanup,code=code,verified=verified,missing=missing))
    try:
        monitor=_Monitor(input_fd,_observe or c._observe,deadline)
        # Initial request is bounded by this same parent/EOF/deadline monitor.
        while True:
            # Validate a complete buffered first frame before classifying a
            # concurrent EOF; malformed input must not become a cancellation.
            try:kind,raw=monitor.events.get(timeout=.05)
            except queue.Empty:
                if monitor.revoked.is_set():raise DriverError(monitor.reason)
                continue
            if kind!='input':raise DriverError()
            request=parse_request(raw);break
        account=request['account'];uid=c._uid()
        lookup=_home_lookup or (lambda uid:pwd.getpwuid(uid).pw_dir)
        home=c._absolute(lookup(uid))
        monitor.checkpoint()
        library=_archive(home,request['archive'])
        monitor.checkpoint()
        helper=(_materialize or helper_payload.materialize)()
        monitor.checkpoint()
        owner=(_launch or c._launch_owned_relay)([helper,'__oneshot_relay','--account',account],
            _home_lookup=lookup,_gate=monitor.checkpoint,_capture_stdout=True,_empty_env=True)
        monitor.attach(owner,account)
        while True:
            if monitor.revoked.is_set() and grace is None:
                grace=time.monotonic()+min(5,max(.1,_cleanup_budget))
                if ticket:c.cancel_connection(ticket)
            if grace is not None and time.monotonic()>=grace:raise DriverError('cleanup_unconfirmed' if started else monitor.reason)
            try:kind,raw=monitor.events.get(timeout=.04)
            except queue.Empty:continue
            if kind=='input':
                if not nonce or not authorize:monitor.revoke('invalid_request');continue
                try:command=parse_control(raw,nonce,account,started)
                except DriverError:monitor.revoke('invalid_request');continue
                if monitor.revoked.is_set():continue
                if command=='cancel':monitor.revoke('cancelled');continue
                # One atomic dispatch boundary; revoke and start serialize.
                with monitor.lock:
                    if monitor.revoked.is_set():continue
                    _command(owner,nonce,account,'start');started=True
            elif kind=='relay':
                try:r=parse_receipt(raw,nonce or None,previous,started,previous_code,ran,cancelled)
                except DriverError:monitor.revoke('invalid_request');continue
                previous,previous_code=r['state'],r['code']
                if not nonce:
                    nonce=r['operation'];monitor.bind(nonce)
                    try:
                        monitor.checkpoint()
                        ticket=c.prepare_connection(library,c._Operation(account,nonce),owner)
                        cached=c.inspect_cached_connection(ticket)
                        verified,missing=cached['verified'],cached['missing']
                        if cached['state']!='missing':
                            state='cache_reused' if cached['state']=='cache_reused' else 'repair_required'
                            code='' if state=='cache_reused' else cached['state']
                            monitor.revoke('cancelled')
                        else:
                            monitor.checkpoint();authorize=True;monitor.controls_enabled=True
                            emit('authorize','authorizing')
                    except Exception:
                        monitor.revoke('cancelled' if monitor.revoked.is_set() else 'invalid_request')
                    continue
                if r['state']=='running':ran=True
                if r['state']=='cancel_requested':cancelled=True
                if r['state'] in ('done','failed','cancelled'):
                    relay_terminal=r
                    if r['state']=='done' and not monitor.revoked.is_set():
                        monitor.checkpoint()
                        result=c.finalize_connection(ticket,json.dumps(r).encode())
                        verified,missing=result['verified'],result['missing']
                        state=result['state'];code=''
                        if state in ('existing_partial','existing_invalid'):
                            code=state;state='repair_required'
                        elif state not in TERMINALS:
                            code='verification_failed';state='failed'
                    elif state not in ('cache_reused','repair_required'):
                        state=('cancelled' if r['state']=='cancelled' or r['state']=='done' and monitor.revoked.is_set()
                               else 'cleanup_unconfirmed' if r['cleanup']=='unconfirmed' else 'failed')
                        code=(monitor.reason if r['state']=='done' and monitor.revoked.is_set() else r['code'])
                    break
                if authorize:emit('progress',r['state'],r['cleanup'],r['code'])
            elif kind=='relay_eof':
                if relay_terminal is None:raise DriverError('cleanup_unconfirmed' if started else monitor.reason or 'work_failed')
            elif kind=='monitor_stopped':raise DriverError('owner_lost')
    except Exception as error:
        code=(error.code if isinstance(error,DriverError)
              else monitor.reason if monitor and monitor.revoked.is_set() else 'work_failed')
        if monitor:monitor.revoke(code if code in CANCEL_CODES else 'invalid_request')
        if state not in ('cache_reused','repair_required'):
            state='cleanup_unconfirmed' if started else 'cancelled' if code in ('cancelled','owner_lost','timeout') else 'failed'
    finally:
        if ticket:
            try:
                if state not in ('published','published_partial'):c.cancel_connection(ticket)
                clean=c.cleanup_connection(ticket)['state']=='cleaned' and clean
            except Exception:clean=False
        if owner:
            try:
                # Real relay stays alive until C3 finalization AND cleanup finish.
                if relay_terminal is not None:_command(owner,nonce,account,'release')
                elif monitor:monitor._cancel()
            except Exception:
                if started:clean=False
            process=owner._process
            try:process.stdin.close()
            except Exception:pass
            try:
                remaining=min(5,max(.1,_cleanup_budget))
                if grace is not None:remaining=max(.05,min(remaining,grace-time.monotonic()))
                exit_code=process.wait(timeout=remaining)
                if relay_terminal is not None:
                    expected=0 if relay_terminal['state']=='done' else 130 if relay_terminal['state']=='cancelled' else 70
                    clean=clean and exit_code==expected
                else:clean=False
            except subprocess.TimeoutExpired:
                # Only the exact owned ordinary child, never a process name,
                # group, privileged peer or scanner PID.
                clean=False
                try:process.kill()
                except Exception:pass
                try:process.wait(timeout=1)
                except Exception:pass
            except Exception:
                clean=False
            finally:
                # Join the only stdout reader before closing its descriptor.
                joined=True
                if monitor:
                    try:joined=monitor.close()
                    except Exception:joined=False
                    clean=joined and clean;monitor=None
                if joined and process.stdout is not None:
                    try:process.stdout.close()
                    except Exception:clean=False
        if monitor:
            try:clean=monitor.close() and clean
            except Exception:clean=False
        if not clean:state='cleanup_unconfirmed';code='cleanup_unconfirmed'
        if state not in TERMINALS:state='failed'
        if state=='cleanup_unconfirmed':code='cleanup_unconfirmed'
        try:emit('terminal',state,'complete' if clean and state!='cleanup_unconfirmed' else 'unconfirmed',code)
        except Exception:pass
        try:os.set_blocking(output_fd,old_output)
        except OSError:pass
    return 0 if state in ('published','published_partial','cache_reused') else 130 if state=='cancelled' else 70

def main(args=None):
    try:validate_mode(sys.argv[1:] if args is None else args)
    except DriverError:
        try:_write(sys.stdout.fileno(),dict(v=1,event='terminal',account='',operation='',state='failed',cleanup='complete',code='invalid_request',verified=0,missing=0))
        except Exception:pass
        return 64
    return run()
