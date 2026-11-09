"""Observer-only primitives. No code here can write a monitored source."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, hashlib, json, os, re, tempfile, time
from pathlib import Path
from collect import clean_text
RESTRICTED = tuple(_install.setting('monitor.live_core', 'RESTRICTED', ['.restricted-archive', 'credential', 'auth.json']))
STATES = {'待推进', '待处理', '进行中', '等反馈', '已交付', '已完成', '已办好', '不做了', '不用管了', '暂缓', '先放放', '状态冲突', '待核实'}

def digest(x):
    return hashlib.sha256(x.encode() if isinstance(x, str) else x).hexdigest()

def checked_path(path, roots):
    p = Path(path)
    if not p.is_absolute() or '.restricted-archive' in p.parts or any((w in p.name.lower() for w in ['auth.json', '.key', 'token', 'credential', 'password'])) or re.search('secret(?!ary)', p.name.lower()):
        raise ValueError('excluded path')
    for a in [p] + list(p.parents):
        if a.is_symlink():
            raise ValueError('symlink refused')
    q = p.resolve()
    if not any((q == r.resolve() or r.resolve() in q.parents for r in roots)):
        raise ValueError('outside allowed roots')
    return q

def redact_record(text):
    if any((w in text.lower() for w in RESTRICTED)):
        return None
    return clean_text(text)

def stable_note(path, json_required=False):
    p = Path(path)
    for _ in range(2):
        a = p.stat()
        if a.st_size > 2000000:
            raise ValueError('note too large')
        raw = p.read_bytes()
        b = p.stat()
        if (a.st_ino, a.st_size, a.st_mtime_ns) == (b.st_ino, b.st_size, b.st_mtime_ns):
            s = raw.decode('utf-8')
            if json_required:
                json.loads(s)
            return (s, b)
    raise ValueError('source changing during read')

def read_append(path, cursor, limit=8000000, cutoff=None):
    p = Path(path)
    st = p.stat()
    off = cursor.get('offset', 0)
    lineno = cursor.get('line', 0)
    with p.open('rb') as f:
        prefix = f.read(min(128, off))
        if st.st_size < off or (cursor.get('inode') and st.st_ino != cursor['inode']) or (cursor.get('prefix') and digest(prefix) != cursor['prefix']):
            off = 0
            lineno = 0
        f.seek(off)
        end = min(st.st_size, off + limit)
        rows = []
        while f.tell() < end:
            start = f.tell()
            line = f.readline(end - start)
            if not line.endswith(b'\n'):
                f.seek(start)
                break
            try:
                r = json.loads(line)
            except (ValueError, UnicodeError):
                f.seek(start)
                raise ValueError('malformed complete session line')
            if cutoff and r.get('timestamp'):
                import datetime
                if datetime.datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00')) > datetime.datetime.fromisoformat(cutoff.replace('Z', '+00:00')):
                    f.seek(start)
                    break
            lineno += 1
            rows.append((lineno, r))
            off = f.tell()
        f.seek(0)
        prefix = f.read(min(128, off))
    return (rows, {'inode': st.st_ino, 'offset': off, 'line': lineno, 'prefix': digest(prefix), 'capturedSize': st.st_size, 'mtimeNs': st.st_mtime_ns})

def atomic_json(path, obj):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    (fd, tmp) = tempfile.mkstemp(prefix='.' + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(obj, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 384)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def unique(rows, keys):
    return list({tuple((x.get(k) for k in keys)): x for x in rows}.values())

def merge_changes(old, patches, sources, employee, new_sources):
    out = copy.deepcopy(old)
    index = {t['id']: t for t in out}
    for p in patches:
        ident = p.get('id', '')
        if not ident or len(ident) > 150:
            raise ValueError('invalid task id')
        if p.get('employee', employee) != employee or (ident in index and index[ident]['employee'] != employee):
            raise ValueError('cross employee patch')
        if p.get('state', '待核实') not in STATES:
            raise ValueError('unknown state')
        ev = p.get('evidence', [])
        if not ev or not any((e.get('id') in new_sources for e in ev)):
            raise ValueError('missing new evidence')
        for e in ev:
            if e.get('id') not in sources or not e.get('quote') or e['quote'] not in sources[e['id']]['text']:
                raise ValueError('unsupported evidence')
        for e in p.get('trajectory', []):
            if e.get('source_id') not in sources:
                raise ValueError('unknown trajectory source')
        if ident not in index:
            if not ident.startswith(employee + '-live-'):
                raise ValueError('new task outside employee namespace')
            t = {k: '' for k in ['title', 'pending', 'next', 'goal', 'origin', 'thought', 'time']}
            t.update({'id': ident, 'employee': employee, 'state': '待核实', 'kind': 'workstream', 'evidence': [], 'trajectory': []})
            out.append(t)
            index[ident] = t
        t = index[ident]
        if t.get('kind') == 'history':
            raise ValueError('history cannot silently become current task')
        for k in ['title', 'state', 'pending', 'next', 'goal', 'origin', 'thought', 'time', 'who_owes']:
            if k in p:
                if not isinstance(p[k], str) or len(p[k]) > 6000:
                    raise ValueError('invalid text field')
                t[k] = p[k]
        t['evidence'] = unique(t['evidence'] + ev, ['id', 'quote'])
        t['trajectory'] = unique(t['trajectory'] + p.get('trajectory', []), ['time', 'event', 'source_id'])
        t['confidence'] = '新增记录支持，未独立验收业务成果'
    return out

def publish(root, snapshot, sources, revision):
    from work_contract import validate_work
    validate_work(snapshot.get('workOverview'), sources)
    for t in snapshot['tasks']:
        if any((e['id'] not in sources for e in t['evidence'])) or any((e['source_id'] not in sources for e in t['trajectory'])):
            raise ValueError('snapshot refers to missing evidence')

    def check_refs(v):
        if isinstance(v, dict):
            if 'id' in v and 'quote' in v and (v['id'] not in sources):
                raise ValueError('missing profile evidence')
            for x in v.values():
                check_refs(x)
        elif isinstance(v, list):
            for x in v:
                check_refs(x)
    check_refs(snapshot.get('profiles', {}))
    if snapshot.get('modelAccounts') is not None:
        from account_contract import validate_accounts
        validate_accounts(snapshot['modelAccounts'])
    root = Path(root)
    folder = root / 'versions' / revision
    atomic_json(folder / 'sources.json', sources)
    atomic_json(folder / 'snapshot.json', snapshot)
    atomic_json(root / 'live.json', {'revision': revision, 'snapshotUrl': '/versions/' + revision + '/snapshot.json', 'sourcesUrl': '/versions/' + revision + '/sources.json'})
    import shutil
    for f in sorted((root / 'versions').iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[3:]:
        if f.is_dir() and (not f.is_symlink()):
            shutil.rmtree(f)
    return folder
