"""Requeue a WeChat request once if its desktop turn ended before the request was read.

A desktop turn that is interrupted (for example by an owner message typed into the
reply conversation) or fails on a model error leaves its request in
`desktop_queued` with no execution checkpoint. Nothing ever revisits it, so a group
message silently expires. This module finds that exact case and puts the identical,
SHA-256-checked text back on the same conversation queue, at most once.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

WAIT_SECONDS = 60
GROUP_MARGIN_SECONDS = 120
SCAN_INTERVAL_SECONDS = 30
TAIL_BYTES = 16 * 1024 * 1024
_scanned = {}


def rollout_for(thread, sessions=None):
    root = Path(sessions) if sessions else Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'sessions'
    found = sorted(root.glob('**/rollout-*-' + thread + '.jsonl'), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def ended_unread(rollout, message_sha):
    """Return the queued text only if every turn that received it ended interrupted or with an error.

    A request already requeued once appears in two turns, so it is not returned again.
    """
    size = rollout.stat().st_size
    with rollout.open('rb') as stream:
        if size > TAIL_BYTES:
            stream.seek(size - TAIL_BYTES)
            stream.readline()  # drop a partial record
        active = None
        received = {}
        ended_bad = set()
        for line in stream:
            if not line.endswith(b'\n'):
                break  # the live writer has not finished this record
            try:
                record = json.loads(line)
            except ValueError:
                continue
            payload = record.get('payload') or {}
            kind = payload.get('type')
            if record.get('type') == 'event_msg':
                if kind == 'task_started':
                    active = (payload.get('turn_attribution') or {}).get('turn_id') or payload.get('turn_id')
                elif kind == 'turn_aborted' and payload.get('turn_id') in received:
                    ended_bad.add(payload['turn_id'])
                elif kind == 'task_complete' and payload.get('turn_id') in received and payload.get('error'):
                    ended_bad.add(payload['turn_id'])
                continue
            if (record.get('type') != 'response_item' or kind != 'message'
                    or payload.get('role') != 'user' or not active):
                continue
            parts = payload.get('content') or []
            if parts and all(part.get('type') == 'input_text' for part in parts):
                text = ''.join(part['text'] for part in parts)
                if hashlib.sha256(text.encode()).hexdigest() == message_sha:
                    received[active] = text
    if len(received) == 1 and set(received) <= ended_bad:
        return next(iter(received.values()))
    return None


def candidates(jobs, now, group_input_time, group_max_age):
    with jobs.connect() as db:
        rows = db.execute("SELECT id,body,thread_id,updated FROM jobs WHERE state='desktop_queued' "
                          "AND (turn_id IS NULL OR turn_id='') AND updated<?", (now - WAIT_SECONDS,)).fetchall()
    for row in rows:
        try:
            body = json.loads(row['body'])
        except (TypeError, ValueError):
            continue
        if body.get('mode') != 'chat':
            continue  # engineering work belongs to the maintenance conversation
        latest = group_input_time(body)
        if latest is not None and latest + group_max_age - GROUP_MARGIN_SECONDS <= now:
            continue  # too close to expiry to finish in time
        folder = jobs.root / row['id']
        if any((folder / name).exists() for name in
               ('desktop-execution.json', 'desktop-completion.json', 'desktop-requeue.json')):
            continue
        yield row, folder


def requeue_interrupted(config, jobs, group_input_time, group_max_age, now=None, sessions=None):
    """Requeue at most one eligible request per call; return its id or None."""
    now = time.time() if now is None else now
    for row, folder in candidates(jobs, now, group_input_time, group_max_age):
        if now - _scanned.get(row['id'], 0) < SCAN_INTERVAL_SECONDS:
            continue
        _scanned[row['id']] = now
        try:
            journal = json.loads((folder / 'desktop-notification.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if (journal.get('state') != 'queued' or journal.get('thread_id') != row['thread_id']
                or not re.fullmatch('[a-f0-9]{64}', journal.get('message_sha256') or '')):
            continue
        rollout = rollout_for(row['thread_id'], sessions)
        if rollout is None:
            continue
        text = ended_unread(rollout, journal['message_sha256'])
        if text is None:
            continue
        record = folder / 'desktop-requeue.json'
        proof = {'state': 'submitting', 'id': row['id'], 'thread_id': row['thread_id'],
                 'message_sha256': journal['message_sha256'], 'at': now}
        fd = os.open(record, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)  # one attempt, even across restarts
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(proof, stream)
            stream.flush()
            os.fsync(stream.fileno())
        result = subprocess.run([config['codex'], 'queue', '--thread', row['thread_id'], '--resume', '--message', text],
                                capture_output=True, text=True, encoding='utf-8', timeout=30,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        match = re.fullmatch(r'Queued message ([a-f0-9-]{36}) for thread ([a-f0-9-]{36})\.\s*', result.stdout)
        proof.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr,
                     state='queued' if (not result.returncode and match and match[2] == row['thread_id']) else 'review')
        if proof['state'] == 'queued':
            proof['desktop_message_id'] = match[1]
        record.write_text(json.dumps(proof), encoding='utf-8')
        return row['id']
    return None
