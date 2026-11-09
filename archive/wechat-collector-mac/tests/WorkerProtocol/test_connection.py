"""C3 test-only Darwin RENAME_EXCL gate; generated files, no capture modules."""
import ctypes
import errno
import json
import os
import stat
import sys
import tempfile
import unittest


RENAME_EXCL = 0x00000004  # Local SDK sys/stdio.h; no overwrite fallback.


@unittest.skipUnless(sys.platform == 'darwin', 'Darwin native gate only')
class Native(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.getuid() == 0 or os.getuid() != os.geteuid():
            raise RuntimeError('native fixture requires an ordinary non-root UID')
        cls.library = ctypes.CDLL('libSystem.B.dylib', use_errno=True)
        cls.rename = cls.library.renameatx_np
        cls.rename.argtypes = [ctypes.c_int, ctypes.c_char_p,
                               ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        cls.rename.restype = ctypes.c_int
        cls.closed_checks = 0
        cls.observed = {}

    @classmethod
    def tearDownClass(cls):
        print(json.dumps({'nativeBinding': 'libSystem.B.dylib:renameatx_np',
                          'flags': RENAME_EXCL, 'actualUid': os.getuid(),
                          'actualEffectiveUid': os.geteuid(),
                          'closedFdChecks': cls.closed_checks,
                          'observed': cls.observed}, sort_keys=True))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(
            prefix='wechat-connection-native-', dir='/private/tmp')
        self.addCleanup(self.directory.cleanup)
        os.chmod(self.directory.name, 0o700)
        self.fd = os.open(self.directory.name,
                          os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self.addCleanup(self.close_checked, self.fd)
        self.pin = self.directory_identity(os.fstat(self.fd))
        self.assertEqual(self.pin, self.directory_identity(os.lstat(self.directory.name)))
        self.assertEqual(stat.S_IMODE(os.fstat(self.fd).st_mode), 0o700)
        self.assertEqual(os.fstat(self.fd).st_uid, os.getuid())
        self.assertFalse(os.get_inheritable(self.fd))
        self.create('unrelated.bin', b'generated unrelated sentinel')
        self.unrelated = self.snapshot('unrelated.bin')

    def tearDown(self):
        self.assertEqual(self.unrelated, self.snapshot('unrelated.bin'))
        self.assertEqual(self.pin, self.directory_identity(os.fstat(self.fd)))
        self.assertEqual(self.pin, self.directory_identity(os.lstat(self.directory.name)))

    @staticmethod
    def directory_identity(info):
        # Directory Nlink changes with entries on macOS; it is not a pin field.
        return (info.st_dev, info.st_ino, info.st_uid, info.st_gid, info.st_mode)

    def close_checked(self, descriptor):
        os.close(descriptor)
        with self.assertRaises(OSError) as caught:
            os.fstat(descriptor)
        self.assertEqual(caught.exception.errno, errno.EBADF)
        type(self).closed_checks += 1

    def create(self, name, content, directory=None):
        parent = self.fd if directory is None else directory
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        try:
            os.fchmod(descriptor, 0o600)
            self.assertFalse(os.get_inheritable(descriptor))
            view = memoryview(content)
            while view:
                count = os.write(descriptor, view)
                self.assertGreater(count, 0)
                view = view[count:]
            os.fsync(descriptor)
        finally:
            self.close_checked(descriptor)

    def snapshot(self, name, directory=None):
        parent = self.fd if directory is None else directory
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=parent)
        try:
            info = os.fstat(descriptor)
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(info.st_uid, os.getuid())
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            self.assertEqual(info.st_nlink, 1)
            chunks = []
            while True:
                chunk = os.read(descriptor, 4096)
                if not chunk:
                    break
                chunks.append(chunk)
            return (info.st_dev, info.st_ino, info.st_uid, info.st_gid,
                    info.st_mode, info.st_nlink, info.st_size,
                    info.st_mtime_ns, b''.join(chunks))
        finally:
            self.close_checked(descriptor)

    def rename_exclusive(self, source, destination, directory=None):
        # Test-only interface: an owned descriptor and literal basenames only.
        for name in (source, destination):
            if (not isinstance(name, bytes) or not name or name in (b'.', b'..')
                    or b'/' in name or b'\0' in name):
                raise ValueError('fixture basename required')
        parent = self.fd if directory is None else directory
        ctypes.set_errno(0)
        result = self.rename(parent, source, parent, destination, RENAME_EXCL)
        native_error = ctypes.get_errno()
        if result != 0:
            raise OSError(native_error, os.strerror(native_error))
        return result  # errno is meaningful only on the failure path.

    def test_existing_target_preserves_both_files(self):
        self.create('source.bin', b'generated new candidate')
        self.create('target.bin', b'generated old target sentinel')
        before_source = self.snapshot('source.bin')
        before_target = self.snapshot('target.bin')
        with self.assertRaises(OSError) as caught:
            self.rename_exclusive(b'source.bin', b'target.bin')
        self.assertEqual(caught.exception.errno, errno.EEXIST)
        self.assertEqual(before_source, self.snapshot('source.bin'))
        self.assertEqual(before_target, self.snapshot('target.bin'))
        type(self).observed['existingTargetErrno'] = caught.exception.errno
        type(self).observed['existingTargetPreserved'] = True

    def test_absent_target_moves_same_private_inode(self):
        self.create('source.bin', b'generated native handoff payload')
        before = self.snapshot('source.bin')
        self.assertEqual(self.rename_exclusive(b'source.bin', b'target.bin'), 0)
        with self.assertRaises(FileNotFoundError):
            os.stat('source.bin', dir_fd=self.fd, follow_symlinks=False)
        self.assertEqual(before, self.snapshot('target.bin'))
        type(self).observed['movePreservedInodeModeUidBytes'] = True

    def test_held_directory_fd_does_not_retarget_after_rename(self):
        os.mkdir('held', 0o700, dir_fd=self.fd)
        held = os.open('held', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                       | os.O_CLOEXEC, dir_fd=self.fd)
        try:
            pin = self.directory_identity(os.fstat(held))
            self.create('source.bin', b'generated held-directory payload', held)
            before = self.snapshot('source.bin', held)
            os.rename('held', 'moved', src_dir_fd=self.fd, dst_dir_fd=self.fd)
            os.mkdir('held', 0o700, dir_fd=self.fd)
            self.assertNotEqual(pin, self.directory_identity(
                os.stat('held', dir_fd=self.fd, follow_symlinks=False)))
            self.assertEqual(self.rename_exclusive(b'source.bin', b'target.bin', held), 0)
            self.assertEqual(before, self.snapshot('target.bin', held))
            self.assertEqual(pin, self.directory_identity(os.fstat(held)))
            with self.assertRaises(FileNotFoundError):
                os.stat('held/target.bin', dir_fd=self.fd, follow_symlinks=False)
            type(self).observed['heldDirectoryPinConfirmed'] = True
        finally:
            self.close_checked(held)

    def test_test_gate_rejects_non_basenames_before_native_call(self):
        # Concrete breaking inputs must not become arbitrary source/dest paths.
        for name in (b'../foreign.bin', b'/foreign.bin', b'bad\0name'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.rename_exclusive(name, b'target.bin')


# Public receiver tests use only a generated home, actual Library and our child.
import hashlib
import hmac
import importlib.util
from pathlib import Path
import struct
import subprocess
import threading
import time
from types import SimpleNamespace

FOUNDATION = Path(__file__).resolve().parents[2] / 'src/MacWorker/foundation'
sys.path.insert(0, str(FOUNDATION))
try:
    import connection
except ImportError:
    connection = None


@unittest.skipUnless(sys.platform == 'darwin', 'Darwin receiver only')
class Connection(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(connection, 'C3 receiver API has not been implemented')
        self.tmp = tempfile.TemporaryDirectory(prefix='wechat-c3-', dir='/private/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir(mode=0o700)
        self.source = self.home / 'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
        self.account = 'fixture_account'
        self.message = self.source / self.account / 'db_storage/message'
        self.message.mkdir(parents=True, mode=0o700)
        self.archive = Path(self.tmp.name) / 'archive'
        from library import Library
        self.library = Library(self.archive, self.source)
        self.index_before = self.library.index.read_bytes()
        self.pages = {}
        self.keys = {}
        self.add_page('message_0.db', 1)
        self.owners = []
        self.tickets = []
        self.addCleanup(self.close_all)
        self.owner = self.launch()
        self.ticket = self.prepare()

    def launch(self, gate=None):
        owner = connection._launch_owned_relay(
            [sys.executable, '-c', 'import sys; sys.stdin.buffer.read()'],
            _home_lookup=lambda uid: str(self.home), _gate=gate)
        self.owners.append(owner)
        return owner

    def prepare(self, nonce=None, owner=None):
        operation = connection._Operation(self.account, nonce or os.urandom(16).hex())
        ticket = connection.prepare_connection(self.library, operation, owner or self.owner)
        self.tickets.append(ticket)
        return ticket

    def close_all(self):
        for ticket in self.tickets:
            connection.cleanup_connection(ticket)
        for owner in self.owners:
            owner._process.stdin.close()
            try:
                owner._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                owner._process.kill()
                owner._process.wait(timeout=2)
        self.assertEqual(self.index_before, self.library.index.read_bytes())
        for name, page in self.pages.items():
            self.assertEqual(page, (self.message / name).read_bytes())

    def add_page(self, name, seed):
        salt = bytes([seed]) * 16
        key = bytes([seed + 20]) * 32
        page = bytearray(bytes([seed + 1]) * 4096)
        page[:16] = salt
        mac = hashlib.pbkdf2_hmac('sha512', key, bytes(x ^ 0x3a for x in salt), 2, 32)
        page[4032:] = hmac.new(mac, page[16:4032] + struct.pack('<I', 1), hashlib.sha512).digest()
        self.pages[name] = bytes(page)
        self.keys[salt.hex()] = key.hex()
        (self.message / name).write_bytes(page)

    def config(self, **changes):
        value = {'schema_version': 2, 'wxid': self.account,
                 'db_root': str(self.source / self.account),
                 'keys': dict(self.keys), 'key_epoch': 1}
        value.update(changes)
        return value

    def nonce_path(self, ticket=None):
        ticket = ticket or self.ticket
        return self.home / 'Library/Application Support/LocalWeChatReader/keys' / (
            'connect-' + ticket._operation.nonce + '.keys.json')

    def write_nonce(self, value=None, raw=None, ticket=None):
        path = self.nonce_path(ticket)
        data = raw if raw is not None else json.dumps(value or self.config()).encode()
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return path

    def receipt(self, ticket=None, **changes):
        value = {'v': 1, 'operation': (ticket or self.ticket)._operation.nonce,
                 'state': 'done', 'cleanup': 'complete', 'code': ''}
        value.update(changes)
        return json.dumps(value).encode()

    def finalize(self, ticket=None, receipt=None):
        return connection.finalize_connection(ticket or self.ticket,
                                               receipt or self.receipt(ticket))

    def assert_state(self, expected, result):
        self.assertEqual(expected, result['state'])
        self.assertEqual({'operation', 'state', 'verified', 'missing'}, set(result))
        return result

    def test_public_publish_and_aes_only_canonical_hex(self):
        self.add_page('message_0.db', 0xab)  # Salt/key contain real hex letters.
        keys = {salt.upper(): key.upper() for salt, key in self.keys.items()}
        self.write_nonce(self.config(keys=keys, image_key='0123456789ABCDEF'))
        result = self.assert_state('published', self.finalize())
        self.assertEqual((1, 0), (result['verified'], result['missing']))
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        saved = json.loads(cache.read_bytes())
        self.assertEqual(self.keys, saved['keys'])
        self.assertNotIn('image_xor_key', saved)
        self.assertFalse(self.nonce_path().exists())
        self.assertEqual(0o600, stat.S_IMODE(cache.stat().st_mode))
        self.assertNotIn(next(iter(self.keys.values())), repr(self.ticket))

    def test_public_publish_accepts_4096_keys_plus_both_image_fields(self):
        keys = dict(self.keys)
        keys.update({('%032x' % (0x100000 + index)): 'ab' * 32 for index in range(4095)})
        self.assertEqual(4096, len(keys))
        self.write_nonce(self.config(keys=keys, image_key='0123456789ABCDEF', image_xor_key=255))
        result = self.assert_state('published', self.finalize())
        self.assertEqual((1, 0), (result['verified'], result['missing']))
        saved = json.loads((self.archive / 'keys' / (self.account + '.keys.json')).read_bytes())
        self.assertEqual(keys, saved['keys'])
        self.assertEqual(('0123456789ABCDEF', 255), (saved['image_key'], saved['image_xor_key']))

    def test_partial_first_publish(self):
        self.add_page('biz_message_1.db', 2)
        keys = dict(self.keys); keys.pop(bytes([2]).hex() * 16)
        self.write_nonce(self.config(keys=keys))
        result = self.assert_state('published_partial', self.finalize())
        self.assertEqual((1, 1), (result['verified'], result['missing']))

    def test_bad_receipts_and_duplicate_bool_extra_trailing(self):
        self.write_nonce()
        cases = [self.receipt(v=True), self.receipt(operation='0' * 32),
                 self.receipt(state='failed'), self.receipt(cleanup='unconfirmed'),
                 self.receipt(code='work_failed'), self.receipt() + b'{}',
                 b'{"v":1,"v":1}', self.receipt()[:-1] + b',"extra":0}', b' ' * 4097]
        for raw in cases:
            self.assert_state('invalid_receipt', self.finalize(receipt=raw))
        self.assertFalse((self.archive / 'keys' / (self.account + '.keys.json')).exists())

    def test_strict_payload_matrix(self):
        valid = self.config()
        cases = [dict(valid, schema_version=True), dict(valid, schema_version=1),
                 dict(valid, wxid='other'), dict(valid, db_root=str(self.home)),
                 dict(valid, key_epoch=True), dict(valid, key_epoch=-1),
                 dict(valid, image_key='short'), dict(valid, image_key='\u00e9' * 16),
                 dict(valid, image_xor_key=True), dict(valid, image_xor_key=256),
                 dict(valid, extra=1), dict(valid, keys={'ab' * 16: 'cd' * 31}),
                 dict(valid, keys={'ab' * 16: 'cd' * 32, 'AB' * 16: 'de' * 32})]
        raws = [json.dumps(v).encode() for v in cases]
        raws += [json.dumps(valid).encode() + b'{}', b'{"keys":{"x":1,"x":2}}',
                 b'[' * 80 + b'0' + b']' * 80, b'{"key_epoch":' + b'1' * 100000 + b'}',
                 b'\xff', b'{}' * 600000]
        for raw in raws:
            with self.subTest(length=len(raw)):
                ticket = self.prepare()
                self.write_nonce(raw=raw, ticket=ticket)
                self.assert_state('invalid_handoff', self.finalize(ticket))

    def test_nonce_links_fifo_modes_and_empty(self):
        for kind in ('symlink', 'hardlink', 'fifo', 'mode', 'empty'):
            ticket = self.prepare(); path = self.nonce_path(ticket)
            if kind == 'symlink': path.symlink_to(self.library.index)
            elif kind == 'hardlink': os.link(self.library.index, path)
            elif kind == 'fifo': os.mkfifo(path, 0o600)
            elif kind == 'empty': path.touch(mode=0o600)
            else:
                self.write_nonce(ticket=ticket); path.chmod(0o644)
            self.assert_state('invalid_handoff', self.finalize(ticket))

    def test_wrong_hmac_and_auxiliary_only(self):
        for keys in ({next(iter(self.keys)): 'ff' * 32}, {'fe' * 16: 'fd' * 32}):
            ticket = self.prepare(); self.write_nonce(self.config(keys=keys), ticket=ticket)
            self.assert_state('invalid_handoff', self.finalize(ticket))

    def test_cancel_and_expiry_before_publish(self):
        self.write_nonce()
        # A name alone is not a registered artifact: preserve the unknown entry.
        self.assert_state('cleanup_unconfirmed', connection.cancel_connection(self.ticket))
        self.assert_state('cleanup_unconfirmed', self.finalize())
        self.assertTrue(self.nonce_path().exists())
        ticket = self.prepare(); self.write_nonce(ticket=ticket)
        # Observe/pin through the real reader before expiry, using an invalid
        # receipt-independent payload; no cache has been created.
        self.nonce_path(ticket).write_text('{"broken":true}')
        self.assert_state('invalid_handoff', self.finalize(ticket))
        ticket._deadline = time.monotonic() - 1
        self.assert_state('expired', self.finalize(ticket))
        self.assertFalse(self.nonce_path(ticket).exists())

    def test_owner_death_prevents_publication(self):
        self.write_nonce()
        self.owner._process.stdin.close(); self.owner._process.wait(timeout=2)
        self.assert_state('owner_lost', self.finalize())

    def test_existing_cache_complete_invalid_partial_preserved(self):
        self.add_page('message_2.db', 2)
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        first_key = next(iter(self.keys))
        for value, expected in ((self.config(), 'cache_reused'),
                                ({'broken': True}, 'existing_invalid'),
                                (self.config(keys={first_key: self.keys[first_key]}), 'existing_partial')):
            cache.write_text(json.dumps(value)); cache.chmod(0o600)
            before = (cache.stat().st_ino, cache.read_bytes())
            ticket = self.prepare(); self.write_nonce(ticket=ticket)
            self.assert_state(expected, self.finalize(ticket))
            self.assertEqual(before, (cache.stat().st_ino, cache.read_bytes()))
            self.assertEqual(expected != 'cache_reused', self.nonce_path(ticket).exists())
            if expected != 'cache_reused':
                self.assertIsNotNone(ticket._candidate)
                self.assert_state('cleaned', connection.cleanup_connection(ticket))
                self.assertIsNone(ticket._candidate)
                self.assertFalse(self.nonce_path(ticket).exists())
            cache.unlink()

    def test_old_uppercase_salt_is_consumer_incompatible_and_preserved(self):
        self.add_page('message_0.db', 0xab)
        old_keys = {salt.upper(): key for salt, key in self.keys.items()}
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        cache.write_text(json.dumps(self.config(keys=old_keys))); cache.chmod(0o600)
        before = (cache.stat().st_ino, cache.read_bytes())
        with (self.message / 'message_0.db').open('rb') as source:
            self.assertNotIn(source.read(16).hex(), json.loads(before[1])['keys'])
        # Real generated Library consumer independently demonstrates raw-map
        # lookup: it marks this primary locked before attempting decryption.
        from library import Library
        consumer = Library(Path(self.tmp.name) / 'consumer-archive', self.source)
        consumer.import_keys(self.account, cache)
        with consumer.connect() as database:
            rows = database.execute('SELECT path,status FROM coverage WHERE account=?',
                                    (self.account,)).fetchall()
        self.assertEqual([('message/message_0.db', 'locked')], [tuple(row) for row in rows])
        self.write_nonce()
        self.assert_state('existing_invalid', self.finalize())
        self.assertEqual(before, (cache.stat().st_ino, cache.read_bytes()))
        self.assertTrue(self.nonce_path().exists())
        self.assertIsNotNone(self.ticket._candidate)

    def test_old_uppercase_key_values_remain_consumer_compatible(self):
        self.add_page('message_0.db', 0xab)
        old_keys = {salt: key.upper() for salt, key in self.keys.items()}
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        cache.write_text(json.dumps(self.config(keys=old_keys))); cache.chmod(0o600)
        before = (cache.stat().st_ino, cache.read_bytes())
        with (self.message / 'message_0.db').open('rb') as source:
            salt = source.read(16).hex()
        self.assertEqual(bytes.fromhex(self.keys[salt]), bytes.fromhex(json.loads(before[1])['keys'][salt]))
        self.write_nonce()
        self.assert_state('cache_reused', self.finalize())
        self.assertEqual(before, (cache.stat().st_ino, cache.read_bytes()))

    def test_two_operations_one_atomic_create(self):
        other = self.prepare(); self.write_nonce(); self.write_nonce(ticket=other)
        barrier = threading.Barrier(2); results = []
        def run(ticket):
            barrier.wait(timeout=3); results.append(self.finalize(ticket)['state'])
        threads = [threading.Thread(target=run, args=(t,)) for t in (self.ticket, other)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=5); self.assertFalse(thread.is_alive())
        self.assertEqual(['cache_reused', 'published'], sorted(results))

    def test_cleanup_never_deletes_replacement_or_published_cache(self):
        path = self.write_nonce(); self.assert_state('published', self.finalize())
        path.write_bytes(b'generated foreign replacement'); path.chmod(0o600)
        self.assert_state('cleanup_unconfirmed', connection.cleanup_connection(self.ticket))
        self.assertEqual(b'generated foreign replacement', path.read_bytes())
        self.assertTrue((self.archive / 'keys' / (self.account + '.keys.json')).exists())

    def test_directory_swap_and_source_selection(self):
        self.write_nonce()
        moved = self.archive.with_name('archive-old'); self.archive.rename(moved)
        self.archive.mkdir(mode=0o700)
        try:
            self.assert_state('authority_lost', self.finalize())
        finally:
            self.archive.rmdir(); moved.rename(self.archive)
        wrong = SimpleNamespace(state=self.archive, source=self.home)
        with self.assertRaises(connection.ConnectionError):
            connection.prepare_connection(wrong, connection._Operation(self.account, '1' * 32), self.owner)

    def test_operation_and_owner_authority_not_plain_metadata(self):
        for account, nonce in (('../escape', '1' * 32), ('a', 'A' * 32), ('a' * 257, '1' * 32)):
            with self.assertRaises(connection.ConnectionError): connection._Operation(account, nonce)
        with self.assertRaises(connection.ConnectionError):
            connection.prepare_connection(self.library, connection._Operation(self.account, '2' * 32),
                                          {'pid': self.owner._process.pid, 'uid': os.getuid()})

    def test_cancel_commit_gate_and_public_secret_sentinel(self):
        ready = threading.Event(); release = threading.Event()
        def gate(point):
            if point == 'before_commit': ready.set(); self.assertTrue(release.wait(3))
        owner = self.launch(gate); ticket = self.prepare(owner=owner); self.write_nonce(ticket=ticket)
        results = []
        thread = threading.Thread(target=lambda: results.append(self.finalize(ticket)))
        thread.start(); self.assertTrue(ready.wait(3))
        self.assert_state('cancelled', connection.cancel_connection(ticket)); release.set()
        thread.join(5); self.assertFalse(thread.is_alive())
        self.assert_state('cancelled', results[0])
        self.assertNotIn(next(iter(self.keys.values())), json.dumps(results))

    def test_added_primary_between_validation_and_commit_is_rejected(self):
        def gate(point):
            if point == 'before_commit': self.add_page('message_3.db', 3)
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket)
        self.assert_state('authority_lost', self.finalize(ticket))

    def test_cleanup_can_race_paused_finalize_without_fd_reuse(self):
        ready = threading.Event(); release = threading.Event()
        def gate(point):
            if point == 'before_commit': ready.set(); self.assertTrue(release.wait(3))
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket); results = []
        thread = threading.Thread(target=lambda: results.append(self.finalize(ticket)))
        thread.start(); self.assertTrue(ready.wait(3))
        self.assert_state('cleaned', connection.cleanup_connection(ticket)); release.set()
        thread.join(5); self.assertFalse(thread.is_alive())
        self.assert_state('closed', results[0])

    def test_observed_nonce_replacement_is_preserved(self):
        path = self.write_nonce(raw=b'{"broken":true}')
        self.assert_state('invalid_handoff', self.finalize())
        path.unlink(); path.write_bytes(b'generated foreign entry'); path.chmod(0o600)
        self.assert_state('cleanup_unconfirmed', connection.cleanup_connection(self.ticket))
        self.assertEqual(b'generated foreign entry', path.read_bytes())

    def test_primary_links_fifo_and_directory_substitution_rejected(self):
        path = self.message / 'message_8.db'
        for kind in ('fifo', 'symlink', 'hardlink', 'directory'):
            if kind == 'fifo': os.mkfifo(path, 0o600)
            elif kind == 'symlink': path.symlink_to(self.message / 'message_0.db')
            elif kind == 'hardlink': os.link(self.message / 'message_0.db', path)
            else: path.mkdir()
            try:
                ticket = self.prepare(); self.write_nonce(ticket=ticket)
                self.assert_state('invalid_handoff', self.finalize(ticket))
            finally:
                if kind == 'directory': path.rmdir()
                else: path.unlink()

    def test_payload_counts_and_key_epoch_width(self):
        values = [self.config(key_epoch=2 ** 63), self.config(key_epoch=1.5),
                  self.config(keys={('%032x' % i): 'ab' * 32 for i in range(4097)})]
        for value in values:
            ticket = self.prepare(); self.write_nonce(value, ticket=ticket)
            self.assert_state('invalid_handoff', self.finalize(ticket))

    def add_acl(self, path, inheritance=False):
        # Generated paths only, no global ACL/user configuration changes.
        entry = 'everyone allow read' + (',file_inherit' if inheritance else '')
        subprocess.run(['/bin/chmod', '+a', entry, str(path)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)

    def test_nonce_and_oldcache_extended_acl_rejected(self):
        path = self.write_nonce(); self.add_acl(path)
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
        self.assert_state('invalid_handoff', self.finalize())
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        cache.write_text(json.dumps(self.config())); cache.chmod(0o600); self.add_acl(cache)
        before = (cache.stat().st_ino, cache.read_bytes())
        ticket = self.prepare(); self.write_nonce(ticket=ticket)
        self.assert_state('existing_invalid', self.finalize(ticket))
        self.assertEqual(before, (cache.stat().st_ino, cache.read_bytes()))

    def test_inherited_cache_stage_acl_never_contains_secret(self):
        cache_dir = self.archive / 'keys'
        writes = []
        owner = self.launch(lambda point: writes.append(point) if point == 'before_stage_write' else None)
        ticket = self.prepare(owner=owner)
        self.add_acl(cache_dir, inheritance=True)
        self.write_nonce(ticket=ticket)
        states = self.finalize(ticket)['state']
        self.assertIn(states, ('invalid_handoff', 'authority_lost'))
        self.assertEqual([], writes)
        self.assertFalse((cache_dir / (self.account + '.keys.json')).exists())
        self.assertFalse(list(cache_dir.glob('*.tmp')))
        # No ACL stripped from the existing parent.
        fd = os.open(str(cache_dir), os.O_RDONLY | os.O_DIRECTORY)
        try:
            lib = connection._native(); acl = lib.acl_get_fd_np(fd, 0x100)
            self.assertTrue(acl)
            self.assertEqual(0, lib.acl_free(acl))
        finally: os.close(fd)

    def test_fd_cleanup_prepare_failure_and_closed_ticket(self):
        ticket = self.prepare()
        descriptors = [fd for chain in ticket._chains for fd, _, _ in chain.nodes]
        self.assert_state('cleaned', connection.cleanup_connection(ticket))
        self.assert_state('cleaned', connection.cleanup_connection(ticket))
        for fd in descriptors:
            with self.assertRaises(OSError) as caught: os.fstat(fd)
            self.assertEqual(errno.EBADF, caught.exception.errno)
        before = len(os.listdir('/dev/fd'))
        for _ in range(10):
            with self.assertRaises(connection.ConnectionError):
                connection.prepare_connection(SimpleNamespace(state=self.message, source=self.source),
                                              connection._Operation(self.account, os.urandom(16).hex()), self.owner)
        self.assertEqual(before, len(os.listdir('/dev/fd')))

    def test_existing_reuse_does_not_hide_failed_nonce_cleanup(self):
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        cache.write_text(json.dumps(self.config())); cache.chmod(0o600)
        def gate(point):
            if point == 'cache_validated':
                path = self.nonce_path(ticket); path.unlink()
                path.write_bytes(b'generated replacement'); path.chmod(0o600)
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket)
        self.assert_state('cleanup_unconfirmed', self.finalize(ticket))
        self.assertEqual(b'generated replacement', self.nonce_path(ticket).read_bytes())

    def test_native_rename_race_revalidates_the_winner(self):
        barrier = threading.Barrier(2); commits = []
        def gate(point):
            if point == 'before_rename':
                commits.append(1); barrier.wait(timeout=3)
        owner = self.launch(gate)
        tickets = [self.prepare(owner=owner), self.prepare(owner=owner)]
        for ticket in tickets: self.write_nonce(ticket=ticket)
        results = []
        threads = [threading.Thread(target=lambda t=t: results.append(self.finalize(t))) for t in tickets]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5); self.assertFalse(thread.is_alive())
        self.assertEqual(2, len(commits))
        self.assertEqual(['cache_reused', 'published'], sorted(r['state'] for r in results))

    def test_postrename_failure_keeps_cache_and_reports_unconfirmed(self):
        sentinel = 'generated-secret-never-report'
        def gate(point):
            if point == 'after_rename': raise RuntimeError(sentinel)
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket)
        result = self.assert_state('cleanup_unconfirmed', self.finalize(ticket))
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        before = (cache.stat().st_ino, cache.read_bytes())
        connection.cleanup_connection(ticket)
        self.assertEqual(before, (cache.stat().st_ino, cache.read_bytes()))
        self.assertNotIn(sentinel, json.dumps(result))

    def test_prewrite_fault_cleans_stage_and_keeps_fixed_error(self):
        sentinel = 'generated-secret-in-native-error'
        def gate(point):
            if point == 'before_stage_write': raise OSError(sentinel)
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket)
        result = self.assert_state('publish_failed', self.finalize(ticket))
        self.assertEqual([], list((self.archive / 'keys').iterdir()))
        self.assertNotIn(sentinel, json.dumps(result))

    def test_bounded_primary_and_directory_entry_counts(self):
        extra = []
        try:
            for i in range(1, 512):
                path = self.message / ('message_%d.db' % i); path.touch(); extra.append(path)
            self.write_nonce()
            self.assert_state('invalid_handoff', self.finalize())
        finally:
            for path in extra: path.unlink()
        extra = []
        try:
            for i in range(4096):
                path = self.message / ('aux_%d' % i); path.touch(); extra.append(path)
            ticket = self.prepare(); self.write_nonce(ticket=ticket)
            self.assert_state('invalid_handoff', self.finalize(ticket))
        finally:
            for path in extra: path.unlink()

    def test_every_matching_primary_mac_must_verify(self):
        self.add_page('message_2.db', 2)
        keys = dict(self.keys); keys[bytes([2]).hex() * 16] = 'ab' * 32
        self.write_nonce(self.config(keys=keys))
        self.assert_state('invalid_handoff', self.finalize())

    def test_source_directory_swap_after_validation(self):
        moved = self.message.with_name('message-old')
        def gate(point):
            if point == 'before_commit': self.message.rename(moved); self.message.mkdir()
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket)
        try: self.assert_state('authority_lost', self.finalize(ticket))
        finally: self.message.rmdir(); moved.rename(self.message)

    def test_commit_wins_late_cancel_and_repeated_finalize(self):
        self.write_nonce()
        published = self.assert_state('published', self.finalize())
        self.assertEqual(published, connection.cancel_connection(self.ticket))
        self.assertEqual(published, self.finalize())
        cache = self.archive / 'keys' / (self.account + '.keys.json')
        before = (cache.stat().st_ino, cache.read_bytes())
        self.assert_state('cleaned', connection.cleanup_connection(self.ticket))
        self.assertEqual(before, (cache.stat().st_ino, cache.read_bytes()))

    def test_cleanup_close_failure_is_fixed_and_closes_remaining_descriptors(self):
        ticket = self.prepare()
        descriptors = [fd for chain in ticket._chains for fd, _, _ in chain.nodes]
        os.close(descriptors[2])  # Real EBADF fault, not a fabricated root stat.
        self.assert_state('cleanup_unconfirmed', connection.cleanup_connection(ticket))
        for fd in descriptors:
            with self.assertRaises(OSError) as caught: os.fstat(fd)
            self.assertEqual(errno.EBADF, caught.exception.errno)

    def test_same_ticket_concurrent_finalizers_have_one_terminal_outcome(self):
        barrier = threading.Barrier(2)
        def gate(point):
            if point == 'before_commit': barrier.wait(timeout=3)
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket); results = []
        threads = [threading.Thread(target=lambda: results.append(self.finalize(ticket))) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(5); self.assertFalse(thread.is_alive())
        self.assertEqual(2, len(results))
        self.assertEqual(results[0], results[1])
        self.assert_state('published', results[0])

    def test_failed_stage_is_recovered_before_another_same_ticket_attempt(self):
        released = threading.Event(); second_done = threading.Event()
        faulted = threading.Event(); stage_names = []; reclaimed = []; results = {}
        cache_dir = self.archive / 'keys'
        sentinel = cache_dir / 'other_account.keys.json'
        sentinel.write_bytes(b'generated old cache sentinel'); sentinel.chmod(0o600)
        old = (sentinel.stat().st_ino, sentinel.read_bytes())
        def gate(point):
            if point != 'before_stage_write': return
            if threading.current_thread().name == 'failed-attempt':
                stage_names.append(ticket._stage[0]); faulted.set()
                raise OSError('generated pre-rename fault')
            reclaimed.append(not (cache_dir / stage_names[0]).exists())
        owner = self.launch(gate); ticket = self.prepare(owner=owner)
        self.write_nonce(ticket=ticket)
        class PauseOnFailedUnlock:
            def __init__(self): self.lock = threading.Lock(); self.paused = False
            def __enter__(self): self.lock.acquire(); return self
            def __exit__(self, kind, value, traceback):
                self.lock.release()
                if (threading.current_thread().name == 'failed-attempt'
                        and faulted.is_set() and not self.paused):
                    self.paused = True; released.set()
                    if not second_done.wait(3): raise RuntimeError('generated schedule timeout')
        ticket._mutex = PauseOnFailedUnlock()
        def first(): results['first'] = self.finalize(ticket)
        def second():
            try: results['second'] = self.finalize(ticket)
            finally: second_done.set()
        first_thread = threading.Thread(target=first, name='failed-attempt')
        second_thread = threading.Thread(target=second, name='retry-attempt')
        first_thread.start(); self.assertTrue(released.wait(3)); second_thread.start()
        for thread in (first_thread, second_thread):
            thread.join(5); self.assertFalse(thread.is_alive())
        # The failed attempt is recovered/linearized before the retry starts;
        # it is nonterminal and must not overwrite the later successful outcome.
        with self.subTest(boundary='first_failure'):
            self.assert_state('publish_failed', results['first'])
        self.assert_state('published', results['second'])
        with self.subTest(boundary='terminal_outcome'):
            self.assertEqual(results['second'], ticket._outcome)
        with self.subTest(boundary='first_stage_before_retry'):
            self.assertEqual([True], reclaimed)
        with self.subTest(boundary='no_lost_stage'):
            self.assertFalse(list(cache_dir.glob('*.tmp')))
        self.assertFalse(self.nonce_path(ticket).exists())
        self.assertEqual(old, (sentinel.stat().st_ino, sentinel.read_bytes()))
        final = cache_dir / (self.account + '.keys.json')
        published = (final.stat().st_ino, final.read_bytes())
        descriptors = [fd for chain in ticket._chains for fd, _, _ in chain.nodes]
        self.assert_state('cleaned', connection.cleanup_connection(ticket))
        self.assertEqual(published, (final.stat().st_ino, final.read_bytes()))
        for fd in descriptors:
            with self.assertRaises(OSError) as caught: os.fstat(fd)
            self.assertEqual(errno.EBADF, caught.exception.errno)

    def test_native_start_identity_is_rechecked_not_taken_from_receipt(self):
        changed = [False]
        def observe(pid):
            value = connection._observe(pid)
            return value[:-1] + (value[-1] + 1,) if changed[0] else value
        owner = connection._launch_owned_relay(
            [sys.executable, '-c', 'import sys; sys.stdin.buffer.read()'],
            _home_lookup=lambda uid: str(self.home), _observe_native=observe)
        self.owners.append(owner)
        ticket = self.prepare(owner=owner); self.write_nonce(ticket=ticket)
        changed[0] = True
        self.assert_state('owner_lost', self.finalize(ticket))

    def test_os_home_change_is_rejected_and_no_database_is_initialized(self):
        selected = [str(self.home)]
        owner = connection._launch_owned_relay(
            [sys.executable, '-c', 'import sys; sys.stdin.buffer.read()'],
            _home_lookup=lambda uid: selected[0])
        self.owners.append(owner)
        ticket = self.prepare(owner=owner); self.write_nonce(ticket=ticket)
        selected[0] = str(self.home / 'other')
        self.assert_state('authority_lost', self.finalize(ticket))
        missing_archive = Path(self.tmp.name) / 'must-not-create-db'
        with self.assertRaises(connection.ConnectionError):
            connection.prepare_connection(SimpleNamespace(state=missing_archive, source=self.source),
                connection._Operation(self.account, os.urandom(16).hex()), self.owner)
        self.assertFalse(missing_archive.exists())



@unittest.skipUnless(sys.platform == 'darwin', 'Darwin receiver only')
class CacheInspection(unittest.TestCase):
    # Reuse fixture helpers without collecting the frozen C3 tests twice.
    setUp = Connection.setUp
    launch = Connection.launch
    prepare = Connection.prepare
    close_all = Connection.close_all
    add_page = Connection.add_page
    config = Connection.config
    nonce_path = Connection.nonce_path
    write_nonce = Connection.write_nonce
    receipt = Connection.receipt
    finalize = Connection.finalize
    assert_state = Connection.assert_state
    add_acl = Connection.add_acl

    def test_inspection_missing_does_not_consume_nonce_or_latch(self):
        self.assertTrue(hasattr(connection, 'inspect_cached_connection'))
        self.assert_state('missing', connection.inspect_cached_connection(self.ticket))
        self.assertIsNone(self.ticket._outcome)
        self.write_nonce()
        self.assert_state('published', self.finalize())
    def test_inspection_valid_uses_current_hmac_and_preserves_cache(self):
        self.assertTrue(hasattr(connection, 'inspect_cached_connection'))
        cache=self.archive/'keys'/(self.account+'.keys.json')
        cache.write_text(json.dumps(self.config())); os.chmod(cache,0o600)
        before=(cache.stat().st_ino,cache.read_bytes())
        self.assert_state('cache_reused',connection.inspect_cached_connection(self.ticket))
        self.assertIsNone(self.ticket._outcome)
        self.assertEqual(before,(cache.stat().st_ino,cache.read_bytes()))
        self.add_page('message_0.db',7)
        self.assert_state('existing_invalid',connection.inspect_cached_connection(self.ticket))
    def test_exact_existing_keys_leaf_restricts_0755_without_replacement(self):
        connection.cleanup_connection(self.ticket)
        keys=self.archive/'keys'; keys.chmod(0o755)
        sentinel=keys/'preserve'; sentinel.write_bytes(b'generated sentinel')
        before=(keys.stat().st_ino,sentinel.stat().st_ino,sentinel.read_bytes())
        ticket=self.prepare()
        self.assertEqual(0o700,stat.S_IMODE(keys.stat().st_mode))
        self.assertEqual(before,(keys.stat().st_ino,sentinel.stat().st_ino,sentinel.read_bytes()))
        self.assert_state('missing',connection.inspect_cached_connection(ticket))
    def test_keys_leaf_acl_refused_before_chmod(self):
        connection.cleanup_connection(self.ticket)
        keys=self.archive/'keys'; keys.chmod(0o755);before=keys.stat().st_ino
        self.add_acl(keys)
        with self.assertRaises(connection.ConnectionError):self.prepare()
        self.assertEqual((before,0o755),(keys.stat().st_ino,stat.S_IMODE(keys.stat().st_mode)))
        subprocess.run(['/bin/chmod','-N',str(keys)],check=True)
    def test_keys_leaf_replacement_refused_before_chmod(self):
        from unittest import mock
        connection.cleanup_connection(self.ticket)
        keys=self.archive/'keys';keys.chmod(0o755);before=keys.stat().st_ino
        moved=self.archive/'original-generated-keys';original=connection._no_acl;changed=[]
        def gate(fd):
            original(fd)
            if os.fstat(fd).st_ino==before and not changed:
                changed.append(True);keys.rename(moved);keys.mkdir(mode=0o755)
        try:
            with mock.patch.object(connection,'_no_acl',gate),self.assertRaises(connection.ConnectionError):self.prepare()
            self.assertEqual(0o755,stat.S_IMODE(moved.stat().st_mode))
            self.assertEqual(0o755,stat.S_IMODE(keys.stat().st_mode))
        finally:keys.rmdir();moved.rename(keys)
    def test_keys_leaf_unsafe_owner_refused_before_chmod(self):
        from unittest import mock
        connection.cleanup_connection(self.ticket)
        keys=self.archive/'keys';keys.chmod(0o755);inode=keys.stat().st_ino
        original=os.fstat
        def info(fd):
            value=original(fd)
            if value.st_ino==inode:
                from types import SimpleNamespace
                fields={name:getattr(value,name) for name in dir(value) if name.startswith('st_')}
                fields['st_uid']=os.getuid()+1
                return SimpleNamespace(**fields)
            return value
        with mock.patch.object(connection.os,'fstat',info),self.assertRaises(connection.ConnectionError):self.prepare()
        self.assertEqual(0o755,stat.S_IMODE(keys.stat().st_mode))

if __name__=='__main__':unittest.main()
