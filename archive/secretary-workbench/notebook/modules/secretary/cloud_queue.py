"""Durable cloud dispatch ledger. Notebook data stays behind the notebook port."""
from contextlib import contextmanager
import copy
import datetime as dt
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from contracts.errors import ValidationError

_IDENTIFIER = re.compile(r'^[\w.:-]{1,160}$', re.UNICODE)
MAX_ATTEMPTS = 3
MAX_RESULT = 65536


def identifier(value):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValidationError('编号格式无效')
    return value


def canonical(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise ValidationError('JSON资料无效') from None


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def public_result(value):
    """Only displayable receipts leave the worker; no model context/plan/details."""
    if not isinstance(value, dict) or set(value) - {'summary','created','matched','closed','linked','records','counts'}:
        raise ValidationError('回执字段无效')
    if len(canonical(value).encode()) > MAX_RESULT:
        raise ValidationError('回执超出大小限制')
    result = {}
    if 'summary' in value:
        summary = value['summary']
        if not isinstance(summary, str) or not 1 <= len(summary) <= 4000 or '\x00' in summary:
            raise ValidationError('回执摘要无效')
        result['summary'] = summary
    for key in ('created','matched','closed','records'):
        if key in value:
            if not isinstance(value[key], list) or len(value[key]) > 100:
                raise ValidationError('回执对象列表无效')
            result[key] = [identifier(item) for item in value[key]]
    if 'linked' in value:
        if not isinstance(value['linked'], list) or len(value['linked']) > 100:
            raise ValidationError('关联回执无效')
        links = []
        for link in value['linked']:
            if not isinstance(link, dict) or set(link) != {'objectIds','relation','recordId'}:
                raise ValidationError('关联回执无效')
            if not isinstance(link['objectIds'], list) or len(link['objectIds']) != 2:
                raise ValidationError('关联回执无效')
            if link['relation'] not in {'belongs_to','follows','related_to','evidence'}:
                raise ValidationError('关联类型无效')
            links.append({'objectIds':[identifier(v) for v in link['objectIds']],
                          'relation':link['relation'], 'recordId':identifier(link['recordId'])})
        result['linked'] = links
    if 'counts' in value:
        counts = value['counts']
        if not isinstance(counts, dict) or set(counts) - {'created','matched','closed','linked','records'}:
            raise ValidationError('回执计数无效')
        if any(type(v) is not int or not 0 <= v <= 100 for v in counts.values()):
            raise ValidationError('回执计数无效')
        result['counts'] = counts.copy()
    return result


class CloudSecretaryQueue:
    def __init__(self, notebook_port, workspace, *, lease_seconds=900, clock=None):
        self.notebook = notebook_port
        self.workspace = Path(workspace).expanduser().resolve()
        self.directory = self.workspace / 'cloud-queue'
        if self.directory.is_symlink():
            raise ValidationError('队列目录不能是链接')
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_file = self.directory / 'jobs.sqlite3'
        if self.db_file.is_symlink():
            raise ValidationError('队列账本不能是链接')
        if type(lease_seconds) is not int or not 30 <= lease_seconds <= 900:
            raise ValidationError('租约时限无效')
        self.lease_seconds = lease_seconds
        self._clock = clock or time.time
        with self._connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, message_id TEXT UNIQUE NOT NULL, input_hash TEXT NOT NULL,
              payload TEXT NOT NULL, worker_id TEXT, token_hash TEXT, lease_until REAL);
            CREATE TABLE IF NOT EXISTS requests (
              id TEXT PRIMARY KEY, message_id TEXT NOT NULL, job_id TEXT NOT NULL);
            ''')
        os.chmod(self.db_file, 0o600)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.db_file, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _job(row):
        return json.loads(row['payload'])

    def _save(self, db, job):
        job['updatedAt'] = stamp()
        db.execute('UPDATE jobs SET payload=? WHERE id=?', (canonical(job),job['id']))

    def submit(self, message_id=None, request_id=None):
        if request_id is not None:
            identifier(request_id)
        if message_id is None:
            messages = [m for m in self.notebook.list_records()
                        if m.get('processing','pending') in {'pending','failed'}
                        and (m.get('actor') or {}).get('kind') == 'human']
            if not messages:
                raise ValidationError('没有待整理的本人留言')
            message_id = messages[0]['id']
        identifier(message_id)
        record = self.notebook.record_detail(message_id)
        if (record.get('actor') or {}).get('kind') != 'human':
            raise ValidationError('只能整理已保存的本人留言')
        # Hash immutable original input only; processing receipts/object bindings evolve.
        digest = hashlib.sha256(canonical({key:record.get(key) for key in ('id','text','attachments','actor','at')}).encode()).hexdigest()
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if request_id:
                request = db.execute('SELECT * FROM requests WHERE id=?',(request_id,)).fetchone()
                if request and request['message_id'] != message_id:
                    raise ValidationError('请求编号已用于另一份输入')
            row = db.execute('SELECT * FROM jobs WHERE message_id=?',(message_id,)).fetchone()
            if row:
                if row['input_hash'] != digest:
                    raise ValidationError('原输入发生变化，不能复用任务')
                job = self._job(row)
                if job['status'] == 'failed' and job['attempts'] < MAX_ATTEMPTS:
                    job.update(status='queued',stage='waiting_for_worker',error=None)
                    self._save(db,job)
                    db.execute('UPDATE jobs SET worker_id=NULL,token_hash=NULL,lease_until=NULL WHERE id=?',(job['id'],))
            else:
                active = sum(self._job(r)['status'] in {'queued','running'} for r in db.execute('SELECT payload FROM jobs'))
                if active >= 8:
                    raise ValidationError('待整理队列已满，请稍后再试')
                now = stamp()
                job = {'id':'cloud-sec-'+uuid.uuid4().hex,'messageId':message_id,'status':'queued',
                       'stage':'waiting_for_worker','attempts':0,'createdAt':now,'updatedAt':now,'result':None,'error':None}
                db.execute('INSERT INTO jobs(id,message_id,input_hash,payload) VALUES(?,?,?,?)',
                           (job['id'],message_id,digest,canonical(job)))
            if request_id:
                db.execute('INSERT OR IGNORE INTO requests VALUES(?,?,?)',(request_id,message_id,job['id']))
        return copy.deepcopy(job)

    def get_job(self, job_id):
        identifier(job_id)
        with self._connect() as db:
            row = db.execute('SELECT payload FROM jobs WHERE id=?',(job_id,)).fetchone()
        if row is None:
            raise KeyError(job_id)
        return self._job(row)

    def list_jobs(self):
        with self._connect() as db:
            rows = db.execute('SELECT payload FROM jobs ORDER BY rowid DESC LIMIT 500').fetchall()
        return [self._job(row) for row in rows]

    def claim(self, worker_id):
        identifier(worker_id)
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            now = self._clock()
            for row in db.execute('SELECT * FROM jobs').fetchall():
                job = self._job(row)
                if job['status'] != 'running':
                    continue
                if row['lease_until'] > now:
                    return None  # one owner for the whole private notebook
                failed = job['attempts'] >= MAX_ATTEMPTS
                job.update(status='failed' if failed else 'queued',stage='failed' if failed else 'waiting_for_worker',
                           error='执行设备租约到期；尚未确认本次整理完成。' if failed else None)
                self._save(db,job)
                db.execute('UPDATE jobs SET worker_id=NULL,token_hash=NULL,lease_until=NULL WHERE id=?',(job['id'],))
            for row in db.execute('SELECT * FROM jobs ORDER BY rowid').fetchall():
                job = self._job(row)
                if job['status'] != 'queued':
                    continue
                token = secrets.token_urlsafe(32)
                job.update(status='running',stage='worker_running',attempts=job['attempts']+1,error=None)
                self._save(db,job)
                db.execute('UPDATE jobs SET worker_id=?,token_hash=?,lease_until=? WHERE id=?',
                           (worker_id,hashlib.sha256(token.encode()).hexdigest(),now+self.lease_seconds,job['id']))
                return {'job':copy.deepcopy(job),'leaseToken':token}
        return None

    def report(self, job_id, worker_id, lease_token, status, result=None, error=None):
        identifier(job_id);identifier(worker_id)
        if not isinstance(lease_token,str) or not 20 <= len(lease_token) <= 160:
            raise ValidationError('设备租约无效')
        if status not in {'running','completed','failed'}:
            raise ValidationError('设备回执状态无效')
        safe_result = public_result(result) if result is not None else None
        if status == 'completed' and safe_result is None:
            raise ValidationError('完成回执需要整理结果')
        if error is not None and (not isinstance(error,str) or len(error) > 4000):
            raise ValidationError('失败回执无效')
        with self._connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if (row['worker_id'] != worker_id or not row['token_hash'] or
                not hmac.compare_digest(row['token_hash'],hashlib.sha256(lease_token.encode()).hexdigest()) or
                row['lease_until'] <= self._clock()):
                raise ValidationError('设备租约已失效')
            job = self._job(row)
            if job['status'] in {'completed','failed'}:
                if status == job['status'] and safe_result == job['result']:
                    return job
                raise ValidationError('任务已结束，不能改写回执')
            if job['status'] != 'running':
                raise ValidationError('任务不在执行中')
            if status == 'running':
                db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(self._clock()+self.lease_seconds,job_id))
            else:
                job.update(status=status,stage=status,result=safe_result,
                           error='执行设备未能完成整理；原留言和已保存记录仍保留。' if status=='failed' else None)
            self._save(db,job)
            return copy.deepcopy(job)
