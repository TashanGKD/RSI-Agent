"""Private, offline SQLite queue for one explicitly bound ClawBot conversation.

No constructor recovery: the worker must call recover_running() after acquiring
its process lock. A separate status/CLI connection must not reset active work.
Returned job dictionaries: id (native message id), text (raw in all_messages mode), status,
attempts. Returned outbox dictionaries: id (integer), request_id, client_id,
kind, status, attempts, plus text OR path/size/sha256. No method sends messages.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import re
from contextlib import contextmanager

MAX_TEXT = 32 * 1024
MAX_BATCH = 4 * 1024 * 1024
MAX_ATTEMPTS = 3
MAX_CURSOR = 65_536
MAX_CONTEXT = 16_384
MAX_IMAGE = 8_000_000
MAX_DELIVERY_EVIDENCE = 4_096


def _string(value, name, limit=512, empty=False):
    if not isinstance(value, str) or '\x00' in value or (not empty and not value.strip()):
        raise ValueError('invalid ' + name)
    if len(value.encode('utf-8')) > limit:
        raise ValueError(name + ' exceeds limit')
    return value


def _json(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('invalid JSON value') from exc


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _no_symlinks(path):
    for part in (path,) + tuple(path.parents):
        if part.is_symlink():
            raise ValueError('symlink paths are not allowed')


class Store:
    def __init__(self, path, account_id, peer_id, prefixes=('秘书：', '秘书:', '/secretary '), all_messages=False):
        if type(all_messages) is not bool:
            raise ValueError('all_messages must be boolean')
        self.all_messages = all_messages
        self.account_id = _string(account_id, 'account_id')
        self.peer_id = _string(peer_id, 'peer_id')
        if account_id == peer_id:
            raise ValueError('account and peer must differ')
        if not isinstance(prefixes, (list, tuple)) or not prefixes or len(prefixes) > 20:
            raise ValueError('invalid prefixes')
        self.prefixes = tuple(_string(x, 'prefix', 128) for x in prefixes)
        self.path = Path(os.path.abspath(_string(os.fspath(path), 'database path', 4096)))
        _no_symlinks(self.path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent = self.path.parent.stat()
        if parent.st_uid != os.getuid() or parent.st_mode & 0o077:
            raise ValueError('database parent must be owned by current user and mode 0700')
        for suffix in ('', '-journal', '-wal', '-shm'):
            candidate = Path(str(self.path) + suffix)
            if candidate.exists() or candidate.is_symlink():
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    raise ValueError('unsafe database file')
                if info.st_mode & 0o077:
                    raise ValueError('database file must be private')
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.executescript('''
                PRAGMA foreign_keys=ON;
                PRAGMA journal_mode=DELETE;
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS incoming (
                    id TEXT PRIMARY KEY, body_hash TEXT NOT NULL, body TEXT NOT NULL, text TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS conflicts (
                    message_id TEXT NOT NULL, body_hash TEXT NOT NULL,
                    PRIMARY KEY(message_id, body_hash));
                CREATE TABLE IF NOT EXISTS received_times (
                    id TEXT PRIMARY KEY REFERENCES incoming(id), received_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY REFERENCES incoming(id), text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    reply TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
                    client_id TEXT UNIQUE NOT NULL, payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    job_id TEXT UNIQUE REFERENCES jobs(id), receipt TEXT);
            ''')
            with self._transaction():
                binding = _json([account_id, peer_id])
                existing = self._get('binding')
                if existing is not None and existing != binding:
                    raise ValueError('database belongs to another account or peer')
                self._set('binding', binding)
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def _transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def close(self):
        self.db.close()

    def _get(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)', (key, value))

    def cursor(self):
        return self._get('cursor') or ''

    def context(self):
        return self._get('context')

    def _trigger(self, text):
        """Pure trigger parsing; all_messages explicitly opts into other text."""
        if self.all_messages:
            return text if text else None
        text = text.strip()
        if text in ('秘书', '/secretary'):
            return text
        for prefix in self.prefixes:
            if text == prefix.strip():
                return '秘书' if prefix.strip() in ('秘书：', '秘书:') else prefix.strip()
            if text.startswith(prefix):
                prompt = text[len(prefix):].strip()
                if prompt:
                    return prompt
        return text if self.all_messages and text else None

    def _message_prompt(self,text,items):
        prompt=self._trigger(text)
        if prompt:return prompt
        if self.all_messages and any(type(i.get('type')) is int and (i['type']!=1 or i.get('ref_msg')) for i in items):
            return ''
        return None

    def message_text(self,message_id):
        """Exact text from an authenticated complete inbound; no prefix parsing."""
        _string(message_id,'message_id')
        row=self.db.execute('SELECT text FROM incoming WHERE id=?',(message_id,)).fetchone()
        if row is None:raise ValueError('message_id does not exist')
        return row['text']

    def message_items(self,message_id):
        """Return only the persisted, bound complete message's original item list."""
        _string(message_id,'message_id')
        row=self.db.execute('SELECT body FROM incoming WHERE id=?',(message_id,)).fetchone()
        if row is None:raise ValueError('message_id does not exist')
        return json.loads(row['body'])

    def recheck_trigger(self, message_id):
        """Explicitly re-evaluate one persisted bound/complete incoming message.

        Returns its existing/new job dictionary (id, text, status, attempts),
        or None for ordinary text. Unknown message IDs fail; existing jobs are
        never reset or duplicated. The stored original text is authoritative.
        """
        _string(message_id, 'message_id')
        with self._transaction():
            incoming = self.db.execute('SELECT text,body FROM incoming WHERE id=?', (message_id,)).fetchone()
            if incoming is None:
                raise ValueError('message_id does not exist')
            existing = self.db.execute('SELECT id,text,status,attempts FROM jobs WHERE id=?', (message_id,)).fetchone()
            if existing:
                return dict(existing)
            prompt = self._message_prompt(incoming['text'],json.loads(incoming['body']))
            if prompt is None:
                return None
            self.db.execute('INSERT INTO jobs(id,text) VALUES(?,?)', (message_id, prompt))
            return dict(self.db.execute('SELECT id,text,status,attempts FROM jobs WHERE id=?', (message_id,)).fetchone())

    def ingest(self, messages, cursor):
        """Commit complete bound-user messages and cursor together; return counts."""
        _string(cursor, 'cursor', MAX_CURSOR, empty=True)
        if not isinstance(messages, list) or len(messages) > 500:
            raise ValueError('message batch must contain at most 500 messages')
        if len(_json(messages).encode('utf-8')) > MAX_BATCH:
            raise ValueError('message batch exceeds 4 MiB')
        prepared = []
        for msg in messages:
            if not isinstance(msg, dict):
                raise ValueError('message must be an object')
            items = msg.get('item_list', [])
            if not isinstance(items, list):
                raise ValueError('item_list must be an array')
            texts = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError('message item must be an object')
                if type(item.get('type')) is int and item['type'] == 1:
                    nested = item.get('text_item')
                    if not isinstance(nested, dict):
                        raise ValueError('text_item must be an object')
                    texts.append(_string(nested.get('text'), 'text', MAX_TEXT, empty=True))
            text = _string(('' if self.all_messages else '\n').join(texts), 'message text', MAX_TEXT, empty=True)
            bound = (msg.get('from_user_id') == self.peer_id
                     and ('to_user_id' not in msg or msg['to_user_id'] == self.account_id)
                     and type(msg.get('message_type')) is int
                     and msg['message_type'] == 1 and not msg.get('group_id'))
            token = msg.get('context_token') if bound else None
            if token is not None:
                _string(token, 'context_token', MAX_CONTEXT, empty=True)
            mid = msg.get('message_id')
            if isinstance(mid, int) and not isinstance(mid, bool) and 0 <= mid < 2**64:
                mid = str(mid)
            valid_id = isinstance(mid, str) and bool(mid.strip()) and len(mid.encode('utf-8')) <= 512 and '\x00' not in mid
            complete = (bound and type(msg.get('message_state')) is int
                        and msg['message_state'] == 2 and valid_id)
            prompt = self._message_prompt(text,items) if complete else None
            prepared.append((msg, mid, text, token, complete, prompt))
        counts = {'stored': 0, 'queued': 0, 'conflicts': 0}
        with self._transaction():
            for msg, mid, text, token, complete, prompt in prepared:
                if token:
                    self._set('context', token)
                if not complete:
                    continue
                body = _json(msg.get('item_list', []))
                digest = _hash(body)
                existing = self.db.execute('SELECT body_hash FROM incoming WHERE id=?', (mid,)).fetchone()
                if existing:
                    if existing[0] != digest:
                        changed = self.db.execute('INSERT OR IGNORE INTO conflicts VALUES(?,?)', (mid, digest)).rowcount
                        counts['conflicts'] += changed
                    continue
                self.db.execute('INSERT INTO incoming VALUES(?,?,?,?)', (mid, digest, body, text))
                self.db.execute('INSERT INTO received_times VALUES(?,?)',(mid,time.time()))
                counts['stored'] += 1
                if prompt is not None:
                    self.db.execute('INSERT INTO jobs(id,text) VALUES(?,?)', (mid, prompt))
                    counts['queued'] += 1
            self._set('cursor', cursor)
        return counts

    def message_received_at(self,message_id):
        row=self.db.execute('SELECT received_at FROM received_times WHERE id=?',(message_id,)).fetchone()
        return row[0] if row else None

    def claim_job(self):
        with self._transaction():
            row = self.db.execute("SELECT id FROM jobs WHERE status='pending' AND attempts<? ORDER BY rowid LIMIT 1", (MAX_ATTEMPTS,)).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE jobs SET status='running', attempts=attempts+1 WHERE id=?", (row[0],))
            return dict(self.db.execute('SELECT id,text,status,attempts FROM jobs WHERE id=?', (row[0],)).fetchone())

    def _outbox(self, row):
        if row is None:
            return None
        result = {key: row[key] for key in ('id', 'request_id', 'client_id', 'status', 'attempts')}
        result.update(json.loads(row['payload']))
        return result

    def _enqueue(self, payload, request_id, job_id=None):
        _string(request_id, 'request_id')
        encoded = _json(payload)
        prior = self.db.execute('SELECT * FROM outbox WHERE request_id=?', (request_id,)).fetchone()
        if prior:
            if prior['payload'] != encoded or prior['job_id'] != job_id:
                raise ValueError('request_id already has different content')
            return self._outbox(prior)
        client_id = 'wb-' + _hash(_json([self.account_id, self.peer_id, request_id]))
        row_id = self.db.execute('INSERT INTO outbox(request_id,client_id,payload,job_id) VALUES(?,?,?,?)',
                                 (request_id, client_id, encoded, job_id)).lastrowid
        return self._outbox(self.db.execute('SELECT * FROM outbox WHERE id=?', (row_id,)).fetchone())

    def complete_job(self, job_id, reply):
        _string(reply, 'reply', MAX_TEXT)
        with self._transaction():
            job = self.db.execute('SELECT status,reply FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['status'] not in ('running', 'completed'):
                raise ValueError('job is not running')
            if job['status'] == 'completed' and job['reply'] != reply:
                raise ValueError('job already completed with a different reply')
            result = self._enqueue({'kind': 'text', 'text': reply}, 'reply:' + _hash(job_id), job_id)
            self.db.execute("UPDATE jobs SET status='completed',reply=?,error=NULL WHERE id=?", (reply, job_id))
            return result

    def coverage_record(self,message_id):
        row=self.db.execute('SELECT record FROM main_input_handlings WHERE message_id=?',(message_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def _cover_in_main(self,plan,native_snapshots):
        """Private transaction; public maintenance entry first owns worker lock.

        handled_in_main is NOT native completed; no reply or outbox is created.
        """
        if type(plan.get('version')) is not int or plan['version']!=1 or plan.get('kind')!='progress_inquiries_handled_in_main' or plan.get('actor')!='main-secretary' or plan.get('attestation')!='read_exact_inputs_in_existing_turn':raise ValueError('explicit main-secretary attestation required')
        operation=_string(plan.get('operation_id'),'operation_id',96)
        turn=plan.get('main_turn_id')
        if not isinstance(turn,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',turn):raise ValueError('existing main turn identity required')
        sources=plan.get('sources')
        if not isinstance(sources,list) or not 1<=len(sources)<=20 or len({s.get('message_id') for s in sources})!=len(sources):raise ValueError('bounded exact source list required')
        digest=_hash(_json(plan));now=time.time()
        with self._transaction():
            self.db.execute('CREATE TABLE IF NOT EXISTS main_input_handlings (message_id TEXT PRIMARY KEY REFERENCES incoming(id),operation_id TEXT NOT NULL,plan_hash TEXT NOT NULL,record TEXT NOT NULL)')
            prepared=[];existing=[]
            for source in sources:
                mid=_string(source.get('message_id'),'source id')
                row=self.db.execute('SELECT i.body,i.body_hash,i.text AS raw_text,j.text AS job_text,j.status,j.error,j.attempts FROM incoming i JOIN jobs j USING(id) WHERE id=?',(mid,)).fetchone()
                if not row or row['body_hash']!=source.get('body_sha256') or _hash(row['body'])!=row['body_hash'] or source.get('classification')!='explicit_status_inquiry':raise ValueError('source identity/hash/classification mismatch')
                items=json.loads(row['body']);texts=[]
                for item in items:
                    if item.get('ref_msg') or type(item.get('type')) is not int or item['type'] not in (1,3):raise ValueError('unsupported or quoted coverage source')
                    obj=item.get('text_item' if item['type']==1 else 'voice_item',{})
                    if not isinstance(obj.get('text'),str) or not obj['text'].strip():raise ValueError('exact readable input required')
                    texts.append(obj['text'])
                if _hash(''.join(texts))!=source.get('text_sha256'):raise ValueError('source text hash mismatch')
                snapshot=native_snapshots[mid]
                if snapshot.get('prompt_hash') is not None and snapshot['prompt_hash']!=_hash(row['job_text'] if snapshot.get('version',1)<2 else row['raw_text']):raise ValueError('native prompt hash differs from source')
                if snapshot.get('items_hash') is not None and snapshot['items_hash']!=_hash(json.dumps(items,ensure_ascii=False,sort_keys=True)):raise ValueError('native item hash differs from source')
                previous=self.db.execute('SELECT plan_hash FROM main_input_handlings WHERE message_id=?',(mid,)).fetchone()
                if previous:
                    if previous[0]!=digest or row['status']!='handled_in_main':raise ValueError('different or inconsistent prior handling')
                    existing.append(mid);continue
                if row['status'] not in ('pending','running'):raise ValueError('source already independently handled')
                if self.db.execute('SELECT 1 FROM outbox WHERE job_id=? OR request_id IN (?,?)',(mid,'reply:'+_hash(mid),'error:'+_hash(mid))).fetchone():raise ValueError('source has another outbound')
                prepared.append((source,dict(row)))
            if existing:
                if prepared:raise ValueError('mixed prior/new operation refused')
                return {'state':'handled_in_main','already_applied':True,'operation_id':operation}
            notice=plan.get('notice',{});out=self.db.execute('SELECT * FROM outbox WHERE request_id=?',(notice.get('request_id'),)).fetchone()
            if not out or out['status']!='accepted' or out['job_id'] is not None or _hash(out['payload'])!=notice.get('payload_sha256') or _hash(out['receipt'] or '')!=notice.get('receipt_sha256'):raise ValueError('accepted unchanged combined notice required')
            received=json.loads(out['receipt']);payload=json.loads(out['payload'])
            expected='wb-'+_hash(_json([self.account_id,self.peer_id,out['request_id']]))
            if out['client_id']!=expected or received.get('client_id')!=expected or received.get('api_accepted') is not True or payload.get('kind')!='text':raise ValueError('notice binding/acceptance mismatch')
            for source,row in prepared:
                mid=source['message_id']
                record={'version':1,'operation_id':operation,'resolution':'read_in_existing_main_turn_covered_by_notice','message_id':mid,'source_body_sha256':source['body_sha256'],'source_text_sha256':source['text_sha256'],'main_thread_id':plan['main_thread_id'],'main_turn_id':turn,'actor':plan['actor'],'handled_at':now,'native_execution_claimed':False,'native_submission':native_snapshots[mid],'previous_job':{k:row[k] for k in ['status','error','attempts']},'audit_sha256':plan['audit_sha256'],'notice':{'request_id':out['request_id'],'outbox_id':out['id'],'client_id':out['client_id'],'status':out['status'],'payload_sha256':notice['payload_sha256'],'receipt_sha256':notice['receipt_sha256'],**received}}
                encoded=_json(record)
                if len(encoded.encode())>65536:raise ValueError('maintenance receipt too large')
                self.db.execute('INSERT INTO main_input_handlings VALUES(?,?,?,?)',(mid,operation,digest,encoded))
                self.db.execute("UPDATE jobs SET status='handled_in_main' WHERE id=?",(mid,))
            return {'state':'handled_in_main','already_applied':False,'operation_id':operation}

    def defer_job(self, job_id, reason='waiting_for_native'):
        """Return running work to pending without charging an execution attempt.

        Native-thread waiting is not a generation failure. Already-pending
        jobs are left unchanged, so duplicate deferrals never reduce attempts
        twice. Returns the current id/text/status/attempts job dictionary.
        """
        _string(job_id, 'job_id')
        _string(reason, 'defer reason', 4096)
        with self._transaction():
            job = self.db.execute('SELECT id,text,status,attempts FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['status'] not in ('running', 'pending'):
                raise ValueError('only running or pending jobs can be deferred')
            if job['status'] == 'running':
                self.db.execute("UPDATE jobs SET status='pending',attempts=MAX(0,attempts-1),error=? WHERE id=?",
                                (reason, job_id))
            return dict(self.db.execute('SELECT id,text,status,attempts FROM jobs WHERE id=?', (job_id,)).fetchone())

    def fail_job(self, job_id, error, retryable=False):
        _string(error, 'error', MAX_TEXT, empty=True)
        with self._transaction():
            job = self.db.execute('SELECT status,attempts FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not job or job['status'] != 'running':
                raise ValueError('job is not running')
            state = 'pending' if retryable and job['attempts'] < MAX_ATTEMPTS else 'failed'
            self.db.execute('UPDATE jobs SET status=?,error=? WHERE id=?', (state, error, job_id))

    def enqueue_text(self, text, request_id):
        _string(text, 'text', MAX_TEXT)
        with self._transaction():
            return self._enqueue({'kind': 'text', 'text': text}, request_id)

    def visible_checkpoint(self):
        return self._get('visible_sync_checkpoint')

    @staticmethod
    def _visible_key(source):
        if not isinstance(source, dict):raise ValueError('invalid visible source')
        turn=_string(source.get('turn_id'),'native turn',128)
        ids=source.get('item_ids')
        if not isinstance(ids,list) or not 1<=len(ids)<=100:raise ValueError('invalid visible item IDs')
        for value in ids:_string(value,'native item',128)
        return 'visible-source:'+_hash(_json({'turn_id':turn,'item_ids':ids}))

    def visible_source(self, outbox_id):
        saved=self._get('visible-outbox:'+str(outbox_id))
        return json.loads(saved) if saved else None

    def needs_visible_source(self, outbox_id):
        row=self.db.execute('SELECT job_id FROM outbox WHERE id=?',(outbox_id,)).fetchone()
        return bool(row and row['job_id'] is None and not self.visible_source(outbox_id))

    def bind_visible_source(self, outbox_id, source):
        key=self._visible_key(source)
        with self._transaction():
            row=self.db.execute('SELECT * FROM outbox WHERE id=?',(outbox_id,)).fetchone()
            if not row:raise ValueError('unknown outbox')
            prior=self._get(key)
            if prior:
                other=self.db.execute('SELECT * FROM outbox WHERE request_id=?',(prior,)).fetchone()
                if not other or other['payload']!=row['payload']:raise ValueError('visible source content conflict')
                return other['id']
            self._set(key,row['request_id'])
            self._set('visible-outbox:'+str(outbox_id),_json(source))
            return outbox_id

    def defer_outbox(self,outbox_id):
        with self._transaction():
            self.db.execute("UPDATE outbox SET status='pending',attempts=MAX(0,attempts-1) WHERE id=? AND status='running'",(outbox_id,))

    def apply_visible_scan(self, result):
        if not isinstance(result,dict) or result.get('state') not in ('initialized','scanned'):raise ValueError('invalid visible scan')
        checkpoint=_string(result.get('after_turn_id'),'visible checkpoint',128)
        turns=result.get('turns')
        if not isinstance(turns,list) or len(turns)>4 or (result['state']=='initialized' and turns):raise ValueError('invalid visible batch')
        prepared=[]
        for turn in turns:
            key=self._visible_key(turn);text=_string(turn.get('reply'),'visible reply',MAX_TEXT)
            mid=turn.get('job_id')
            if mid is not None:
                _string(mid,'source job')
                if not self.db.execute('SELECT 1 FROM jobs WHERE id=?',(mid,)).fetchone():raise ValueError('missing source job')
            request='reply:'+_hash(mid) if mid else 'native-final:'+_hash(turn['turn_id'])
            prepared.append((turn,key,text,mid,request))
        with self._transaction():
            for turn,key,text,mid,request in prepared:
                prior=self._get(key)
                if prior:
                    row=self.db.execute('SELECT * FROM outbox WHERE request_id=?',(prior,)).fetchone()
                    if not row or row['payload']!=_json({'kind':'text','text':text}):raise ValueError('visible source content conflict')
                    continue
                out=self._enqueue({'kind':'text','text':text},request,mid)
                source={'turn_id':turn['turn_id'],'item_ids':turn['item_ids']}
                self._set(key,request);self._set('visible-outbox:'+str(out['id']),_json(source))
            self._set('visible_sync_checkpoint',checkpoint)
        return {'state':result['state'],'after_turn_id':checkpoint,'turns':len(turns)}

    def enqueue_image(self, path, request_id):
        _string(request_id, 'request_id')
        path = Path(os.path.abspath(_string(os.fspath(path), 'image path', 4096)))
        _no_symlinks(path)
        try:
            with os.fdopen(os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= MAX_IMAGE:
                    raise ValueError('image must be a regular file of 1 to 8000000 bytes')
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_IMAGE:
                        raise ValueError('image exceeds limit')
                    digest.update(chunk)
                after = os.fstat(handle.fileno())
                if (info.st_size, info.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or size != info.st_size:
                    raise ValueError('image changed while reading')
        except OSError as exc:
            raise ValueError('image cannot be read') from exc
        with self._transaction():
            return self._enqueue({'kind': 'image', 'path': str(path), 'size': size, 'sha256': digest.hexdigest()}, request_id)

    def claim_outbox(self):
        with self._transaction():
            row = self.db.execute("SELECT id FROM outbox WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if not row:
                return None
            self.db.execute("UPDATE outbox SET status='running',attempts=attempts+1 WHERE id=?", (row[0],))
            return self._outbox(self.db.execute('SELECT * FROM outbox WHERE id=?', (row[0],)).fetchone())

    def finish_outbox(self, outbox_id, status, receipt):
        if status not in ('accepted', 'unknown', 'failed'):
            raise ValueError('invalid send status')
        encoded = _json(receipt)
        if len(encoded.encode('utf-8')) > 64 * 1024:
            raise ValueError('receipt exceeds limit')
        with self._transaction():
            row = self.db.execute('SELECT status,receipt FROM outbox WHERE id=?', (outbox_id,)).fetchone()
            if row and row['status'] == status and row['receipt'] == encoded:
                return
            if not row or row['status'] != 'running':
                raise ValueError('outbox item is not running')
            self.db.execute('UPDATE outbox SET status=?,receipt=? WHERE id=?', (status, encoded, outbox_id))

    def acknowledge_delivery(self, outbox_id, evidence):
        """Record explicit human phone receipt without sending or requeueing.

        Evidence is a nonempty string, at most 4096 UTF-8 bytes and at most
        4096 JSON-encoded bytes. Only unknown/accepted items are eligible.
        Return the normal outbox dictionary plus the stored receipt envelope.
        Identical evidence is idempotent; conflicting acknowledgments fail.
        """
        _string(evidence, 'delivery evidence', MAX_DELIVERY_EVIDENCE)
        if len(_json(evidence).encode('utf-8')) > MAX_DELIVERY_EVIDENCE:
            raise ValueError('encoded delivery evidence exceeds limit')
        if type(outbox_id) is not int or outbox_id < 1:
            raise ValueError('invalid outbox id')
        with self._transaction():
            row = self.db.execute('SELECT * FROM outbox WHERE id=?', (outbox_id,)).fetchone()
            if not row or row['status'] not in ('unknown', 'accepted'):
                raise ValueError('only unknown or accepted delivery can be acknowledged')
            previous = json.loads(row['receipt']) if row['receipt'] is not None else None
            if (isinstance(previous, dict) and previous.get('phone_delivery_verified') is True
                    and set(previous) == {'phone_delivery_verified', 'evidence',
                                          'previous_status', 'previous_receipt'}):
                if previous['evidence'] != evidence:
                    raise ValueError('delivery already acknowledged with different evidence')
                receipt = previous
            else:
                receipt = {'phone_delivery_verified': True, 'evidence': evidence,
                           'previous_status': row['status'], 'previous_receipt': previous}
            encoded = _json(receipt)
            if len(encoded.encode('utf-8')) > 72 * 1024:
                raise ValueError('delivery acknowledgment exceeds limit')
            self.db.execute("UPDATE outbox SET status='accepted',receipt=? WHERE id=?", (encoded, outbox_id))
            result = self._outbox(self.db.execute('SELECT * FROM outbox WHERE id=?', (outbox_id,)).fetchone())
            result['receipt'] = receipt
            return result

    def recover_running(self):
        """Call once with worker process lock held; never replay uncertain sends."""
        with self._transaction():
            self.db.execute("UPDATE jobs SET status=CASE WHEN attempts<? THEN 'pending' ELSE 'failed' END WHERE status='running'", (MAX_ATTEMPTS,))
            self.db.execute("UPDATE outbox SET status='unknown' WHERE status='running'")

    def snapshot(self):
        """Counts and presence flags only: no message bodies, IDs, tokens, or errors."""
        return {
            'jobs': dict(self.db.execute('SELECT status,count(*) FROM jobs GROUP BY status').fetchall()),
            'outbox': dict(self.db.execute('SELECT status,count(*) FROM outbox GROUP BY status').fetchall()),
            'incoming': self.db.execute('SELECT count(*) FROM incoming').fetchone()[0],
            'conflicts': self.db.execute('SELECT count(*) FROM conflicts').fetchone()[0],
            'has_cursor': bool(self.cursor()), 'has_context': bool(self.context()),
        }

    def recent_dialogue(self, limit=10, before_job_id=None):
        """Recent trigger jobs and accepted replies, optionally before one job.

        before_job_id selects by insertion order, never by prompt text. This
        excludes the current job and later jobs from its model history.
        """
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError('dialogue limit must be 1..100')
        cutoff = None
        if before_job_id is not None:
            _string(before_job_id, 'before_job_id')
            current = self.db.execute('SELECT rowid FROM jobs WHERE id=?', (before_job_id,)).fetchone()
            if current is None:
                raise ValueError('before_job_id does not exist')
            cutoff = current[0]
        rows = self.db.execute('''SELECT j.text,j.reply,o.status FROM jobs j
            LEFT JOIN outbox o ON o.job_id=j.id
            WHERE (? IS NULL OR j.rowid < ?) ORDER BY j.rowid DESC LIMIT ?''',
            (cutoff, cutoff, limit)).fetchall()
        result = []
        for row in reversed(rows):
            result.append({'role': 'user', 'content': row['text']})
            if row['reply'] is not None and row['status'] == 'accepted':
                result.append({'role': 'assistant', 'content': row['reply']})
        return result
