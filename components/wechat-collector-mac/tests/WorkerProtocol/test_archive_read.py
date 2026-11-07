"""Only private generated SQLite fixtures; never real archives, keys or processes.

Invariant: an archive read accepts only regular index/sidecar entries, reads a
stable journal-free snapshot without writes, and preserves live WAL semantics.
Breaking inputs tested before implementation: index symlink to valid DELETE DB;
dangling -wal symlink; directory at reserved -shm. The old reader accepts all.
"""
from contextlib import closing
import importlib.util
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch

WORKER = Path(__file__).resolve().parents[2] / 'src/MacWorker/mac_worker.py'
spec = importlib.util.spec_from_file_location('archive_read_worker_fixture', WORKER)
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class ArchiveRead(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='archive-read-fixture-')
        self.root = Path(self.folder.name)
        self.archive = self.root / 'archive'
        self.archive.mkdir()
        self.index = self.archive / 'index.db'

    def tearDown(self):
        self.archive.chmod(0o700)
        self.folder.cleanup()

    def delete_index(self, path=None):
        with closing(sqlite3.connect(path or self.index)) as db:
            db.execute('CREATE TABLE messages(value TEXT)')
            db.execute("INSERT INTO messages VALUES ('checkpointed')")
            db.commit()

    def wal_snapshot(self):
        source = self.root / 'source.db'
        with closing(sqlite3.connect(source)) as db:
            self.assertEqual(db.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            db.execute('CREATE TABLE messages(value TEXT)')
            db.execute("INSERT INTO messages VALUES ('checkpointed')")
            db.commit()
            self.assertEqual(db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0], 0)
            shutil.copy2(source, self.index)
        self.assertEqual(self.index.read_bytes()[18:20], bytes((2, 2)))
        with closing(sqlite3.connect(self.index.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            self.assertEqual(db.execute('SELECT value FROM messages').fetchone()[0], 'checkpointed')

    def read(self):
        with worker.ReadOnlyArchive(self.archive).connect() as db:
            return db.execute('SELECT value FROM messages').fetchone()[0]

    def test_reject_index_symlink_to_valid_database(self):
        target = self.root / 'target.db'
        self.delete_index(target)
        self.index.symlink_to(target)
        with self.assertRaises(ValueError):
            self.read()

    def test_reject_dangling_wal_symlink(self):
        self.delete_index()
        Path(str(self.index) + '-wal').symlink_to(self.root / 'missing')
        with self.assertRaises(ValueError):
            self.read()

    def test_reject_shm_directory(self):
        self.delete_index()
        Path(str(self.index) + '-shm').mkdir()
        with self.assertRaises(ValueError):
            self.read()

    def test_main_only_wal_snapshot_in_readonly_directory(self):
        self.wal_snapshot()
        self.index.chmod(0o444)
        before = (self.index.read_bytes(), stat.S_IMODE(self.index.stat().st_mode), sorted(self.archive.iterdir()))
        self.archive.chmod(0o555)
        with worker.ReadOnlyArchive(self.archive).connect() as db:
            self.assertIsInstance(db.execute('SELECT value FROM messages').fetchone(), sqlite3.Row)
            self.assertEqual(db.execute('SELECT value FROM messages').fetchone()['value'], 'checkpointed')
            with self.assertRaises(sqlite3.OperationalError):
                db.execute("INSERT INTO messages VALUES ('forbidden')")
        self.assertEqual((self.index.read_bytes(), stat.S_IMODE(self.index.stat().st_mode), sorted(self.archive.iterdir())), before)


    def test_unsafe_entries_are_rejected_before_sqlite(self):
        self.delete_index()
        for suffix in ('-wal', '-shm', '-journal'):
            entry = Path(str(self.index) + suffix)
            with self.subTest(suffix=suffix):
                entry.symlink_to(self.root / 'absent')
                try:
                    with patch.object(sqlite3, 'connect', side_effect=AssertionError('SQLite must not open')):
                        with self.assertRaises(ValueError):
                            self.read()
                finally:
                    entry.unlink()

    def test_reject_nonregular_index_before_sqlite(self):
        self.index.mkdir()
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('SQLite must not open')):
            with self.assertRaises(ValueError):
                self.read()

    def test_missing_index_does_not_create_anything(self):
        with self.assertRaises((FileNotFoundError, ValueError)):
            self.read()
        self.assertEqual(list(self.archive.iterdir()), [])

    def test_regular_readonly_hardlink_is_allowed(self):
        target = self.root / 'target.db'
        self.delete_index(target)
        os.link(target, self.index)
        self.index.chmod(0o444)
        self.archive.chmod(0o555)
        self.assertEqual(self.read(), 'checkpointed')
        self.assertEqual(self.index.stat().st_nlink, 2)

    def test_regular_empty_sidecars_select_normal_readonly(self):
        self.delete_index()
        real_connect = sqlite3.connect
        for suffix in ('-wal', '-shm', '-journal'):
            entry = Path(str(self.index) + suffix)
            entry.touch()
            try:
                with self.subTest(suffix=suffix), patch.object(sqlite3, 'connect', wraps=real_connect) as opened:
                    self.assertEqual(self.read(), 'checkpointed')
                    self.assertEqual(opened.call_count, 1)
                    self.assertEqual(opened.call_args.args[0], (self.archive.resolve() / 'index.db').as_uri() + '?mode=ro')
                    self.assertEqual(opened.call_args.kwargs, dict(uri=True, timeout=30))
            finally:
                entry.unlink(missing_ok=True)

    def test_real_live_wal_is_visible_and_read_context_is_consistent(self):
        with closing(sqlite3.connect(self.index)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('CREATE TABLE messages(value TEXT)')
            writer.execute("INSERT INTO messages VALUES ('first')")
            writer.commit()
            self.assertGreater(Path(str(self.index) + '-wal').stat().st_size, 0)
            with worker.ReadOnlyArchive(self.archive).connect() as db:
                self.assertEqual([r[0] for r in db.execute('SELECT value FROM messages')], ['first'])
                writer.execute("INSERT INTO messages VALUES ('second')")
                writer.commit()
                self.assertEqual([r[0] for r in db.execute('SELECT value FROM messages')], ['first'])
            with worker.ReadOnlyArchive(self.archive).connect() as db:
                self.assertEqual([r[0] for r in db.execute('SELECT value FROM messages')], ['first', 'second'])

    def test_journal_appearance_after_selection_closes_before_yield(self):
        self.delete_index()
        real_connect = sqlite3.connect
        connections = []
        def changed(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            connections.append(db)
            Path(str(self.index) + '-journal').touch()
            return db
        entered = []
        with patch.object(sqlite3, 'connect', side_effect=changed):
            with self.assertRaisesRegex(ValueError, '正在更新'):
                with worker.ReadOnlyArchive(self.archive).connect() as db:
                    entered.append(True)
        self.assertEqual(entered, [])
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute('SELECT 1')

    def test_index_substitution_after_selection_closes_before_yield(self):
        self.delete_index()
        replacement = self.root / 'replacement.db'
        self.delete_index(replacement)
        real_connect = sqlite3.connect
        connections = []
        def changed(*args, **kwargs):
            db = real_connect(*args, **kwargs)
            connections.append(db)
            replacement.replace(self.index)
            return db
        with patch.object(sqlite3, 'connect', side_effect=changed):
            with self.assertRaisesRegex(ValueError, '正在更新'):
                self.read()
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute('SELECT 1')

    def test_changed_snapshot_never_publishes_result(self):
        self.delete_index()
        published = []
        saved = []
        with self.assertRaisesRegex(ValueError, '正在更新'):
            with worker.ReadOnlyArchive(self.archive).connect() as db:
                saved.append(db)
                result = db.execute('SELECT value FROM messages').fetchone()[0]
                Path(str(self.index) + '-wal').touch()
            published.append(result)
        self.assertEqual(published, [])
        with self.assertRaises(sqlite3.ProgrammingError):
            saved[0].execute('SELECT 1')

    def test_index_metadata_changes_are_detected_after_close(self):
        self.delete_index()
        with self.assertRaisesRegex(ValueError, '正在更新'):
            with worker.ReadOnlyArchive(self.archive).connect() as db:
                db.execute('SELECT value FROM messages').fetchone()
                self.index.chmod(0o400)
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')

    def test_postcheck_does_not_mask_caller_exception_or_cancellation(self):
        self.delete_index()
        for error in (RuntimeError('original caller failure'), KeyboardInterrupt('cancelled')):
            entry = Path(str(self.index) + '-journal')
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(type(error)) as caught:
                    with worker.ReadOnlyArchive(self.archive).connect() as db:
                        entry.touch()
                        raise error
                self.assertIs(caught.exception, error)
                with self.assertRaises(sqlite3.ProgrammingError):
                    db.execute('SELECT 1')
                entry.unlink()

    def test_open_errors_are_not_retried_with_immutable(self):
        self.delete_index()
        for suffix in (None, '-wal'):
            if suffix:
                Path(str(self.index) + suffix).touch()
            for error in (sqlite3.OperationalError('fixture failure'), PermissionError('fixture permission')):
                with self.subTest(sidecar=suffix, error=type(error).__name__):
                    with patch.object(sqlite3, 'connect', side_effect=error) as opened:
                        with self.assertRaises(type(error)) as caught:
                            self.read()
                    self.assertIs(caught.exception, error)
                    self.assertEqual(opened.call_count, 1)
                    self.assertEqual('immutable=1' in opened.call_args.args[0], suffix is None)

    def test_corrupt_database_fails_without_retry(self):
        self.index.write_bytes(b'not a sqlite database' * 100)
        real_connect = sqlite3.connect
        with patch.object(sqlite3, 'connect', wraps=real_connect) as opened:
            with self.assertRaises(sqlite3.DatabaseError):
                self.read()
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(sorted(p.name for p in self.archive.iterdir()), ['index.db'])


if __name__ == '__main__':
    unittest.main()
