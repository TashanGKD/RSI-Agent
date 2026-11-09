"""Accept a fixed snapshot archive over authenticated SSH stdin, never via HTTP."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, hashlib, io, json, os, re, shutil, tarfile, tempfile
from pathlib import Path
MAX_ARCHIVE = 12000000
MAX_TOTAL = 40000000

def atomic_json(p, v):
    p.parent.mkdir(parents=True, exist_ok=True)
    (fd, tmp) = tempfile.mkstemp(prefix='.' + p.name, dir=p.parent)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(v, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 384)
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def receive(root, revision, payload):
    if not re.fullmatch('[0-9]{8}T[0-9]{6}-[a-f0-9]{6}', revision):
        raise ValueError('bad revision')
    root = Path(root)
    if root.is_symlink() or (root / 'versions').is_symlink():
        raise ValueError('managed directory symlink refused')
    if len(payload) > MAX_ARCHIVE:
        raise ValueError('archive too large')
    members = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name not in ['snapshot.json', 'sources.json', 'status.json'] or member.name in members:
                raise ValueError('unexpected archive entry')
            total += member.size
            if member.size < 0 or total > MAX_TOTAL:
                raise ValueError('excessive snapshot size')
            b = tar.extractfile(member).read(member.size + 1)
            if len(b) != member.size:
                raise ValueError('incomplete archive member')
            members[member.name] = b
    if set(members) != {'snapshot.json', 'sources.json', 'status.json'}:
        raise ValueError('incomplete snapshot')
    snapshot = json.loads(members['snapshot.json'])
    sources = json.loads(members['sources.json'])
    status = json.loads(members['status.json'])
    from work_contract import validate_work
    validate_work(snapshot.get('workOverview'), sources)
    if snapshot.get('live', {}).get('revision') != revision:
        raise ValueError('revision mismatch')
    for task in snapshot['tasks']:
        if any((e['id'] not in sources for e in task['evidence'])) or any((e['source_id'] not in sources for e in task['trajectory'])):
            raise ValueError('missing evidence')

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
    root.mkdir(parents=True, exist_ok=True)
    versions = root / 'versions'
    versions.mkdir(exist_ok=True)
    target = versions / revision
    if target.exists():
        if target.is_symlink() or any(((target / name).read_bytes() != members[name] for name in ['snapshot.json', 'sources.json'])):
            raise ValueError('immutable version conflict')
    else:
        staging = Path(tempfile.mkdtemp(prefix='.upload-', dir=versions))
        try:
            for name in ['snapshot.json', 'sources.json']:
                p = staging / name
                p.write_bytes(members[name])
                p.chmod(384)
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    atomic_json(root / 'status.json', status)
    manifest = {'revision': revision, 'snapshotUrl': '/versions/' + revision + '/snapshot.json', 'sourcesUrl': '/versions/' + revision + '/sources.json'}
    atomic_json(root / 'live.json', manifest)
    published = sorted((p for p in versions.iterdir() if re.fullmatch('[0-9]{8}T[0-9]{6}-[a-f0-9]{6}', p.name)), key=lambda p: p.name, reverse=True)
    for p in published[3:]:
        if p.is_dir() and (not p.is_symlink()):
            shutil.rmtree(p)
    return {'stored': True, 'revision': revision, 'snapshotSha256': hashlib.sha256(members['snapshot.json']).hexdigest(), 'sourcesSha256': hashlib.sha256(members['sources.json']).hexdigest()}
if __name__ == '__main__':
    import sys
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--revision')
    a = p.parse_args()
    if not a.execute:
        p.print_help()
    else:
        if not a.revision:
            raise SystemExit('--revision is required')
        payload = sys.stdin.buffer.read(MAX_ARCHIVE + 1)
        print(json.dumps(receive(_install.path('monitor.cloud_root') / 'public/data', a.revision, payload)))
