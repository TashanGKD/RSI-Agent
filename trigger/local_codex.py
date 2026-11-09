"""Private owner handoff to the existing local Codex maintenance conversation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

from rsi_agent.wechat import private_file


def settings(state):
    path = Path(state) / 'local-codex.json'
    if not path.exists():
        return None
    if not private_file(path):
        raise ValueError('Private local Codex settings required.')
    value = json.loads(path.read_text())
    if (set(value) != {'enabled', 'since', 'target_thread_id'} or type(value['enabled']) is not bool
            or type(value['since']) is not int or value['since'] <= 0
            or not isinstance(value['target_thread_id'], str)
            or not re.fullmatch(r'[a-f0-9-]{36}', value['target_thread_id'])):
        raise ValueError('Explicit local Codex activation and thread required.')
    return value if value['enabled'] else None


def instruction(text):
    match = re.fullmatch(r'/codex\s+(.+)', text, re.S)
    return match[1].strip() if match else ''


def input_digest(db, row):
    binding = db.execute('SELECT binding FROM meta').fetchone()[0]
    return hashlib.sha256(json.dumps([binding, row['id'], row['created'], row['text'], row['kind']]).encode()).hexdigest()


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS codex_jobs(id TEXT PRIMARY KEY,input_sha256 TEXT NOT NULL,'
        'state TEXT NOT NULL,claim_id TEXT UNIQUE,thread_id TEXT,reply_sha256 TEXT)')


def enqueue(db, server):
    row = db.execute('SELECT * FROM inbox WHERE id=?', (server,)).fetchone()
    if row['kind'] != 1 or not instruction(row['text']) or row['reply'] is not None or row['state'] != 'new':
        raise ValueError('Unprocessed original owner text required.')
    db.execute('INSERT INTO codex_jobs(id,input_sha256,state) VALUES(?,?,?)',
               (server, input_digest(db, row), 'queued'))
    db.execute("UPDATE inbox SET state='local_codex' WHERE id=?", (server,))


def process(db, policy, request):
    """Claim once; cache completion before the original resident sender sees it."""
    op = request.get('op')
    fields = {'check': {'op'}, 'claim': {'op', 'claim_id', 'thread_id'},
              'complete': {'op', 'claim_id', 'thread_id', 'id', 'input_sha256', 'text'}}
    if op not in fields or set(request) != fields[op]:
        raise ValueError('Exact local Codex operation required.')
    if op == 'check':
        return {'state': 'enabled', 'jobs': dict(db.execute('SELECT state,count(*) FROM codex_jobs GROUP BY state')),
                'delivery': dict(db.execute('SELECT inbox.state,count(*) FROM inbox JOIN codex_jobs USING(id) GROUP BY inbox.state'))}
    if (request['thread_id'] != policy['target_thread_id']
            or not isinstance(request['claim_id'], str) or not re.fullmatch('[a-f0-9]{32}', request['claim_id'])):
        raise ValueError('Fixed local conversation and durable claim required.')
    db.execute('BEGIN IMMEDIATE')
    try:
        job = db.execute('SELECT * FROM codex_jobs WHERE claim_id=?', (request['claim_id'],)).fetchone()
        if op == 'claim' and job is None:
            if db.execute("SELECT 1 FROM codex_jobs WHERE state='claimed'").fetchone():
                return {'state': 'original_work_unresolved', 'retry_allowed': False}
            job = db.execute("SELECT codex_jobs.* FROM codex_jobs JOIN inbox USING(id) WHERE codex_jobs.state='queued' ORDER BY created,id LIMIT 1").fetchone()
            if job is None:
                return {'state': 'idle'}
            db.execute("UPDATE codex_jobs SET state='claimed',claim_id=?,thread_id=? WHERE id=?",
                       (request['claim_id'], request['thread_id'], job['id']))
            job = db.execute('SELECT * FROM codex_jobs WHERE id=?', (job['id'],)).fetchone()
        if job is None or job['thread_id'] != request['thread_id']:
            raise ValueError('Original local Codex claim required.')
        row = db.execute('SELECT * FROM inbox WHERE id=?', (job['id'],)).fetchone()
        if input_digest(db, row) != job['input_sha256']:
            raise ValueError('Original native input changed; preserve the claim.')
        if op == 'complete':
            text = request['text']
            if (request['id'] != job['id'] or request['input_sha256'] != job['input_sha256']
                    or not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > 16384):
                raise ValueError('Bounded completion for the original native input required.')
            digest = hashlib.sha256(text.encode()).hexdigest()
            if job['state'] == 'completed':
                if digest != job['reply_sha256'] or text != row['reply']:
                    raise ValueError('Original completed reply cannot be replaced.')
            else:
                if job['state'] != 'claimed' or row['state'] != 'local_codex' or row['reply'] is not None:
                    raise ValueError('Original held reply required.')
                db.execute("UPDATE inbox SET reply=?,state='pending' WHERE id=?", (text, job['id']))
                db.execute("UPDATE codex_jobs SET state='completed',reply_sha256=? WHERE id=?", (digest, job['id']))
        job = db.execute('SELECT * FROM codex_jobs WHERE id=?', (job['id'],)).fetchone()
        row = db.execute('SELECT * FROM inbox WHERE id=?', (job['id'],)).fetchone()
        result = dict(job) | {'delivery': row['state'], 'native_owner_verified': True}
        if job['state'] == 'claimed':
            result['instruction'] = instruction(row['text'])
        db.commit()
        return result
    except BaseException:
        db.rollback()
        raise
    finally:
        if db.in_transaction:
            db.rollback()


def handle(path, request):
    from .owner_reply import Transport
    if not private_file(path):
        raise ValueError('Private owner reply configuration required.')
    value = json.loads(Path(path).read_text())
    owner = Transport(value)()
    policy = settings(value['state'])
    if not policy or not value['enabled'] or not owner['enabled'] or owner['scope']['mode'] != 'owner-private-text':
        raise ValueError('Owner-local Codex handoff is not enabled.')
    database = Path(value['state']) / 'inbox.sqlite'
    if not private_file(database):
        raise ValueError('Original private inbox required.')
    with sqlite3.connect(database) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        expected = json.dumps([owner['account'], owner['peer'], owner['scope']], sort_keys=True)
        if db.execute('SELECT binding FROM meta').fetchone()[0] != expected:
            raise ValueError('Original native owner binding changed.')
        return process(db, policy, request)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        raw = sys.stdin.read(100001)
        if len(raw.encode()) > 100000:
            raise ValueError('Local handoff request too large.')
        print(json.dumps(handle(args.config, json.loads(raw)), ensure_ascii=False))
    except (OSError, ValueError, sqlite3.Error):
        print(json.dumps({'state': 'blocked', 'original_work_preserved': True}))
        raise SystemExit(2)


if __name__ == '__main__':
    main()
