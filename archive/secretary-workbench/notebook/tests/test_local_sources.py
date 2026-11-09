"""SOURCE contract tests. All storage is under disposable temporary directories."""
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / 'workspace'

    def registry(self):
        try:
            from modules.sources import SourceRegistry
        except ImportError:
            self.fail('SourceRegistry public API is not implemented yet')
        return SourceRegistry(self.workspace)

    def record(self, native='msg/原生:001', **patch):
        result = dict(nativeId=native, at='2026-10-22', sender='原微信名',
                      conversation='真实群名', text='原文：下一次开会', type='text',
                      locator={'messageId': native}, attachments=[])
        result.update(patch)
        return result

    # Invariant: caller IDs and imported content can never select a filesystem path.
    # A naive join accepts ../, a symlink redirects an otherwise safe join, and
    # unrestricted JSON/content consumes disk before rejecting malformed records.
    def test_rejects_path_traversal_ids_without_writes(self):
        registry = self.registry()
        for source_type, account in [('../wechat', 'me'), ('wechat', '../me'),
                                     ('/tmp', 'me'), ('wechat', 'a/b')]:
            with self.subTest(source_type=source_type, account=account):
                with self.assertRaises(ValueError):
                    registry.import_records(source_type, account, [self.record()])
        with self.assertRaises(ValueError):
            registry.query('../../outside')
        self.assertFalse(self.workspace.exists())

    def test_rejects_symlink_source_root_escape(self):
        self.workspace.mkdir()
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (self.workspace / 'sources').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.registry().import_records('wechat', 'me', [self.record()])
        self.assertEqual(list(outside.iterdir()), [])

    def test_rejects_invalid_and_oversized_records_atomically(self):
        registry = self.registry()
        for bad in [self.record(text='x' * 300_000), self.record(at='tomorrow'),
                    self.record(attachments=[{'path': '/etc/passwd'}]),
                    self.record(nativeId=''), self.record(taskState='已完成')]:
            with self.subTest(bad_keys=list(bad)):
                with self.assertRaises(ValueError):
                    registry.import_records('wechat', 'me', [self.record(), bad])
                self.assertFalse(self.workspace.exists())

    def test_import_read_query_preserve_identity_and_receipts(self):
        registry = self.registry()
        receipt = registry.import_records('wechat', 'me', [self.record(),
            self.record('second', at='2026-10-22T09:00:00+08:00', sender='另一个人')],
            display_name='我的已保存微信资料')
        sid = receipt['sourceId']
        self.assertEqual(receipt['importedCount'], 2)
        sources = registry.list_sources()
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]['status'], 'cached_only')
        page = registry.query(sid, start='2026-10-22', end='2026-10-23', limit=1)
        self.assertEqual(len(page['records']), 1)
        self.assertTrue(page['nextCursor'])
        page2 = registry.query(sid, start='2026-10-22', end='2026-10-23', limit=1,
                               cursor=page['nextCursor'])
        self.assertIsNone(page2['nextCursor'])
        self.assertNotEqual(page['records'][0]['id'], page2['records'][0]['id'])
        self.assertEqual(page['receipt']['contentReadCoverage']['recordIds'],
                         [page['records'][0]['id']])
        self.assertTrue(page['gaps'])
        original = next(r for r in page['records'] + page2['records'] if r['nativeId'].startswith('msg'))
        self.assertEqual(registry.read(sid, original['id'])['text'], self.record()['text'])
        self.assertEqual(original['at'], '2026-10-22')
        self.assertEqual(original['locator'], self.record()['locator'])
        self.assertEqual(len(registry.query(sid, sender='另一个人')['records']), 1)
        self.assertEqual(len(registry.query(sid, keyword='开会', conversation='真实群名',
                                             content_type='text')['records']), 2)
        repeat = registry.import_records('wechat', 'me', [self.record()])
        self.assertEqual(repeat['unchangedCount'], 1)
        self.assertEqual(len(registry.query(sid)['records']), 2)
        manifest = self.workspace / 'sources/wechat/me/source.json'
        manifest_data = json.loads(manifest.read_text())
        self.assertEqual(manifest_data['sourceId'], sid)
        self.assertIsNone(manifest_data['authRef'])
        self.assertTrue(manifest_data['storage']['sha256'])

    def test_account_isolation_missing_times_and_media_gaps(self):
        registry = self.registry()
        a = registry.import_records('wechat', 'a', [self.record(at=None,
            attachments=[{'assetRef': 'external:voice-1', 'type': 'audio', 'readable': False,
                          'missingReason': '未导入音频'}])])['sourceId']
        b = registry.import_records('wechat', 'b', [self.record(text='账户B')])['sourceId']
        self.assertNotEqual(a, b)
        self.assertEqual(registry.query(a)['records'][0]['text'], self.record()['text'])
        self.assertEqual(registry.query(a, start='2026-10-01')['records'], [])
        self.assertIn('unknown_record_time', {g['code'] for g in registry.query(a)['gaps']})
        self.assertIn('media_not_read', {g['code'] for g in registry.query(a)['gaps']})
        with self.assertRaises(KeyError):
            registry.read(a, registry.query(b)['records'][0]['id'])

    def test_query_limits_and_snapshot_bound_cursors(self):
        registry = self.registry()
        sid = registry.import_records('mail', 'a', [self.record('1'), self.record('2')])['sourceId']
        for kwargs in [{'limit': 0}, {'limit': 501}, {'cursor': '../bad'},
                       {'start': 'tomorrow'}, {'start': '2026-10-23', 'end': '2026-10-22'}]:
            with self.assertRaises(ValueError):
                registry.query(sid, **kwargs)
        page = registry.query(sid, limit=1)
        with self.assertRaises(ValueError):
            registry.query(sid, limit=1, keyword='different', cursor=page['nextCursor'])
        registry.import_records('mail', 'a', [self.record('3')])
        with self.assertRaises(ValueError):
            registry.query(sid, limit=1, cursor=page['nextCursor'])

    def test_read_only_calls_do_not_initialize_or_mutate(self):
        registry = self.registry()
        self.assertEqual(registry.list_sources(), [])
        self.assertFalse(self.workspace.exists())
        sid = registry.import_records('mail', 'a', [self.record()])['sourceId']
        before = {str(p): p.read_bytes() for p in self.workspace.rglob('*') if p.is_file()}
        registry.query(sid)
        registry.read(sid, registry.query(sid)['records'][0]['id'])
        registry.list_sources()
        after = {str(p): p.read_bytes() for p in self.workspace.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_rejects_symlink_snapshot_and_keeps_import_atomic(self):
        registry = self.registry()
        sid = registry.import_records('mail', 'a', [self.record()])['sourceId']
        directory = self.workspace / 'sources/mail/a'
        manifest = json.loads((directory / 'source.json').read_text())
        target = directory / manifest['storage']['path']
        saved = target.read_bytes()
        target.unlink()
        outside = Path(self.tmp.name) / 'outside.json'
        outside.write_bytes(saved)
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            registry.query(sid)
        with self.assertRaises(ValueError):
            registry.import_records('mail', 'a', [self.record('new')])
        self.assertEqual(outside.read_bytes(), saved)
        self.assertFalse(list(directory.glob('*.tmp')))

    def test_missing_committed_snapshot_rejects_import_without_replacing_manifest(self):
        registry = self.registry()
        sid = registry.import_records('mail', 'a', [self.record()])['sourceId']
        directory = self.workspace / 'sources/mail/a'
        manifest = directory / 'source.json'
        before = manifest.read_bytes()
        data = json.loads(before)
        (directory / data['storage']['path']).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            registry.import_records('mail', 'a', [self.record('new')])
        self.assertEqual(manifest.read_bytes(), before)

    def test_write_failure_cleans_new_files_and_preserves_committed_snapshot(self):
        registry = self.registry()
        sid = registry.import_records('mail', 'a', [self.record()])['sourceId']
        directory = self.workspace / 'sources/mail/a'
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        with patch('modules.sources.registry.os.replace', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                registry.import_records('mail', 'a', [self.record('new')])
        self.assertEqual({p.name: p.read_bytes() for p in directory.iterdir()}, before)
        self.assertEqual(len(registry.query(sid)['records']), 1)

    def test_post_commit_sync_failure_keeps_new_snapshot_readable(self):
        registry = self.registry()
        sid = registry.import_records('mail', 'a', [self.record()])['sourceId']
        original_fsync = os.fsync
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError('simulated directory sync failure after commit')
            return original_fsync(fd)
        with patch('modules.sources.registry.os.fsync', side_effect=sync):
            with self.assertRaises(OSError):
                registry.import_records('mail', 'a', [self.record('new')])
        self.assertEqual(len(registry.query(sid)['records']), 2)

    def test_source_directory_rename_keeps_identity_and_update_history(self):
        registry = self.registry()
        sid = registry.import_records('mail', 'a', [self.record()])['sourceId']
        directory = self.workspace / 'sources/mail/a'
        directory.rename(directory.parent / 'renamed')
        original = registry.query(sid)['records'][0]
        receipt = registry.import_records('mail', 'a', [self.record(text='更正后的原文')])
        changed = registry.read(sid, original['id'])
        self.assertEqual(receipt['updatedCount'], 1)
        self.assertEqual(changed['nativeId'], original['nativeId'])
        self.assertNotEqual(changed['contentHash'], original['contentHash'])
        self.assertEqual(len(list((directory.parent / 'renamed').glob('snapshot_*.json'))), 2)
        self.assertFalse(directory.exists())

    def test_no_args_cli_and_list_have_no_writes_import_is_explicit(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        def cli(*args, data=None):
            return subprocess.run([sys.executable, '-m', 'modules.sources', *args],
                                  cwd=ROOT, env=env, input=data, text=True, capture_output=True)
        usage = cli()
        self.assertEqual(usage.returncode, 0, usage.stderr)
        self.assertIn('--workspace', usage.stdout)
        self.assertNotEqual(cli('list').returncode, 0)
        listed = cli('--workspace', str(self.workspace), 'list')
        self.assertEqual(json.loads(listed.stdout), {'sources': []})
        self.assertFalse(self.workspace.exists())
        imported = cli('--workspace', str(self.workspace), 'import', '--source-type', 'mail',
                       '--account-id', 'a', data=json.dumps([self.record()]))
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertEqual(json.loads(imported.stdout)['importedCount'], 1)


if __name__ == '__main__':
    unittest.main()
