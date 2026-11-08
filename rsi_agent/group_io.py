"""Native group data and original V2 sends for one explicitly invited group."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from xml.etree import ElementTree as ET

from .config import WORKBENCH, load
from .reply_io import advance, status
from .wechat import environment, private_file

CLIENT = 'rsi-group'
INTRODUCTION = '大家好，我是 RSI Agent，受邀参与群里的讨论。我会优先回应 @ 和提问，有合适的补充时简短发言，平时不刷屏。'


def token(value):
    return hashlib.sha256(json.dumps([value['account'], value['owner_peer'], value['group_peer'],
        value['send_scope'], value['reply_model_binding']], sort_keys=True).encode()).hexdigest()


def group_info(value):
    from linux_tool import native
    with native('contact/contact.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed group membership required.')
        row = db.execute('SELECT c.nick_name,c.is_in_chat_room,g.id FROM contact c '
            'JOIN chat_room g ON g.username=c.username WHERE c.username=?', (value['group_peer'],)).fetchone()
        if not row or row['is_in_chat_room'] != 1 or row['nick_name'] != value['send_scope']['name']:
            raise ValueError('Invited group identity changed.')
        members = {r['username']: r['nick_name'] for r in db.execute('SELECT c.username,c.nick_name '
            'FROM chatroom_member m JOIN contact c ON c.id=m.member_id WHERE m.room_id=?', (row['id'],))}
        if value['account'] not in members or value['owner_peer'] not in members or len(members) > 1000:
            raise ValueError('Self and inviting owner must remain in the confirmed group.')
        return members


def load_binding(path, installation):
    if not private_file(path):
        raise ValueError('Private invited-group binding required.')
    value = json.loads(Path(path).read_text())
    scope = value.get('send_scope') or {}
    if (value.get('confirmed_by_user') is not True
            or not (value.get('invited_by_owner') is True or value.get('admission') == 'new-owner-shared-group')
            or value.get('account') != installation['wechat']['account']
            or not isinstance(value.get('group_peer'), str) or not value['group_peer'].endswith('@chatroom')
            or scope.get('mode') != 'invited-group-text' or type(scope.get('since')) is not int
            or not isinstance(scope.get('name'), str) or not scope['name']):
        raise ValueError('Explicit invited-group scope required.')
    return value


def mentioned(source, account):
    if not isinstance(source, str) or len(source.encode()) > 100000 or '<!DOCTYPE' in source.upper() or '<!ENTITY' in source.upper():
        return False
    try:
        names = ET.fromstring(source).findtext('.//atuserlist') or ''
        return account in {s.strip() for s in names.split(',')}
    except ET.ParseError:
        return False


def read_group(root, value, request, members):
    from linux_tool import native, decode
    from receive_source import SourceInbox, sid
    peer, scope = value['group_peer'], value['send_scope']
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    path = root / ('group-source-' + hashlib.sha256(peer.encode()).hexdigest()[:20] + '.sqlite')

    def context(row, event):
        previous = db.execute('SELECT real_sender_id,local_type FROM ' + table +
            ' WHERE (local_type & 4294967295)=1 AND (create_time,COALESCE(sort_seq,0),local_id)<(?,?,?)'
            ' ORDER BY create_time DESC,COALESCE(sort_seq,0) DESC,local_id DESC LIMIT 1',
            (row['create_time'], row['sort_seq'] or 0, row['local_id'])).fetchone()
        return {'sender_name': members.get(event['sender']) or '群成员',
                'mentioned': mentioned(decode(row['source']), value['account']) if 'source' in row.keys() else False,
                'follows_self': bool(previous and names.get(previous['real_sender_id']) == value['account']
                    and int(previous['local_type']) & 0xffffffff == 1)}

    if request['op'] == 'ack':
        inbox = SourceInbox(path, None, table, value['account'], peer, decode, str(scope['since']),
            only_incoming=True, incoming_senders=members)
        try:
            return inbox.ack(request['batch_id'], request['batch_hash'], request['ack_ids'])
        finally:
            inbox.close()
    with native('message/message_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed group messages required.')
        names = {r[0]: r[1] for r in db.execute('SELECT rowid,user_name FROM Name2Id')}
        rows = db.execute('SELECT real_sender_id,message_content,source,create_time FROM ' + table +
            ' WHERE (local_type & 4294967295)=1 ORDER BY create_time DESC,COALESCE(sort_seq,0) DESC,local_id DESC LIMIT 20').fetchall()
        history = []
        for row in reversed(rows):
            sender = names.get(row['real_sender_id'])
            if sender not in members:
                continue
            text = decode(row['message_content'])
            if text.startswith(sender + ':\n'):
                text = text[len(sender) + 2:]
            history.append({'name': members[sender] or '群成员', 'text': text[:2000],
                'self': sender == value['account'], 'time': row['create_time'],
                'mentioned': mentioned(decode(row['source']), value['account'])})
        if request['op'] == 'context':
            return {'messages': history, 'consistency': 'committed'}
        inbox = SourceInbox(path, lambda: db, table, value['account'], peer, decode,
            str(scope['since']), only_incoming=True, incoming_senders=members, event_context=context)
        try:
            mark = json.dumps(scope, sort_keys=True)
            old = inbox.c.execute("SELECT v FROM meta WHERE k='group_scope'").fetchone()
            if old and old[0] != mark:
                raise ValueError('Original group source scope changed.')
            with inbox.c:
                inbox.c.execute("INSERT OR IGNORE INTO meta VALUES('group_scope',?)", (mark,))
                for row in db.execute('SELECT server_id FROM ' + table + ' WHERE create_time<? AND server_id!=0', (scope['since'],)):
                    inbox.c.execute('INSERT OR IGNORE INTO acked VALUES(?,?)', (sid(row[0]), time.time()))
            result = inbox.read()
            for event in result.get('events', []):
                if event['text'].startswith(event['sender'] + ':\n'):
                    event['text'] = event['text'][len(event['sender']) + 2:]
                from .finder_cover import annotate
                annotate(event)
            result['context'] = history
            return result
        finally:
            inbox.close()


def handle(installation, value, request):
    if request.get('_binding') != token(value):
        raise ValueError('Invited group scope changed.')
    request = {k: v for k, v in request.items() if k != '_binding'}
    fields = {'read': {'op'}, 'context': {'op'}, 'image': {'op', 'server_id'}, 'ack': {'op', 'batch_id', 'batch_hash', 'ack_ids'},
        'submit': {'op', 'server_id', 'text'}, 'advance': {'op', 'server_id'}}
    op = request.get('op')
    if op not in fields or set(request) != fields[op] or value.get('auto_reply_enabled') is not True:
        raise ValueError('Group action is outside its enabled scope.')
    members = group_info(value)
    root = Path(installation['wechat']['runtime_root'])
    if op in ('read', 'ack', 'context'):
        return read_group(root, value, request, members)
    if op == 'image':
        from .media_io import image
        return image(root, value['account'], value['group_peer'], request['server_id'], set(members) - {value['account']})
    from operations.cli import load_config
    from operations.public_api import PublicAPI
    from receive_source import sid
    server = request['server_id']
    if server == 'introduction':
        server = 'introduction:' + str(value['send_scope']['since'])
        if op == 'submit' and request['text'] != INTRODUCTION:
            raise ValueError('Only the fixed one-time introduction is allowed.')
    else:
        server = sid(server)
    rid = CLIENT + '-' + hashlib.sha256((value['account'] + '\0' + value['group_peer'] + '\0' + server).encode()).hexdigest()
    policy = load_config(root / 'operations-state/config.json')
    if policy['account'] != value['account']:
        raise ValueError('Group sender account changed.')
    api = PublicAPI(root / 'operations-state', policy)
    try:
        if op == 'submit':
            text = request['text']
            if not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > 6000:
                raise ValueError('Short group text required.')
            return status(api.call({'op': 'submit', 'job': {'client': CLIENT, 'request_id': rid,
                'peer': value['group_peer'], 'action': 'send_text', 'payload': {'text': text},
                'execution_mode': 'verified_fast'}}))
        job = api.s.get(CLIENT, rid)
        if job['peer'] != value['group_peer'] or job['action'] != 'send_text':
            raise ValueError('Original group request changed.')
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
    os.environ.update(environment(installation))
    sys.path.insert(0, str(WORKBENCH / 'wechat'))
    value = load_binding(args.binding, installation)
    if args.check:
        members = group_info(value)
        print(json.dumps({'state': 'ready', 'account': value['account'], 'peer': value['group_peer'],
            'owner_peer': value['owner_peer'],
            'name': value['send_scope']['name'], 'scope': value['send_scope'],
            'enabled': value.get('auto_reply_enabled') is True, 'binding_token': token(value),
            'member_count': len(members)}, ensure_ascii=False))
    else:
        raw = sys.stdin.read(1000001)
        if len(raw.encode()) > 1000000:
            raise ValueError('Group request too large.')
        print(json.dumps(handle(installation, value, json.loads(raw)), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'state': 'blocked', 'code': type(error).__name__}))
        raise SystemExit(2)
