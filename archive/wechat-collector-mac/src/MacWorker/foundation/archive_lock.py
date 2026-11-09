"""parent-leaf-v1: permanent coordination files, never archive mutations.

Identity v1 = SHA256(domain || BE32(dev) || BE64(ino) || BE32(utf8 length)
                     || UTF8(NFC(leaf).casefold())). Only this module defines it.
Preparation is not ownership. Every consumer must own its own flock descriptors.
"""
import contextlib
import ctypes
import errno
import fcntl
import hashlib
import os
import pwd
import stat
import struct
import threading
import time
import unicodedata

class ArchiveLockError(Exception):
    """Finite public failure; never carries a path or raw OS exception."""
    def __init__(self, code='unsafe_archive'):
        self.code=code
        super().__init__(code)

_DIR=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC
_FILE=os.O_RDWR|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC
_DOMAIN=b'WechatCollectorMac\x00archive-lock\x00parent-leaf-v1\x00'
_libc=ctypes.CDLL(None,use_errno=True)
_libc.acl_get_fd_np.argtypes=[ctypes.c_int,ctypes.c_int]
_libc.acl_get_fd_np.restype=ctypes.c_void_p
_libc.acl_get_entry.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_void_p)]
_libc.acl_free.argtypes=[ctypes.c_void_p]

def _ordinary_uid():
    uid=os.getuid()
    if uid==0 or uid!=os.geteuid():raise ArchiveLockError('invalid_user')
    return uid

def _canonical(value):
    if not isinstance(value,str) or not 1<len(value)<=4096 or '\0' in value or not value.startswith('/'):
        raise ArchiveLockError()
    parts=value.split('/')[1:]
    if any(p in ('.','..') for p in parts):raise ArchiveLockError()
    value='/'+'/'.join(p for p in parts if p)
    top='/'+value.split('/')[1]
    if top in ('/tmp','/var','/etc') and os.path.islink(top):
        info=os.lstat(top)
        if info.st_uid!=0 or os.readlink(top)!='private'+top:raise ArchiveLockError()
        value='/private'+value
    return value

def _fold_leaf(name):
    return unicodedata.normalize('NFC',name).casefold()

def _identity(info,leaf):
    raw=_fold_leaf(leaf).encode('utf-8','strict')
    return hashlib.sha256(_DOMAIN+struct.pack('>IQI',info.st_dev&0xffffffff,info.st_ino,len(raw))+raw).hexdigest()

def _pin(s):return (s.st_dev&0xffffffff,s.st_ino,s.st_uid,s.st_gid,s.st_mode)
def _same(a,b):
    if _pin(a)!=_pin(b):raise ArchiveLockError('authority_lost')
def _no_acl(fd):
    ctypes.set_errno(0)
    acl=_libc.acl_get_fd_np(fd,256)
    if not acl:
        if ctypes.get_errno()==errno.ENOENT:return
        raise ArchiveLockError('unsafe_coordination')
    try:
        entry=ctypes.c_void_p();ctypes.set_errno(0)
        result=_libc.acl_get_entry(acl,0,ctypes.byref(entry))
        if result==0 or ctypes.get_errno()!=errno.EINVAL:raise ArchiveLockError('unsafe_coordination')
    finally:_libc.acl_free(acl)

def _private(fd,uid,directory):
    s=os.fstat(fd)
    if s.st_uid!=uid or stat.S_IMODE(s.st_mode)!=(0o700 if directory else 0o600):raise ArchiveLockError('unsafe_coordination')
    if directory:
        if not stat.S_ISDIR(s.st_mode):raise ArchiveLockError('unsafe_coordination')
    elif not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size!=0:raise ArchiveLockError('unsafe_coordination')
    _no_acl(fd)
    if fcntl.fcntl(fd,fcntl.F_GETFD)&fcntl.FD_CLOEXEC==0:raise ArchiveLockError('unsafe_coordination')
    return s

class _Chain:
    """Held root-to-leaf nofollow descriptors and entry identities."""
    def __init__(self,path,missing_ok=False):
        self.fds=[];self.entries=[];self.complete=True;self.missing_name=None
        try:
            fd=os.open('/',_DIR);self.fds.append(fd)
            for part in path.split('/')[1:]:
                if part:
                    try:self.append(part)
                    except FileNotFoundError:
                        if not missing_ok:raise
                        self.complete=False;self.missing_name=part;break
            self.check()
        except BaseException:self.close();raise
    @property
    def fd(self):return self.fds[-1]
    def append(self,part):
        parent=self.fd;fd=os.open(part,_DIR,dir_fd=parent)
        self.fds.append(fd);self.entries.append((parent,part,os.fstat(fd)))
    def check(self):
        for parent,part,pin in self.entries:
            current=os.stat(part,dir_fd=parent,follow_symlinks=False)
            _same(pin,current)
        for fd,entry in zip(self.fds[1:],self.entries):_same(os.fstat(fd),entry[2])
    def close(self):
        for fd in reversed(self.fds):os.close(fd)
        self.fds=[]

class _Target:
    def __init__(self,path,mode,uid):
        self.chain=None;self.target_fd=None
        try:
            if mode not in ('shared','exclusive'):raise ArchiveLockError('invalid_request')
            self.path=_canonical(path);self.mode=mode;parent,self.leaf=self.path.rsplit('/',1)
            if not parent or not self.leaf:raise ArchiveLockError()
            self.chain=_Chain(parent);self.parent=os.fstat(self.chain.fd)
            if self.parent.st_uid!=uid or self.parent.st_mode&0o022:raise ArchiveLockError()
            self.target_pin=None
            try:self.target_fd=os.open(self.leaf,_DIR,dir_fd=self.chain.fd)
            except FileNotFoundError:
                if mode=='shared':raise ArchiveLockError()
            if self.target_fd is not None:
                self.target_pin=os.fstat(self.target_fd)
                if self.target_pin.st_uid!=uid or self.target_pin.st_mode&0o022:raise ArchiveLockError()
            self.id=_identity(self.parent,self.leaf);self.check()
        except BaseException:self.close();raise
    def check(self):
        self.chain.check();_same(self.parent,os.fstat(self.chain.fd))
        try:current=os.stat(self.leaf,dir_fd=self.chain.fd,follow_symlinks=False)
        except FileNotFoundError:
            if self.target_pin is not None:raise ArchiveLockError('authority_lost')
            return
        if not stat.S_ISDIR(current.st_mode) or current.st_uid!=self.parent.st_uid or current.st_mode&0o022:raise ArchiveLockError('authority_lost')
        if self.target_pin is not None:
            _same(self.target_pin,current);_same(self.target_pin,os.fstat(self.target_fd))
        else:
            # Pin an EX leaf once it first appears, including after our own mkdir.
            self.target_fd=os.open(self.leaf,_DIR,dir_fd=self.chain.fd)
            self.target_pin=os.fstat(self.target_fd);_same(current,self.target_pin)
    def binding(self):return {'id':self.id,'mode':self.mode,'parentDev':self.parent.st_dev&0xffffffff,'parentIno':self.parent.st_ino}
    def close(self):
        if self.target_fd is not None:os.close(self.target_fd);self.target_fd=None
        if self.chain is not None:self.chain.close();self.chain=None

_gate=threading.RLock()
_local=threading.local()
_active=[]
def _after_fork():
    global _gate,_local,_active
    # close only: flock(LOCK_UN) here would unlock the parent's shared description.
    for lease in _active:
        lease._close_resources()
        lease._forked=True
    _active=[];_gate=threading.RLock();_local=threading.local()
def _before_fork():_gate.acquire()
def _parent_after_fork():_gate.release()
os.register_at_fork(before=_before_fork,after_in_parent=_parent_after_fork,after_in_child=_after_fork)

class _Store:
    def __init__(self):
        self.uid=_ordinary_uid();self.home=_canonical(pwd.getpwuid(self.uid).pw_dir)
        self.anchor=self.home+'/Library/Application Support'
        self.components=('WechatCollectorMac','archive-locks','parent-leaf-v1')
        self.root=self.anchor+'/'+'/'.join(self.components)
    @classmethod
    def _for_tests(cls,root):
        self=cls.__new__(cls);self.uid=_ordinary_uid();self.home=_canonical(pwd.getpwuid(self.uid).pw_dir)
        self.root=_canonical(os.fspath(root));self.anchor,self.components=self.root.rsplit('/',1);self.components=(self.components,)
        return self
    def _targets(self,targets):
        if not isinstance(targets,(list,tuple)) or not 1<=len(targets)<=2:raise ArchiveLockError('invalid_request')
        result=[]
        try:
            for item in targets:
                if not isinstance(item,(tuple,list)) or len(item)!=2:raise ArchiveLockError('invalid_request')
                target=_Target(item[0],item[1],self.uid);result.append(target)
                if target.path in ('/',self.home) or target.path==self.root or target.path.startswith(self.root+'/') or self.root.startswith(target.path+'/'):raise ArchiveLockError()
                # Inode ancestry rejects firmlink aliases even when the private
                # tree is not yet present. No mkdir occurs during this pass.
                with contextlib.closing(_Chain(self.root,missing_ok=True)) as reserved:
                    pins=[os.fstat(fd) for fd in reserved.fds]
                    if target.target_pin is not None and any((x.st_dev,x.st_ino)==(target.target_pin.st_dev,target.target_pin.st_ino) for x in pins):raise ArchiveLockError()
                    if not reserved.complete and (target.parent.st_dev,target.parent.st_ino)==(pins[-1].st_dev,pins[-1].st_ino) and _fold_leaf(target.leaf)==_fold_leaf(reserved.missing_name):raise ArchiveLockError()
                    if reserved.complete:
                        root_pin=pins[-1]
                        if any((os.fstat(fd).st_dev,os.fstat(fd).st_ino)==(root_pin.st_dev,root_pin.st_ino) for fd in target.chain.fds):raise ArchiveLockError()
            return result
        except BaseException:
            for t in result:t.close()
            raise
    def _check_coord_targets(self,chain,targets):
        # Compare held inode identities, not mutable selected path strings.
        # This must run on each opened ancestor before any descendant/file create.
        chain.check()
        selected={(t.target_pin.st_dev&0xffffffff,t.target_pin.st_ino) for t in targets if t.target_pin is not None}
        for fd in chain.fds:
            info=os.fstat(fd)
            if (info.st_dev&0xffffffff,info.st_ino) in selected:raise ArchiveLockError('authority_lost')
    def _coord(self,create,targets=()):
        chain=_Chain(self.anchor)
        try:
            self._check_coord_targets(chain,targets)
            for fd in chain.fds:
                info=os.fstat(fd)
                if info.st_uid not in (0,self.uid) or info.st_mode&0o022 and not (info.st_uid==0 and info.st_mode&stat.S_ISVTX):raise ArchiveLockError('unsafe_coordination')
            for part in self.components:
                if create:
                    self._check_coord_targets(chain,targets)
                    try:os.mkdir(part,0o700,dir_fd=chain.fd)
                    except FileExistsError:pass
                chain.append(part);_private(chain.fd,self.uid,True)
                self._check_coord_targets(chain,targets)
            chain.check();return chain
        except BaseException:chain.close();raise
    def _open_lock(self,chain,digest,create,targets=()):
        if create:
            self._check_coord_targets(chain,targets)
            try:
                fd=os.open(digest,_FILE|os.O_CREAT|os.O_EXCL,0o600,dir_fd=chain.fd)
            except FileExistsError:fd=os.open(digest,_FILE,dir_fd=chain.fd)
        else:fd=os.open(digest,_FILE,dir_fd=chain.fd)
        try:
            pin=_private(fd,self.uid,False);_same(pin,os.stat(digest,dir_fd=chain.fd,follow_symlinks=False));chain.check();return fd,pin
        except BaseException:os.close(fd);raise
    def _prepare(self,targets):
        # Reject changed selections before opening a chain that may create nodes.
        for target in targets:target.check()
        chain=self._coord(True,targets)
        try:
            for digest in sorted(set(t.id for t in targets)):
                fd,_=self._open_lock(chain,digest,True,targets);os.close(fd)
            for t in targets:t.check()
            chain.check()
        finally:chain.close()
    def prepare(self,targets):
        with _gate:return self._prepare_public(targets)
    def _prepare_public(self,targets):
        if _ordinary_uid()!=self.uid:raise ArchiveLockError('invalid_user')
        try:
            checked=self._targets(targets)
            try:self._prepare(checked);return [t.binding() for t in checked]
            finally:
                for t in checked:t.close()
        except ArchiveLockError:raise
        except (OSError,ValueError,UnicodeError):raise ArchiveLockError('unsafe_archive') from None
    def acquire_many(self,targets,checkpoint=lambda:None):
        if _ordinary_uid()!=self.uid:raise ArchiveLockError('invalid_user')
        pid=os.getpid();thread=threading.get_ident()
        # The process gate covers the whole lease. RLock only permits same-thread nesting.
        while not _gate.acquire(timeout=0.025):checkpoint()
        checked=[];lease=None
        try:
            checked=self._targets(targets)
            modes={}
            for t in checked:modes[t.id]='exclusive' if t.mode=='exclusive' or modes.get(t.id)=='exclusive' else 'shared'
            outer=getattr(_local,'lease',None)
            if outer is not None:
                outer.check()
                if self.root!=outer.store.root or any(k not in outer.modes or (v=='exclusive' and outer.modes[k]!='exclusive') for k,v in modes.items()):raise ArchiveLockError('nested_acquisition')
                lease=_NestedLease(outer,checked,pid,thread);outer.nested+=1;_active.append(lease);return lease
            self._prepare(checked)
            lease=_Lease(self,checked,modes,pid,thread);checked=[];_active.append(lease)
            lease.chain=self._coord(False)
            for digest,mode in sorted(modes.items()):
                fd,pin=self._open_lock(lease.chain,digest,False);lease.locks.append((fd,digest,pin))
                while True:
                    checkpoint()
                    try:fcntl.flock(fd,(fcntl.LOCK_EX if mode=='exclusive' else fcntl.LOCK_SH)|fcntl.LOCK_NB);break
                    except OSError as error:
                        if error.errno not in (errno.EWOULDBLOCK,errno.EAGAIN):raise
                        time.sleep(0.025)
            lease.check();_local.lease=lease;return lease
        except BaseException:
            for t in checked:t.close()
            if lease is not None:
                lease._close_resources()
                if lease in _active:_active.remove(lease)
            _gate.release();raise

def acquire_many(targets,checkpoint=lambda:None):return _Store().acquire_many(targets,checkpoint)
def prepare(targets):return _Store().prepare(targets)

class _Lease:
    def __init__(self,store,targets,modes,pid,thread):
        self.store=store;self.targets=targets;self.modes=modes;self.pid=pid;self.thread=thread;self.locks=[];self.chain=None;self.closed=False;self._forked=False;self.nested=0
    def _authority(self):
        if self.pid!=os.getpid() or self._forked:raise ArchiveLockError('forked_lease')
        if self.thread!=threading.get_ident() or self.closed or _ordinary_uid()!=self.store.uid:raise ArchiveLockError('authority_lost')
    def check(self):
        self._authority();self.chain.check()
        for fd,digest,pin in self.locks:
            _same(pin,_private(fd,self.store.uid,False));_same(pin,os.stat(digest,dir_fd=self.chain.fd,follow_symlinks=False))
        for fd in self.chain.fds[-len(self.store.components):]:_private(fd,self.store.uid,True)
        for t in self.targets:t.check()
    def _close_resources(self):
        for fd,_,_ in reversed(self.locks):os.close(fd)
        self.locks=[]
        if self.chain is not None:self.chain.close();self.chain=None
        for t in self.targets:t.close()
        self.targets=[]
    def close(self):
        if self.pid!=os.getpid() or self._forked:raise ArchiveLockError('forked_lease')
        if self.closed:return
        self._authority()
        if self.nested:raise ArchiveLockError('nested_acquisition')
        self._close_resources();self.closed=True;_local.lease=None;_active.remove(self);_gate.release()
    def __enter__(self):self.check();return self
    def __exit__(self,*args):self.close()
class _NestedLease:
    def __init__(self,outer,targets,pid,thread):self.outer=outer;self.targets=targets;self.pid=pid;self.thread=thread;self.closed=False
    def check(self):
        if self.pid!=os.getpid() or self.thread!=threading.get_ident() or self.closed:raise ArchiveLockError('authority_lost')
        self.outer.check()
        for t in self.targets:t.check()
    def close(self):
        if self.pid!=os.getpid():raise ArchiveLockError('forked_lease')
        if self.closed:return
        if self.thread!=threading.get_ident():raise ArchiveLockError('authority_lost')
        for t in self.targets:t.close()
        self.outer.nested-=1;self.closed=True;_active.remove(self);_gate.release()
    def __enter__(self):self.check();return self
    def __exit__(self,*args):self.close()

    def _close_resources(self):
        for t in self.targets:t.close()
        self.targets=[]
