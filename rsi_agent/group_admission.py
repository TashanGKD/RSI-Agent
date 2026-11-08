"""Admit new owner-shared groups from native membership, without GUI input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time

from .config import ROOT, WORKBENCH, load
from .wechat import environment, private_file


def read_private(path):
    if not private_file(path):
        raise ValueError('Private admission configuration required.')
    return json.loads(Path(path).read_text())


def put(path, value, uid=None, gid=None):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('Admission path is a symlink.')
    temporary = path.with_name('.' + path.name + '-' + secrets.token_hex(6))
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        if uid is not None:
            os.fchown(stream.fileno(), uid, gid)
        stream.write(json.dumps(value) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def catalog(installation, owner_binding):
    from .reply_io import binding
    config = load(installation)
    owner = binding(owner_binding, config)
    os.environ.update(environment(config))
    sys.path.insert(0, str(WORKBENCH / 'wechat'))
    from linux_tool import native
    with native('contact/contact.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed native membership required.')
        rows = db.execute('SELECT c.username,c.nick_name,c.remark,g.id FROM contact c '
            'JOIN chat_room g ON g.username=c.username WHERE c.is_in_chat_room=1 LIMIT 101').fetchall()
        if len(rows) > 100:
            raise ValueError('Group catalog exceeds the supported registry capacity.')
        groups = []
        for row in rows:
            members = {r[0] for r in db.execute('SELECT c.username FROM chatroom_member m '
                'JOIN contact c ON c.id=m.member_id WHERE m.room_id=?', (row['id'],))}
            display = row['remark'] or row['nick_name'] or ''
            unique = bool(display) and db.execute('SELECT count(DISTINCT username) FROM contact '
                'WHERE username=? OR remark=? OR nick_name=? OR alias=?', (display,) * 4).fetchone()[0] == 1
            groups.append({'peer': row['username'], 'name': row['nick_name'] or '',
                'display_name': display, 'addressable': unique, 'self_present': owner['account'] in members,
                'owner_present': owner['owner_peer'] in members})
    return {'account': owner['account'], 'owner_peer': owner['owner_peer'],
            'reply_model_binding': owner['reply_model_binding'], 'groups': groups,
            'checked_at': int(time.time())}


def provision(registry, owner_config, snapshot, group, since, uid, gid):
    """Write immutable per-group scope before making it visible to the worker."""
    from .group_io import token
    from .config import load
    key = hashlib.sha256(group['peer'].encode()).hexdigest()[:24]
    state = registry.parent / ('auto-' + key)
    config_path = state / 'config.json'
    if state.is_symlink():
        raise ValueError('Automatic group state is a symlink.')
    if config_path.exists():
        old = read_private(config_path)
        original = json.loads(Path(old['binding']).read_text())
        if (old['state'] != str(state) or old['model'] != owner_config['model']
                or original['group_peer'] != group['peer'] or original['account'] != snapshot['account']
                or original['owner_peer'] != snapshot['owner_peer']):
            raise ValueError('Earlier automatic admission changed; preserve its state.')
        return config_path
    runtime = Path(load(owner_config['installation'])['wechat']['runtime_root'])
    bindings = runtime / 'auto-groups'
    bindings.mkdir(mode=0o700, exist_ok=True)
    if bindings.is_symlink() or bindings.stat().st_mode & 0o077:
        raise ValueError('Private binding directory required.')
    os.chown(bindings, uid, gid)
    binding_path = bindings / (key + '.json')
    value = {'account': snapshot['account'], 'owner_peer': snapshot['owner_peer'],
        'group_peer': group['peer'], 'confirmed_by_user': True,
        'admission': 'new-owner-shared-group', 'auto_reply_enabled': True,
        'reply_model_binding': snapshot['reply_model_binding'],
        'send_scope': {'mode': 'invited-group-text', 'since': since, 'name': group['name'],
                       'introduction': False}}
    put(binding_path, value, uid, gid)
    # Identity seed only. No pixel/header claim or editor coordinates: the
    # existing native navigation must prove the actual target before input.
    import fcntl
    fd = os.open(runtime / 'native-ui.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        os.fchown(fd, uid, gid)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        targets_path = runtime / 'tool-targets.json'
        if targets_path.is_symlink():
            raise ValueError('Native target registry is a symlink.')
        targets = json.loads(targets_path.read_text()) if targets_path.exists() else {}
        targets.setdefault(group['peer'], {'peer': group['peer'], 'displayName': group['display_name'],
                                          'paired_account': snapshot['account']})
        put(targets_path, targets, uid, gid)
    finally:
        os.close(fd)
    state.mkdir(mode=0o700, exist_ok=True)
    if state.is_symlink() or state.stat().st_mode & 0o077 or state.stat().st_uid != os.getuid():
        raise ValueError('Private per-group state required.')
    put(config_path, {'installation': owner_config['installation'], 'binding': str(binding_path),
        'model': owner_config['model'], 'state': str(state), 'enabled': True, 'binding_token': token(value)})
    return config_path


def refresh(registry):
    registry = Path(registry)
    policy_path = registry.with_name('admission.json')
    if not policy_path.exists():
        return None
    policy = read_private(policy_path)
    if policy.get('enabled') is not True:
        return None
    owner_config = read_private(policy['owner_config'])
    result = subprocess.run(['runuser', '-u', 'wechat-gui', '--', sys.executable, '-B',
        '-m', 'rsi_agent.group_admission', '--installation', owner_config['installation'],
        '--binding', owner_config['binding']], cwd=ROOT, capture_output=True, text=True, timeout=25)
    if result.returncode or len(result.stdout.encode()) > 100000:
        raise ValueError('Native group catalog unavailable.')
    snapshot = json.loads(result.stdout)
    if snapshot['account'] != policy['account'] or snapshot['owner_peer'] != policy['owner_peer']:
        raise ValueError('Automatic admission owner/account changed.')
    registry_value = read_private(registry)
    existing = set(policy['initial_groups'])
    for path in registry_value['groups']:
        config = read_private(path)
        existing.add(json.loads(Path(config['binding']).read_text())['group_peer'])
    import pwd
    user = pwd.getpwnam('wechat-gui')
    added, waiting, unaddressable = 0, 0, 0
    since = max(policy['since'], policy['last_checked'])
    for group in snapshot['groups']:
        if group['peer'] in existing or not group['self_present']:
            continue
        if not group['owner_present']:
            waiting += 1
            continue
        if not group['name'] or not group['addressable']:
            unaddressable += 1
            continue
        if len(registry_value['groups']) >= 100:
            raise ValueError('Group registry capacity reached.')
        path = provision(registry, owner_config, snapshot, group, since, user.pw_uid, user.pw_gid)
        registry_value['groups'].append(str(path))
        put(registry, registry_value)
        existing.add(group['peer'])
        added += 1
    policy['last_checked'] = snapshot['checked_at']
    put(policy_path, policy)
    status = {'state': 'enabled', 'checked_at': time.time(), 'added': added,
              'waiting_owner': waiting, 'unaddressable': unaddressable}
    put(registry.with_name('admission-status.json'), status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', required=True)
    parser.add_argument('--binding', required=True)
    args = parser.parse_args()
    print(json.dumps(catalog(args.installation, args.binding)))


if __name__ == '__main__':
    main()
