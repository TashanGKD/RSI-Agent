"""Read-only, explicitly bounded source snapshots. Never sends or updates workers."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, datetime, glob, hashlib, json, os, re, sqlite3, subprocess
from pathlib import Path
ROOT = _install.path('monitor_workspace')
PRIVATE = ROOT / 'private'
IDS = _install.setting('monitor.collect', 'IDS', {})
CUTOFF = _install.setting('monitor.collect', 'CUTOFF', '')
ALLOWED = _install.path_list('monitor.collect', 'ALLOWED')

def safe_source(p):
    p = Path(p)
    if p.is_symlink() or '.restricted-archive' in p.parts or any((x in p.name.lower() for x in ['auth.json', '.key', 'secret', 'token', 'credential'])):
        raise ValueError('excluded source')
    q = p.resolve()
    if not any((a == q or a in q.parents for a in ALLOWED)):
        raise ValueError('source outside allowed roots')
    return q

def clean_text(text):
    text = re.sub('\\bsk-[A-Za-z0-9_-]{16,}\\b', '[已隐藏凭据]', text)
    text = re.sub('(?i)(authorization\\s*[:=]\\s*bearer\\s+)\\S+', '\\1[已隐藏]', text)
    text = re.sub('(?i)((?:access_token|refresh_token|password|api_key)\\s*[=:]\\s*)[^\\s,;]+', '\\1[已隐藏]', text)
    return text

def sha(b):
    return hashlib.sha256(b).hexdigest()

def bj(t):
    try:
        return datetime.datetime.fromisoformat(t.replace('Z', '+00:00')).astimezone(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        return t

def read_lines(path, size):
    if path.suffix == '.zst':
        p = subprocess.Popen([_install.setting('monitor.tools','ZSTD','zstd'), '-dc', '--', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        yield from p.stdout
        if p.wait() != 0:
            raise RuntimeError('zstd read failed')
    else:
        with path.open('rb') as f:
            consumed = 0
            while consumed < size:
                line = f.readline()
                consumed += len(line)
                if not line or consumed > size:
                    break
                yield line.decode('utf-8')

def main():
    PRIVATE.mkdir(exist_ok=True)
    c = sqlite3.connect('file:' + str(_install.path('codex_home') / 'state_5.sqlite') + '?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    allcoverage = {}
    registry = []
    for (name, ident) in IDS.items():
        meta = dict(c.execute('select id,cwd,rollout_path,updated_at,title,first_user_message from threads where id=?', (ident,)).fetchone())
        registry.append(meta)
        files = sorted(glob.glob(str(_install.path('codex_home') / 'sessions/**/rollout-*') + ident + '*', recursive=True))
        rows = []
        seen = {}
        coverage = []
        excluded = 0
        compactions = 0
        paths = set()
        for filename in files:
            path = safe_source(Path(filename))
            size = path.stat().st_size
            linecount = 0
            visible = 0
            malformed = 0
            new = 0
            for (linecount, line) in enumerate(read_lines(path, size), 1):
                try:
                    o = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                ts = o.get('timestamp', '')
                if ts:
                    try:
                        if datetime.datetime.fromisoformat(ts.replace('Z', '+00:00')) > datetime.datetime.fromisoformat(CUTOFF):
                            continue
                    except ValueError:
                        continue
                v = o.get('payload', {})
                kind = o.get('type')
                if kind == 'compacted':
                    compactions += 1
                    continue
                if kind != 'response_item' or v.get('type') != 'message' or v.get('role') not in ('user', 'assistant'):
                    continue
                text = '\n'.join((x.get('text', '') for x in v.get('content', []) if x.get('type') in ('input_text', 'output_text', 'text')))
                if not text:
                    continue
                visible += 1
                if any((s in text for s in ['玻尔', '波尔', 'bohrium', '.restricted-archive', _install.identity('monitor.collect.identity_6a0f861c')])):
                    excluded += 1
                    continue
                if text.startswith(('<environment_context>', '<external_codex_apps_open_page>', '<in-app-browser-context')) and '<request>' not in text:
                    continue
                for pth in re.findall(str(_install.path('monitor.collect.path_fbfb7117')), text):
                    if any((k in pth.lower() for k in ['current', 'notebook', '记事', '工作本', 'plan.md', 'log.md', 'group-rules', 'workbook'])):
                        paths.add(pth.rstrip(' 。：:；;,）)'))
                text = clean_text(text)
                key = sha((v['role'] + '\x00' + text).encode())
                ref = {'path': str(path), 'line': linecount, 'timestamp': ts, 'message_id': v.get('id')}
                if key in seen:
                    seen[key]['sources'].append(ref)
                    continue
                row = {'id': name + '-' + key[:14], 'timestamp': ts, 'time': bj(ts), 'role': v['role'], 'phase': v.get('phase'), 'text': text, 'sources': [ref]}
                rows.append(row)
                seen[key] = row
                new += 1
            coverage.append({'path': str(path), 'captured_bytes': size, 'lines_parsed': linecount, 'visible_records': visible, 'new_unique': new, 'malformed_lines': malformed, 'read_to_captured_eof': True})
        rows.sort(key=lambda x: (x['timestamp'] or '', x['sources'][0]['line']))
        (PRIVATE / (name + '-messages.json')).write_text(json.dumps(rows, ensure_ascii=False, indent=2))
        folder = PRIVATE / (name + '-batches')
        folder.mkdir(exist_ok=True)
        chunks = []
        current = ''
        batch = 1
        for row in rows:
            entry = f"\n## {row['id']} | {row['time']} | {row['role']} | {row['phase']}\n{row['text']}\n"
            if current and len(current) + len(entry) > 16000:
                (folder / f'{batch:03}.md').write_text(current)
                chunks.append(len(current))
                current = ''
                batch += 1
            current += entry
        if current:
            (folder / f'{batch:03}.md').write_text(current)
            chunks.append(len(current))
        (PRIVATE / (name + '-path-hints.json')).write_text(json.dumps(sorted(paths), ensure_ascii=False, indent=2))
        allcoverage[name] = {'thread_id': ident, 'files': coverage, 'unique_visible_messages': len(rows), 'characters': sum((len(x['text']) for x in rows)), 'batches': len(chunks), 'restricted_message_exclusions': excluded, 'compaction_events': compactions, 'semantic_read_status': 'pending', 'first_time': rows[0]['time'] if rows else None, 'last_time': rows[-1]['time'] if rows else None}
        print(json.dumps({k: v for (k, v) in allcoverage[name].items() if k != 'files'}, ensure_ascii=False))
    (PRIVATE / 'registry.json').write_text(json.dumps(registry, ensure_ascii=False, indent=2))
    (PRIVATE / 'coverage.json').write_text(json.dumps({'cutoff': CUTOFF, 'threads': allcoverage}, ensure_ascii=False, indent=2))
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    if a.execute:
        main()
    else:
        p.print_help()
