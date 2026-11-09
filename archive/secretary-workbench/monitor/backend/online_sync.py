"""Publish the necessary read-only projection to one authorized SSH destination."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, copy, datetime, io, json, re, subprocess, tarfile
from pathlib import Path
from collect import ROOT, PRIVATE
from live_core import atomic_json
from employee_profiles import profile_refs
REMOTE = str(_install.path('monitor.online_sync.remote_root'))
SSH_ALIAS = _install.setting('monitor.online_sync', 'ssh_alias', '')
PUBLIC_URL = _install.setting('monitor.online_sync', 'public_url', '')

def make_projection(snapshot, sources):
    from work_contract import validate_work
    snap = copy.deepcopy(snapshot)
    from research_secretary_scope import public_metadata
    sources = public_metadata(snap, sources)
    if snap.get('workOverview'):
        snap['workOverview'].pop('deliveryObligations', None)
    validate_work(snap.get('workOverview'), sources)
    if snapshot.get('modelAccounts') is not None:
        from account_contract import validate_accounts
        validate_accounts(snapshot['modelAccounts'])
    wanted = {e['id'] for t in snap['tasks'] for e in t['evidence']} | {e['source_id'] for t in snap['tasks'] for e in t['trajectory']}
    profile_evidence = profile_refs(snap.get('profiles', {}))
    wanted.update((e['id'] for e in profile_evidence))
    work = snap.get('workOverview', {})
    work_ids = {i['sourceId'] for i in work.get('items', [])}
    for row in work.get('sending', {}).get('items', []):
        work_ids.update((x for x in [row.get('sourceId'), row.get('proofSourceId')] if x))
    if work.get('modes', {}).get('sourceId'):
        work_ids.add(work['modes']['sourceId'])
    work_ids.update((p['modeNotes']['sourceId'] for p in work.get('employees', []) if p.get('modeNotes')))
    obs = work.get('observation', {})
    if obs.get('eventSourceId'):
        work_ids.add(obs['eventSourceId'])
    work_ids.update((r['sourceId'] for r in obs.get('reviews', [])))
    wanted.update(work_ids)
    from work_contract import source_refs
    wanted.update(source_refs(work))
    out = {}
    for ident in wanted:
        if ident not in sources:
            raise ValueError('missing source')
        s = copy.deepcopy(sources[ident])
        body = s['text']
        quoted = [e['quote'] for t in snap['tasks'] for e in t['evidence'] if e['id'] == ident and e.get('quote') in body] + [e['quote'] for e in profile_evidence if e['id'] == ident and e.get('quote') in body]
        if len(body) > 24000:
            spans = [(0, 1800), (max(0, len(body) - 2500), len(body))]
            for q in quoted:
                at = body.find(q)
                spans.append((max(0, at - 650), min(len(body), at + len(q) + 650)))
            merged = []
            for (lo, hi) in sorted(spans):
                if merged and lo <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
                else:
                    merged.append((lo, hi))
            s['text'] = '【在线依据摘录；完整原文保留在Mac，以下省略处不是原文缺失】\n\n' + '\n\n……【摘录间省略】……\n\n'.join((body[a:b] for (a, b) in merged))
            s['role'] = s.get('role', '') + ' · 在线摘录'
        s['path'] = re.sub(r'^/(?:Users|home)/[^/]+/', '[local]/', s.get('path', ''))
        out[ident] = s
    note = '在线站点仅同步监控所需快照与被引用依据；较长原文显示相关摘录，完整原件留Mac。无员工控制或修改入口。'
    if note not in snap['warnings']:
        snap['warnings'].append(note)
    snap['online'] = {'readOnly': True, 'originalsOnMac': True}
    return (snap, out)

def build_payload(snapshot, sources, status):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as tar:
        for (name, value) in [('snapshot.json', snapshot), ('sources.json', sources), ('status.json', status)]:
            b = json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True).encode()
            t = tarfile.TarInfo(name)
            t.size = len(b)
            t.mode = 384
            t.mtime = 0
            tar.addfile(t, io.BytesIO(b))
    return data.getvalue()

def sync_online():
    config = PRIVATE / 'online-config.json'
    if not config.exists():
        return {'enabled': False}
    if config.is_symlink() or config.stat().st_mode & 63:
        raise ValueError('private config permissions required')
    cfg = json.loads(config.read_text())
    if not cfg.get('enabled'):
        return {'enabled': False}
    if not SSH_ALIAS or not PUBLIC_URL or cfg.get('sshAlias') != SSH_ALIAS or cfg.get('remoteRoot') != REMOTE or cfg.get('publicUrl') != PUBLIC_URL:
        raise ValueError('unapproved deployment destination')
    live = ROOT / 'live'
    manifest = json.loads((live / 'live.json').read_text())
    rev = manifest['revision']
    if not re.fullmatch('[0-9]{8}T[0-9]{6}-[a-f0-9]{6}', rev):
        raise ValueError('invalid revision')
    folder = live / 'versions' / rev
    snap = json.loads((folder / 'snapshot.json').read_text())
    sources = json.loads((folder / 'sources.json').read_text())
    (snap, sources) = make_projection(snap, sources)
    status = {'collectorState': 'snapshot-published', 'intervalSeconds': 300, 'lastCycleEnded': snap['live']['lastCycleFinished'], 'source': 'Mac read-only collector'}
    payload = build_payload(snap, sources, status)
    args = ['/usr/bin/ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', SSH_ALIAS, '/usr/bin/python3 ' + __import__('shlex').quote(REMOTE + '/cloud_receive.py') + ' --execute --revision ' + rev]
    p = subprocess.run(args, input=payload, capture_output=True, timeout=40)
    if p.returncode:
        raise RuntimeError('online snapshot sync failed; local collection preserved')
    result = json.loads(p.stdout)
    if not result.get('stored') or result.get('revision') != rev:
        raise ValueError('online acknowledgement mismatch')
    result.update(enabled=True, publicUrl=cfg['publicUrl'], uploadedBytes=len(payload), syncedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    atomic_json(PRIVATE / 'online-last-sync.json', result)
    return result
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    if a.execute:
        print(json.dumps(sync_online(), ensure_ascii=False))
    else:
        p.print_help()
