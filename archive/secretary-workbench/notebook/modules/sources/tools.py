"""Local source tools. No live collection, semantic decisions or notebook imports.

Receipts prove what this local tool delivered/read, never human comprehension.
Checkpoint application is an explicit consumer acknowledgment, not a task status.
"""
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
import stat
import uuid

SNAPSHOT_ID = re.compile(r'[a-f0-9]{32}\Z')
ASSET_REF = re.compile(r'asset:([a-f0-9]{64})\Z')
RECEIPT_ID = re.compile(r'receipt_[a-f0-9]{32}\Z')
MAX_ASSET_BYTES = 8 * 1024 * 1024
MAX_ASSET_TOTAL = 64 * 1024 * 1024
MAX_ASSETS = 128
MAX_RECEIPTS = 256
MAX_RECEIPT_BYTES = 8 * 1024 * 1024
MAX_RECEIPT_TOTAL = 64 * 1024 * 1024
MAX_CHECKPOINT_EVENTS = 256


class CheckpointConflictError(ValueError):
    """An optimistic consumer checkpoint revision no longer matches."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _valid_snapshot(value):
    if not isinstance(value, str) or not SNAPSHOT_ID.fullmatch(value):
        raise ValueError('invalid snapshot ID')
    return value


def _valid_receipt(value):
    if not isinstance(value, str) or not RECEIPT_ID.fullmatch(value):
        raise ValueError('invalid read receipt ID')
    return value


def _asset_hash(value):
    match = ASSET_REF.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError('invalid managed asset reference')
    return match[1]


def _read_bytes(fd, name, maximum):
    if not isinstance(name, str) or '/' in name or name in ('', '.', '..'):
        raise ValueError('unsafe managed filename')
    try:
        opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError('managed asset must not be a symlink') from exc
    with os.fdopen(opened, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('managed file must be bounded and regular')
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('managed file exceeds limit')
    return data


class SourceToolsMixin:
    """Public local tools layered on the registry's no-follow storage primitives."""

    def _atomic_json(self, fd, name, value):
        from .registry import _json_bytes
        temporary = 'write_' + uuid.uuid4().hex + '.tmp'
        try:
            self._write_new(fd, temporary, _json_bytes(value))
            os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
        # The replacement is committed before the sync; a sync failure must not
        # remove the now-readable committed data.
        os.fsync(fd)

    def _snapshot_inventory(self, manifest, fd):
        from .registry import SNAPSHOT_NAME, MAX_SNAPSHOTS, MAX_SNAPSHOT_BYTES
        history = manifest.get('snapshotHistory', [])
        if not isinstance(history, list) or len(history) > MAX_SNAPSHOTS:
            raise ValueError('invalid snapshot history')
        trusted = {}
        for entry in history:
            if not isinstance(entry, dict):
                raise ValueError('invalid committed snapshot entry')
            snapshot = _valid_snapshot(entry.get('snapshot'))
            if snapshot in trusted:
                raise ValueError('duplicate committed snapshot')
            trusted[snapshot] = entry
        current = dict(snapshot=manifest['snapshot'], sha256=manifest['storage']['sha256'],
                       size=manifest['storage']['size'], at=None)
        if current['snapshot'] in trusted and any(trusted[current['snapshot']].get(key) != current[key]
                                                  for key in ('sha256', 'size')):
            raise ValueError('current snapshot hash conflicts with committed history')
        trusted.setdefault(current['snapshot'], current)
        names = sorted(n for n in os.listdir(fd) if SNAPSHOT_NAME.fullmatch(n))
        if len(names) > MAX_SNAPSHOTS:
            raise ValueError('snapshot quota exceeded')
        inventory = []
        for name in names:
            snapshot = name[len('snapshot_'):-len('.json')]
            data, raw = self._read_json(fd, name, MAX_SNAPSHOT_BYTES)
            digest = hashlib.sha256(raw).hexdigest()
            anchor = trusted.get(snapshot)
            if anchor and (anchor.get('sha256') != digest or anchor.get('size') != len(raw)):
                raise ValueError('historical snapshot hash/size mismatch')
            if not isinstance(data, dict) or not isinstance(data.get('records'), list):
                raise ValueError('invalid historical snapshot')
            if any(not isinstance(record, dict) or record.get('sourceId') != manifest['sourceId']
                   for record in data['records']):
                raise ValueError('historical snapshot source mismatch')
            inventory.append(dict(snapshot=snapshot, sha256=digest, size=len(raw),
                recordCount=len(data['records']), current=snapshot == manifest['snapshot'],
                at=anchor.get('at') if anchor else None,
                integrity='committed' if anchor else 'uncommitted',
                upstreamComplete=False, liveFetched=False))
        if set(trusted) - {entry['snapshot'] for entry in inventory}:
            raise ValueError('committed historical snapshot is missing')
        return inventory

    def list_snapshots(self, source_id):
        """List locally present versions; uncommitted/orphan files stay untrusted."""
        manifest, parts = self._locate(source_id)
        with self._directory(parts) as fd:
            return self._snapshot_inventory(manifest, fd)

    def _version_records(self, manifest, fd, snapshot):
        from .registry import MAX_SNAPSHOT_BYTES
        _valid_snapshot(snapshot)
        for entry in self._snapshot_inventory(manifest, fd):
            if entry['snapshot'] == snapshot:
                if entry['integrity'] != 'committed':
                    raise ValueError('snapshot has no committed hash anchor; cannot use as evidence')
                payload, _ = self._read_json(fd, 'snapshot_' + snapshot + '.json', MAX_SNAPSHOT_BYTES)
                return payload['records'], entry
        raise KeyError(snapshot)

    def list_record_versions(self, source_id, record_id):
        from .registry import RECORD_ID, _digest
        if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
            raise ValueError('invalid record ID')
        manifest, parts = self._locate(source_id)
        from .registry import MAX_SNAPSHOT_BYTES
        versions = []
        with self._directory(parts) as fd:
            for snapshot in self._snapshot_inventory(manifest, fd):
                if snapshot['integrity'] != 'committed':
                    continue
                data, _ = self._read_json(fd, 'snapshot_' + snapshot['snapshot'] + '.json', MAX_SNAPSHOT_BYTES)
                for record in data['records']:
                    if record['id'] == record_id:
                        versions.append(dict(sourceId=source_id, recordId=record_id,
                            nativeId=record['nativeId'], nativeVersion=record.get('nativeVersion'),
                            contentHash=record['contentHash'], recordHash=_digest(record), **snapshot))
        return versions

    def read_record_version(self, source_id, record_id, snapshot):
        from .registry import RECORD_ID
        if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
            raise ValueError('invalid record ID')
        _valid_snapshot(snapshot)
        manifest, parts = self._locate(source_id)
        with self._directory(parts) as fd:
            records, metadata = self._version_records(manifest, fd, snapshot)
            for record in records:
                if record['id'] == record_id:
                    return dict(record=record, snapshot=metadata, gaps=manifest['gaps'])
        raise KeyError(record_id)

    @staticmethod
    def _validate_mime(content, mime):
        checks = {
            'application/octet-stream': lambda b: True,
            'text/plain': lambda b: b'\x00' not in b and bool(b.decode('utf-8') or True),
            'application/pdf': lambda b: b.startswith(b'%PDF-'),
            'image/png': lambda b: b.startswith(b'\x89PNG\r\n\x1a\n'),
            'image/jpeg': lambda b: b.startswith(b'\xff\xd8\xff'),
            'image/gif': lambda b: b.startswith((b'GIF87a', b'GIF89a')),
            'image/webp': lambda b: b.startswith(b'RIFF') and b[8:12] == b'WEBP',
            'audio/wav': lambda b: b.startswith(b'RIFF') and b[8:12] == b'WAVE',
            'audio/ogg': lambda b: b.startswith(b'OggS'),
            'audio/mpeg': lambda b: b.startswith(b'ID3') or (len(b) > 1 and b[0] == 255 and b[1] & 224 == 224),
            'audio/mp4': lambda b: len(b) >= 12 and b[4:8] == b'ftyp',
            'video/mp4': lambda b: len(b) >= 12 and b[4:8] == b'ftyp',
        }
        if not isinstance(mime, str) or mime not in checks:
            raise ValueError('unsupported MIME; use a safe media type or application/octet-stream')
        try:
            valid = checks[mime](content)
        except UnicodeError as exc:
            raise ValueError('text/plain asset must be UTF-8') from exc
        if not valid:
            raise ValueError('asset bytes do not match declared MIME signature')

    def _asset(self, source_id, fd, asset_ref):
        digest = _asset_hash(asset_ref)
        metadata, _ = self._read_json(fd, digest + '.json', 16384)
        fields = {'schemaVersion', 'sourceId', 'assetRef', 'sha256', 'size', 'mime', 'name',
                  'at', 'localOnly', 'readingNature'}
        if (not isinstance(metadata, dict) or set(metadata) != fields or
                metadata.get('schemaVersion') != 1 or metadata.get('localOnly') is not True or
                metadata.get('sourceId') != source_id or
                metadata.get('assetRef') != asset_ref or metadata.get('sha256') != digest):
            raise ValueError('asset metadata identity mismatch')
        content = _read_bytes(fd, digest + '.blob', MAX_ASSET_BYTES)
        if hashlib.sha256(content).hexdigest() != digest or len(content) != metadata.get('size'):
            raise ValueError('asset hash/size mismatch')
        self._validate_mime(content, metadata.get('mime'))
        return dict(metadata=metadata, content=content)

    def list_assets(self, source_id):
        _, parts = self._locate(source_id)
        try:
            with self._directory(parts + ('assets',)) as fd:
                names = sorted(n for n in os.listdir(fd) if re.fullmatch(r'[a-f0-9]{64}\.json', n))
                if len(names) > MAX_ASSETS:
                    raise ValueError('asset quota exceeded')
                return [self._asset(source_id, fd, 'asset:' + n[:-5])['metadata'] for n in names]
        except FileNotFoundError:
            with self._directory(parts) as source_fd:
                if 'assets' in os.listdir(source_fd):
                    raise ValueError('committed asset bytes are missing')
            return []

    def put_asset(self, source_id, content, *, mime, name=None, expected_sha256=None):
        """Store bytes under one source/account. Never accepts a local input path."""
        from .registry import _string
        _, parts = self._locate(source_id)
        if not isinstance(content, bytes) or len(content) > MAX_ASSET_BYTES:
            raise ValueError('asset content must be at most 8MiB bytes')
        _string(name, 'asset name', 256)
        if name is not None and any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise ValueError('asset label must not contain control characters')
        self._validate_mime(content, mime)
        digest = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None and expected_sha256 != digest:
            raise ValueError('asset checksum mismatch')
        metadata = dict(schemaVersion=1, sourceId=source_id, assetRef='asset:' + digest,
                        sha256=digest, size=len(content), mime=mime, name=name, at=_now(),
                        localOnly=True, readingNature='stored_bytes_not_semantically_read')
        with self._directory(parts) as source_fd:
            fcntl.flock(source_fd, fcntl.LOCK_EX)
            try:
                with self._directory(parts + ('assets',), create=True) as fd:
                    names = os.listdir(fd)
                    if digest + '.json' in names:
                        old = self._asset(source_id, fd, metadata['assetRef'])['metadata']
                        if old['mime'] != mime:
                            raise ValueError('same asset bytes already stored with a different MIME')
                        return old
                    # Include uncommitted/orphan blobs in quota and fail closed on
                    # symlinks or unexpected nodes; failed writes cannot bypass it.
                    blobs = [n for n in names if re.fullmatch(r'[a-f0-9]{64}\.blob', n)]
                    sizes = [len(_read_bytes(fd, n, MAX_ASSET_BYTES)) for n in blobs]
                    if len(blobs) >= MAX_ASSETS or sum(sizes) + len(content) > MAX_ASSET_TOTAL:
                        raise ValueError('source asset quota reached')
                    blob = digest + '.blob'
                    created = False
                    committed = False
                    try:
                        if blob in names:
                            if _read_bytes(fd, blob, MAX_ASSET_BYTES) != content:
                                raise ValueError('orphan asset checksum mismatch')
                        else:
                            self._write_new(fd, blob, content)
                            created = True
                        self._atomic_json(fd, digest + '.json', metadata)
                        committed = True
                    except BaseException:
                        # _atomic_json can fail syncing after its rename. Keep a
                        # committed metadata/blob pair if the final entry exists.
                        try:
                            os.stat(digest + '.json', dir_fd=fd, follow_symlinks=False)
                            committed = True
                        except FileNotFoundError:
                            pass
                        if created and not committed:
                            os.unlink(blob, dir_fd=fd)
                        raise
                    return metadata
            finally:
                fcntl.flock(source_fd, fcntl.LOCK_UN)

    def get_asset(self, source_id, asset_ref):
        _asset_hash(asset_ref)
        _, parts = self._locate(source_id)
        try:
            with self._directory(parts + ('assets',)) as fd:
                return self._asset(source_id, fd, asset_ref)
        except FileNotFoundError as exc:
            raise KeyError(asset_ref) from exc

    @staticmethod
    def _record_ids(record_ids):
        from .registry import RECORD_ID
        if (not isinstance(record_ids, list) or not 1 <= len(record_ids) <= 100 or
                any(not isinstance(rid, str) or not RECORD_ID.fullmatch(rid) for rid in record_ids) or
                len(set(record_ids)) != len(record_ids)):
            raise ValueError('record_ids must contain 1-100 distinct stable record IDs')
        return record_ids

    def persist_read_receipt(self, source_id, snapshot, record_ids, *, media_reads=None):
        """Explicit write: record exact saved text delivered and optional byte reads.

        Media defaults to not_read even when its reference says readable=True.
        Explicit media_reads can name only managed assets attached to these rows.
        """
        from .registry import _digest, _json_bytes
        self._record_ids(record_ids)
        _valid_snapshot(snapshot)
        media_reads = [] if media_reads is None else media_reads
        if (not isinstance(media_reads, list) or len(media_reads) > 64 or
                any(not isinstance(ref, str) for ref in media_reads) or len(set(media_reads)) != len(media_reads)):
            raise ValueError('media_reads must be a distinct bounded asset reference list')
        for ref in media_reads:
            _asset_hash(ref)
        manifest, parts = self._locate(source_id)
        with self._directory(parts) as source_fd:
            fcntl.flock(source_fd, fcntl.LOCK_EX)
            try:
                manifest = self._manifest(source_fd)
                rows, metadata = self._version_records(manifest, source_fd, snapshot)
                selected = {r['id']: r for r in rows if r['id'] in record_ids}
                if len(selected) != len(record_ids):
                    raise KeyError('record ID absent from selected source snapshot')
                attached = {a['assetRef'] for row in selected.values() for a in row['attachments']}
                if set(media_reads) - attached:
                    raise ValueError('media read must refer to an attachment of selected records')
                items = []
                for rid in record_ids:
                    row = selected[rid]
                    media = []
                    for attachment in row['attachments']:
                        ref = attachment['assetRef']
                        asset = None
                        if ASSET_REF.fullmatch(ref):
                            try:
                                asset = self.get_asset(source_id, ref)
                            except KeyError:
                                pass
                        if ref in media_reads and asset is None:
                            raise ValueError('requested media bytes are unavailable locally')
                        info = dict(assetRef=ref, localAssetKnown=asset is not None,
                                    status='bytes_read' if ref in media_reads else 'not_read',
                                    declaredMetadata=attachment)
                        if asset:
                            info['localMetadata'] = asset['metadata']
                        if ref in media_reads:
                            info['sha256'] = hashlib.sha256(asset['content']).hexdigest()
                        media.append(info)
                    readable = row.get('readable', True)
                    items.append(dict(recordId=rid, nativeId=row['nativeId'],
                        contentHash=row['contentHash'], recordHash=_digest(row),
                        content=dict(text=row['text'], textHash=_digest(row['text']), readable=readable,
                            readingNature='saved_text' if readable else 'not_read',
                            missingReason=row.get('missingReason') if not readable else None), media=media))
                receipt = dict(schemaVersion=1, id='receipt_' + uuid.uuid4().hex,
                    sourceId=source_id, snapshot=snapshot, snapshotHash=metadata['sha256'],
                    at=_now(), operation='read_saved_record_versions', records=items,
                    upstreamComplete=False, liveFetched=False, gaps=manifest['gaps'],
                    meaning='local tool delivery and byte access; no semantic understanding asserted')
                receipt['receiptHash'] = _digest(receipt)
                payload = _json_bytes(receipt)
                if len(payload) > MAX_RECEIPT_BYTES:
                    raise ValueError('read receipt exceeds size limit')
                with self._directory(parts + ('receipts',), create=True) as fd:
                    names = [n for n in os.listdir(fd) if re.fullmatch(r'receipt_[a-f0-9]{32}\.json', n)]
                    if len(names) >= MAX_RECEIPTS:
                        raise ValueError('read receipt quota reached; preserve history before more writes')
                    total = sum(len(_read_bytes(fd, n, MAX_RECEIPT_BYTES)) for n in names)
                    if total + len(payload) > MAX_RECEIPT_TOTAL:
                        raise ValueError('read receipt storage quota reached')
                    self._write_new(fd, receipt['id'] + '.json', payload)
                    os.fsync(fd)
                return receipt
            finally:
                fcntl.flock(source_fd, fcntl.LOCK_UN)

    def read_read_receipt(self, source_id, receipt_id):
        from .registry import _digest
        _valid_receipt(receipt_id)
        manifest, parts = self._locate(source_id)
        try:
            with self._directory(parts + ('receipts',)) as fd:
                receipt, _ = self._read_json(fd, receipt_id + '.json', MAX_RECEIPT_BYTES)
        except FileNotFoundError as exc:
            raise KeyError(receipt_id) from exc
        fields = {'schemaVersion', 'id', 'sourceId', 'snapshot', 'snapshotHash', 'at', 'operation',
                  'records', 'upstreamComplete', 'liveFetched', 'gaps', 'meaning', 'receiptHash'}
        if (not isinstance(receipt, dict) or set(receipt) != fields or receipt.get('schemaVersion') != 1 or
                receipt.get('upstreamComplete') is not False or receipt.get('liveFetched') is not False or
                receipt.get('operation') != 'read_saved_record_versions' or
                receipt.get('sourceId') != source_id or receipt.get('id') != receipt_id or
                receipt.get('receiptHash') != _digest({k: v for k, v in receipt.items() if k != 'receiptHash'})):
            raise ValueError('invalid or modified read receipt')
        with self._directory(parts) as fd:
            rows, snapshot = self._version_records(manifest, fd, receipt.get('snapshot'))
        if receipt.get('snapshotHash') != snapshot['sha256']:
            raise ValueError('receipt snapshot mismatch')
        indexed = {row['id']: row for row in rows}
        if not isinstance(receipt.get('records'), list) or not 1 <= len(receipt['records']) <= 100:
            raise ValueError('invalid read receipt record evidence')
        seen = set()
        for item in receipt['records']:
            row = indexed.get(item.get('recordId')) if isinstance(item, dict) else None
            if row is None:
                raise ValueError('receipt contains an unknown record')
            readable = row.get('readable', True)
            expected_content = dict(text=row['text'], textHash=_digest(row['text']), readable=readable,
                readingNature='saved_text' if readable else 'not_read',
                missingReason=row.get('missingReason') if not readable else None)
            if (set(item) != {'recordId', 'nativeId', 'contentHash', 'recordHash', 'content', 'media'} or
                    item['recordId'] in seen or item.get('recordHash') != _digest(row) or
                    item.get('contentHash') != row['contentHash'] or item.get('nativeId') != row['nativeId'] or
                    item.get('content') != expected_content):
                raise ValueError('receipt does not match exact saved record content')
            seen.add(item['recordId'])
            if not isinstance(item.get('media'), list) or len(item['media']) != len(row['attachments']):
                raise ValueError('receipt attachment evidence mismatch')
            for media, attachment in zip(item['media'], row['attachments']):
                if (not isinstance(media, dict) or media.get('assetRef') != attachment['assetRef'] or
                        media.get('declaredMetadata') != attachment or
                        not isinstance(media.get('localAssetKnown'), bool) or
                        media.get('status') not in ('not_read', 'bytes_read')):
                    raise ValueError('invalid media receipt evidence')
                expected_fields = {'assetRef', 'localAssetKnown', 'status', 'declaredMetadata'}
                if media['localAssetKnown']:
                    expected_fields.add('localMetadata')
                    digest = _asset_hash(media['assetRef'])
                    local = media.get('localMetadata')
                    if (not isinstance(local, dict) or local.get('sourceId') != source_id or
                            local.get('assetRef') != media['assetRef'] or local.get('sha256') != digest):
                        raise ValueError('media receipt asset metadata mismatch')
                if media['status'] == 'bytes_read':
                    expected_fields.add('sha256')
                    if not media['localAssetKnown'] or media.get('sha256') != _asset_hash(media['assetRef']):
                        raise ValueError('media byte read has no exact managed hash')
                if set(media) != expected_fields:
                    raise ValueError('invalid media receipt fields')
        return receipt

    def list_read_receipts(self, source_id):
        _, parts = self._locate(source_id)
        try:
            with self._directory(parts + ('receipts',)) as fd:
                names = sorted(n for n in os.listdir(fd) if re.fullmatch(r'receipt_[a-f0-9]{32}\.json', n))
                if len(names) > MAX_RECEIPTS:
                    raise ValueError('read receipt quota exceeded')
            return sorted([self.read_read_receipt(source_id, n[:-5]) for n in names],
                          key=lambda r: (r['at'], r['id']))
        except FileNotFoundError:
            with self._directory(parts) as source_fd:
                if 'receipts' in os.listdir(source_fd):
                    raise ValueError('committed receipt history is missing')
            return []

    def get_checkpoints(self, source_id, consumer_id):
        from .registry import _identifier
        _identifier(consumer_id)
        _, parts = self._locate(source_id)
        try:
            with self._directory(parts + ('checkpoints',)) as fd:
                state, _ = self._read_json(fd, consumer_id + '.json', MAX_RECEIPT_BYTES)
        except FileNotFoundError:
            return dict(schemaVersion=1, sourceId=source_id, consumerId=consumer_id, revision=0,
                        stages=dict(retrieved=None, read=None, applied=None), history=[], upstreamComplete=False)
        fields = {'schemaVersion', 'sourceId', 'consumerId', 'revision', 'stages', 'history', 'upstreamComplete'}
        if (not isinstance(state, dict) or set(state) != fields or
                state.get('upstreamComplete') is not False or state.get('schemaVersion') != 1 or
                state.get('sourceId') != source_id or state.get('consumerId') != consumer_id or
                not isinstance(state.get('revision'), int) or isinstance(state['revision'], bool) or
                not isinstance(state.get('history'), list) or len(state['history']) != state['revision'] or
                len(state['history']) > MAX_CHECKPOINT_EVENTS or
                not isinstance(state.get('stages'), dict) or set(state['stages']) != {'retrieved', 'read', 'applied'}):
            raise ValueError('invalid consumer checkpoint state')
        from .registry import _time
        last = dict(retrieved=None, read=None, applied=None)
        event_fields = {'stage', 'snapshot', 'snapshotHash', 'recordIds', 'recordHashes',
                        'receiptIds', 'at', 'acknowledgment'}
        for event in state['history']:
            if (not isinstance(event, dict) or set(event) != event_fields or
                    event.get('stage') not in ('retrieved', 'read', 'applied')):
                raise ValueError('invalid checkpoint event fields')
            _valid_snapshot(event['snapshot'])
            _time(event['at'])
            ids = self._record_ids(event['recordIds'])
            hashes = event['recordHashes']
            if (not isinstance(hashes, dict) or set(hashes) != set(ids) or
                    not isinstance(event['snapshotHash'], str) or
                    not re.fullmatch(r'[a-f0-9]{64}', event['snapshotHash']) or
                    any(not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value)
                        for value in hashes.values())):
                raise ValueError('invalid checkpoint record hash evidence')
            receipts = event['receiptIds']
            if (not isinstance(receipts, list) or len(receipts) > 100 or
                    any(not isinstance(rid, str) for rid in receipts) or len(set(receipts)) != len(receipts)):
                raise ValueError('invalid checkpoint receipt evidence')
            for rid in receipts:
                _valid_receipt(rid)
            ack = event['acknowledgment']
            if event['stage'] == 'applied':
                if (not isinstance(ack, dict) or set(ack) - {'operationRef', 'detail'} or
                        not isinstance(ack.get('operationRef'), str) or not 1 <= len(ack['operationRef']) <= 512 or
                        not isinstance(ack.get('detail', ''), str) or len(ack.get('detail', '')) > 2000):
                    raise ValueError('invalid downstream acknowledgment')
            elif ack is not None:
                raise ValueError('unexpected downstream acknowledgment')
            if (event['stage'] == 'retrieved' and receipts) or (event['stage'] != 'retrieved' and not receipts):
                raise ValueError('checkpoint stage and receipts disagree')
            last[event['stage']] = event
        if state['stages'] != last:
            raise ValueError('checkpoint stage projection disagrees with history')
        return state

    def advance_checkpoint(self, source_id, consumer_id, stage, *, expected_revision,
                           snapshot, record_ids, receipt_ids=None, acknowledgment=None):
        """CAS write with exact snapshot evidence and explicit applied operation ref."""
        from .registry import _identifier, _digest, _json_bytes
        _identifier(consumer_id)
        if stage not in ('retrieved', 'read', 'applied'):
            raise ValueError('checkpoint stage must be retrieved, read or applied')
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError('expected_revision must be a nonnegative integer')
        _valid_snapshot(snapshot)
        self._record_ids(record_ids)
        receipt_ids = [] if receipt_ids is None else receipt_ids
        if (not isinstance(receipt_ids, list) or len(receipt_ids) > 100 or
                any(not isinstance(rid, str) for rid in receipt_ids) or len(set(receipt_ids)) != len(receipt_ids)):
            raise ValueError('receipt_ids must be a bounded distinct list')
        for rid in receipt_ids:
            _valid_receipt(rid)
        if stage == 'applied':
            if (not isinstance(acknowledgment, dict) or set(acknowledgment) - {'operationRef', 'detail'} or
                    not isinstance(acknowledgment.get('operationRef'), str) or
                    not 1 <= len(acknowledgment['operationRef']) <= 512 or
                    not isinstance(acknowledgment.get('detail', ''), str) or
                    len(acknowledgment.get('detail', '')) > 2000):
                raise ValueError('applied requires explicit downstream acknowledgment with operationRef')
        elif acknowledgment is not None:
            raise ValueError('only applied accepts a downstream acknowledgment')
        manifest, parts = self._locate(source_id)
        with self._directory(parts) as source_fd:
            fcntl.flock(source_fd, fcntl.LOCK_EX)
            try:
                manifest = self._manifest(source_fd)
                state = self.get_checkpoints(source_id, consumer_id)
                if state['revision'] != expected_revision:
                    raise CheckpointConflictError('checkpoint revision conflict')
                if len(state['history']) >= MAX_CHECKPOINT_EVENTS:
                    raise ValueError('checkpoint event quota reached; preserve history before more writes')
                rows, metadata = self._version_records(manifest, source_fd, snapshot)
                indexed = {r['id']: r for r in rows}
                if set(record_ids) - set(indexed):
                    raise KeyError('record ID absent from selected source snapshot')
                records = {rid: _digest(indexed[rid]) for rid in record_ids}
                if stage != 'retrieved':
                    previous = 'retrieved' if stage == 'read' else 'read'
                    evidence = {}
                    for event in state['history']:
                        if event['stage'] == previous and event['snapshot'] == snapshot:
                            evidence.update(event['recordHashes'])
                    if any(evidence.get(rid) != digest for rid, digest in records.items()):
                        raise ValueError('checkpoint requires matching prior ' + previous + ' evidence')
                    receipt_evidence = {}
                    for rid in receipt_ids:
                        receipt = self.read_read_receipt(source_id, rid)
                        if receipt['snapshot'] != snapshot or receipt['snapshotHash'] != metadata['sha256']:
                            raise ValueError('read receipt belongs to a different snapshot')
                        receipt_evidence.update({r['recordId']: r['recordHash'] for r in receipt['records']
                                                 if r['content']['readable']})
                    if any(receipt_evidence.get(rid) != digest for rid, digest in records.items()):
                        raise ValueError('checkpoint requires exact persisted readable-content receipts')
                elif receipt_ids:
                    raise ValueError('retrieved uses snapshot evidence, not read receipts')
                event = dict(stage=stage, snapshot=snapshot, snapshotHash=metadata['sha256'],
                             recordIds=list(record_ids), recordHashes=records, receiptIds=list(receipt_ids),
                             at=_now(), acknowledgment=acknowledgment)
                state['history'].append(event)
                state['revision'] += 1
                state['stages'][stage] = event
                if len(_json_bytes(state)) > MAX_RECEIPT_BYTES:
                    raise ValueError('checkpoint storage quota reached')
                with self._directory(parts + ('checkpoints',), create=True) as fd:
                    if len(os.listdir(fd)) >= 128 and consumer_id + '.json' not in os.listdir(fd):
                        raise ValueError('consumer checkpoint quota reached')
                    self._atomic_json(fd, consumer_id + '.json', state)
                return state
            finally:
                fcntl.flock(source_fd, fcntl.LOCK_UN)
