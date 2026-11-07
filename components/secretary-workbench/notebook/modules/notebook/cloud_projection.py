"""Explicit, local-only generation/import of a minimal private cloud notebook.

This component owns its storage access with NotebookService. It never copies a
native DB/source JSON, opens media, reads credentials, calls a model, or uploads.
Only current task meaning and audited human notes cross the boundary. All source
evidence and original history remain on Mac; cloud events explicitly say so.
"""
import copy
import hashlib
import html
import json
import os
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

from contracts import DOMAINS, KINDS, STATES, actor, day, state
from .legacy_store import ValidationError, stamp, strict_json, validate_id
from .service import NotebookService

VERSION = 1
MAX_BUNDLE = 32 * 1024 * 1024
PLACEHOLDER = '原文保留Mac，线上仅保存事项摘要。'
EVIDENCE = {'label': '原文保留Mac', 'quote': PLACEHOLDER, 'localOnly': True}
MARKER = {'version': VERSION, 'localOnly': True, 'historyComplete': False, 'sourcePolicy': 'local-only'}
TEXT_FIELDS = {'title': 1000, 'summary': 12000, 'assignee': 120, 'counterparty': 500,
               'timeRequirement': 1000, 'condition': 2000, 'completionCriterion': 2000}
VALUE_FIELDS = {'id', 'kind', 'domain', 'state', 'selectedState', 'proposedAt', 'deadlineDate',
                'planDate', 'reviewDate', 'planDateExplicit', 'needsReview', 'revision', 'active',
                'recommendation', 'relatedRecordIds'}
OBJECT_FIELDS = set(TEXT_FIELDS) | VALUE_FIELDS | {'legacy', 'importedLegacyPlanning', 'evidence',
    'sourceContacts', 'cloudProjection', 'cloudProjectionTimeline', 'cloudProjectionHistory'}
CONTACT_FIELDS = {'channel', 'conversationName', 'senderName', 'conversation', 'sender',
                  'at', 'time', 'sourceTime', 'nativeId', 'recordId', 'sourceId'}
EVENT_FIELDS = {'id', 'at', 'actor', 'author', 'body', 'note', 'changes', 'previous', 'sources',
                'localOnly', 'historyComplete', 'state', 'sourceTime', 'suggestedState', 'reminder'}
CHANGE_FIELDS = set(TEXT_FIELDS) | (VALUE_FIELDS - {'id', 'revision'})
RECORD_FIELDS = {'id', 'text', 'objectIds', 'attachments', 'actor', 'at', 'processing',
                 'receipts', 'sourceRefs', 'localOnly'}
AUDIT_FIELDS = {'version', 'createdAt', 'objectCount', 'recordCount', 'ids', 'bundleSha256',
                'sourceFingerprintCount', 'sourceFingerprintSha256', 'sourceEchoAuditPassed',
                'sourcePolicy', 'historyComplete', 'historyEventCount', 'excluded'}
_HOSTILE = re.compile(
    r'<\s*(?:[a-zA-Z!/?]|!\[CDATA)|(?:^|\n)\s*>\s|'
    r'(?:原文|逐字稿|完整转写|引用)\s*[:：]|'
    r'\b(?:authorization|bearer|aeskey|cdnthumburl|cdnurl|filekey|decryptkey)\b|'
    r'\b(?:api[_ -]?key|secret|(?:access[_ -]?)?token|password|passwd|cookie|csrf)\s*[=:]|'
    r'(?:密钥|密码|令牌)\s*[:：=]|\bsk-(?:proj-|svcacct-)?[a-zA-Z0-9_-]{16,}|'
    r'\b(?:ghp_|github_pat_)[a-zA-Z0-9_]{16,}|'
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----|'
    r'https?://|file://|[a-zA-Z]:[\\/]|'
    r'(?:^|[\s\"\x27(（])/(?:[a-zA-Z_.][^\s，。；、]*)|'
    r'[「『“][^」』”]{8,}[」』”]', re.I)
_CREDENTIAL_VALUE = re.compile(r'\bsk-(?:proj-|svcacct-)?[a-zA-Z0-9_-]{16,}|\b(?:ghp_|github_pat_)[a-zA-Z0-9_]{16,}', re.I)
_ID_FIELDS = {'id', 'ids', 'objectIds', 'relatedRecordIds'}


def _normal(value):
    return ''.join(c.lower() for c in html.unescape(str(value)) if c.isalnum())


def _hostile(value):
    if '\x00' in value or any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        return True
    decoded = value
    for _ in range(3):
        decoded = html.unescape(unquote(decoded))
    return bool(_HOSTILE.search(decoded))


def _safe_time(value, boundary, rid, field, unknown=False):
    if value is None or (unknown and value == '待核实'):
        return value
    try:
        if not isinstance(value, str) or len(value) > 60:
            raise ValueError()
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value
    except (TypeError, ValueError):
        boundary.excluded[(rid, field, 'invalid-time')] += 1
        return None


class _Boundary:
    """Source fingerprints stay in memory; audit contains hashes/counts only."""
    def __init__(self):
        self.quotes = set()
        self.shingles = set()
        self.short = set()
        self.excluded = Counter()

    def add(self, value):
        if not isinstance(value, str):
            return
        value = _normal(value)
        if len(value) < 4:
            return
        self.quotes.add(value)
        if len(value) < 12:
            self.short.add(value)
        else:
            self.shingles.update(value[i:i+12] for i in range(len(value)-11))

    def scan(self, obj, source=False):
        if isinstance(obj, list):
            for v in obj:
                self.scan(v, source)
        elif isinstance(obj, dict):
            for k, v in obj.items():
                if k in ('quote', 'transcript', 'rawText', 'originalText') and isinstance(v, str):
                    self.add(v)
                elif source and k in ('text', 'content', 'body') and isinstance(v, str):
                    self.add(v)
                self.scan(v, source or k in ('evidence', 'sources', 'sourceEvidence'))

    def echo(self, value):
        norm = _normal(value)
        return any(s in norm for s in self.short) or any(norm[i:i+12] in self.shingles for i in range(len(norm)-11))

    def text(self, value, rid, field, fallback=''):
        value = value if isinstance(value, str) else ''
        why = 'unsafe-text' if _hostile(value) else 'source-echo' if self.echo(value) else None
        if why:
            self.excluded[(rid, field, why)] += 1
            return fallback
        return value


def _path(value):
    path = Path(value).expanduser().absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValidationError('云投影路径不能含符号链接')
    return path


def _contacts(values, boundary, rid):
    result = []
    for contact in values or []:
        if not isinstance(contact, dict):
            continue
        safe = {}
        for k in CONTACT_FIELDS:
            v = contact.get(k)
            limit = 160 if k in ('nativeId', 'recordId', 'sourceId') else 120
            if isinstance(v, str) and len(v) <= limit and not _hostile(v) and not boundary.echo(v):
                # Contact names are necessary locators, not source text bodies.
                if k in ('nativeId', 'recordId', 'sourceId') and not re.fullmatch(r'[\w:.-]{1,160}', v):
                    continue
                safe[k] = v
        if safe and safe not in result:
            result.append(safe)
    return result


def _patch(values, boundary, rid):
    result = {}
    if not isinstance(values, dict):
        return result
    for key in CHANGE_FIELDS:
        if key not in values:
            continue
        value = values[key]
        if key in TEXT_FIELDS:
            value = boundary.text(value, rid, 'history.' + key)
        elif key == 'proposedAt':
            value = _safe_time(value, boundary, rid, 'history.proposedAt', unknown=True)
        elif key == 'recommendation' and isinstance(value, dict):
            value = {'state': value.get('state'), 'reason': boundary.text(value.get('reason'), rid, 'history.recommendation')}
        result[key] = copy.deepcopy(value)
    return result


def _event(event, boundary, rid, index):
    a = event.get('actor') or {'name': event.get('author') or '我', 'kind': 'human'}
    a = actor(a)
    a['name'] = boundary.text(a['name'], rid, 'actor', '我' if a['kind'] == 'human' else 'AI')
    changes = event.get('changes') if isinstance(event.get('changes'), dict) else event
    changes = _patch(changes, boundary, rid)
    original_note = event.get('note') or event.get('body') or ''
    if a['kind'] == 'human':
        note = boundary.text(original_note, rid, 'human-note', PLACEHOLDER)
    else:
        note = 'AI操作已记录；原始进展及依据保留Mac。'
        if original_note:
            boundary.excluded[(rid, 'ai-note', 'operational-summary')] += 1
    result = {'id': str(event.get('id') or 'history-' + str(index)), 'at': event.get('at'),
        'actor': a, 'author': a['name'], 'body': note, 'note': note,
        'changes': changes, 'previous': _patch(event.get('previous', {}), boundary, rid),
        'sources': [dict(EVIDENCE)] if event.get('sources') else [], 'localOnly': True, 'historyComplete': False}
    for k in ('state', 'suggestedState'):
        if k in event:
            result[k] = event[k]
    if event.get('sourceTime'):
        result['sourceTime'] = _safe_time(event['sourceTime'], boundary, rid, 'history.sourceTime')
    if isinstance(event.get('reminder'), dict):
        reminder = event['reminder']
        result['reminder'] = {k: _safe_time(reminder.get(k), boundary, rid, 'history.reminder.' + k) for k in ('at', 'firedAt')}
        for k in ('kind', 'timezone'):
            if k in reminder:
                result['reminder'][k] = boundary.text(reminder[k], rid, 'history.reminder.' + k)
    return result


def _scan_private_sources(port, boundary):
    """Read only via the notebook owner's connection; no source files/media."""
    if not hasattr(port, '_connect'):
        return
    with port._connect() as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ('tasks', 'source_versions', 'progress_updates', 'notebook_events', 'local_objects', 'local_changes'):
            if table not in tables:
                continue
            for row in db.execute('SELECT payload FROM ' + table):
                boundary.scan(json.loads(row[0]))
        if 'local_records' in tables:
            for row in db.execute('SELECT text,source_refs FROM local_records'):
                if json.loads(row['source_refs']):
                    boundary.add(row['text'])


def _scan_visible_sources(detail, boundary):
    for value in (detail.get('evidence', []), detail.get('task', {}).get('evidence', [])):
        for evidence in value:
            # NotebookService also uses a human/AI note as fallback evidence. Its
            # own presentation is not an independent source quote fingerprint.
            if str(evidence.get('label', '')).startswith(('本人批注', '本人留言', 'AI记录')):
                continue
            boundary.scan(evidence, source=True)
    for event in detail.get('timeline', []):
        boundary.scan(event.get('sources', []), source=True)


def _validate_tree(value, depth=0, field=None):
    if depth > 24:
        raise ValidationError('云投影嵌套过深')
    if isinstance(value, str):
        if field in _ID_FIELDS:
            # Stable business IDs can contain words such as AUTHORIZATION. They
            # have a separate bounded ASCII grammar; do not treat their topic
            # names as evidence prose. Actual recognizable key values still fail.
            validate_id(value)
            if _CREDENTIAL_VALUE.search(value):
                raise ValidationError('云投影编号不能包含认证凭证')
        elif len(value) > 64000 or _hostile(value):
            raise ValidationError('云投影含受限来源或认证内容')
    elif isinstance(value, dict):
        for k, v in value.items():
            _validate_tree(k, depth + 1)
            _validate_tree(v, depth + 1, k)
    elif isinstance(value, list):
        for v in value:
            _validate_tree(v, depth + 1, field)
    elif value is not None and type(value) not in (int, bool):
        raise ValidationError('云投影字段类型无效')


def _validate_time(value, unknown=False):
    if value is None or (unknown and value == '待核实'):
        return
    try:
        if not isinstance(value, str) or len(value) > 60:
            raise ValueError()
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except (TypeError, ValueError):
        raise ValidationError('云投影时间无效') from None


def _validate_changes(p):
    if not isinstance(p, dict) or set(p) - CHANGE_FIELDS:
        raise ValidationError('云投影历史变化无效')
    for k, v in p.items():
        if k in TEXT_FIELDS and (not isinstance(v, str) or len(v) > TEXT_FIELDS[k]):
            raise ValidationError('云投影变化文字无效')
        if k == 'recommendation' and v is not None:
            if not isinstance(v, dict) or set(v) != {'state', 'reason'} or not isinstance(v['reason'], str) or len(v['reason']) > 4000:
                raise ValidationError('云投影建议字段无效')
            state(v['state'])
        if k in ('state', 'selectedState'):
            state(v)
        if k == 'kind' and v not in KINDS:
            raise ValidationError('云投影性质无效')
        if k == 'domain' and v not in (*DOMAINS, ''):
            raise ValidationError('云投影领域无效')
        if k in ('planDate', 'reviewDate', 'deadlineDate'):
            day(v)
        if k == 'proposedAt':
            _validate_time(v, unknown=True)
        if k in ('needsReview', 'active', 'planDateExplicit') and type(v) is not bool:
            raise ValidationError('云投影变化标志无效')
        if k == 'relatedRecordIds':
            if not isinstance(v, list) or len(v) > 100:
                raise ValidationError('云投影变化关联无效')
            for rid in v:
                validate_id(rid)


def _validate_bundle(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {'version', 'createdAt', 'objects', 'records'} or bundle['version'] != VERSION:
        raise ValidationError('云投影版本或字段无效')
    _validate_tree(bundle)
    _validate_time(bundle['createdAt'])
    if not isinstance(bundle['objects'], list) or len(bundle['objects']) > 10000:
        raise ValidationError('云投影事项数量无效')
    ids = []
    for t in bundle['objects']:
        if not isinstance(t, dict) or set(t) != OBJECT_FIELDS:
            raise ValidationError('云投影事项字段无效')
        ids.append(validate_id(t['id']))
        if t['state'] not in STATES or t['selectedState'] != t['state'] or t['kind'] not in KINDS or t['domain'] not in (*DOMAINS, ''):
            raise ValidationError('云投影事项状态无效')
        if type(t['revision']) is not int or t['revision'] < 0:
            raise ValidationError('云投影版本号无效')
        for field in ('active', 'needsReview', 'planDateExplicit', 'importedLegacyPlanning'):
            if type(t[field]) is not bool:
                raise ValidationError('云投影标志无效')
        if t['legacy'] is not False or t['evidence'] != [EVIDENCE] or t['cloudProjection'] != MARKER:
            raise ValidationError('云投影来源边界标志无效')
        for field, limit in TEXT_FIELDS.items():
            if not isinstance(t[field], str) or len(t[field]) > limit:
                raise ValidationError('云投影事项文字无效')
        if not t['title'] or not t['assignee']:
            raise ValidationError('云投影事项缺少名称或负责人')
        _validate_changes({k: v for k, v in t.items() if k in CHANGE_FIELDS})
        for field in ('deadlineDate', 'planDate', 'reviewDate'):
            day(t[field])
        for contact in t['sourceContacts']:
            if not isinstance(contact, dict) or set(contact) - CONTACT_FIELDS or any(not isinstance(v, str) or len(v) > 160 for v in contact.values()):
                raise ValidationError('云投影来源定位字段无效')
        for events in (t['cloudProjectionTimeline'], t['cloudProjectionHistory']):
            if not isinstance(events, list):
                raise ValidationError('云投影历史无效')
            for e in events:
                if not isinstance(e, dict) or set(e) - EVENT_FIELDS or e.get('localOnly') is not True or e.get('historyComplete') is not False:
                    raise ValidationError('云投影历史字段无效')
                validate_id(e['id'])
                actor(e['actor'])
                _validate_time(e['at'])
                _validate_time(e.get('sourceTime'))
                for field in ('body', 'note', 'author'):
                    if not isinstance(e.get(field), str):
                        raise ValidationError('云投影历史文字无效')
                for p in (e['changes'], e['previous']):
                    _validate_changes(p)
                for field in ('state', 'suggestedState'):
                    if e.get(field) is not None:
                        state(e[field])
                if 'reminder' in e:
                    reminder = e['reminder']
                    if not isinstance(reminder, dict) or set(reminder) - {'kind', 'at', 'timezone', 'firedAt'}:
                        raise ValidationError('云投影历史提醒无效')
                    for k, v in reminder.items():
                        if k in ('at', 'firedAt'):
                            _validate_time(v)
                        elif not isinstance(v, str) or len(v) > 120:
                            raise ValidationError('云投影历史提醒字段无效')
                if e['sources'] not in ([], [EVIDENCE]):
                    raise ValidationError('云投影历史不能带原文')
    if len(ids) != len(set(ids)):
        raise ValidationError('云投影事项编号重复')
    for t in bundle['objects']:
        if not isinstance(t['relatedRecordIds'], list) or set(t['relatedRecordIds']) - set(ids):
            raise ValidationError('云投影关联事项无效')
    if not isinstance(bundle['records'], list):
        raise ValidationError('云投影留言无效')
    record_ids = []
    for r in bundle['records']:
        if not isinstance(r, dict) or set(r) != RECORD_FIELDS or r['attachments'] or r['sourceRefs'] or r['localOnly'] is not True:
            raise ValidationError('云投影留言字段无效')
        record_ids.append(validate_id(r['id']))
        actor(r['actor'])
        _validate_time(r['at'])
        if not isinstance(r['text'], str):
            raise ValidationError('云投影留言文字无效')
        if not isinstance(r['objectIds'], list) or set(r['objectIds']) - set(ids):
            raise ValidationError('云投影留言关联无效')
        if r['processing'] not in ('pending', 'running', 'completed', 'failed') or r['receipts']:
            raise ValidationError('云投影留言处理状态无效')
    if len(record_ids) != len(set(record_ids)):
        raise ValidationError('云投影留言编号重复')


def export_projection(notebook_port, output_dir):
    """Create a NEW directory containing projection.json and non-echoing audit.json.

    Caller should supply a consistent read-only notebook snapshot. Export performs
    no mutations on that port; concurrent source changes cause an explicit error.
    """
    output = _path(output_dir)
    if output.exists():
        raise ValidationError('投影输出目录已存在，不覆盖')
    boundary = _Boundary()
    tasks = notebook_port.list_tasks()
    before = {t['id']: t['revision'] for t in tasks}
    _scan_private_sources(notebook_port, boundary)
    details = {}
    for task in tasks:
        detail = notebook_port.detail(task['id'])
        details[task['id']] = detail
        _scan_visible_sources(detail, boundary)
    records = notebook_port.list_records()
    record_ids = {r['id'] for r in records}
    for record in records:
        if record.get('sourceRefs'):
            boundary.add(record['text'])
    objects = []
    for task in tasks:
        rid = task['id']
        boundary.excluded[(rid, 'source-evidence', 'originals-remain-local')] += len(task.get('evidence') or [])
        obj = {k: copy.deepcopy(task.get(k)) for k in VALUE_FIELDS}
        obj['planDateExplicit'] = bool(task.get('planDateExplicit'))
        obj['proposedAt'] = _safe_time(obj['proposedAt'], boundary, rid, 'proposedAt', unknown=True)
        for field in TEXT_FIELDS:
            obj[field] = boundary.text(task.get(field), rid, field,
                '事项摘要保留Mac' if field == 'title' else '我' if field == 'assignee' else '')
        if isinstance(obj['recommendation'], dict):
            obj['recommendation'] = {'state': obj['recommendation'].get('state'),
                'reason': boundary.text(obj['recommendation'].get('reason'), rid, 'recommendation')}
        obj.update(legacy=False, importedLegacyPlanning=bool(task.get('legacy') or task.get('importedLegacyPlanning')),
            evidence=[dict(EVIDENCE)], sourceContacts=_contacts(task.get('sourceContacts'), boundary, rid),
            cloudProjection=dict(MARKER),
            cloudProjectionTimeline=[_event(e, boundary, rid, i) for i, e in enumerate(details[rid].get('timeline', [])) if e.get('id') not in record_ids],
            cloudProjectionHistory=[_event(e, boundary, rid, i) for i, e in enumerate(details[rid].get('history', []))])
        objects.append(obj)
    projected_records = []
    for record in records:
        rid = record['id']
        a = actor(record['actor'])
        a['name'] = boundary.text(a['name'], rid, 'actor', '我' if a['kind'] == 'human' else 'AI')
        if record.get('sourceRefs'):
            value = PLACEHOLDER
            boundary.excluded[(rid, 'source-message', 'originals-remain-local')] += 1
        elif a['kind'] == 'human':
            value = boundary.text(record['text'], rid, 'human-message', PLACEHOLDER)
        else:
            value = 'AI处理记录保留Mac，线上仅保存关联与处理状态。'
        if record.get('attachments'):
            boundary.excluded[(rid, 'attachments', 'originals-remain-local')] += len(record['attachments'])
        if record.get('receipts'):
            boundary.excluded[(rid, 'receipts', 'originals-remain-local')] += len(record['receipts'])
        projected_records.append({'id': rid, 'text': value, 'objectIds': record['objectIds'],
            'attachments': [], 'actor': a, 'at': record['at'], 'processing': record['processing'],
            'receipts': [], 'sourceRefs': [], 'localOnly': True})
    if {t['id']: t['revision'] for t in notebook_port.list_tasks()} != before:
        raise ValidationError('来源事项在导出期间发生变化，请使用一致性只读快照')
    bundle = {'version': VERSION, 'createdAt': stamp(), 'objects': objects, 'records': projected_records}
    _validate_bundle(bundle)
    encoded = json.dumps(bundle, ensure_ascii=False, sort_keys=True, indent=2).encode('utf-8')
    if len(encoded) > MAX_BUNDLE:
        raise ValidationError('云投影超过大小上限')
    audit = {'version': VERSION, 'createdAt': bundle['createdAt'], 'objectCount': len(objects),
        'recordCount': len(projected_records), 'ids': sorted(before), 'bundleSha256': hashlib.sha256(encoded).hexdigest(),
        'sourceFingerprintCount': len(boundary.quotes), 'sourceFingerprintSha256': hashlib.sha256(
            '\n'.join(sorted(hashlib.sha256(q.encode()).hexdigest() for q in boundary.quotes)).encode()).hexdigest(),
        'sourceEchoAuditPassed': True, 'sourcePolicy': 'local-only', 'historyComplete': False,
        'historyEventCount': sum(len(t['cloudProjectionTimeline']) for t in objects),
        'excluded': [{'id': rid, 'type': field, 'reason': why, 'count': count}
            for (rid, field, why), count in sorted(boundary.excluded.items())]}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        output.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValidationError('投影输出目录已存在，不覆盖') from exc
    try:
        for name, data in (('projection.json', encoded), ('audit.json', json.dumps(audit, ensure_ascii=False, sort_keys=True, indent=2).encode())):
            fd = os.open(str(output / name), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
    except Exception:
        shutil.rmtree(output)
        raise
    return {'bundle': str(output / 'projection.json'), 'audit': str(output / 'audit.json'),
            'objectCount': len(objects), 'recordCount': len(projected_records)}


def import_projection(bundle_dir, db_file, workspace):
    """Validate first, then create a new empty destination; never replace a DB."""
    source = _path(bundle_dir)
    workspace = _path(workspace)
    db_file = _path(db_file)
    if not db_file.is_relative_to(workspace) or db_file == workspace:
        raise ValidationError('云数据库必须位于指定工作区内')
    if db_file.exists() or any(Path(str(db_file) + s).exists() for s in ('-wal', '-shm', '-journal')):
        raise ValidationError('云数据库已存在，不覆盖')
    for path in (source / 'projection.json', source / 'audit.json'):
        _path(path)
        if not path.is_file() or path.stat().st_size > MAX_BUNDLE:
            raise ValidationError('云投影文件缺失或过大')
    raw = (source / 'projection.json').read_bytes()
    bundle = strict_json(raw)
    audit = strict_json((source / 'audit.json').read_bytes())
    if not isinstance(audit, dict) or set(audit) != AUDIT_FIELDS or audit.get('bundleSha256') != hashlib.sha256(raw).hexdigest() or audit.get('sourceEchoAuditPassed') is not True:
        raise ValidationError('云投影校验或来源审核未通过')
    _validate_tree(audit)
    for entry in audit['excluded']:
        if not isinstance(entry, dict) or set(entry) != {'id', 'type', 'reason', 'count'}:
            raise ValidationError('云投影审核字段无效')
        validate_id(entry['id'])
    _validate_bundle(bundle)
    if audit.get('ids') != sorted(t['id'] for t in bundle['objects']) or audit.get('objectCount') != len(bundle['objects']) or audit.get('recordCount') != len(bundle['records']):
        raise ValidationError('云投影清单与内容不一致')
    # This file MUST NOT exist: NotebookService otherwise refreshes legacy tasks.
    missing_source = workspace / '.cloud-projection-no-source.json'
    if missing_source.exists() or missing_source.is_symlink():
        raise ValidationError('云投影工作区存在意外来源文件')
    workspace_was_new = not workspace.exists()
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    db_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    created = False
    try:
        try:
            fd = os.open(str(db_file), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ValidationError('云数据库已存在，不覆盖') from exc
        os.close(fd)
        created = True
        notebook = NotebookService(db_file, missing_source, workspace)
        with notebook._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for t in bundle['objects']:
                db.execute('INSERT INTO local_objects(id,payload,created_at) VALUES(?,?,?)',
                    (t['id'], json.dumps(t, ensure_ascii=False), bundle['createdAt']))
                notebook._sync_schedule(db,t,{}, {'name':'迁移','kind':'ai'},'导入现有明确计划')
            for r in bundle['records']:
                db.execute('INSERT INTO local_records(id,text,object_ids,attachments,actor,at,processing,receipts,source_refs) VALUES(?,?,?,?,?,?,?,?,?)',
                    (r['id'], r['text'], json.dumps(r['objectIds']), '[]', json.dumps(r['actor'], ensure_ascii=False), r['at'], r['processing'], '[]', '[]'))
            db.execute('INSERT INTO metadata(key,value) VALUES(?,?)', ('cloud_projection', json.dumps({
                'version': VERSION, 'objectCount': len(bundle['objects']), 'sourcePolicy': 'local-only',
                'historyComplete': False, 'bundleSha256': audit['bundleSha256']})))
        actual = notebook.list_tasks()
        if {t['id']: t['revision'] for t in actual} != {t['id']: t['revision'] for t in bundle['objects']}:
            raise ValidationError('导入后事项编号或版本回读不一致')
    except Exception:
        if created:
            for suffix in ('', '-wal', '-shm', '-journal'):
                Path(str(db_file) + suffix).unlink(missing_ok=True)
        if workspace_was_new:
            shutil.rmtree(workspace)
        raise
    return {'dbFile': str(db_file), 'objectCount': len(bundle['objects']), 'recordCount': len(bundle['records']),
            'bundleSha256': audit['bundleSha256']}
