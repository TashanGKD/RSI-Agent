"""Central read-only native mention source. No arguments: help only."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, json, time, re, sys, hashlib
from pathlib import Path
from xml.etree import ElementTree as ET
ACCOUNT = _install.setting('continuity.native_source', 'ACCOUNT', 'wxid_fixture_operator')
OWNER = _install.setting('continuity.native_source', 'OWNER', 'wxid_fixture_owner')
RELEASE = str(_install.REPO / 'wechat')
PROFILE = _install.path('wechat_profile') / 'db_storage/message/message_0.db'
MAX_ROUTES = 128

def mentions(s):
    if not isinstance(s, str) or len(s.encode()) > 65536 or '<!DOCTYPE' in s.upper() or ('<!ENTITY' in s.upper()):
        raise ValueError('bounded non-entity source')
    matches = re.findall('<atuserlist>(.*?)</atuserlist>', s, re.S)
    if len(matches) > 1:
        raise ValueError('ambiguous at source')
    if not matches:
        return []
    s = matches[0]
    if s.startswith('<![CDATA[') and s.endswith(']]>'):
        s = s[9:-3]
    if len(s) > 12000 or not re.fullmatch('[A-Za-z0-9_@, .-]*', s):
        raise ValueError('at identity')
    ids = [x.strip() for x in s.split(',') if x.strip()]
    if len(ids) > 100:
        raise ValueError('at cap')
    return ids

def valid_aliases(xs):
    return isinstance(xs, list) and 1 <= len(xs) <= 10 and all((isinstance(x, str) and re.fullmatch('[A-Za-z0-9\\u4e00-\\u9fff_-]{2,24}', x) for x in xs)) and (len({x.casefold() for x in xs}) == len(xs))

def addressed_names(text, aliases):
    if not isinstance(text, str) or len(text.encode()) > 65536:
        return []
    canonical = {x.casefold(): x for x in aliases}
    pattern = re.compile('\\s*[@＠](' + '|'.join((re.escape(x) for x in sorted(set(aliases), key=len, reverse=True))) + ')(?=$|[\\s:：,，、;；.!！?？@＠]|(?:\\u8bf7|\\u9ebb\\u70e6)(?:\\u4f60|\\u60a8))', re.IGNORECASE) if aliases else None
    if pattern is None:
        return []
    names = []
    pos = 0
    while True:
        m = pattern.match(text, pos)
        if not m:
            break
        name = canonical.get(m[1].casefold())
        if name is None:
            return []
        names.append(name)
        pos = m.end()
    return list(dict.fromkeys(names))

def current_quote_text(text):
    if not isinstance(text, str) or len(text.encode()) > 65536 or re.search('<!\\s*(DOCTYPE|ENTITY)', text, re.I):
        return ''
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return ''
    apps = root.findall('./appmsg') if root.tag == 'msg' else []
    if len(apps) != 1:
        return ''
    app = apps[0]
    titles = app.findall('./title')
    types = app.findall('./type')
    if len(titles) != 1 or len(types) != 1 or len(titles[0]) or len(types[0]) or (types[0].text != '57'):
        return ''
    return titles[0].text or ''

def validated_routes(rows):
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROUTES:
        raise ValueError('route cap')
    seen = set()
    private_names = set()
    binding_ids = set()
    for b in rows:
        if not isinstance(b, dict):
            raise ValueError('route object')
        if b.get('account') != ACCOUNT or not re.fullmatch('[a-z][a-z0-9_-]{0,40}', str(b.get('id', ''))) or b['id'] in binding_ids:
            raise ValueError('route')
        binding_ids.add(b['id'])
        if b.get('triggerMode') == 'owner_name':
            if b.get('peer') != OWNER or b.get('ownerId') != OWNER or (not valid_aliases(b.get('aliases'))):
                raise ValueError('private route')
            normalized = {x.casefold() for x in b['aliases']}
            if private_names.intersection(normalized):
                raise ValueError('ambiguous employee name')
            private_names.update(normalized)
        else:
            if b.get('triggerMode') not in [None, 'native_at'] or not re.fullmatch('[0-9]{5,20}@chatroom', str(b.get('peer', ''))) or b['peer'] in seen:
                raise ValueError('group route')
            seen.add(b['peer'])
        if 'ownerTextAliases' in b and (b.get('ownerId') != OWNER or not valid_aliases(b['ownerTextAliases'])):
            raise ValueError('owner group aliases')
        if type(b.get('since')) is not int or b['since'] < 1 or b['since'] > int(time.time()) + 60:
            raise ValueError('since')
    return rows

def peer_gap(binding, reason):
    return dict(kind='source_gap', binding=binding['id'], observedAt=time.time(), reason=reason, coverage={'complete': False, 'scope': 'registered peer native mention or explicit owner employee name', 'rawTextReturned': False})

def read(routes):
    sys.path.insert(0, RELEASE)
    from linux_tool import native, decode, ACCOUNT as actual
    from receive_source import sid
    if actual != ACCOUNT:
        raise ValueError('account deployment mismatch')
    results = []
    all_names = [n for b in routes if b.get('triggerMode') == 'owner_name' for n in b['aliases']]
    with native('message/message_0.db') as (c, receipt):
        if receipt.get('gap') or receipt.get('integrity') != 'ok':
            raise ValueError('native snapshot incomplete')
        for b in routes:
            table = 'Msg_' + hashlib.md5(b['peer'].encode()).hexdigest()
            if not c.execute('select 1 from sqlite_master where type=? and name=?', ('table', table)).fetchone():
                results.append(peer_gap(b, 'message_table_missing'))
                continue
            rows = c.execute('select server_id,create_time,local_type,real_sender_id,source,local_id from ' + table + ' where create_time>=? order by create_time,sort_seq,local_id limit 1001', (max(b['since'], int(time.time()) - 172800),)).fetchall()
            if len(rows) > 1000:
                results.append(peer_gap(b, 'peer_window_exceeded'))
                continue
            events = []
            ambiguities = []
            for row in rows:
                kind = int(row['local_type']) & 4294967295
                app_type = int(row['local_type']) >> 32
                if not row['server_id'] or (kind != 1 and (not (kind == 49 and app_type == 57))):
                    continue
                person = c.execute('select user_name from Name2Id where rowid=?', (row['real_sender_id'],)).fetchone()
                if not person or person[0] == ACCOUNT:
                    continue
                ids = mentions(decode(row['source']))
                extra = {}
                if kind != 1 and ACCOUNT not in ids and (b.get('triggerMode') != 'owner_name'):
                    continue
                if b.get('triggerMode') == 'owner_name' or (ACCOUNT not in ids and b.get('ownerTextAliases')):
                    if person[0] != OWNER:
                        continue
                    body = c.execute('select message_content from ' + table + ' where server_id=? and local_id=?', (row['server_id'], row['local_id'])).fetchone()
                    text = decode(body[0]) if body else ''
                    if text.startswith(person[0] + ':\n'):
                        text = text[len(person[0]) + 2:]
                    if kind == 49:
                        text = current_quote_text(text)
                    names = addressed_names(text, all_names if b.get('triggerMode') == 'owner_name' else b['ownerTextAliases'])
                    if len(names) > 1:
                        ambiguities.append(sid(row['server_id']))
                        continue
                    if len(names) != 1 or (b.get('triggerMode') == 'owner_name' and names[0] not in b['aliases']):
                        continue
                    extra = dict(triggerType='owner_name' if b.get('triggerMode') == 'owner_name' else 'owner_group_name', namedRecipient=names[0], sourceTextSHA256=hashlib.sha256(text.encode()).hexdigest())
                elif ACCOUNT not in ids:
                    continue
                events.append(dict(account=ACCOUNT, peer=b['peer'], serverId=sid(row['server_id']), senderId=person[0], time=int(row['create_time']), kind=kind, atUserIds=[ACCOUNT] if ACCOUNT in ids else [], nativeSourceVerified=True, **{'appType': 57} if kind == 49 else {}, **extra))
            results.append(dict(kind='source', binding=b['id'], observedAt=time.time(), events=events, coverage={'complete': True, 'scope': 'registered peer native mention or explicit owner employee name', 'rawTextReturned': False, 'ambiguousSources': ambiguities}))
    return results

def stamp():
    out = []
    for p in [PROFILE, Path(str(PROFILE) + '-wal'), Path(str(PROFILE) + '-shm')]:
        try:
            s = p.stat()
            out.append((s.st_ino, s.st_size, s.st_mtime_ns))
        except FileNotFoundError:
            out.append(None)
    return out

def emit(v):
    print(json.dumps(v, ensure_ascii=False, separators=(',', ':')), flush=True)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument('--stream', action='store_true')
    g.add_argument('--once', action='store_true')
    a = p.parse_args()
    if not (a.stream or a.once):
        p.print_help()
        return
    raw = sys.stdin.readline(65537)
    if len(raw) > 65536:
        raise ValueError('registry frame cap')
    routes = validated_routes(json.loads(raw)['bindings'])
    if a.once:
        for r in read(routes):
            emit(r)
        return
    last = None
    heartbeat = 0
    while True:
        s = stamp()
        if s != last:
            try:
                for r in read(routes):
                    emit(r)
                last = s
            except Exception as e:
                emit(dict(kind='source_error', errorType=type(e).__name__))
                time.sleep(3)
        if time.monotonic() - heartbeat > 15:
            emit(dict(kind='alive', at=time.time()))
            heartbeat = time.monotonic()
        time.sleep(1)
if __name__ == '__main__':
    main()
