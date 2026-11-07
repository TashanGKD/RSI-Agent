"""Read the system owner's existing --pending view once per registered thread.

Only metadata is projected. No dispatch/prepare/resolve/queue/write or raw event bodies.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, json, math, re, subprocess
from pathlib import Path
SYSTEM = _install.path('continuity_workspace')

def unique_threads(bindings):
    return list(dict.fromkeys((b['threadId'] for b in bindings)))

def seconds(n):
    if type(n) not in [int, float] or not math.isfinite(n) or (not 0 <= n <= 32503680000):
        raise ValueError('invalid seconds timestamp')
    return n

def project_pending(raw, thread, bindings):
    if raw.get('state') == 'not_started':
        return {'state': 'not_started', 'pending': None, 'pendingEvidenceCount': None, 'conversations': [], 'existingNotices': [], 'readingOrBusinessCompletionInferred': False}
    if raw.get('threadId') != thread:
        raise ValueError('thread mismatch')
    if len(raw.get('conversations', [])) > 1000 or len(raw.get('existingNotices', [])) > 1000:
        raise ValueError('reminder metadata budget')
    allowed = {(b['account'], b['peer']) for b in bindings}
    binding_ids = {b['id'] for b in bindings}
    seen = set()
    view = []
    for r in raw.get('conversations', []):
        pair = (r.get('account'), r.get('peer'))
        if pair not in allowed or pair in seen:
            raise ValueError('foreign or duplicated conversation')
        seen.add(pair)
        first = seconds(r.get('firstSourceTime'))
        latest = seconds(r.get('latestSourceTime'))
        if first > latest:
            raise ValueError('reversed reminder times')
        count = r.get('reminderCount')
        if type(count) != int or not 1 <= count <= 100000:
            raise ValueError('invalid reminder count')
        if not isinstance(r.get('latestSourceId'), str) or not re.fullmatch('[1-9][0-9]{0,24}', r['latestSourceId']):
            raise ValueError('invalid native source')
        view.append({k: r[k] for k in ['account', 'peer', 'latestSourceId', 'latestSourceTime', 'firstSourceTime', 'reminderCount']})
    count = raw.get('pending')
    evidence = raw.get('pendingEvidenceCount')
    if type(count) != int or type(evidence) != int or count != len(view) or (evidence != sum((v['reminderCount'] for v in view))):
        raise ValueError('conversation/evidence count mismatch')
    notices = []
    for n in raw.get('existingNotices', []):
        if n.get('binding') not in binding_ids:
            raise ValueError('foreign notice')
        notices.append({k: n.get(k) for k in ['id', 'binding', 'state', 'queue_id', 'native_id', 'turn_id']})
    return {'state': 'known', 'sampledAtUnix': seconds(raw.get('observedAt')), 'pending': count, 'pendingEvidenceCount': evidence, 'conversations': view, 'existingNotices': notices, 'readingOrBusinessCompletionInferred': False}

def read_pending(thread, bindings):
    if not bindings:
        return {'state': 'not_registered', 'pending': None, 'pendingEvidenceCount': None, 'conversations': [], 'existingNotices': [], 'readingOrBusinessCompletionInferred': False}
    if not re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', thread) or any((b['threadId'] != thread for b in bindings)):
        raise ValueError('explicit registered thread required')
    from live_core import checked_path
    code = _install.REPO / 'host/continuity/runtime.py'
    checked_path(code, [code.parent])
    checked_path(SYSTEM / 'registry.json', [SYSTEM])
    p = subprocess.run(['/usr/bin/python3', str(code), '--pending', '--registry', str(SYSTEM / 'registry.json'), '--thread-id', thread], capture_output=True, text=True, timeout=12)
    if p.returncode or len(p.stdout.encode()) > 4000000:
        raise ValueError('pending read failed or exceeded budget')
    return project_pending(json.loads(p.stdout), thread, bindings)
