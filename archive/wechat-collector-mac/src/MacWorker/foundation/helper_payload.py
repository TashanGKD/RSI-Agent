"""Sealed build data -> persistent, private, hash-addressed helper code cache.

The returned user-owned path is NOT privileged execution attestation. Native
must copy and verify it in its root-owned stage before privileged execution.
Private arguments exist solely for generated, in-process fixtures.
"""
import base64
import hashlib
import os
from pathlib import Path
import pwd
import stat
import sys

import connection as _c

RAW_LIMIT = 32 * 1024 * 1024
ENCODED_LIMIT = 48 * 1024 * 1024
CACHE_RELATIVE = 'Library/Application Support/WechatCollectorMac/helpers'

class PayloadError(Exception):
    def __init__(self): super().__init__('helper_unavailable')

def decode(raw):
    try:
        value = _c._json(raw, ENCODED_LIMIT, 4)
        if (set(value) != {'v', 'sha256', 'bytes', 'image'}
                or type(value['v']) is not int or value['v'] != 1
                or type(value['bytes']) is not int or not 0 < value['bytes'] <= RAW_LIMIT
                or not isinstance(value['sha256'], str)
                or not _c._HEX64.fullmatch(value['sha256'])
                or value['sha256'] != value['sha256'].lower()
                or not isinstance(value['image'], str)
                or len(value['image']) != 4 * ((value['bytes'] + 2) // 3)):
            raise PayloadError()
        image = base64.b64decode(value['image'], validate=True)
        if (len(image) != value['bytes'] or hashlib.sha256(image).hexdigest() != value['sha256']
                or base64.b64encode(image).decode('ascii') != value['image']):
            raise PayloadError()
        return value['sha256'], image
    except Exception:
        raise PayloadError() from None

def _sealed_data():
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent))
    path = base / 'vendor/oneshot-helper.pack'
    fd = os.open(path, _c._READ)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= ENCODED_LIMIT:
            raise PayloadError()
        chunks = bytearray()
        while len(chunks) <= ENCODED_LIMIT:
            block = os.read(fd, min(65536, ENCODED_LIMIT + 1 - len(chunks)))
            if not block: break
            chunks.extend(block)
        if len(chunks) != info.st_size or _c._fpin(os.fstat(fd)) != _c._fpin(info):
            raise PayloadError()
        return bytes(chunks)
    finally: os.close(fd)

def _extend(chain, part, uid):
    try: os.mkdir(part, 0o700, dir_fd=chain.fd)
    except FileExistsError: pass
    fd = os.open(part, _c._READ | os.O_DIRECTORY, dir_fd=chain.fd)
    info = os.fstat(fd)
    chain.nodes.append((fd, part, _c._dpin(info)))
    if info.st_uid != uid or stat.S_IMODE(info.st_mode) != 0o700:
        raise PayloadError()
    _c._no_acl(fd)
    chain.check()

def _verify(chain, digest, image, uid):
    fd = os.open('wxkey', _c._READ, dir_fd=chain.fd)
    try:
        before = os.fstat(fd); pin = _c._fpin(before)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid
                or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o500
                or before.st_size != len(image)):
            raise PayloadError()
        _c._no_acl(fd)
        sha = hashlib.sha256(); count = 0
        while count <= RAW_LIMIT:
            block = os.read(fd, min(65536, RAW_LIMIT + 1 - count))
            if not block: break
            count += len(block); sha.update(block)
        chain.check(); _c._no_acl(fd)
        if (count != len(image) or sha.hexdigest() != digest
                or _c._fpin(os.fstat(fd)) != pin
                or _c._fpin(os.stat('wxkey',dir_fd=chain.fd,follow_symlinks=False)) != pin):
            raise PayloadError()
    finally: os.close(fd)

def materialize(*, _sealed=None, _home=None):
    chain = None; stage = None; stage_pin = None
    try:
        # Full decode/hash precedes directory creation or executable publication.
        digest, image = decode(_sealed if _sealed is not None else _sealed_data())
        uid = _c._uid()
        home = _c._absolute(_home if _home is not None else pwd.getpwuid(uid).pw_dir)
        chain = _c._Chain(home + '/Library/Application Support', uid)
        for fd,_,_ in chain.nodes:
            info=os.fstat(fd)
            if stat.S_IMODE(info.st_mode)&0o022 and not (info.st_uid==0 and info.st_mode&stat.S_ISVTX):
                raise PayloadError()
        # OS-home/Library anchors may have the standard deny-delete ACL.
        # Every app-owned cache directory below this anchor is no-ACL/private.
        for part in ('WechatCollectorMac', 'helpers', digest): _extend(chain, part, uid)
        try:
            _verify(chain, digest, image, uid)
        except FileNotFoundError:
            stage = '.wxkey-' + os.urandom(16).hex()
            fd = os.open(stage, os.O_RDWR | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         0o600, dir_fd=chain.fd)
            try:
                info=os.fstat(fd); stage_pin=_c._fpin(info)
                if (info.st_uid != uid or not stat.S_ISREG(info.st_mode)
                        or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600): raise PayloadError()
                _c._no_acl(fd); chain.check()
                view=memoryview(image)
                while view:
                    count=os.write(fd,view)
                    if count <= 0: raise PayloadError()
                    view=view[count:]
                os.fsync(fd); stage_pin=_c._fpin(os.fstat(fd))
                os.lseek(fd,0,os.SEEK_SET)
                sha=hashlib.sha256(); count=0
                while count < len(image):
                    block=os.read(fd,min(65536,len(image)-count))
                    if not block: raise PayloadError()
                    sha.update(block);count+=len(block)
                if count!=len(image) or sha.hexdigest()!=digest: raise PayloadError()
                os.fchmod(fd,0o500); stage_pin=_c._fpin(os.fstat(fd))
                _c._no_acl(fd);chain.check()
                if _c._fpin(os.stat(stage,dir_fd=chain.fd,follow_symlinks=False))!=stage_pin: raise PayloadError()
                lib=_c._native()
                import ctypes, errno
                ctypes.set_errno(0)
                ret=lib.renameatx_np(chain.fd,stage.encode(),chain.fd,b'wxkey',4)
                if ret != 0:
                    if ctypes.get_errno()!=errno.EEXIST: raise PayloadError()
                    _verify(chain,digest,image,uid)
                else:
                    stage=None
                    os.fsync(chain.fd)
                _verify(chain,digest,image,uid)
            finally:
                if stage is not None: stage_pin=_c._fpin(os.fstat(fd))
                os.close(fd)
        chain.check()
        return home + '/' + CACHE_RELATIVE + '/' + digest + '/wxkey'
    except Exception:
        raise PayloadError() from None
    finally:
        if chain:
            if stage is not None:
                try: _c._remove(chain,stage,stage_pin)
                except Exception: pass
            chain.close()
