"""Dedicated-user side of the owner reply bridge; reuse the native inbox and V2 sender."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from .config import WORKBENCH, load
from .wechat import environment, private_file

CLIENT = 'rsi-owner'


def binding_token(owner):
    return hashlib.sha256(json.dumps([owner['account'], owner['owner_peer'], owner.get('send_scope'),
        owner.get('reply_model_binding')], sort_keys=True).encode()).hexdigest()


def request_id(account, peer, server):
    return CLIENT + '-' + hashlib.sha256((account + '\0' + peer + '\0' + str(server)).encode()).hexdigest()


def binding(path, installation, enabled=True):
    if not private_file(path):
        raise ValueError('Private owner binding required.')
    value = json.loads(Path(path).read_text())
    if (value.get('confirmed_by_user') is not True or value.get('account') != installation['wechat']['account']
            or not isinstance(value.get('owner_peer'), str) or value['owner_peer'].endswith('@chatroom')
            or value['owner_peer'] == value['account']):
        raise ValueError('Confirmed private owner identity required.')
    if enabled:
        scope = value.get('send_scope') or {}
        if (value.get('auto_reply_enabled') is not True
                or scope.get('mode') not in ('owner-private-text', 'one-message')
                or type(scope.get('since')) is not int or scope['since'] <= 0):
            raise ValueError('Explicit owner reply scope is not enabled.')
    return value


def source(root, owner, request):
    from linux_tool import native, decode
    from receive_source import SourceInbox, sid
    scope = owner['send_scope']
    peer = owner['owner_peer']
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    path = root / 'owner-reply-source.sqlite'
    if request['op'] == 'ack':
        inbox = SourceInbox(path, None, table, owner['account'], peer, decode,
                            str(scope['since']), only_incoming=True)
        try:
            return inbox.ack(request['batch_id'], request['batch_hash'], request['ack_ids'])
        finally:
            inbox.close()
    with native('message/message_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed native source required.')
        inbox = SourceInbox(path, lambda: db, table, owner['account'], peer, decode,
                            str(scope['since']), only_incoming=True)
        try:
            mark = json.dumps(scope, sort_keys=True)
            old = inbox.c.execute("SELECT v FROM meta WHERE k='owner_scope'").fetchone()
            if old and old[0] != mark:
                raise ValueError('Original source scope changed; preserve its receipt database.')
            rows = db.execute('SELECT m.server_id,m.create_time FROM ' + table +
                ' m JOIN Name2Id n ON n.rowid=m.real_sender_id WHERE n.user_name=? LIMIT 100001', (peer,)).fetchall()
            if len(rows) > 100000:
                raise ValueError('Owner source exceeds bounded metadata review.')
            with inbox.c:
                inbox.c.execute("INSERT OR IGNORE INTO meta VALUES('owner_scope',?)", (mark,))
                for row in rows:
                    if not row['server_id']:
                        continue
                    key = sid(row['server_id'])
                    bootstrap = key == scope.get('bootstrap_server_id')
                    if not bootstrap and (scope['mode'] == 'one-message' or row['create_time'] < scope['since']):
                        inbox.c.execute('INSERT OR IGNORE INTO acked VALUES(?,?)', (key, time.time()))
            return inbox.read()
        finally:
            inbox.close()


def status(job):
    result = job.get('result') or {}
    return {'state': job['state'], 'request_id': job['request_id'],
            'outcome': job.get('outcome', {}).get('status'),
            'code': result.get('code'),
            'cleanup_pending': any(result.get(k) for k in
                ('postActionPending', 'draftRecoveryPending', 'navigationRecoveryPending'))}


def advance(api, job, policy):
    """Run only this immutable job through the original executor and display locks."""
    import fcntl
    from operations.runtime import Executor
    from operations.driver import NativeDriver
    from operations.dispatch import choose
    store = api.s

    class ScopedStore:
        def __getattr__(self, name):
            return getattr(store, name)

        def active(self):
            current = store.active()
            if current and current['id'] != job['id']:
                raise BlockingIOError('Another original request owns the queue.')
            return current

        def peek_ready(self):
            current = store.peek_ready()
            return current if current and current['id'] == job['id'] else None

        def claim(self):
            # Same original scheduling decision and transaction; never claim a foreign job.
            with store.tx():
                current = choose(store)
                if not current or current['id'] != job['id']:
                    return None
                store.c.execute("UPDATE jobs SET state='preparing',updated=? WHERE id=?", (time.time(), current['id']))
                store.event(current['id'], 'preparing')
            return store.by_id(current['id'])

    class ScopedExecutor(Executor):
        def recover_accepted_cleanup(self):
            return None  # Foreign originals and terminal cleanup belong to their original operator.

    fd = os.open(store.root / 'executor.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    driver = None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'busy'}
        ScopedStore().active()
        if job['state'] in ('executing', 'preparing'):
            state = 'unknown' if job['state'] == 'executing' else 'needs_attention'
            store.set_state(job['id'], state, {'reason': 'owner_reply_interrupted', 'automaticReplay': False})
            return status(api.view(store.by_id(job['id'])))
        driver = NativeDriver(store.root, policy)
        executor = ScopedExecutor(ScopedStore(), driver)
        for _ in range(3):
            executor.step()
            current = store.by_id(job['id'])
            if current['state'] != 'confirmed':
                break
        return status(api.view(store.by_id(job['id'])))
    except BlockingIOError:
        return {'state': 'busy'}
    finally:
        if driver is not None:
            driver.release()
        os.close(fd)


def handle(installation, owner, request):
    root = Path(installation['wechat']['runtime_root'])
    if request.get('_binding') != binding_token(owner):
        raise ValueError('Owner reply scope changed; preserve the original request.')
    request = {key: value for key, value in request.items() if key != '_binding'}
    op = request.get('op')
    fields = {'read': {'op'}, 'ack': {'op', 'batch_id', 'batch_hash', 'ack_ids'},
              'submit': {'op', 'server_id', 'text'}, 'advance': {'op', 'server_id'}}
    if op not in fields or set(request) != fields[op]:
        raise ValueError('Unsupported owner reply transport fields.')
    if op in ('read', 'ack'):
        return source(root, owner, request)
    from operations.cli import load_config
    from operations.public_api import PublicAPI
    from receive_source import sid
    server = sid(request['server_id'])
    rid = request_id(owner['account'], owner['owner_peer'], server)
    policy = load_config(root / 'operations-state/config.json')
    if policy['account'] != owner['account']:
        raise ValueError('Native sender account differs from confirmed binding.')
    api = PublicAPI(root / 'operations-state', policy)
    try:
        if op == 'submit':
            text = request['text']
            if not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > 16384:
                raise ValueError('Bounded nonempty reply text required.')
            job = api.call({'op': 'submit', 'job': {'client': CLIENT, 'request_id': rid,
                'peer': owner['owner_peer'], 'action': 'send_text', 'payload': {'text': text},
                'execution_mode': 'verified_fast'}})
            return status(job)
        job = api.s.get(CLIENT, rid)
        if job['peer'] != owner['owner_peer'] or job['action'] != 'send_text':
            raise ValueError('Original reply request binding changed.')
        return advance(api, job, policy)
    finally:
        api.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', required=True)
    parser.add_argument('--binding', required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    installation = load(args.installation)
    owner = binding(args.binding, installation, enabled=not args.check)
    if args.check:
        print(json.dumps({'state': 'ready', 'account': owner['account'], 'peer': owner['owner_peer'],
                          'scope': owner.get('send_scope'), 'binding_token': binding_token(owner),
                          'enabled': owner.get('auto_reply_enabled') is True}))
        return
    os.environ.update(environment(installation))
    sys.path.insert(0, str(WORKBENCH / 'wechat'))
    raw = sys.stdin.read(1000001)
    if len(raw.encode()) > 1000000:
        raise ValueError('Owner reply transport input too large.')
    print(json.dumps(handle(installation, owner, json.loads(raw)), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'state': 'blocked', 'code': type(error).__name__}))
        raise SystemExit(2)
