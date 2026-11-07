"""SOURCE storage: immutable snapshots plus an atomically replaced manifest.

Untrusted IDs never become paths. Directory handles and O_NOFOLLOW keep every
managed operation inside the explicitly selected workspace, including on failure.
"""
import base64
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from .tools import SourceToolsMixin

IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
RECORD_ID = re.compile(r'rec_[a-f0-9]{40}\Z')
SNAPSHOT_NAME = re.compile(r'snapshot_[a-f0-9]{32}\.json\Z')
MAX_RECORD_BYTES = 256 * 1024
MAX_BATCH_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 10000
MAX_SNAPSHOTS = 16
CAPABILITIES = {'query': ['start', 'end', 'keyword', 'conversation', 'sender', 'content_type'],
                'read': ['saved_text', 'attachment_references'], 'import': True, 'liveRefresh': False}
BASE_GAPS = [dict(code='live_not_connected', detail='只读取已保存资料，未连接实时上游适配器。'),
             dict(code='upstream_coverage_unknown', detail='导入记录清单不证明上游完整覆盖。')]


def _json_bytes(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise ValueError('must be finite, bounded JSON data') from exc


def _digest(value):
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError('source type/account must use 1-64 ASCII letters, digits, underscore or hyphen')
    return value


def _source_id(value):
    if not isinstance(value, str) or value.count(':') != 1:
        raise ValueError('invalid source ID')
    parts = value.split(':')
    return tuple(_identifier(p) for p in parts)


def _time(value, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('time must be ISO date or timezone-aware ISO datetime')
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            # Date-only filtering uses Beijing midnight; original precision is retained.
            return datetime.fromisoformat(value + 'T00:00:00+08:00')
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or 'T' not in value:
            raise ValueError()
        return parsed
    except ValueError as exc:
        raise ValueError('time must be ISO date or timezone-aware ISO datetime') from exc


def _string(value, field, maximum=1000, nullable=True):
    if nullable and value is None:
        return value
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError(field + ' must be bounded text')
    return value


def _record(value, sid):
    allowed = {'nativeId', 'nativeRecordId', 'at', 'sender', 'conversation', 'text', 'type',
               'attachments', 'locator', 'nativeVersion', 'originalLabel', 'sourceTime',
               'readable', 'missingReason', 'readingNature', 'provenance'}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ValueError('invalid record fields; task judgments and paths are not record fields')
    native = value.get('nativeId', value.get('nativeRecordId'))
    if not isinstance(native, str) or not native or len(native) > 1000:
        raise ValueError('record nativeId is required; use an explicit import ID if unavailable')
    if 'nativeRecordId' in value and value['nativeRecordId'] != native:
        raise ValueError('native identifiers conflict')
    result = dict(value)
    result.pop('nativeRecordId', None)
    result['nativeId'] = native
    result['sourceId'] = sid
    result['id'] = 'rec_' + _digest([sid, native])[:40]
    result['at'] = value.get('at')
    _time(result['at'], optional=True)
    for field in ['sender', 'conversation']:
        result[field] = _string(value.get(field), field)
    result['text'] = _string(value.get('text', ''), 'text', MAX_RECORD_BYTES, nullable=False)
    result['type'] = _string(value.get('type', 'text'), 'type', 64, nullable=False)
    if not result['type']:
        raise ValueError('record type cannot be empty')
    attachments = value.get('attachments', [])
    if not isinstance(attachments, list) or len(attachments) > 64:
        raise ValueError('attachments must be a bounded list of references')
    attachment_fields = {'assetRef', 'name', 'type', 'mime', 'size', 'sha256', 'readable',
                         'missingReason', 'readingNature'}
    for attachment in attachments:
        if not isinstance(attachment, dict) or set(attachment) - attachment_fields:
            raise ValueError('attachments accept references, never filesystem paths')
        ref = attachment.get('assetRef')
        if not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9:_.-]{0,255}', ref):
            raise ValueError('invalid assetRef')
        if '..' in ref:
            raise ValueError('invalid assetRef')
        if 'readable' in attachment and not isinstance(attachment['readable'], bool):
            raise ValueError('attachment readable must be boolean')
    result['attachments'] = attachments
    if 'readable' in value and not isinstance(value['readable'], bool):
        raise ValueError('readable must be boolean')
    for field in ['locator', 'provenance', 'sourceTime']:
        if field in value and not isinstance(value[field], (dict, str, type(None))):
            raise ValueError(field + ' must be an inert JSON object or text')
    if len(_json_bytes(result)) > MAX_RECORD_BYTES:
        raise ValueError('record exceeds 256 KiB')
    result['contentHash'] = _digest(value)
    return result


class SourceRegistry(SourceToolsMixin):
    """Read-only construction; import and persisted-tool writes are explicit.

    Source/account IDs are stable and separate from physical directory names.
    list/query/read never access credential storage or arbitrary source paths.
    """
    def __init__(self, workspace):
        if not workspace:
            raise ValueError('explicit workspace is required')
        supplied = Path(os.path.abspath(os.fspath(workspace)))
        if supplied.is_symlink():
            raise ValueError('workspace itself must not be a symlink')
        # macOS exposes /var as a system symlink. Resolve the caller-selected
        # parent once; all managed descendants are still opened without following.
        self.workspace = supplied.parent.resolve() / supplied.name

    @contextmanager
    def _directory(self, parts=(), *, create=False):
        # Walk from / via no-follow directory handles, rather than resolving a
        # symlink and trusting a string prefix. No race can replace held parents.
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in self.workspace.parts[1:] + tuple(parts):
                if part in ('', '.', '..') or '/' in part:
                    raise ValueError('unsafe path component')
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                try:
                    next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                except OSError as exc:
                    if isinstance(exc, FileNotFoundError):
                        raise
                    raise ValueError('managed directory must not be a symlink or non-directory') from exc
                os.close(fd)
                fd = next_fd
            yield fd
        finally:
            os.close(fd)

    def _read_json(self, fd, name, maximum):
        if '/' in name or name in ('.', '..'):
            raise ValueError('invalid managed filename')
        try:
            opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise ValueError('managed file must not be a symlink') from exc
        with os.fdopen(opened, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
                raise ValueError('managed file must be a bounded regular file')
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise ValueError('managed file exceeds size limit')
        try:
            return json.loads(payload), payload
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ValueError('invalid managed JSON') from exc

    def _manifest(self, fd):
        manifest, _ = self._read_json(fd, 'source.json', MAX_BATCH_BYTES)
        if not isinstance(manifest, dict) or manifest.get('schemaVersion') != 1:
            raise ValueError('invalid source manifest')
        _source_id(manifest.get('sourceId'))
        if manifest.get('sourceId') != manifest.get('sourceType', '') + ':' + manifest.get('accountId', ''):
            raise ValueError('source identity mismatch')
        return manifest

    def _manifests(self):
        found = []
        try:
            with self._directory(('sources',)) as root_fd:
                names = sorted(os.listdir(root_fd))
                if len(names) > 256:
                    raise ValueError('too many source directories')
                for source_dir in names:
                    _identifier(source_dir)
                    with self._directory(('sources', source_dir)) as source_fd:
                        accounts = sorted(os.listdir(source_fd))
                    if len(accounts) > 256:
                        raise ValueError('too many account directories')
                    for account_dir in accounts:
                        _identifier(account_dir)
                        with self._directory(('sources', source_dir, account_dir)) as account_fd:
                            try:
                                manifest = self._manifest(account_fd)
                            except FileNotFoundError:
                                continue  # Failed first import has no committed source.
                        found.append((manifest, ('sources', source_dir, account_dir)))
        except FileNotFoundError:
            return []
        ids = [m['sourceId'] for m, _ in found]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate source identity')
        return found

    def _locate(self, sid):
        _source_id(sid)
        for manifest, parts in self._manifests():
            if manifest['sourceId'] == sid:
                return manifest, parts
        raise KeyError(sid)

    def _snapshot(self, manifest, fd):
        storage = manifest.get('storage', {})
        name = storage.get('path', '')
        if not isinstance(name, str) or not SNAPSHOT_NAME.fullmatch(name):
            raise ValueError('unsafe snapshot reference')
        data, raw = self._read_json(fd, name, MAX_SNAPSHOT_BYTES)
        if hashlib.sha256(raw).hexdigest() != storage.get('sha256') or len(raw) != storage.get('size'):
            raise ValueError('snapshot hash/size mismatch')
        if not isinstance(data, dict) or not isinstance(data.get('records'), list) or len(data['records']) > MAX_RECORDS:
            raise ValueError('invalid snapshot')
        for record in data['records']:
            if not isinstance(record, dict) or record.get('sourceId') != manifest['sourceId']:
                raise ValueError('snapshot source mismatch')
        return data['records']

    def list_sources(self):
        return [dict(id=m['sourceId'], type=m['sourceType'], accountId=m['accountId'],
                     displayName=m['displayName'], status='cached_only', capabilities=m['capabilities'],
                     coverage=m['coverage'], gaps=m['gaps']) for m, _ in self._manifests()]

    def import_records(self, source_type, account_id, records, *, display_name=None,
                       gaps=None, coverage=None):
        """Explicit atomic import of at most 1000 records/8MiB; no file acquisition.

        Exact repeats are idempotent. A changed native ID version replaces the
        current projection while previous immutable snapshots remain inspectable.
        """
        source_type, account_id = _identifier(source_type), _identifier(account_id)
        sid = source_type + ':' + account_id
        _string(display_name, 'display_name', 256)
        if not isinstance(records, list) or len(records) > 1000:
            raise ValueError('records must be a list of at most 1000 records')
        if len(_json_bytes(records)) > MAX_BATCH_BYTES:
            raise ValueError('import exceeds 8 MiB')
        normalized = [_record(value, sid) for value in records]
        if len({r['id'] for r in normalized}) != len(normalized):
            raise ValueError('duplicate nativeId within one import')
        if gaps is not None and (not isinstance(gaps, list) or len(_json_bytes(gaps)) > 16384):
            raise ValueError('gaps must be a bounded list')
        if coverage is not None and (not isinstance(coverage, dict) or len(_json_bytes(coverage)) > 16384):
            raise ValueError('coverage must be a bounded declaration')
        try:
            _, parts = self._locate(sid)
        except KeyError:
            parts = ('sources', source_type, account_id)
        with self._directory(parts, create=True) as fd:
            # The account-directory inode is the lock, so read-only calls need
            # no lockfile and readers always see a complete atomic manifest.
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                try:
                    previous = self._manifest(fd)
                except FileNotFoundError:
                    previous = None
                if previous is None:
                    existing = []
                else:
                    if previous['sourceId'] != sid:
                        raise ValueError('source directory identity conflict')
                    existing = self._snapshot(previous, fd)
                indexed = {r['id']: r for r in existing}
                added = updated = unchanged = 0
                for record in normalized:
                    old = indexed.get(record['id'])
                    if old is None:
                        added += 1
                    elif old['contentHash'] == record['contentHash']:
                        unchanged += 1
                    else:
                        updated += 1
                    indexed[record['id']] = record
                if len(indexed) > MAX_RECORDS:
                    raise ValueError('source exceeds 10000 records')
                snapshot = uuid.uuid4().hex
                receipt = dict(id='import_' + uuid.uuid4().hex, sourceId=sid, operation='import_saved_records',
                               at=datetime.now(timezone.utc).isoformat(), importedCount=added,
                               updatedCount=updated, unchangedCount=unchanged, snapshot=snapshot,
                               recordIds=[r['id'] for r in normalized], liveFetched=False)
                if previous is not None and not added and not updated and gaps is None and coverage is None and display_name is None:
                    receipt['snapshot'] = previous['snapshot']
                    return receipt
                payload = _json_bytes({'records': list(indexed.values())})
                if len(payload) > MAX_SNAPSHOT_BYTES:
                    raise ValueError('source snapshot exceeds 16 MiB')
                snapshot_files = [n for n in os.listdir(fd) if SNAPSHOT_NAME.fullmatch(n)]
                if len(snapshot_files) >= MAX_SNAPSHOTS:
                    raise ValueError('source snapshot quota reached; preserve/archive outside this module before more imports')
                own_gaps = list(BASE_GAPS) + (gaps or [])
                if any(r['at'] is None for r in indexed.values()):
                    own_gaps.append(dict(code='unknown_record_time', detail='部分原记录无时间，时间过滤不会包含这些记录。'))
                if any(r['attachments'] for r in indexed.values()):
                    own_gaps.append(dict(code='media_not_read', detail='仅保存附件引用，未读取或验证媒体内容。'))
                name = 'snapshot_' + snapshot + '.json'
                manifest = dict(schemaVersion=1, sourceId=sid, sourceType=source_type, accountId=account_id,
                                displayName=display_name or (previous or {}).get('displayName') or sid,
                                capabilities=CAPABILITIES, authRef=None, status='cached_only', snapshot=snapshot,
                                storage=dict(path=name, sha256=hashlib.sha256(payload).hexdigest(), size=len(payload),
                                             externalReferences=sorted({a['assetRef'] for r in indexed.values() for a in r['attachments']})),
                                coverage=dict(kind='explicit_record_ids', recordCount=len(indexed),
                                              recordIds=list(indexed), upstreamComplete=False,
                                              declaredCoverage=coverage), gaps=own_gaps,
                                receipts=((previous or {}).get('receipts', []) + [receipt])[-16:])
                # Commit immutable historical hash anchors along with the latest projection.
                # Older unindexed files are never promoted into trusted history.
                history = list((previous or {}).get('snapshotHistory', []))
                if previous and not any(h.get('snapshot') == previous['snapshot'] for h in history):
                    history.append(dict(snapshot=previous['snapshot'], sha256=previous['storage']['sha256'],
                                        size=previous['storage']['size'], at=None))
                history.append(dict(snapshot=snapshot, sha256=manifest['storage']['sha256'],
                                    size=manifest['storage']['size'], at=receipt['at']))
                manifest['snapshotHistory'] = history
                temp_name = 'manifest_' + uuid.uuid4().hex + '.tmp'
                created = []
                committed = False
                try:
                    self._write_new(fd, name, payload)
                    created.append(name)
                    self._write_new(fd, temp_name, _json_bytes(manifest))
                    created.append(temp_name)
                    os.replace(temp_name, 'source.json', src_dir_fd=fd, dst_dir_fd=fd)
                    created.remove(temp_name)
                    committed = True
                    os.fsync(fd)
                except BaseException:
                    for item in ([] if committed else created):
                        try:
                            os.unlink(item, dir_fd=fd)
                        except FileNotFoundError:
                            pass
                    raise
                return receipt
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)

    @staticmethod
    def _write_new(fd, name, payload):
        opened = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(opened, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            os.unlink(name, dir_fd=fd)
            raise

    def query(self, source_id, start=None, end=None, keyword=None, conversation=None,
              sender=None, content_type=None, limit=100, cursor=None):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError('limit must be 1-500')
        start_time, end_time = _time(start, optional=True), _time(end, optional=True)
        if start_time is not None and end_time is not None and start_time >= end_time:
            raise ValueError('start must be before end; end is exclusive')
        for field, value in [('keyword', keyword), ('conversation', conversation),
                             ('sender', sender), ('content_type', content_type)]:
            _string(value, field)
        manifest, parts = self._locate(source_id)
        with self._directory(parts) as fd:
            records = self._snapshot(manifest, fd)
        filters = dict(start=start, end=end, keyword=keyword, conversation=conversation,
                       sender=sender, content_type=content_type, limit=limit)
        signature = _digest([source_id, manifest['snapshot'], filters])
        offset = 0
        if cursor is not None:
            if not isinstance(cursor, str) or len(cursor) > 512 or not re.fullmatch(r'[A-Za-z0-9_-]+', cursor):
                raise ValueError('invalid cursor')
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
                offset = decoded['offset']
                if decoded['signature'] != signature or isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
                    raise ValueError()
            except (KeyError, ValueError, TypeError, UnicodeError) as exc:
                raise ValueError('cursor does not match this query/snapshot') from exc
        matched = []
        for record in records:
            at = _time(record['at'], optional=True)
            if (start_time is not None or end_time is not None) and at is None:
                continue
            if start_time is not None and at < start_time:
                continue
            if end_time is not None and at >= end_time:
                continue
            if keyword is not None and keyword.casefold() not in record['text'].casefold():
                continue
            if any(value is not None and record[field] != value for field, value in
                   [('conversation', conversation), ('sender', sender), ('type', content_type)]):
                continue
            matched.append(record)
        matched.sort(key=lambda r: (r['at'] is None, _time(r['at'], optional=True) or datetime.max.replace(tzinfo=timezone.utc), r['id']))
        if offset > len(matched):
            raise ValueError('cursor offset exceeds query results')
        page = matched[offset:offset + limit]
        next_cursor = None
        if offset + len(page) < len(matched):
            next_cursor = base64.urlsafe_b64encode(_json_bytes(dict(signature=signature, offset=offset + len(page)))).decode().rstrip('=')
        receipt = dict(operation='query_saved_records', sourceId=source_id, snapshot=manifest['snapshot'],
                       queryRange=dict(start=start, end=end, startInclusive=True, endExclusive=True,
                                       dateOnlyTimezone='Asia/Shanghai'), filters=filters,
                       pageReceipt=dict(offset=offset, returned=len(page), nextCursor=next_cursor),
                       fetchedCursor=None, liveFetched=False, upstreamComplete=False,
                       queryCompleteWithinSnapshot=next_cursor is None,
                       contentReadCoverage=dict(kind='explicit_record_ids', recordIds=[r['id'] for r in page],
                                                readingNature='saved_text'),
                       mediaReadCoverage=dict(recordIds=[], readingNature='not_read'))
        return dict(records=page, nextCursor=next_cursor, receipt=receipt, gaps=manifest['gaps'])

    def read(self, source_id, record_id):
        if not isinstance(record_id, str) or not RECORD_ID.fullmatch(record_id):
            raise ValueError('invalid record ID')
        manifest, parts = self._locate(source_id)
        with self._directory(parts) as fd:
            records = self._snapshot(manifest, fd)
        for record in records:
            if record['id'] == record_id:
                return record
        raise KeyError(record_id)
