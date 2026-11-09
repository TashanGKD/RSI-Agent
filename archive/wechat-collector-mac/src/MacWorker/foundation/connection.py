"""Private, in-process first-connection credential handoff (no capture/import).

C3 only creates a missing cache. Existing invalid/partial caches require the
separate reconnect transaction; they are never overwritten here.
"""
import ctypes
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import pwd
import re
import stat
import struct
import subprocess
import sys
import threading
import time


class ConnectionError(Exception):
    """Fixed, non-secret failure; never attach native/JSON exception text."""
    def __init__(self, code='invalid_request'):
        self.code = code
        super().__init__(code)


_AUTH = object()
_SOURCE = 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
_HANDOFF = 'Library/Application Support/LocalWeChatReader/keys'
_ACCOUNT = re.compile(r'[A-Za-z0-9_-]{1,256}\Z', re.ASCII)
_NONCE = re.compile(r'[0-9a-f]{32}\Z', re.ASCII)
_PRIMARY = re.compile(r'(?:biz_)?message_[0-9]+\.db\Z', re.ASCII)
_HEX32 = re.compile(r'[0-9a-fA-F]{32}\Z', re.ASCII)
_HEX64 = re.compile(r'[0-9a-fA-F]{64}\Z', re.ASCII)
_READ = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_MAX = 1024 * 1024


class _BSDInfo(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint32) for n in (
        'flags', 'status', 'xstatus', 'pid', 'ppid', 'uid', 'gid', 'ruid',
        'rgid', 'svuid', 'svgid', 'reserved')]
    _fields_ += [('comm', ctypes.c_char * 16), ('name', ctypes.c_char * 32)]
    _fields_ += [(n, ctypes.c_uint32) for n in ('files', 'pgid', 'jobs', 'device', 'ttygroup')]
    _fields_ += [('nice', ctypes.c_int32), ('seconds', ctypes.c_uint64), ('micros', ctypes.c_uint64)]


def _native():
    if sys.platform != 'darwin' or ctypes.sizeof(_BSDInfo) != 136:
        raise ConnectionError('unsupported')
    lib = ctypes.CDLL('libSystem.B.dylib', use_errno=True)
    lib.acl_get_fd_np.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.acl_get_fd_np.restype = ctypes.c_void_p
    lib.acl_free.argtypes = [ctypes.c_void_p]
    lib.acl_free.restype = ctypes.c_int
    lib.renameatx_np.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                                 ctypes.c_char_p, ctypes.c_uint]
    lib.renameatx_np.restype = ctypes.c_int
    return lib


def _observe(pid):
    lib = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
    fn = lib.proc_pidinfo
    fn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    fn.restype = ctypes.c_int
    info = _BSDInfo()
    if fn(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info)) != 136:
        raise ConnectionError('owner_lost')
    if (info.pid != pid or info.status not in (1, 2, 3, 4) or info.seconds == 0
            or info.micros >= 1000000):
        raise ConnectionError('owner_lost')
    return (info.pid, info.ppid, info.uid, info.ruid, info.seconds, info.micros)


def _uid():
    value = os.getuid()
    if value == 0 or value != os.geteuid():
        raise ConnectionError('invalid_authority')
    return value


class _OwnedRelay:
    def __init__(self, token, process, identity, home_lookup, observe, gate):
        if token is not _AUTH:
            raise ConnectionError('invalid_authority')
        self._token = token
        self._process = process
        self._identity = identity
        self._home_lookup = home_lookup
        self._observe = observe
        self._gate = gate

    def __repr__(self):
        return '<OwnedRelay>'

    def _check(self):
        uid = _uid()
        if (self._token is not _AUTH or self._process.returncode is not None
                or self._identity[2:4] != (uid, uid)
                or self._identity[1] != os.getpid()
                or self._observe(self._process.pid) != self._identity):
            raise ConnectionError('owner_lost')


def _launch_owned_relay(argv, *, _home_lookup=None, _observe_native=None, _gate=None,
                        _capture_stdout=False, _empty_env=False):
    """Trusted driver launch seam, never a wire command or supplied PID witness.

    The caller owns the returned child's lifetime and must keep it alive through
    finalization/cleanup. Standard streams cannot carry credentials here.
    """
    _uid()
    observe = _observe_native or _observe
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE if _capture_stdout else subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, close_fds=True,
                               env={} if _empty_env else None)
    try:
        identity = observe(process.pid)  # capture immediately, before any receipt
        owner = _OwnedRelay(_AUTH, process, identity,
                            _home_lookup or (lambda uid: pwd.getpwuid(uid).pw_dir),
                            observe, _gate or (lambda point: None))
        owner._check()
        return owner
    except Exception:
        process.kill()
        process.wait()
        process.stdin.close()
        if process.stdout is not None: process.stdout.close()
        raise ConnectionError('owner_lost') from None


class _Operation:
    def __init__(self, account, nonce):
        if (not isinstance(account, str) or not _ACCOUNT.fullmatch(account)
                or not isinstance(nonce, str) or not _NONCE.fullmatch(nonce)):
            raise ConnectionError()
        self.account, self.nonce = account, nonce

    def __repr__(self):
        return '<Operation>'


def _dpin(info):
    return info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode


def _fpin(info):
    return _dpin(info) + (info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _no_acl(fd):
    lib = _native()
    ctypes.set_errno(0)
    acl = lib.acl_get_fd_np(fd, 0x100)  # SDK ACL_TYPE_EXTENDED
    error = ctypes.get_errno()
    if acl:
        lib.acl_free(acl)
        raise ConnectionError('unsafe_file')
    if error != errno.ENOENT:
        raise ConnectionError('unsafe_file')


class _Chain:
    """Pinned components for this operation only; mutable dir link counts excluded."""
    def __init__(self, path, uid, create=False, private=False, owned_from=None,
                 reconcile_private=False):
        self.path, self.nodes = path, []
        try:
            fd = os.open('/', _READ | os.O_DIRECTORY)
            self.nodes.append((fd, None, _dpin(os.fstat(fd))))
            for index, part in enumerate(Path(path).parts[1:], 1):
                parent = self.nodes[-1][0]
                if create:
                    try:
                        os.mkdir(part, 0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                child = os.open(part, _READ | os.O_DIRECTORY, dir_fd=parent)
                info = os.fstat(child)
                self.nodes.append((child, part, _dpin(info)))
                if info.st_uid not in (0, uid):
                    raise ConnectionError('authority_lost')
                if owned_from is not None and index >= owned_from and info.st_uid != uid:
                    raise ConnectionError('authority_lost')
            info = os.fstat(self.fd)
            if reconcile_private and stat.S_IMODE(info.st_mode) == 0o755:
                # Only the exact selected archive/keys leaf opts in. All links
                # and owners were checked through held descriptors first.
                if not private or info.st_uid != uid:
                    raise ConnectionError('authority_lost')
                self.check()
                _no_acl(self.fd)
                self.check()
                os.fchmod(self.fd, 0o700)
                self.nodes[-1] = (self.fd, self.nodes[-1][1], _dpin(os.fstat(self.fd)))
                self.check()
                _no_acl(self.fd)
                info = os.fstat(self.fd)
            if info.st_uid != uid or (private and stat.S_IMODE(info.st_mode) != 0o700):
                raise ConnectionError('authority_lost')
            if private:
                _no_acl(self.fd)
            self.check()
        except Exception:
            self.close()
            raise

    @property
    def fd(self):
        return self.nodes[-1][0]

    def check(self):
        for index, (fd, name, pin) in enumerate(self.nodes):
            if _dpin(os.fstat(fd)) != pin:
                raise ConnectionError('authority_lost')
            if index and _dpin(os.stat(name, dir_fd=self.nodes[index - 1][0],
                                      follow_symlinks=False)) != pin:
                raise ConnectionError('authority_lost')

    def close(self):
        okay = True
        for fd, _, _ in reversed(self.nodes):
            try: os.close(fd)
            except OSError: okay = False  # Do not retry an ambiguous close.
        self.nodes = []
        return okay


def _absolute(path):
    value = os.fspath(path)
    if (not isinstance(value, str) or not value.startswith('/') or '\0' in value
            or value != os.path.normpath(value)):
        raise ConnectionError('invalid_authority')
    return value


def _overlap(left, right):
    return os.path.commonpath([left, right]) in (left, right)


class _ConnectionTicket:
    def __init__(self, operation, owner, uid, home):
        self._operation, self._owner, self._uid = operation, owner, uid
        self._home = home
        self._deadline = time.monotonic() + 360
        self._mutex = threading.Lock()
        self._chains = []
        self._nonce_pin = self._stage = self._candidate = None
        self._closed = self._cancelled = self._published = False
        self._cleanup_ok = True
        self._outcome = None

    def __repr__(self):
        return '<ConnectionTicket>'

    def _check(self):
        if self._closed:
            raise ConnectionError('closed')
        if self._cancelled:
            raise ConnectionError('cancelled')
        if time.monotonic() >= self._deadline:
            raise ConnectionError('expired')
        self._owner._check()
        if _absolute(self._owner._home_lookup(self._uid)) != self._home:
            raise ConnectionError('authority_lost')
        for chain in self._chains:
            chain.check()


def prepare_connection(library, operation, owner):
    """Bind an existing selected Library; never initialize/import its database."""
    ticket = None
    try:
        uid = _uid()
        if type(operation) is not _Operation or type(owner) is not _OwnedRelay:
            raise ConnectionError('invalid_authority')
        # Revalidate mutable private value objects at the authority boundary.
        operation = _Operation(operation.account, operation.nonce)
        owner._check()
        home = _absolute(owner._home_lookup(uid))
        source = os.path.join(home, _SOURCE)
        archive = _absolute(library.state)
        handoff = os.path.join(home, _HANDOFF)
        if (_absolute(library.source) != source or _overlap(source, archive)
                or _overlap(handoff, archive) or _overlap(source, handoff)):
            raise ConnectionError('invalid_authority')
        ticket = _ConnectionTicket(operation, owner, uid, home)
        ticket._root = os.path.join(source, operation.account)
        for name, path, create, private in (
                ('_source', ticket._root + '/db_storage/message', False, False),
                ('_archive', archive, False, False),
                ('_handoff', handoff, True, True),
                ('_cache', archive + '/keys', True, True)):
            owned_from = len(Path(home).parts) - 1 if name in ('_source', '_handoff') else None
            chain = _Chain(path, uid, create, private, owned_from,
                           reconcile_private=(name == '_cache'))
            ticket._chains.append(chain)
            setattr(ticket, name, chain)
        ticket._nonce_name = 'connect-' + operation.nonce + '.keys.json'
        ticket._cache_name = operation.account + '.keys.json'
        ticket._check()
        return ticket
    except Exception:
        if ticket:
            for chain in ticket._chains:
                chain.close()
        raise ConnectionError('invalid_authority') from None


def _json(raw, limit, member_limit=4096):
    if not isinstance(raw, (bytes, str)):
        raise ConnectionError('invalid_json')
    if isinstance(raw, str):
        raw = raw.encode('utf-8', 'strict')
    if not raw or len(raw) > limit:
        raise ConnectionError('invalid_json')
    text = raw.decode('utf-8', 'strict')
    # Bound parser stack before json's recursive descent (brackets in strings ignored).
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped: escaped = False
            elif char == '\\': escaped = True
            elif char == '"': quoted = False
        elif char == '"': quoted = True
        elif char in '[{':
            depth += 1
            if depth > 8: raise ConnectionError('invalid_json')
        elif char in ']}': depth -= 1
    count = [0]
    def pairs(items):
        result = {}
        for key, value in items:
            count[0] += 1
            if count[0] > member_limit or key in result:
                raise ConnectionError('invalid_json')
            result[key] = value
        return result
    def integer(value):
        if len(value) > 20: raise ConnectionError('invalid_json')
        return int(value)
    def constant(value):
        raise ConnectionError('invalid_json')
    result = json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                        parse_constant=constant)
    if type(result) is not dict:
        raise ConnectionError('invalid_json')
    return result


def _receipt(raw, nonce):
    value = _json(raw, 4096)
    return (set(value) == {'v', 'operation', 'state', 'cleanup', 'code'}
            and type(value['v']) is int and value['v'] == 1
            and value['operation'] == nonce and value['state'] == 'done'
            and value['cleanup'] == 'complete' and value['code'] == '')


def _config(raw, ticket, canonical_salts=False):
    required = {'schema_version', 'wxid', 'db_root', 'keys', 'key_epoch'}
    # The 4096-key map excludes the five required and two optional root fields.
    value = _json(raw, _MAX, 4096 + len(required) + 2)
    if (not required <= set(value) or set(value) - required - {'image_key', 'image_xor_key'}
            or type(value['schema_version']) is not int or value['schema_version'] != 2
            or value['wxid'] != ticket._operation.account or value['db_root'] != ticket._root
            or type(value['key_epoch']) is not int or not 0 <= value['key_epoch'] <= 0x7fffffffffffffff
            or type(value['keys']) is not dict or not 1 <= len(value['keys']) <= 4096):
        raise ConnectionError('invalid_handoff')
    keys = {}
    for salt, key in value['keys'].items():
        if (not isinstance(salt, str) or not _HEX32.fullmatch(salt)
                or not isinstance(key, str) or not _HEX64.fullmatch(key)
                or salt.lower() in keys or (canonical_salts and salt != salt.lower())):
            raise ConnectionError('invalid_handoff')
        keys[salt.lower()] = key.lower()
    if 'image_key' in value:
        key = value['image_key']
        if not isinstance(key, str) or len(key) != 16 or not key.isascii():
            raise ConnectionError('invalid_handoff')
    if 'image_xor_key' in value and (type(value['image_xor_key']) is not int
                                    or not 0 <= value['image_xor_key'] <= 255):
        raise ConnectionError('invalid_handoff')
    value['keys'] = keys
    return value


def _private_file(ticket, chain, name, remember=False):
    fd = os.open(name, _READ, dir_fd=chain.fd)
    try:
        before = os.fstat(fd)
        pin = _fpin(before)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != ticket._uid
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_nlink != 1
                or not 0 < before.st_size <= _MAX):
            raise ConnectionError('unsafe_file')
        _no_acl(fd)
        if _fpin(os.stat(name, dir_fd=chain.fd, follow_symlinks=False)) != pin:
            raise ConnectionError('authority_lost')
        if remember:
            if ticket._nonce_pin is not None and ticket._nonce_pin != pin:
                raise ConnectionError('authority_lost')
            ticket._nonce_pin = pin
        data = bytearray()
        while len(data) <= _MAX:
            chunk = os.read(fd, min(65536, _MAX + 1 - len(data)))
            if not chunk: break
            data.extend(chunk)
        if len(data) != before.st_size or len(data) > _MAX:
            raise ConnectionError('unsafe_file')
        _no_acl(fd)
        chain.check()
        if (_fpin(os.fstat(fd)) != pin
                or _fpin(os.stat(name, dir_fd=chain.fd, follow_symlinks=False)) != pin):
            raise ConnectionError('authority_lost')
        return bytes(data), pin
    finally:
        os.close(fd)


def _verify(ticket, value):
    chain = ticket._source
    chain.check()
    names = []
    with os.scandir(chain.fd) as entries:
        for index, entry in enumerate(entries):
            if index >= 4096: raise ConnectionError('invalid_handoff')
            if _PRIMARY.fullmatch(entry.name):
                names.append(entry.name)
                if len(names) > 511: raise ConnectionError('invalid_handoff')
    verified = missing = 0
    pins = []
    for name in sorted(names):
        fd = os.open(name, _READ, dir_fd=chain.fd)
        try:
            info = os.fstat(fd); pin = _fpin(info)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != ticket._uid
                    or info.st_nlink != 1 or info.st_size < 4096
                    or _fpin(os.stat(name, dir_fd=chain.fd, follow_symlinks=False)) != pin):
                raise ConnectionError('invalid_handoff')
            page = os.read(fd, 4096)
            if len(page) != 4096: raise ConnectionError('invalid_handoff')
            key = value['keys'].get(page[:16].hex())
            if key is None:
                missing += 1
            else:
                mac_key = hashlib.pbkdf2_hmac('sha512', bytes.fromhex(key),
                    bytes(x ^ 0x3a for x in page[:16]), 2, 32)
                mac = hmac.new(mac_key, page[16:4032] + struct.pack('<I', 1), hashlib.sha512).digest()
                if not hmac.compare_digest(mac, page[4032:]):
                    raise ConnectionError('invalid_handoff')
                verified += 1
            if (_fpin(os.fstat(fd)) != pin
                    or _fpin(os.stat(name, dir_fd=chain.fd, follow_symlinks=False)) != pin):
                raise ConnectionError('authority_lost')
            pins.append((name, pin))
        finally:
            os.close(fd)
    chain.check()
    if not verified: raise ConnectionError('invalid_handoff')
    return verified, missing, pins


def _pins_current(ticket, pins):
    names = []
    with os.scandir(ticket._source.fd) as entries:
        for index, entry in enumerate(entries):
            if index >= 4096: raise ConnectionError('authority_lost')
            if _PRIMARY.fullmatch(entry.name): names.append(entry.name)
    if sorted(names) != [name for name, _ in pins]:
        raise ConnectionError('authority_lost')
    for name, pin in pins:
        if _fpin(os.stat(name, dir_fd=ticket._source.fd, follow_symlinks=False)) != pin:
            raise ConnectionError('authority_lost')


def _result(ticket, state, verified=0, missing=0):
    return {'operation': ticket._operation.nonce, 'state': state,
            'verified': verified, 'missing': missing}


def _terminal(ticket, result):
    # Late cancellation cannot undo an already committed publication/reuse.
    ticket._outcome = dict(result)
    return dict(result)


def _existing(ticket):
    try:
        raw, pin = _private_file(ticket, ticket._cache, ticket._cache_name)
    except FileNotFoundError:
        return None
    except Exception:
        return _result(ticket, 'existing_invalid')
    try:
        # Reuse preserves the original bytes. Library.import_keys performs an
        # exact salt.hex() lookup, so memory-only normalization cannot fix them.
        value = _config(raw, ticket, canonical_salts=True)
        verified, missing, pins = _verify(ticket, value)
        ticket._check()
        _pins_current(ticket, pins)
        again, again_pin = _private_file(ticket, ticket._cache, ticket._cache_name)
        if again_pin != pin or again != raw: raise ConnectionError('authority_lost')
        return _result(ticket, 'existing_partial' if missing else 'cache_reused', verified, missing)
    except Exception:
        return _result(ticket, 'existing_invalid')


def inspect_cached_connection(ticket):
    """Read-only current primary-HMAC check before authorization; no latch."""
    if type(ticket) is not _ConnectionTicket:
        raise ConnectionError()
    with ticket._mutex:
        ticket._check()
        result = _existing(ticket)
        ticket._check()
        return result if result is not None else _result(ticket, 'missing')


def _remove(chain, name, pin):
    try:
        current = _fpin(os.stat(name, dir_fd=chain.fd, follow_symlinks=False))
    except FileNotFoundError:
        return True
    if pin is None or current != pin:
        return False
    chain.check()
    os.unlink(name, dir_fd=chain.fd)
    return True


def _artifacts(ticket):
    okay = True
    if ticket._stage is not None:
        name, pin = ticket._stage
        try: okay = _remove(ticket._cache, name, pin) and okay
        except Exception: okay = False
        ticket._stage = None
    try:
        okay = _remove(ticket._handoff, ticket._nonce_name, ticket._nonce_pin) and okay
    except Exception:
        okay = False
    ticket._candidate = None
    ticket._cleanup_ok = ticket._cleanup_ok and okay
    return ticket._cleanup_ok


def _failed_finalize(ticket, error):
    """Recover this attempt before releasing its lifecycle mutex."""
    if ticket._outcome is not None: return dict(ticket._outcome)
    if isinstance(error, ConnectionError):
        code = error.code
        if ticket._published: code = 'cleanup_unconfirmed'
        elif code not in ('cancelled', 'expired', 'owner_lost', 'authority_lost', 'closed', 'publish_failed'):
            code = 'invalid_handoff'
    else:
        code = ('cleanup_unconfirmed' if ticket._published else
                'publish_failed' if ticket._stage is not None else 'invalid_handoff')
    if code in ('cancelled', 'expired'):
        if not _artifacts(ticket): code = 'cleanup_unconfirmed'
    elif ticket._stage is not None:
        name, pin = ticket._stage
        try: ticket._cleanup_ok = _remove(ticket._cache, name, pin) and ticket._cleanup_ok
        except Exception: ticket._cleanup_ok = False
        ticket._stage = None
    result = _result(ticket, code)
    return _terminal(ticket, result) if ticket._published else result


def finalize_connection(ticket, handoff_receipt):
    """Validate one fixed nonce, independently MAC-check, then publish/reuse."""
    if type(ticket) is not _ConnectionTicket:
        raise ConnectionError()
    try:
        if not _receipt(handoff_receipt, ticket._operation.nonce):
            return _result(ticket, 'invalid_receipt')
    except Exception:
        return _result(ticket, 'invalid_receipt')
    with ticket._mutex:
        try:
            if ticket._outcome is not None: return dict(ticket._outcome)
            ticket._check()
            if ticket._published:
                return _result(ticket, 'already_finalized')
            # Hold the lifecycle mutex while using descriptors. The only pause
            # outside it occurs after validation, before the commit decision;
            # cleanup/cancel can win there without recycling FDs under a read.
            raw, pin = _private_file(ticket, ticket._handoff, ticket._nonce_name, True)
            value = _config(raw, ticket)
            verified, missing, pins = _verify(ticket, value)
            ticket._candidate = value
        except Exception as error:
            return _failed_finalize(ticket, error)
    try:
        ticket._owner._gate('before_commit')
    except Exception as error:
        with ticket._mutex:
            return _failed_finalize(ticket, error)
    with ticket._mutex:
        try:
            if ticket._outcome is not None: return dict(ticket._outcome)
            ticket._check()
            _pins_current(ticket, pins)
            again, again_pin = _private_file(ticket, ticket._handoff, ticket._nonce_name, True)
            if again != raw or again_pin != pin: raise ConnectionError('authority_lost')
            existing = _existing(ticket)
            if existing:
                if existing['state'] == 'cache_reused':
                    ticket._owner._gate('cache_validated')
                    ticket._check()
                    if not _artifacts(ticket):
                        return _terminal(ticket, _result(ticket, 'cleanup_unconfirmed'))
                    return _terminal(ticket, existing)
                return existing
            encoded = json.dumps(value, ensure_ascii=True, separators=(',', ':'), sort_keys=True).encode()
            name = '.connect-' + ticket._operation.nonce + '-' + os.urandom(8).hex() + '.tmp'
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                         | os.O_NONBLOCK | os.O_CLOEXEC, 0o600, dir_fd=ticket._cache.fd)
            try:
                info = os.fstat(fd)
                ticket._stage = (name, _fpin(info))
                if (info.st_uid != ticket._uid or not stat.S_ISREG(info.st_mode)
                        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
                    raise ConnectionError('unsafe_file')
                _no_acl(fd)  # Must precede every credential byte.
                ticket._owner._gate('before_stage_write')
                view = memoryview(encoded)
                while view:
                    count = os.write(fd, view)
                    if count <= 0: raise ConnectionError('publish_failed')
                    view = view[count:]
                os.fsync(fd)
                ticket._stage = (name, _fpin(os.fstat(fd)))
                _no_acl(fd)
                ticket._check()
                _pins_current(ticket, pins)
                if _fpin(os.stat(name, dir_fd=ticket._cache.fd, follow_symlinks=False)) != ticket._stage[1]:
                    raise ConnectionError('authority_lost')
                # Input file/chain checked again at the publication boundary.
                last, last_pin = _private_file(ticket, ticket._handoff, ticket._nonce_name, True)
                if last != raw or last_pin != pin: raise ConnectionError('authority_lost')
                ticket._owner._gate('before_rename')
                ticket._check()
                _pins_current(ticket, pins)
                _no_acl(fd)
                if (_fpin(os.fstat(fd)) != ticket._stage[1]
                        or _fpin(os.stat(name, dir_fd=ticket._cache.fd,
                                         follow_symlinks=False)) != ticket._stage[1]
                        or _fpin(os.stat(ticket._nonce_name, dir_fd=ticket._handoff.fd,
                                         follow_symlinks=False)) != pin):
                    raise ConnectionError('authority_lost')
                lib = _native()
                ctypes.set_errno(0)
                ret = lib.renameatx_np(ticket._cache.fd, name.encode(), ticket._cache.fd,
                                      ticket._cache_name.encode(), 4)
                error = ctypes.get_errno() if ret == -1 else 0
                if ret != 0:
                    if ret == -1 and error == errno.EEXIST:
                        existing = _existing(ticket)
                        if existing is not None:
                            if existing['state'] == 'cache_reused':
                                ticket._owner._gate('cache_validated')
                                ticket._check()
                                if not _artifacts(ticket):
                                    return _terminal(ticket, _result(ticket, 'cleanup_unconfirmed'))
                                return _terminal(ticket, existing)
                            return existing
                    raise ConnectionError('publish_failed')
                ticket._published = True
                ticket._stage = None  # Final cache is never a cleanup target.
                ticket._owner._gate('after_rename')
                os.fsync(ticket._cache.fd)
                readback, final_pin = _private_file(ticket, ticket._cache, ticket._cache_name)
                if (readback != encoded or final_pin[:7] != _fpin(os.fstat(fd))[:7]
                        or hashlib.sha256(readback).digest() != hashlib.sha256(encoded).digest()):
                    raise ConnectionError('cleanup_unconfirmed')
                _config(readback, ticket)
                ticket._check()
                _pins_current(ticket, pins)
            finally:
                # Even a write/fsync failure may change size/mtime on our held inode.
                if ticket._stage is not None:
                    ticket._stage = (name, _fpin(os.fstat(fd)))
                os.close(fd)
            if not _artifacts(ticket):
                return _terminal(ticket, _result(ticket, 'cleanup_unconfirmed'))
            return _terminal(ticket, _result(ticket, 'published_partial' if missing else 'published',
                                             verified, missing))
        except Exception as error:
            return _failed_finalize(ticket, error)


def cancel_connection(ticket):
    if type(ticket) is not _ConnectionTicket: raise ConnectionError()
    with ticket._mutex:
        if ticket._outcome is not None: return dict(ticket._outcome)
        if ticket._published: return _result(ticket, 'cleanup_unconfirmed')
        ticket._cancelled = True
        okay = True if ticket._closed else _artifacts(ticket)
        return _result(ticket, 'cancelled' if okay else 'cleanup_unconfirmed')


def cleanup_connection(ticket):
    if type(ticket) is not _ConnectionTicket: raise ConnectionError()
    with ticket._mutex:
        if not ticket._closed:
            _artifacts(ticket)
            ticket._closed = True
            for chain in ticket._chains:
                ticket._cleanup_ok = chain.close() and ticket._cleanup_ok
        return _result(ticket, 'cleaned' if ticket._cleanup_ok else 'cleanup_unconfirmed')
