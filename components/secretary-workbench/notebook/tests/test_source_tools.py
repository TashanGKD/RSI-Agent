"""Source tools: immutable versions, exact receipts, consumer checkpoints and assets.

Path invariant: a source/asset/snapshot ID never selects arbitrary filesystem data.
Breaking inputs written before implementation: ../../etc/passwd IDs, an assets
symlink pointing outside the source, a forged receipt ID, and a stale revision.
All fixtures are explicit saved imports; no upstream adapters or personal scans.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modules.sources import SourceRegistry


class SourceToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.workspace = Path(self.tmp.name) / 'workspace'
        self.registry = SourceRegistry(self.workspace)
        self.sid = self.registry.import_records('mail', 'account', [self.record()])['sourceId']
        self.row = self.registry.query(self.sid)['records'][0]
        self.snapshot = self.registry.query(self.sid)['receipt']['snapshot']
        self.directory = self.workspace / 'sources/mail/account'

    def record(self, text='original', attachments=None):
        return dict(nativeId='native:1', at='2026-10-24', text=text,
                    nativeVersion='vendor-revision', attachments=attachments or [])

    def state(self):
        return {str(p.relative_to(self.workspace)): p.read_bytes()
                for p in self.workspace.rglob('*') if p.is_file() and not p.is_symlink()}

    def test_invalid_ids_and_path_refs_rejected_before_writes(self):
        before = self.state()
        for sid in ['../mail', 'mail:../account', 'mail:account/../../secret', 'mail:']:
            with self.subTest(sid=sid):
                with self.assertRaises(ValueError):
                    self.registry.list_snapshots(sid)
                with self.assertRaises(ValueError):
                    self.registry.put_asset(sid, b'abc', mime='text/plain')
        for ref in ['../../etc/passwd', '/etc/passwd', 'asset:../secret', 'asset:' + '0' * 63]:
            with self.assertRaises(ValueError):
                self.registry.get_asset(self.sid, ref)
        with self.assertRaises(ValueError):
            self.registry.read_record_version(self.sid, self.row['id'], '../source.json')
        self.assertEqual(self.state(), before)

    def test_asset_symlink_escape_and_invalid_mime_or_checksum_leave_no_files(self):
        outside = Path(self.tmp.name) / 'outside'
        outside.mkdir()
        (self.directory / 'assets').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.registry.put_asset(self.sid, b'abc', mime='text/plain')
        self.assertEqual(list(outside.iterdir()), [])
        (self.directory / 'assets').unlink()
        before = self.state()
        for kwargs in [dict(mime='text/html'), dict(mime='text/plain\r\nX: bad'),
                       dict(mime='image/png'), dict(mime='text/plain', expected_sha256='0' * 64)]:
            with self.assertRaises(ValueError):
                self.registry.put_asset(self.sid, b'abc', **kwargs)
        with self.assertRaises(ValueError):
            self.registry.put_asset(self.sid, b'x' * (8 * 1024 * 1024 + 1), mime='application/octet-stream')
        self.assertEqual(self.state(), before)

    def test_snapshot_versions_read_historical_content_and_keep_native_identity(self):
        self.registry.import_records('mail', 'account', [self.record('changed')])
        versions = self.registry.list_record_versions(self.sid, self.row['id'])
        self.assertEqual(len(versions), 2)
        old = self.registry.read_record_version(self.sid, self.row['id'], self.snapshot)
        self.assertEqual(old['record']['text'], 'original')
        self.assertEqual(old['record']['nativeVersion'], 'vendor-revision')
        self.assertEqual(old['snapshot']['snapshot'], self.snapshot)
        self.assertFalse(old['snapshot']['upstreamComplete'])
        self.assertEqual(len(self.registry.list_snapshots(self.sid)), 2)
        self.assertEqual(self.registry.read(self.sid, self.row['id'])['text'], 'changed')
        self.assertEqual({v['contentHash'] for v in versions},
                         {self.row['contentHash'], self.registry.read(self.sid, self.row['id'])['contentHash']})

    def test_historical_hash_tampering_rejected_and_orphans_not_promoted(self):
        self.registry.import_records('mail', 'account', [self.record('changed')])
        old_path = self.directory / ('snapshot_' + self.snapshot + '.json')
        saved = old_path.read_bytes()
        old_path.write_bytes(saved.replace(b'original', b'forgery!'))
        with self.assertRaises(ValueError):
            self.registry.read_record_version(self.sid, self.row['id'], self.snapshot)
        old_path.write_bytes(saved)
        orphan = 'f' * 32
        (self.directory / ('snapshot_' + orphan + '.json')).write_bytes(saved)
        inventory = self.registry.list_snapshots(self.sid)
        self.assertEqual(next(s for s in inventory if s['snapshot'] == orphan)['integrity'], 'uncommitted')
        with self.assertRaises(ValueError):
            self.registry.read_record_version(self.sid, self.row['id'], orphan)

    def test_receipt_is_persisted_exact_and_media_is_not_implicitly_read(self):
        asset = self.registry.put_asset(self.sid, b'hello', mime='text/plain', name='note.txt')
        attachment = dict(assetRef=asset['assetRef'], mime='text/plain', readable=True)
        self.registry.import_records('mail', 'account', [self.record(attachments=[attachment])])
        page = self.registry.query(self.sid)
        receipt = self.registry.persist_read_receipt(self.sid, page['receipt']['snapshot'], [self.row['id']])
        item = receipt['records'][0]
        self.assertEqual(item['content']['text'], 'original')
        self.assertEqual(item['recordHash'], hashlib.sha256(json.dumps(page['records'][0], ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        self.assertEqual(item['media'][0]['status'], 'not_read')
        self.assertTrue(item['media'][0]['localAssetKnown'])
        saved = self.registry.read_read_receipt(self.sid, receipt['id'])
        self.assertEqual(saved, receipt)
        self.assertEqual(self.registry.list_read_receipts(self.sid), [receipt])
        self.assertFalse(receipt['upstreamComplete'])
        self.assertIn('live_not_connected', {g['code'] for g in receipt['gaps']})

    def test_unknown_media_and_unreadable_content_are_explicit(self):
        record = self.record(attachments=[dict(assetRef='external:audio', type='audio', readable=True)])
        record.update(readable=False, missingReason='body not imported', text='')
        imported = self.registry.import_records('mail', 'account', [record])
        receipt = self.registry.persist_read_receipt(self.sid, imported['snapshot'], [self.row['id']])
        self.assertFalse(receipt['records'][0]['content']['readable'])
        self.assertEqual(receipt['records'][0]['content']['readingNature'], 'not_read')
        self.assertFalse(receipt['records'][0]['media'][0]['localAssetKnown'])
        self.assertEqual(receipt['records'][0]['media'][0]['status'], 'not_read')
        with self.assertRaises(ValueError):
            self.registry.persist_read_receipt(self.sid, imported['snapshot'], [self.row['id']], media_reads=['external:audio'])

    def test_forged_receipts_skipped_stages_and_stale_revisions_rejected(self):
        self.assertEqual(self.registry.get_checkpoints(self.sid, 'consumer')['revision'], 0)
        before = self.state()
        for stage, revision, receipts in [('read', 0, ['receipt_' + '0' * 32]),
                                          ('applied', 0, []), ('retrieved', 1, [])]:
            with self.subTest(stage=stage):
                with self.assertRaises(ValueError):
                    self.registry.advance_checkpoint(self.sid, 'consumer', stage, expected_revision=revision,
                        snapshot=self.snapshot, record_ids=[self.row['id']], receipt_ids=receipts)
        with self.assertRaises(ValueError):
            self.registry.advance_checkpoint(self.sid, '../consumer', 'retrieved', expected_revision=0,
                snapshot=self.snapshot, record_ids=[self.row['id']])
        self.assertEqual(self.state(), before)

    def test_checkpoints_require_exact_receipts_and_explicit_downstream_ack(self):
        receipt = self.registry.persist_read_receipt(self.sid, self.snapshot, [self.row['id']])
        state = self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=0,
            snapshot=self.snapshot, record_ids=[self.row['id']])
        self.assertEqual(state['revision'], 1)
        self.assertIsNone(state['stages']['read'])
        state = self.registry.advance_checkpoint(self.sid, 'consumer', 'read', expected_revision=1,
            snapshot=self.snapshot, record_ids=[self.row['id']], receipt_ids=[receipt['id']])
        self.assertEqual(state['revision'], 2)
        with self.assertRaises(ValueError):
            self.registry.advance_checkpoint(self.sid, 'consumer', 'applied', expected_revision=2,
                snapshot=self.snapshot, record_ids=[self.row['id']], receipt_ids=[receipt['id']])
        state = self.registry.advance_checkpoint(self.sid, 'consumer', 'applied', expected_revision=2,
            snapshot=self.snapshot, record_ids=[self.row['id']], receipt_ids=[receipt['id']],
            acknowledgment={'operationRef': 'consumer-operation:1', 'detail': 'explicit consumer acknowledgment'})
        self.assertEqual(state['revision'], 3)
        self.assertEqual(len(state['history']), 3)
        self.assertEqual(state['stages']['applied']['acknowledgment']['operationRef'], 'consumer-operation:1')
        self.assertEqual(self.registry.get_checkpoints(self.sid, 'consumer'), state)
        self.assertNotIn('taskState', json.dumps(state))
        self.assertFalse(state['upstreamComplete'])
        # A newer snapshot cannot borrow a receipt from an old native-record version.
        newer = self.registry.import_records('mail', 'account', [self.record('changed')])
        self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=3,
            snapshot=newer['snapshot'], record_ids=[self.row['id']])
        with self.assertRaises(ValueError):
            self.registry.advance_checkpoint(self.sid, 'consumer', 'read', expected_revision=4,
                snapshot=newer['snapshot'], record_ids=[self.row['id']], receipt_ids=[receipt['id']])

    def test_assets_are_account_scoped_relocatable_and_hash_verified(self):
        asset = self.registry.put_asset(self.sid, b'hello', mime='text/plain', name='../../not-a-path.txt')
        self.assertEqual(asset['sha256'], hashlib.sha256(b'hello').hexdigest())
        self.assertEqual(asset['name'], '../../not-a-path.txt')
        self.assertEqual(self.registry.get_asset(self.sid, asset['assetRef'])['content'], b'hello')
        self.assertEqual(len(self.registry.list_assets(self.sid)), 1)
        self.registry.import_records('mail', 'other', [self.record()])
        with self.assertRaises(KeyError):
            self.registry.get_asset('mail:other', asset['assetRef'])
        receipt = self.registry.persist_read_receipt(self.sid, self.snapshot, [self.row['id']])
        copied = Path(self.tmp.name) / 'copy'
        shutil.copytree(self.workspace, copied)
        other = SourceRegistry(copied)
        self.assertEqual(other.get_asset(self.sid, asset['assetRef'])['content'], b'hello')
        self.assertEqual(other.read_read_receipt(self.sid, receipt['id']), receipt)
        blob = self.directory / 'assets' / (asset['sha256'] + '.blob')
        blob.write_bytes(b'wrong')
        with self.assertRaises(ValueError):
            self.registry.get_asset(self.sid, asset['assetRef'])

    def test_asset_failures_cleanup_and_existing_blob_symlink_rejected(self):
        with patch('modules.sources.registry.os.replace', side_effect=OSError('simulated commit failure')):
            with self.assertRaises(OSError):
                self.registry.put_asset(self.sid, b'hello', mime='text/plain')
        assets = self.directory / 'assets'
        self.assertEqual(list(assets.iterdir()), [])
        asset = self.registry.put_asset(self.sid, b'hello', mime='text/plain')
        blob = assets / (asset['sha256'] + '.blob')
        blob.unlink()
        outside = Path(self.tmp.name) / 'outside'
        outside.write_bytes(b'hello')
        blob.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.registry.get_asset(self.sid, asset['assetRef'])
        self.assertEqual(outside.read_bytes(), b'hello')

    def test_readonly_tools_do_not_write_and_module_has_no_notebook_dependency(self):
        before = self.state()
        self.registry.list_snapshots(self.sid)
        self.registry.list_record_versions(self.sid, self.row['id'])
        self.registry.read_record_version(self.sid, self.row['id'], self.snapshot)
        self.registry.get_checkpoints(self.sid, 'consumer')
        self.registry.list_read_receipts(self.sid)
        self.registry.list_assets(self.sid)
        self.assertEqual(self.state(), before)
        for path in (ROOT / 'modules/sources').glob('*.py'):
            self.assertNotIn('modules.notebook', path.read_text())

    def test_receipt_tampering_cannot_relabel_unreadable_saved_text_as_read(self):
        record = self.record()
        record.update(readable=False, missingReason='not imported')
        snapshot = self.registry.import_records('mail', 'account', [record])['snapshot']
        receipt = self.registry.persist_read_receipt(self.sid, snapshot, [self.row['id']])
        receipt['records'][0]['content']['readable'] = True
        receipt['records'][0]['content']['readingNature'] = 'saved_text'
        body = {k: v for k, v in receipt.items() if k != 'receiptHash'}
        receipt['receiptHash'] = hashlib.sha256(json.dumps(body, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        (self.directory / 'receipts' / (receipt['id'] + '.json')).write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            self.registry.read_read_receipt(self.sid, receipt['id'])

    def test_receipt_schema_tamper_media_and_semantic_state_rejected(self):
        receipt = self.registry.persist_read_receipt(self.sid, self.snapshot, [self.row['id']])
        receipt['taskState'] = 'complete'
        body = {k: v for k, v in receipt.items() if k != 'receiptHash'}
        receipt['receiptHash'] = hashlib.sha256(json.dumps(body, ensure_ascii=False,
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        (self.directory / 'receipts' / (receipt['id'] + '.json')).write_text(json.dumps(receipt))
        with self.assertRaises(ValueError):
            self.registry.read_read_receipt(self.sid, receipt['id'])

    def test_missing_committed_asset_cannot_be_reported_as_empty_inventory(self):
        asset = self.registry.put_asset(self.sid, b'hello', mime='text/plain')
        (self.directory / 'assets' / (asset['sha256'] + '.blob')).unlink()
        with self.assertRaises((ValueError, FileNotFoundError)):
            self.registry.list_assets(self.sid)

    def test_control_characters_in_asset_labels_are_rejected(self):
        before = self.state()
        for label in ['bad\x00name', 'bad\r\nheader', 'bad\nname']:
            with self.assertRaises(ValueError):
                self.registry.put_asset(self.sid, b'hello', mime='text/plain', name=label)
        self.assertEqual(self.state(), before)

    def test_only_explicit_media_reads_are_recorded_with_verified_hash(self):
        asset = self.registry.put_asset(self.sid, b'hello', mime='text/plain')
        snapshot = self.registry.import_records('mail', 'account', [self.record(
            attachments=[{'assetRef': asset['assetRef']}])])['snapshot']
        receipt = self.registry.persist_read_receipt(self.sid, snapshot, [self.row['id']],
            media_reads=[asset['assetRef']])
        media = receipt['records'][0]['media'][0]
        self.assertEqual(media['status'], 'bytes_read')
        self.assertEqual(media['sha256'], asset['sha256'])
        self.assertEqual(self.registry.read_read_receipt(self.sid, receipt['id']), receipt)
        other = self.registry.put_asset(self.sid, b'unattached', mime='text/plain')
        with self.assertRaises(ValueError):
            self.registry.persist_read_receipt(self.sid, snapshot, [self.row['id']],
                media_reads=[other['assetRef']])

    def test_missing_committed_history_is_an_error_and_missing_manifest_is_not_rebuilt(self):
        self.registry.import_records('mail', 'account', [self.record('changed')])
        (self.directory / ('snapshot_' + self.snapshot + '.json')).unlink()
        with self.assertRaises(ValueError):
            self.registry.list_snapshots(self.sid)
        before = (self.directory / 'source.json').read_bytes()
        (self.directory / 'source.json').unlink()
        with self.assertRaises(KeyError):
            self.registry.list_snapshots(self.sid)
        self.assertFalse((self.directory / 'source.json').exists())
        self.assertTrue(before)

    def test_checkpoint_payload_rejects_semantic_fields_and_invalid_stage(self):
        receipt = self.registry.persist_read_receipt(self.sid, self.snapshot, [self.row['id']])
        self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=0,
            snapshot=self.snapshot, record_ids=[self.row['id']])
        self.registry.advance_checkpoint(self.sid, 'consumer', 'read', expected_revision=1,
            snapshot=self.snapshot, record_ids=[self.row['id']], receipt_ids=[receipt['id']])
        before = self.state()
        with self.assertRaises(ValueError):
            self.registry.advance_checkpoint(self.sid, 'consumer', 'applied', expected_revision=2,
                snapshot=self.snapshot, record_ids=[self.row['id']], receipt_ids=[receipt['id']],
                acknowledgment={'operationRef': 'op:1', 'taskState': 'complete'})
        with self.assertRaises(ValueError):
            self.registry.advance_checkpoint(self.sid, 'consumer', 'completed', expected_revision=2,
                snapshot=self.snapshot, record_ids=[self.row['id']])
        self.assertEqual(self.state(), before)

    def test_snapshot_quota_never_silently_prunes_native_record_history(self):
        for index in range(1, 16):
            self.registry.import_records('mail', 'account', [self.record('version:' + str(index))])
        before = self.state()
        with self.assertRaises(ValueError):
            self.registry.import_records('mail', 'account', [self.record('overflow')])
        self.assertEqual(self.state(), before)
        self.assertEqual(len(self.registry.list_snapshots(self.sid)), 16)
        self.assertEqual(self.registry.read_record_version(self.sid, self.row['id'],
            self.snapshot)['record']['text'], 'original')
        repeat = self.registry.import_records('mail', 'account', [self.record('version:15')])
        self.assertEqual(repeat['unchangedCount'], 1)
        self.assertEqual(self.state(), before)

    def test_checkpoint_compare_and_swap_serializes_concurrent_consumers(self):
        from concurrent.futures import ThreadPoolExecutor
        from modules.sources import CheckpointConflictError
        def advance():
            try:
                self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=0,
                    snapshot=self.snapshot, record_ids=[self.row['id']])
                return 'stored'
            except CheckpointConflictError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: advance(), range(2)))
        self.assertCountEqual(results, ['stored', 'conflict'])
        self.assertEqual(self.registry.get_checkpoints(self.sid, 'consumer')['revision'], 1)

    def test_checkpoint_commit_failure_preserves_prior_revision(self):
        self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=0,
            snapshot=self.snapshot, record_ids=[self.row['id']])
        before = self.state()
        with patch('modules.sources.registry.os.replace', side_effect=OSError('simulated replace failure')):
            with self.assertRaises(OSError):
                self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=1,
                    snapshot=self.snapshot, record_ids=[self.row['id']])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.registry.get_checkpoints(self.sid, 'consumer')['revision'], 1)
        self.assertFalse(list(self.directory.rglob('*.tmp')))

    def test_receipt_commit_failure_cleans_uncommitted_file(self):
        with patch('modules.sources.registry.os.fsync', side_effect=OSError('simulated sync failure')):
            with self.assertRaises(OSError):
                self.registry.persist_read_receipt(self.sid, self.snapshot, [self.row['id']])
        self.assertEqual(self.registry.list_read_receipts(self.sid), [])
        self.assertFalse(list(self.directory.rglob('*.tmp')))

    def test_stored_checkpoint_cannot_expose_unknown_semantic_state_or_relabel_history(self):
        state = self.registry.advance_checkpoint(self.sid, 'consumer', 'retrieved', expected_revision=0,
            snapshot=self.snapshot, record_ids=[self.row['id']])
        checkpoint_path = self.directory / 'checkpoints/consumer.json'
        for patch_data in [dict(taskState='complete'), dict(stages=dict(retrieved=None, read=None, applied=None))]:
            bad = dict(state)
            bad.update(patch_data)
            checkpoint_path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                self.registry.get_checkpoints(self.sid, 'consumer')

    def test_stored_asset_metadata_cannot_expose_unknown_semantic_state(self):
        asset = self.registry.put_asset(self.sid, b'hello', mime='text/plain')
        asset['taskState'] = 'complete'
        (self.directory / 'assets' / (asset['sha256'] + '.json')).write_text(json.dumps(asset))
        with self.assertRaises(ValueError):
            self.registry.get_asset(self.sid, asset['assetRef'])

    def test_cli_lists_history_and_receipts_and_explicit_mutations(self):
        def cli(*args, data=None):
            return subprocess.run([sys.executable, '-m', 'modules.sources', '--workspace', str(self.workspace), *args],
                cwd=ROOT, text=True, input=data, capture_output=True,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        result = cli('versions', self.sid, self.row['id'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)['versions']), 1)
        result = cli('read-version', self.sid, self.row['id'], self.snapshot)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['record']['text'], 'original')
        result = cli('receipt-create', self.sid, self.snapshot, self.row['id'])
        self.assertEqual(result.returncode, 0, result.stderr)
        receipt_id = json.loads(result.stdout)['id']
        result = cli('receipts', self.sid)
        self.assertEqual(json.loads(result.stdout)['receipts'][0]['id'], receipt_id)
        result = cli('asset-put', self.sid, '--mime', 'text/plain', data='hello')
        self.assertEqual(result.returncode, 0, result.stderr)
        ref = json.loads(result.stdout)['assetRef']
        result = cli('asset-get', self.sid, ref)
        self.assertEqual(json.loads(result.stdout)['contentBase64'], 'aGVsbG8=')


if __name__ == '__main__':
    unittest.main()
