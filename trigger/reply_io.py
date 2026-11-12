"""Dedicated-user side of the owner reply bridge; reuse the native inbox and V2 sender."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

from rsi_agent.config import WECHAT_LINUX, load
from rsi_agent.wechat import environment, private_file

CLIENT = 'rsi-owner'
FRIEND_CLIENT = 'rsi-friend'
FRIEND_MODE = 'friend-private-chat'


def binding_token(owner):
    identity = [owner['account'], owner['owner_peer'], owner.get('send_scope'), owner.get('reply_model_binding')]
    if 'friend_peer' in owner:
        identity.append(owner['friend_peer'])
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def request_id(account, peer, server, client=CLIENT):
    return client + '-' + hashlib.sha256((account + '\0' + peer + '\0' + str(server)).encode()).hexdigest()


def binding(path, installation, enabled=True):
    if not private_file(path):
        raise ValueError('Private owner binding required.')
    value = json.loads(Path(path).read_text())
    scope = value.get('send_scope') or {}
    if (value.get('confirmed_by_user') is not True or value.get('account') != installation['wechat']['account']
            or not isinstance(value.get('owner_peer'), str) or value['owner_peer'].endswith('@chatroom')
            or value['owner_peer'] == value['account']):
        raise ValueError('Confirmed private owner identity required.')
    if 'friend_peer' in value or scope.get('mode') == FRIEND_MODE:
        import re
        peer = value.get('friend_peer')
        if (scope.get('mode') != FRIEND_MODE or not isinstance(peer, str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,120}', peer)
                or '..' in peer or peer in (value['account'], value['owner_peer'])):
            raise ValueError('Distinct native friend required.')
    if enabled:
        if (value.get('auto_reply_enabled') is not True
                or scope.get('mode') not in ('owner-private-text', 'one-message', FRIEND_MODE)
                or type(scope.get('since')) is not int or scope['since'] <= 0):
            raise ValueError('Explicit owner reply scope is not enabled.')
    return value


def require_friend(peer):
    from linux_tool import native
    from operations.proof import friend
    with native('contact/contact.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed native friendship required.')
        rows = db.execute('SELECT local_type,flag,delete_flag FROM contact WHERE username=? LIMIT 2', (peer,)).fetchall()
        if len(rows) != 1 or not friend(dict(rows[0])):
            raise ValueError('Current native friendship required.')


def source(root, owner, request):
    from linux_tool import native, decode
    from receive_source import SourceInbox, sid
    scope = owner['send_scope']
    peer = owner.get('friend_peer', owner['owner_peer'])
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    path = root / (table + '-friend-source.sqlite' if 'friend_peer' in owner else 'owner-reply-source.sqlite')
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
        if 'friend_peer' in owner and not db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            return {'events': []}

        def context(row, event):
            if event['kind'] != 49:
                return {}
            from .link_reader import shared_link
            from .media import pdf_name
            raw = decode(row['message_content'])
            if raw.startswith(event['sender'] + ':\n'):
                raw = raw[len(event['sender']) + 2:]
            link = shared_link(raw)
            if link:
                return {'link': link}
            name = pdf_name(raw)
            return {'pdf_name': name} if name else {}

        inbox = SourceInbox(path, lambda: db, table, owner['account'], peer, decode,
                            str(scope['since']), only_incoming=True, event_context=context)
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
            result = inbox.read()
            from .finder_cover import annotate
            for event in result.get('events', []):
                annotate(event)
            return result
        finally:
            inbox.close()


def status(job):
    result = job.get('result') or {}
    value = {'state': job['state'], 'request_id': job['request_id'],
            'outcome': job.get('outcome', {}).get('status'),
            'code': result.get('code'),
            'cleanup_pending': any(result.get(k) for k in
                ('postActionPending', 'draftRecoveryPending', 'navigationRecoveryPending'))}
    if job.get('action') == 'send_text':
        value['reply_sha256'] = hashlib.sha256(job['payload']['text'].encode()).hexdigest()
    return value


def original_status(api, job, client):
    """Read the existing receipt without claiming or advancing its send."""
    return dict(status(api.view(job)), recoverable_preinput_failure=failed_before_input(api.s, job, client))


def failed_before_input(store, job, client):
    from operations import navigation
    result = job.get('result') or {}
    if job['state'] == 'cancelled' and job['client'] == client and job['action'] == 'send_text':
        from .group_text import untouched_part
        return untouched_part(store, job)
    if (job['state'] != 'failed' or job['client'] != client or job['action'] != 'send_text'
            or job.get('preview') is not None or result.get('noSend') is not True
            or result.get('sideEffectStarted') is not False
            or any(result.get(k) for k in ('postActionPending', 'draftRecoveryPending', 'navigationRecoveryPending'))):
        return False
    events = [row[0] for row in store.c.execute('SELECT state FROM events WHERE job_id=? ORDER BY seq', (job['id'],))]
    if events != ['queued', 'preparing', 'failed']:
        if (events != ['queued', 'preparing', 'needs_attention', 'failed']
                or result.get('code') != 'NAVIGATION_PREPARATION_FAILED'
                or result.get('navigationRestored') is not True or result.get('automaticReplay') is not False):
            return False
    journal = navigation.path(store.root, job)
    if any(path != journal for path in store.root.glob(job['id'] + '-*')):
        return False
    original = navigation.load(store.root, job)
    if not original or original.get('state') != 'settled':
        return False
    if client == FRIEND_CLIENT and result.get('code') == 'DRAFT_PROTECTED':
        return original.get('protectedDraft') is True and original.get('priorDraftWindowRetained') is True
    return True


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
    fields = {'read': {'op'}, 'image': {'op', 'server_id'}, 'pdf': {'op', 'server_id'},
              'ack': {'op', 'batch_id', 'batch_hash', 'ack_ids'},
              'submit': {'op', 'server_id', 'text'}, 'advance': {'op', 'server_id'}}
    if 'friend_peer' in owner:
        fields['status'] = {'op', 'server_id'}
    elif owner['send_scope']['mode'] == 'owner-private-text':
        fields['voice'] = {'op', 'server_id'}
    if op not in fields or set(request) != fields[op]:
        raise ValueError('Unsupported owner reply transport fields.')
    peer = owner.get('friend_peer', owner['owner_peer'])
    client = CLIENT
    if 'friend_peer' in owner:
        require_friend(peer)
        client = FRIEND_CLIENT
    if op in ('read', 'ack'):
        return source(root, owner, request)
    if op == 'image':
        from .media_io import image
        return image(root, owner['account'], peer, request['server_id'], {peer})
    if op == 'voice':
        from .voice_input import read_owner_voice
        return read_owner_voice(peer, request['server_id'], owner['send_scope']['since'])
    if op == 'pdf':
        from .media_io import pdf
        scope = owner['send_scope']
        if scope['mode'] not in ('owner-private-text', FRIEND_MODE):
            raise ValueError('PDFs require a continuous private scope.')
        return pdf(owner['account'], peer, request['server_id'], {peer}, scope['since'])
    from operations.cli import load_config
    from operations.public_api import PublicAPI
    from receive_source import sid
    server = sid(request['server_id'])
    rid = request_id(owner['account'], peer, server, client)
    policy = load_config(root / 'operations-state/config.json')
    if policy['account'] != owner['account']:
        raise ValueError('Native sender account differs from confirmed binding.')
    state = root / 'operations-state'
    if op == 'status' and not (state / 'queue.sqlite').is_file():
        raise ValueError('Original friend queue is missing.')
    api = PublicAPI(state, policy)
    try:
        if op == 'submit':
            text = request['text']
            if not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > 16384:
                raise ValueError('Bounded nonempty reply text required.')
            job = api.call({'op': 'submit', 'job': {'client': client, 'request_id': rid,
                'peer': peer, 'action': 'send_text', 'payload': {'text': text},
                'execution_mode': 'verified_fast'}})
            return status(job)
        job = api.s.get(client, rid)
        if job['peer'] != peer or job['action'] != 'send_text':
            raise ValueError('Original reply request binding changed.')
        if op == 'status':
            return original_status(api, job, client)
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
        print(json.dumps({'state': 'ready', 'account': owner['account'], 'peer': owner.get('friend_peer', owner['owner_peer']),
                          'scope': owner.get('send_scope'), 'binding_token': binding_token(owner),
                          'enabled': owner.get('auto_reply_enabled') is True}))
        return
    os.environ.update(environment(installation))
    sys.path.insert(0, str(WECHAT_LINUX))
    raw = sys.stdin.read(1000001)
    if len(raw.encode()) > 1000000:
        raise ValueError('Owner reply transport input too large.')
    print(json.dumps(handle(installation, owner, json.loads(raw)), ensure_ascii=False))


def cli():
    try:
        main()
    except Exception as error:
        print(json.dumps({'state': 'blocked', 'code': type(error).__name__}))
        raise SystemExit(2)


if __name__ == '__main__':
    cli()
