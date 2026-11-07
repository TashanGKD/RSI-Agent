"""System-owned native mention routing. No arguments: help, no network or writes."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, datetime, hashlib, json, os, re, select, sqlite3, subprocess, time, fcntl, math
from pathlib import Path
ROOT = _install.path('continuity_workspace')
CLI = _install.setting('continuity.runtime', 'CLI', 'codex')
HOME = _install.path('continuity.runtime.HOME')
REMOTE = _install.setting('continuity.runtime', 'REMOTE', '')
SSH_ALIAS = _install.setting('continuity.runtime','SSH_ALIAS','')
UUID = re.compile('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}')

def sha(s):
    return hashlib.sha256(s.encode()).hexdigest()

def valid_sid(s):
    return isinstance(s, str) and bool(re.fullmatch('[1-9][0-9]{0,19}', s)) and (int(s) < 2 ** 64)

def validate_binding(b):
    if not isinstance(b, dict) or not re.fullmatch('[a-z][a-z0-9_-]{0,40}', str(b.get('id', ''))):
        raise ValueError('binding id')
    from native_source import validated_routes
    validated_routes([b])
    if not re.fullmatch('wxid_[A-Za-z0-9_]+', str(b.get('account', ''))):
        raise ValueError('account')
    for k in ['threadId', 'historyThreadId']:
        if not isinstance(b.get(k), str) or not UUID.fullmatch(b[k]):
            raise ValueError('thread')
    for k in ['cwd', 'workEntry'] + [k for k in ['workRoot', 'workbookDir'] if k in b]:
        p = Path(b.get(k, ''))
        if not p.is_absolute() or '..' in p.parts or '\x00' in str(p):
            raise ValueError('path')
        for a in [p, *p.parents]:
            if a.is_symlink():
                raise ValueError('symlink')
    root = Path(b.get('workRoot', b['cwd']))
    if not Path(b['cwd']).is_dir() or not root.is_dir() or (not Path(b['workEntry']).is_file()) or (root not in Path(b['workEntry']).parents):
        raise ValueError('entry scope')
    if 'workbookDir' in b and (not Path(b['workbookDir']).is_dir() or root not in Path(b['workbookDir']).parents):
        raise ValueError('workbook scope')
    if 'automationId' in b and (not re.fullmatch('[a-zA-Z0-9][a-zA-Z0-9_-]{0,79}', str(b['automationId']))):
        raise ValueError('automation id')
    if type(b.get('since')) is not int or b['since'] < 1 or b['since'] > int(time.time()) + 60:
        raise ValueError('since')
    if not isinstance(b.get('handledSources'), list) or any((not valid_sid(x) for x in b['handledSources'])):
        raise ValueError('handled ids')
    return b

def validate_event(b, e):
    if not isinstance(e, dict) or e.get('peer') != b['peer'] or e.get('account') != b['account']:
        raise ValueError('event scope')
    if not valid_sid(e.get('serverId')) or e.get('senderId') == b['account'] or (not re.fullmatch('wxid_[A-Za-z0-9_]+|[A-Za-z0-9_.-]{3,100}', str(e.get('senderId', '')))):
        raise ValueError('identity')
    if e.get('nativeSourceVerified') is not True or not isinstance(e.get('atUserIds'), list) or len(e['atUserIds']) > 100:
        raise ValueError('native source')
    trigger = e.get('triggerType', 'native_at')
    if trigger in ['owner_name', 'owner_group_name']:
        from native_source import OWNER
        aliases = b.get('aliases', []) if trigger == 'owner_name' else b.get('ownerTextAliases', [])
        if b.get('ownerId') != OWNER or e['senderId'] != OWNER or e.get('namedRecipient') not in aliases or (not re.fullmatch('[a-f0-9]{64}', str(e.get('sourceTextSHA256', '')))):
            raise ValueError('owner name source')
        if (trigger == 'owner_name') != (b.get('triggerMode') == 'owner_name'):
            raise ValueError('name trigger scope')
    elif trigger != 'native_at' or b.get('triggerMode') == 'owner_name' or b['account'] not in e['atUserIds']:
        raise ValueError('native mention')
    if type(e.get('time')) is not int or e['time'] < 1 or e['time'] > int(time.time()) + 60 or (type(e.get('kind')) is not int):
        raise ValueError('event time/type')
    if e['kind'] == 49:
        if trigger not in ['native_at', 'owner_name'] or type(e.get('appType')) is not int or e['appType'] != 57:
            raise ValueError('quoted reply type')
    elif e['kind'] != 1:
        raise ValueError('event type')
    return {k: e[k] for k in ['account', 'peer', 'serverId', 'senderId', 'time', 'kind', 'atUserIds', 'nativeSourceVerified'] + (['appType'] if e['kind'] == 49 else []) + (['triggerType', 'namedRecipient', 'sourceTextSHA256'] if trigger != 'native_at' else [])}

def atomic(p, obj):
    p = Path(p)
    tmp = p.with_name(p.name + '.tmp-' + str(os.getpid()))
    with tmp.open('x', encoding='utf8') as f:
        os.chmod(tmp, 384)
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, p)

def ro(path):
    c = sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, timeout=2)
    c.row_factory = sqlite3.Row
    c.execute('pragma query_only=1')
    return c

def text_of(j):
    if 'UserInput' in j:
        j = j['UserInput']
    return ''.join((c.get('text', '') for c in j.get('content', []) if isinstance(c, dict)))

def live(b):
    with ro(HOME / 'state_5.sqlite') as c:
        m = c.execute('select cwd from threads where id=?', (b['threadId'],)).fetchone()
        if not m or m['cwd'] != b['cwd']:
            raise ValueError('live metadata binding mismatch')
    with ro(HOME / 'thread_history_1.sqlite') as c:
        t = c.execute('select turn_id,status,started_at,completed_at from thread_turns where thread_id=? order by rollout_ordinal desc limit 1', (b['historyThreadId'],)).fetchone()
        if not t:
            raise ValueError('live turn unavailable')
    return dict(t)

def queued(b):
    with ro(HOME / 'queue_1.sqlite') as c:
        return [dict(x) for x in c.execute('select id,payload_json from queued_items where thread_id=? order by queue_order', (b['threadId'],))]

def find_native(b, body):
    for q in queued(b):
        if text_of(json.loads(q['payload_json'])) == body:
            return {'where': 'queue', 'id': q['id']}
    with ro(HOME / 'thread_history_1.sqlite') as c:
        rows = c.execute("select item_id,turn_id,item_json from thread_items where thread_id=? and item_type='userMessage' order by rollout_ordinal desc limit 120", (b['historyThreadId'],)).fetchall()
        for q in rows:
            if text_of(json.loads(q['item_json'])) == body:
                return {'where': 'history', 'id': q['item_id'], 'turnId': q['turn_id']}
    return None

def continuation_prompt(b):
    if b.get('automationId'):
        import tomli
        p = HOME / 'automations' / b['automationId'] / 'automation.toml'
        if any((a.is_symlink() for a in [p, *p.parents])) or p.stat().st_size > 65536:
            raise ValueError('automation config scope')
        j = tomli.loads(p.read_text())
        if j.get('kind') != 'heartbeat' or j.get('target_thread_id') != b['threadId'] or (not isinstance(j.get('prompt'), str)) or (not j['prompt'].strip()):
            raise ValueError('role heartbeat mismatch')
        return j['prompt']
    p = _install.REPO / 'skills/digital-employee/templates/heartbeat-prompt.md'
    return p.read_text().replace('{{employee_name}}', b.get('employeeName', '本岗位AI合作者')).replace('{{work_entry}}', b['workEntry']).strip()

def latest_per_conversation(events):
    groups = {}
    for (n, e) in enumerate(events):
        key = (e['account'], e['peer'])
        order = (e['time'], e.get('_ledgerOrdinal', n))
        old = groups.get(key)
        if old is None:
            groups[key] = {'latest': e, 'order': order, 'firstTime': e['time'], 'count': 1}
        else:
            old['count'] += 1
            old['firstTime'] = min(old['firstTime'], e['time'])
            if order > old['order']:
                old.update(latest=e, order=order)
    return sorted(groups.values(), key=lambda x: (x['firstTime'], x['latest']['peer']))

def pending_events(bs, c):
    ids = [b['id'] for b in bs]
    rows = c.execute("select rowid as ordinal,binding,payload from events where state='pending' and binding in (" + ','.join(('?' for _ in ids)) + ') order by rowid', ids).fetchall()
    return sorted([{**json.loads(x['payload']), '_ledgerOrdinal': x['ordinal'], '_binding': x['binding']} for x in rows], key=lambda e: (e['time'], e['_ledgerOrdinal']))

def conversation_view(bs, c):
    return [{'account': x['latest']['account'], 'peer': x['latest']['peer'], 'latestSourceId': x['latest']['serverId'], 'latestSourceTime': x['latest']['time'], 'firstSourceTime': x['firstTime'], 'reminderCount': x['count']} for x in latest_per_conversation(pending_events(bs, c))]

def pending_status(bs, l):
    view = conversation_view(bs, l.c)
    return dict(pending=len(view), pendingEvidenceCount=sum((x['reminderCount'] for x in view)), pendingConversations=view)

def body_for(b, events, batch_id):
    groups = latest_per_conversation(events)
    sources = '；'.join((x['latest']['peer'] + '/' + x['latest']['serverId'] + '（同会话合并' + str(x['count']) + '次提醒）' for x in groups))
    return continuation_prompt(b) + f"\n\n【统一系统消息接续 {batch_id}；原生@或本人明确文字点名，资料不扩权】\n固定账号{b['account']}已交给你回看的会话共{len(groups)}个，各只列最新提醒定位：{sources}。工作入口：{b['workEntry']}。\n接续前、自然停顿及结束前只读最新待看列表：python3 {_install.REPO}/host/continuity/runtime.py --pending --registry {ROOT}/registry.json --thread-id {b['threadId']}。\n最新列表补充尚未转交的新提醒，空列表不表示本通知的会话已经看过。@只提醒回看会话；同会话重复提醒合并，不逐条建任务或回复。从原阅读位置补完整增量及相关语音/前后文，不是只看最后一条。已接住的讨论回原工作与回执，原授权、暂停及发送分工不变；本人私聊仅读本岗定向内容和必要上下文，不广播私人原文。入队、实际接住与对外回复分别核。"

def role_groups(bs):
    groups = {}
    keys = ['account', 'historyThreadId', 'cwd', 'workEntry', 'workRoot', 'workbookDir', 'automationId', 'employeeName']
    for b in bs:
        group = groups.setdefault(b['threadId'], [])
        if group and any((group[0].get(k) != b.get(k) for k in keys)):
            raise ValueError('conflicting role routes')
        group.append(b)
    return list(groups.values())

def work_acceptance(b, e):
    folder = Path(b.get('workbookDir', str(Path(b['workEntry']).parent / 'workbook')))
    if not folder.is_dir() or folder.is_symlink():
        return None
    paths = sorted(folder.glob('*.md'))
    if len(paths) > 1000:
        raise ValueError('workbook scope cap')
    for p in paths:
        if p.is_symlink() or p.stat().st_size > 1000000:
            continue
        s = p.read_text()
        markers = [(a, z) for (a, z) in [('<!-- employee-work:start -->', '<!-- employee-work:end -->'), ('<!-- secretary-work-current:start -->', '<!-- secretary-work-current:end -->')] if s.count(a) == 1 and s.count(z) == 1]
        if len(markers) != 1:
            continue
        (a, z) = markers[0]
        block = s.split(a)[1].split(z)[0]
        fields = dict(re.findall('^- \\*\\*([^*]+)\\*\\*：(.+)$', block, re.M))
        origin = fields.get('怎么来的', '')
        if not re.search('(?<![0-9])' + re.escape(e['serverId']) + '(?![0-9])', origin):
            continue
        if any((w in origin for w in ['尚未承接', '候选', '待确认是否承接'])):
            continue
        if fields.get('现在怎么样') in ['待推进', '等反馈', '先放放', '已办好', '不做了'] and fields.get('下一步'):
            return str(p)
    return None

class Ledger:

    def __init__(self, path):
        if str(path) != ':memory:':
            p = Path(path)
            if p.is_symlink():
                raise ValueError('ledger symlink')
            if not p.exists():
                fd = os.open(p, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 384)
                os.close(fd)
        self.c = sqlite3.connect(str(path))
        self.c.row_factory = sqlite3.Row
        self.c.executescript('CREATE TABLE IF NOT EXISTS events(binding TEXT,id TEXT,payload TEXT,state TEXT,batch TEXT,PRIMARY KEY(binding,id));CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,binding TEXT,body TEXT,ids TEXT,state TEXT,queue_id TEXT,native_id TEXT,turn_id TEXT,error TEXT,created REAL);CREATE TABLE IF NOT EXISTS audit(at REAL,kind TEXT,detail TEXT);')

    def audit(self, k, v):
        self.c.execute('insert into audit values(?,?,?)', (time.time(), k, json.dumps(v, ensure_ascii=False)))
        self.c.commit()

    def ingest(self, b, e):
        e = validate_event(b, e)
        if e['time'] < b['since'] and e['serverId'] not in b['handledSources']:
            return False
        payload = json.dumps(e, sort_keys=True)
        old = self.c.execute('select payload from events where binding=? and id=?', (b['id'], e['serverId'])).fetchone()
        if old:
            if old['payload'] != payload:
                raise ValueError('source identity conflict')
            return False
        accepted_note = work_acceptance(b, e)
        state = 'already_handled' if e['serverId'] in b['handledSources'] or accepted_note else 'pending'
        row = self.c.execute('insert into events values(?,?,?,?,NULL)', (b['id'], e['serverId'], payload, state))
        ordinal = row.lastrowid
        self.c.commit()
        self.audit('source_observed', {'binding': b['id'], 'id': e['serverId'], 'state': state, 'originalWorkAcceptance': accepted_note})
        if accepted_note:
            self.accept_conversation([b], {**e, '_ledgerOrdinal': ordinal}, accepted_note)
        return True

    def accept_conversation(self, bs, latest, note):
        cutoff = (latest['time'], latest['_ledgerOrdinal'])
        rows = [e for e in pending_events(bs, self.c) if (e['account'], e['peer']) == (latest['account'], latest['peer']) and (e['time'], e['_ledgerOrdinal']) <= cutoff]
        if not rows:
            return
        self.c.executemany("update events set state='already_handled' where binding=? and id=? and state='pending'", [(e['_binding'], e['serverId']) for e in rows])
        self.c.commit()
        self.audit('conversation_review_accepted', {'peer': latest['peer'], 'latestSourceId': latest['serverId'], 'mergedReminderCount': len(rows), 'originalWorkAcceptance': note, 'businessCompletionNotInferred': True})

    def pending(self, binding):
        return [json.loads(x['payload']) for x in self.c.execute("select payload from events where binding=? and state='pending' order by rowid", (binding,))]

    def inflight(self, binding):
        q = self.c.execute("select * from batches where binding=? and state not in ('delivered','work_accepted_delivery_unverified') order by created limit 1", (binding,)).fetchone()
        return dict(q) if q else None

    def settle_accepted_work(self, batch, routes):
        sources = self.c.execute("select binding,id,payload from events where batch=? and state='batched'", (batch['id'],)).fetchall()
        if not sources or sorted((row['id'] for row in sources)) != sorted(json.loads(batch['ids'])):
            return False
        acceptance = []
        for row in sources:
            route = routes.get(row['binding'])
            event = json.loads(row['payload'])
            if not route or (event.get('serverId'), event.get('account'), event.get('peer')) != (row['id'], route['account'], route['peer']):
                return False
            note = work_acceptance(route, event)
            if not note:
                return False
            acceptance.append({'binding': row['binding'], 'sourceId': row['id'], 'workNote': note})
        with self.c:
            changed = self.c.execute("update batches set state='work_accepted_delivery_unverified' where id=? and state=? and native_id is null and turn_id is null", (batch['id'], batch['state']))
            if changed.rowcount != 1:
                return False
            detail = {'batch': batch['id'], 'previousState': batch['state'], 'queueId': batch['queue_id'], 'originalWorkAcceptance': acceptance, 'nativeDeliveryVerified': False}
            self.c.execute('insert into audit values(?,?,?)', (time.time(), 'batch_work_accepted_delivery_unverified', json.dumps(detail, ensure_ascii=False)))
        return True

    def prepare(self, b, events, bindings=None):
        bindings = bindings or [b]
        routes = {x['id']: x for x in bindings}
        claims = []
        for e in events:
            ident = e.get('_binding')
            if ident is None:
                matches = [x for x in bindings if x['peer'] == e.get('peer') and x['account'] == e.get('account')]
                if len(matches) != 1:
                    raise ValueError('ambiguous batch event binding')
                route = matches[0]
            else:
                if not isinstance(ident, str) or ident not in routes:
                    raise ValueError('unknown batch event binding')
                route = routes[ident]
            if (route['account'], route['peer']) != (e.get('account'), e.get('peer')):
                raise ValueError('batch event scope')
            claims.append((route['id'], e))
        ids = [x['serverId'] for x in events]
        ident = 'mention-' + sha(b['id'] + '|' + ','.join(ids))[:28]
        body = body_for(b, events, ident)
        with self.c:
            if self.c.execute('select id from batches where id=?', (ident,)).fetchone():
                raise ValueError('immutable batch already exists')
            for (route_id, e) in claims:
                row = self.c.execute('select state from events where binding=? and id=?', (route_id, e['serverId'])).fetchone()
                if not row or row['state'] != 'pending':
                    raise ValueError('event not pending')
            self.c.execute('insert into batches values(?,?,?,?,?,?,?,?,?,?)', (ident, b['id'], body, json.dumps(ids), 'prepared', None, None, None, None, time.time()))
            self.c.executemany("update events set state='batched',batch=? where binding=? and id=?", [(ident, route_id, e['serverId']) for (route_id, e) in claims])
        self.audit('batch_prepared', {'id': ident, 'sourceIds': ids})
        return self.inflight(b['id'])

    def patch(self, ident, **kw):
        if any((k not in ['state', 'queue_id', 'native_id', 'turn_id', 'error'] for k in kw)):
            raise ValueError('patch key')
        self.c.execute('update batches set ' + ','.join((k + '=?' for k in kw)) + ' where id=?', (*kw.values(), ident))
        self.c.commit()

    def close(self):
        self.c.close()

def dispatch(b, l):
    return dispatch_role([b], l)

def dispatch_role(bs, l):
    role_groups(bs)
    b = bs[0]
    t = live(b)
    batches = [x for x in [l.inflight(x['id']) for x in bs] if x]
    batch = min(batches, key=lambda x: x['created']) if batches else None
    if batch:
        found = find_native(b, batch['body'])
        if found:
            if found['where'] == 'history':
                l.patch(batch['id'], state='delivered', native_id=found['id'], turn_id=found['turnId'], error=None)
                l.audit('native_input_observed', {'batch': batch['id'], **found})
            else:
                l.patch(batch['id'], state='queued', queue_id=found['id'])
            return dict(nativeTurn=t, batchState=found['where'], **pending_status(bs, l))
        if batch['state'] != 'prepared':
            if batch['state'] in ('queued', 'unknown', 'submitting') and t['status'] == 'completed' and (not queued(b)):
                if l.settle_accepted_work(batch, {route['id']: route for route in bs}):
                    return dict(nativeTurn=t, batchState='work_accepted_delivery_unverified', **pending_status(bs, l))
            return dict(nativeTurn=t, batchState='unknown_no_retry', **pending_status(bs, l))
    routes = {x['id']: x for x in bs}
    for group in latest_per_conversation(pending_events(bs, l.c)) if not batch else []:
        e = group['latest']
        route = routes[e['_binding']]
        accepted = work_acceptance(route, e)
        if accepted:
            l.accept_conversation(bs, e, accepted)
    pending = pending_events(bs, l.c) if not batch else []
    summary = pending_status(bs, l)
    if t['status'] == 'inProgress':
        return dict(nativeTurn=t, waitingForIdle=True, **summary)
    if queued(b):
        return dict(nativeTurn=t, waitingForExistingQueue=True, **summary)
    if not batch:
        if not pending:
            return dict(nativeTurn=t, **summary)
        batch = l.prepare(b, pending, bs)
    l.patch(batch['id'], state='submitting')
    l.audit('official_queue_submitting', {'batch': batch['id'], 'previousNativeTurn': t})
    try:
        r = subprocess.run([CLI, 'queue', '--thread', b['threadId'], '--message', batch['body']], capture_output=True, text=True, timeout=15)
        m = re.search('Queued message ([a-f0-9-]+) for thread ' + re.escape(b['threadId']) + '\\.', r.stdout)
        if r.returncode or not m:
            raise RuntimeError('official queue outcome unknown; reconcile only')
        l.patch(batch['id'], state='queued', queue_id=m.group(1))
        l.audit('official_queue_accepted', {'batch': batch['id'], 'queueId': m.group(1)})
    except Exception as e:
        l.patch(batch['id'], state='unknown', error=str(e))
        raise
    return dict(nativeTurn=t, batchState='queued', **pending_status(bs, l))

def registry(path):
    p = Path(path)
    if p.is_symlink() or p.parent != ROOT or p.stat().st_mode & 63:
        raise ValueError('explicit private system registry required')
    j = json.loads(p.read_text())
    bs = [validate_binding(b) for b in j['bindings']]
    from native_source import validated_routes
    validated_routes(bs)
    role_groups(bs)
    return bs

def extend_bindings(old, new):
    from native_source import validated_routes
    validated_routes(new)
    mapping = {b['id']: b for b in new}
    if any((mapping.get(b['id']) != b for b in old)):
        raise ValueError('live registration may only add, not alter existing routes')
    role_groups(new)
    return new

def start_source(bs):
    if not SSH_ALIAS or not REMOTE:raise ValueError('configure the existing authorized SSH source explicitly')
    source = subprocess.Popen(['/usr/bin/ssh', '-oBatchMode=yes', '-oConnectTimeout=10', '-oServerAliveInterval=10', '-oServerAliveCountMax=2', SSH_ALIAS, REMOTE], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    try:
        os.set_blocking(source.stderr.fileno(), False)
        source.stdin.write(json.dumps({'bindings': [{k: b[k] for k in ['id', 'account', 'peer', 'since', 'triggerMode', 'ownerId', 'aliases', 'ownerTextAliases'] if k in b} for b in bs]}) + '\n')
        source.stdin.flush()
        return source
    except Exception:
        stop_source(source)
        raise

def stop_source(source):
    if source is None:
        return
    if source.poll() is None:
        source.terminate()
    try:
        source.wait(timeout=3)
    except subprocess.TimeoutExpired:
        source.kill()
        source.wait()
    for s in [source.stdin, source.stdout, getattr(source, 'stderr', None)]:
        if s:
            s.close()

def apply_source_frame(bs, ledger, status, msg):
    b = next((b for b in bs if b['id'] == msg.get('binding')), None)
    at = msg.get('observedAt')
    if not b or type(at) not in (int, float) or (not math.isfinite(at)) or (not 0 < at <= time.time() + 60):
        raise ValueError('source frame identity/time')
    if msg.get('kind') == 'source':
        if msg.get('coverage', {}).get('complete') is not True or not isinstance(msg.get('events'), list) or len(msg['events']) > 1000:
            raise ValueError('source coverage/events')
        for event in msg['events']:
            ledger.ingest(b, event)
        status.setdefault('bindings', {}).setdefault(b['id'], {}).update(sourceReady=True, lastSourceAt=at, sourceGapReason=None, ambiguousSources=msg['coverage'].get('ambiguousSources', []))
    elif msg.get('kind') == 'source_gap':
        expected = {'complete': False, 'scope': 'registered peer native mention or explicit owner employee name', 'rawTextReturned': False}
        if set(msg) != {'kind', 'binding', 'observedAt', 'reason', 'coverage'} or msg['coverage'] != expected or msg.get('reason') not in ('message_table_missing', 'peer_window_exceeded'):
            raise ValueError('source peer gap')
        status.setdefault('bindings', {}).setdefault(b['id'], {}).update(sourceReady=False, lastSourceAt=at, sourceGapReason=msg['reason'], ambiguousSources=[])
    else:
        raise ValueError('source frame type')
    status.update(sourceReady=True, lastSourceAt=at, sourceError=None, sourceCoverageComplete=all((status.get('bindings', {}).get(b['id'], {}).get('sourceReady') is True for b in bs)))

class SourceConnection:
    """Reconnect only this runtime's read-only source, preserving its Ledger."""

    def __init__(self, folder, status, clock=time.monotonic):
        self.folder = Path(folder)
        self.status = status
        self.clock = clock
        self.source = None
        self.retry_at = 0
        self.failures = 0
        self.connections = 0
        self.started_at = 0
        self.tail = b''

    def drain(self):
        stream = getattr(self.source, 'stderr', None)
        if stream is None:
            return
        for _ in range(16):
            try:
                data = os.read(stream.fileno(), 4096)
            except BlockingIOError:
                break
            if not data:
                break
            self.tail = (self.tail + data)[-4096:]

    def unavailable(self):
        self.status['sourceReady'] = False
        self.status['sourceCoverageComplete'] = False
        for state in self.status.get('bindings', {}).values():
            state['sourceReady'] = False

    def failed(self, reason):
        self.drain()
        code = self.source.poll() if self.source is not None else None
        if self.source is not None and self.clock() - self.started_at >= 60:
            self.failures = 0
        self.failures += 1
        delay = min(30, 2 ** min(self.failures - 1, 5))
        self.retry_at = self.clock() + delay
        digest = hashlib.sha256(self.tail).hexdigest()
        at = time.time()
        tail = self.tail.decode('utf8', 'replace').encode('utf8')[-4096:].decode('utf8', 'ignore')
        atomic(self.folder / 'source-last-failure.json', {'at': at, 'reason': reason, 'exitCode': code, 'stderrTail': tail, 'stderrSHA256': digest, 'retryAfterSeconds': delay})
        self.unavailable()
        self.status.update(sourceError=reason, sourceLastFailureAt=at, sourceLastExitCode=code, sourceDiagnosticSHA256=digest, sourceRetryAt=at + delay, sourceConsecutiveFailures=self.failures)
        self.close()

    def read(self, bs):
        if self.source is None:
            if self.clock() < self.retry_at:
                return None
            self.tail = b''
            try:
                self.source = start_source(bs)
            except OSError as e:
                self.failed('source_start_' + type(e).__name__)
                return None
            self.started_at = self.clock()
            self.connections += 1
            self.status['sourceReconnectCount'] = self.connections - 1
            self.unavailable()
        self.drain()
        (ready, _, _) = select.select([self.source.stdout], [], [], 1)
        if not ready:
            return None
        line = self.source.stdout.readline(262145)
        if not line:
            self.failed('source_stream_closed')
            return None
        if len(line.encode()) > 262144:
            raise ValueError('source frame cap')
        return json.loads(line)

    def close(self):
        stop_source(self.source)
        self.source = None

def run(bs, registry_path):
    from delivery_health import Supervisor
    folder = ROOT / 'runtime'
    folder.mkdir(mode=448, exist_ok=True)
    lock = (folder / 'service.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    l = Ledger(folder / 'events.sqlite')
    status = {'pid': os.getpid(), 'bindings': {}, 'sourceReady': False, 'startedAt': time.time()}
    owner = json.loads(Path(registry_path).read_text()).get('ownerThread')
    if not isinstance(owner, str) or not UUID.fullmatch(owner):
        raise ValueError('system owner identity')
    health = Supervisor(Path(str(_install.path('continuity.runtime.path_ae96f978'))), dict(id='delivery-health-supervisor', threadId=owner, historyThreadId=owner, cwd=str(ROOT.parent.parent)))
    connection = SourceConnection(folder, status)
    try:
        while True:
            try:
                new = registry(registry_path)
                if new != bs:
                    new = extend_bindings(bs, new)
                    connection.close()
                    connection.retry_at = 0
                    bs = new
                    status['registrationError'] = None
                    l.audit('routes_added', {'ids': [b['id'] for b in bs]})
            except Exception as e:
                status['registrationError'] = type(e).__name__ + ': ' + str(e)
            msg = connection.read(bs)
            if msg is not None:
                if msg.get('kind') in ('source', 'source_gap'):
                    apply_source_frame(bs, l, status, msg)
                elif msg.get('kind') == 'source_error':
                    status.update(sourceReady=False, sourceError=msg.get('errorType'))
            for group in role_groups(bs):
                try:
                    result = dispatch_role(group, l)
                except Exception as e:
                    result = {'error': type(e).__name__ + ': ' + str(e)}
                for b in group:
                    source_state = {k: v for (k, v) in status['bindings'].get(b['id'], {}).items() if k in ['sourceReady', 'lastSourceAt', 'sourceGapReason', 'ambiguousSources']}
                    status['bindings'][b['id']] = {**source_state, **result}
            try:
                status['deliveryHealth'] = health.step(l, {b['threadId'] for b in bs}, live, queued, find_native, subprocess.run, CLI)
            except Exception as e:
                status['deliveryHealth'] = {'sourceReady': False, 'error': type(e).__name__ + ': delivery supervision unavailable'}
            status['updatedAt'] = time.time()
            atomic(folder / 'status.json', status)
            if connection.source is None:
                time.sleep(min(1, max(0, connection.retry_at - time.monotonic())))
    finally:
        connection.close()
        l.close()
        lock.close()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group()
    g.add_argument('--run', action='store_true')
    g.add_argument('--status', action='store_true')
    g.add_argument('--pending', action='store_true')
    p.add_argument('--registry', type=Path)
    p.add_argument('--binding')
    p.add_argument('--thread-id')
    a = p.parse_args()
    if not (a.run or a.status or a.pending):
        p.print_help()
        return
    if a.registry is None:
        p.error('--registry required')
    bs = registry(a.registry)
    if a.binding and a.binding not in {b['id'] for b in bs}:
        p.error('binding not registered')
    if a.thread_id and (not UUID.fullmatch(a.thread_id) or a.thread_id not in {b['threadId'] for b in bs}):
        p.error('thread not registered')
    if a.thread_id and a.binding:
        p.error('choose binding or thread-id')
    if a.pending:
        if not (a.binding or a.thread_id):
            p.error('--pending requires --binding or --thread-id')
        f = ROOT / 'runtime/events.sqlite'
        if not f.exists():
            print(json.dumps({'state': 'not_started'}))
            return
        selected = [b for b in bs if b['id'] == a.binding or b['threadId'] == a.thread_id]
        ids = [b['id'] for b in selected]
        with ro(f) as c:
            c.execute('begin')
            rows = [dict(x) for x in c.execute('select binding,id,payload,state,batch from events where binding in (' + ','.join(('?' for _ in ids)) + ") and state!='already_handled' order by rowid", ids)]
            view = conversation_view(selected, c)
            notices = [{k: x[k] for k in ['id', 'binding', 'state', 'queue_id', 'native_id', 'turn_id']} for x in c.execute('select * from batches where binding in (' + ','.join(('?' for _ in ids)) + ") and state not in ('delivered','work_accepted_delivery_unverified') order by created", ids)]
        print(json.dumps({'binding': a.binding, 'threadId': a.thread_id, 'observedAt': time.time(), 'pending': len(view), 'pendingEvidenceCount': sum((x['reminderCount'] for x in view)), 'conversations': view, 'existingNotices': notices, 'events': rows}, ensure_ascii=False))
        return
    if a.status:
        f = ROOT / 'runtime/status.json'
        j = json.loads(f.read_text()) if f.exists() else {'state': 'not_started'}
        if a.binding:
            j = {**{k: v for (k, v) in j.items() if k != 'bindings'}, 'bindings': {a.binding: j.get('bindings', {}).get(a.binding)}}
        if a.thread_id:
            j = {**{k: v for (k, v) in j.items() if k != 'bindings'}, 'bindings': {b['id']: j.get('bindings', {}).get(b['id']) for b in bs if b['threadId'] == a.thread_id}}
        print(json.dumps(j, ensure_ascii=False))
        return
    run(bs, a.registry)
if __name__ == '__main__':
    main()
