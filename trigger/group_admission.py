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

from rsi_agent.config import ROOT, WECHAT_LINUX, load
from rsi_agent.wechat import environment, private_file


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


def catalog(installation, owner_binding, friends_enabled=False):
    from .reply_io import binding
    config = load(installation)
    owner = binding(owner_binding, config)
    if 'friend_peer' in owner:
        raise ValueError('Automatic admission requires the original owner binding.')
    os.environ.update(environment(config))
    sys.path.insert(0, str(WECHAT_LINUX))
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
        friends = friend_catalog(db, owner) if friends_enabled else []
    return {'account': owner['account'], 'owner_peer': owner['owner_peer'], 'friends': friends,
            'reply_model_binding': owner['reply_model_binding'], 'groups': groups,
            'checked_at': int(time.time())}


def friend_catalog(db, owner):
    from operations.proof import friend
    rows = db.execute('SELECT username,nick_name,remark,local_type,flag,delete_flag FROM contact '
        "WHERE local_type=1 AND username NOT IN (?,?) AND username NOT LIKE '%@%' "
        "AND username NOT GLOB 'gh_*' LIMIT 1001",
        (owner['account'], owner['owner_peer'])).fetchall()
    if len(rows) > 1000:
        raise ValueError('Friend contact catalog exceeds the supported capacity.')
    result = []
    for row in rows:
        if not friend(dict(row)):
            continue
        peer = row['username']
        display = row['remark'] or row['nick_name'] or peer
        unique = db.execute('SELECT DISTINCT username FROM contact '
            'WHERE username=? OR remark=? OR nick_name=? OR alias=? LIMIT 2', (display,) * 4).fetchall()
        if len(unique) == 1 and unique[0][0] == peer:
            result.append({'peer': peer, 'display_name': display})
    return result


def provision(registry, owner_config, snapshot, group, since, uid, gid, *, friend_scope=None, joined=False):
    """Write immutable per-peer scope before making it visible to the worker."""
    from .group_io import token
    from .reply_io import binding_token
    from rsi_agent.config import load
    is_friend = friend_scope is not None
    peer_key = 'friend_peer' if is_friend else 'group_peer'
    key = hashlib.sha256(group['peer'].encode()).hexdigest()[:24]
    state = registry.parent / (('friend-' if is_friend else 'auto-') + key)
    config_path = state / 'config.json'
    if state.is_symlink():
        raise ValueError('Automatic group state is a symlink.')
    if config_path.exists():
        old = read_private(config_path)
        original = json.loads(Path(old['binding']).read_text())
        if (old['state'] != str(state) or old['model'] != owner_config['model']
                or original[peer_key] != group['peer'] or original['account'] != snapshot['account']
                or original['owner_peer'] != snapshot['owner_peer']):
            raise ValueError('Earlier automatic admission changed; preserve its state.')
        return config_path
    runtime = Path(load(owner_config['installation'])['wechat']['runtime_root'])
    bindings = runtime / ('auto-friends' if is_friend else 'auto-groups')
    bindings.mkdir(mode=0o700, exist_ok=True)
    if bindings.is_symlink() or bindings.stat().st_mode & 0o077:
        raise ValueError('Private binding directory required.')
    os.chown(bindings, uid, gid)
    binding_path = bindings / (key + '.json')
    value = {'account': snapshot['account'], 'owner_peer': snapshot['owner_peer'],
        peer_key: group['peer'], 'confirmed_by_user': True, 'auto_reply_enabled': True,
        'reply_model_binding': snapshot['reply_model_binding']}
    if is_friend:
        value['send_scope'] = friend_scope
    else:
        value['admission'] = 'native-joined-group' if joined else 'new-owner-shared-group'
        value['send_scope'] = {'mode': 'invited-group-text', 'since': since, 'name': group['name'], 'introduction': False}
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
        'model': owner_config['model'], 'state': str(state), 'enabled': True,
        'binding_token': binding_token(value) if is_friend else token(value)})
    return config_path


def refresh(registry):
    registry = Path(registry)
    policy_path = registry.with_name('admission.json')
    if not policy_path.exists():
        return None
    policy = read_private(policy_path)
    if policy.get('enabled') is not True:
        return None
    conversation_since = policy.get('conversation_since')
    if conversation_since is not None and (type(conversation_since) is not int or conversation_since <= 0):
        raise ValueError('An explicit positive conversation activation time is required.')
    owner_config = read_private(policy['owner_config'])
    command = ['runuser', '-u', 'wechat-gui', '--', sys.executable, '-B',
        '-m', 'trigger.group_admission', '--installation', owner_config['installation'],
        '--binding', owner_config['binding']]
    if conversation_since is not None:
        command.append('--friends')
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=25)
    if result.returncode or len(result.stdout.encode()) > 100000:
        raise ValueError('Native group catalog unavailable.')
    snapshot = json.loads(result.stdout)
    if snapshot['account'] != policy['account'] or snapshot['owner_peer'] != policy['owner_peer']:
        raise ValueError('Automatic admission owner/account changed.')
    registry_value = read_private(registry)
    existing = set(policy['initial_groups']) if conversation_since is None else set()
    for path in registry_value['groups']:
        config = read_private(path)
        existing.add(json.loads(Path(config['binding']).read_text())['group_peer'])
    import pwd
    user = pwd.getpwnam('wechat-gui')
    added, waiting, unaddressable = 0, 0, 0
    since = max(policy['since'], policy['last_checked'], conversation_since or 0)
    for group in snapshot['groups']:
        if group['peer'] in existing or not group['self_present']:
            continue
        if not group['owner_present'] and conversation_since is None:
            waiting += 1
            continue
        if not group['name'] or not group['addressable']:
            unaddressable += 1
            continue
        if len(registry_value['groups']) >= 100:
            raise ValueError('Group registry capacity reached.')
        path = provision(registry, owner_config, snapshot, group, since, user.pw_uid, user.pw_gid,
                         joined=not group['owner_present'])
        registry_value['groups'].append(str(path))
        put(registry, registry_value)
        existing.add(group['peer'])
        added += 1
    friends_added = 0
    if conversation_since is not None:
        friends_added = refresh_friends(registry.with_name('friends.json'), owner_config, snapshot,
                                        policy, user.pw_uid, user.pw_gid)
    policy['last_checked'] = snapshot['checked_at']
    put(policy_path, policy)
    status = {'state': 'enabled', 'checked_at': time.time(), 'added': added,
              'waiting_owner': waiting, 'unaddressable': unaddressable, 'friends_added': friends_added}
    put(registry.with_name('admission-status.json'), status)
    return status


def refresh_friends(registry, owner_config, snapshot, policy, uid, gid):
    from .reply_io import FRIEND_MODE
    value = read_private(registry) if registry.exists() else {'friends': []}
    existing = {json.loads(Path(read_private(p)['binding']).read_text())['friend_peer'] for p in value['friends']}
    added = 0
    for contact in snapshot['friends']:
        if contact['peer'] in existing:
            continue
        if len(value['friends']) >= 100:
            raise ValueError('Friend conversation registry capacity reached.')
        scope = {'mode': FRIEND_MODE, 'since': max(policy['conversation_since'], policy['last_checked']),
                 'greeting': True}
        bootstrap = policy.get('friend_bootstrap') or {}
        if bootstrap.get('peer') == contact['peer']:
            scope['bootstrap_server_id'] = bootstrap['server_id']
        path = provision(registry, owner_config, snapshot, contact, scope['since'], uid, gid, friend_scope=scope)
        value['friends'].append(str(path))
        put(registry, value)
        existing.add(contact['peer'])
        added += 1
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--friends', action='store_true')
    args = parser.parse_args()
    print(json.dumps(catalog(args.installation, args.binding, args.friends)))


if __name__ == '__main__':
    main()
