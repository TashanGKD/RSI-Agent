"""Incremental local source readers; never follows content links or instructions."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, datetime, json, sqlite3, subprocess
from pathlib import Path
from collect import IDS, ALLOWED, PRIVATE, bj
from live_core import checked_path, redact_record, digest, read_append, stable_note
SOURCE_ROOTS = ALLOWED

def baseline_state():
    cov = json.loads((PRIVATE / 'coverage.json').read_text())
    out = {}
    for name in IDS:
        notes = json.loads((PRIVATE / (name + '-notes.json')).read_text())
        paths = {}
        for f in cov['threads'][name]['files']:
            p = Path(f['path'])
            size = f['captured_bytes']
            if p.suffix == '.zst':
                paths[str(p)] = {'compressedCaptured': size}
            else:
                with p.open('rb') as h:
                    start = max(0, size - 262144)
                    h.seek(start)
                    if start:
                        h.readline()
                    off = h.tell()
                    h.seek(0)
                    prefix = h.read(min(128, off))
                paths[str(p)] = {'offset': off, 'line': 0, 'prefix': digest(prefix), 'initialOverlap': True}
        out[name] = {'files': paths, 'notes': {n['path']: {'sha': n['sha256'], 'text': n['text'], 'mtimeNs': int(n['mtime'] * 1000000000.0)} for n in notes}, 'seen': [], 'initialCutoff': cov['cutoff'], 'lastSuccess': None, 'lastAttempt': None, 'error': None, 'totalNewMessages': 0}
    return out

def source_from_text(name, path, text, when, label, role, line=None):
    sid = 'live-' + name + '-' + digest(str(path) + '\x00' + when + '\x00' + text)[:20]
    return {'id': sid, 'label': label, 'path': str(path), 'time': bj(when), 'role': role, 'text': text, **({'line': line} if line else {})}

def read_messages(name, state, cutoff):
    st = copy.deepcopy(state)
    records = []
    stats = {'newMessages': 0, 'bytesRead': 0, 'excluded': 0}
    seen = set(st['seen'])
    db = sqlite3.connect('file:' + str(_install.path('codex_home') / 'state_5.sqlite') + '?mode=ro', uri=True, timeout=2)
    try:
        row = db.execute('select rollout_path from threads where id=?', (IDS[name],)).fetchone()
        if row:
            st['files'].setdefault(row[0], {})
    finally:
        db.close()
    for (path, cur) in list(st['files'].items()):
        p = checked_path(path, SOURCE_ROOTS)
        if not p.exists():
            raise ValueError('已有工作记录文件暂不可读')
        if p.suffix == '.zst':
            if cur.get('compressedCaptured') == p.stat().st_size:
                continue
            proc = subprocess.run([_install.setting('monitor.tools','ZSTD','zstd'), '-dc', '--', str(p)], capture_output=True, timeout=15)
            if proc.returncode or len(proc.stdout) > 80000000:
                raise ValueError('压缩记录读取失败或超过上限')
            lines = [(i + 1, json.loads(s)) for (i, s) in enumerate(proc.stdout.splitlines())]
            ncur = {'compressedCaptured': p.stat().st_size}
        else:
            (lines, ncur) = read_append(p, cur, cutoff=cutoff)
            stats['bytesRead'] += max(0, ncur['offset'] - cur.get('offset', 0))
            if cur.get('initialOverlap'):
                base = 0
                remaining = cur.get('offset', 0)
                with p.open('rb') as f:
                    while remaining:
                        part = f.read(min(65536, remaining))
                        base += part.count(b'\n')
                        remaining -= len(part)
                        if not part:
                            break
                lines = [(n + base, x) for (n, x) in lines]
                ncur['line'] += base
        for (line, obj) in lines:
            ts = obj.get('timestamp', '')
            if not ts or ts <= st['initialCutoff'] or ts > cutoff:
                continue
            v = obj.get('payload', {})
            if obj.get('type') != 'response_item' or v.get('type') != 'message' or v.get('role') not in ['user', 'assistant']:
                continue
            text = '\n'.join((x.get('text', '') for x in v.get('content', []) if x.get('type') in ['input_text', 'output_text', 'text']))
            if not text or (text.startswith(('<environment_context>', '<in-app-browser-context')) and '<request>' not in text):
                continue
            key = digest(ts + '\x00' + v['role'] + '\x00' + text)
            if key in seen:
                continue
            cleaned = redact_record(text)
            seen.add(key)
            if cleaned is None:
                stats['excluded'] += 1
                continue
            r = source_from_text(name, p, cleaned, ts, bj(ts) + ' · 新增可见交流', v['role'], line)
            r['id'] = 'live-msg-' + key[:24]
            records.append(r)
            stats['newMessages'] += 1
        st['files'][path] = ncur
    st['seen'] = sorted(seen)
    st['totalNewMessages'] += stats['newMessages']
    return (records, st, stats)

def note_paths(name, state):
    paths = set(state['notes'])
    if name == 'secretary':
        paths.update((str(x) for x in Path(str(_install.path('monitor.live_sources.path_47dd57e9'))).glob('*.md') if not any((w in x.name.lower() for w in ['玻尔', '波尔', 'bohrium']))))
    roots = {'secretary': Path(str(_install.path('monitor.live_sources.path_88b7c616'))), 'science': Path(str(_install.path('monitor.live_sources.path_07fe995a'))), 'organoid': Path(str(_install.path('monitor.live_sources.path_a1cd8f04')))}
    for dirname in ['notebook', 'workbook', '工作本', '责任笔记']:
        folder = roots[name] / dirname
        if folder.is_dir() and (not folder.is_symlink()):
            paths.update((str(x) for x in folder.glob('*.md') if not any((w in x.name.lower() for w in ['玻尔', '波尔', 'bohrium']))))
    return sorted(paths)

def read_notes(name, state, when):
    st = copy.deepcopy(state)
    records = []
    changed = []
    count = 0
    for path in note_paths(name, st):
        p = checked_path(path, SOURCE_ROOTS)
        if any((w in p.name.lower() for w in ['玻尔', '波尔', 'bohrium'])):
            continue
        if not p.is_file():
            raise ValueError('已有笔记暂不可读；保留其上次事项')
        old = st['notes'].get(path, {})
        if p.stat().st_mtime_ns == old.get('mtimeNs'):
            continue
        (text, stat) = stable_note(p, json_required=p.suffix == '.json')
        h = digest(text)
        if h != old.get('sha'):
            if p.name == 'CURRENT.md' and name == 'secretary':
                pass
            elif redact_record(text) is None:
                count += 1
            else:
                newrec = []
                if p.name == 'CURRENT_RESEARCH.json' and old.get('text'):
                    before = json.loads(old['text'])
                    after = json.loads(text)
                    for (key, value) in after.items():
                        if before.get(key) == value:
                            continue
                        part = json.dumps({key: value}, ensure_ascii=False, indent=2)
                        if redact_record(part) is not None:
                            newrec.append(source_from_text(name, p, redact_record(part), when, p.name + ' · ' + key, '变化笔记片段'))
                else:
                    newrec.append(source_from_text(name, p, redact_record(text), when, p.name, '变化工作笔记'))
                records.extend(newrec)
                changed.append((path, text, newrec))
        st['notes'][path] = {'sha': h, 'text': text if redact_record(text) is not None else '', 'mtimeNs': stat.st_mtime_ns}
    return (records, st, changed, {'changedNotes': len(changed), 'excludedNotes': count})
