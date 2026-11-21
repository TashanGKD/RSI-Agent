"""Durable late-receipt notices; they never regenerate or send a native reply."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


def enqueue(db, row, receipt):
    if not row['desktop_message_id'] or time.time() - row['updated'] <= 18:
        return
    raw = json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(raw.encode()).hexdigest()
    db.execute('INSERT OR IGNORE INTO delivery_updates VALUES(?,?,?,?,?,?)',
               (row['id'], digest, raw, row['thread_id'], 'pending', time.time()))


def notify(config, jobs):
    with jobs.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT * FROM delivery_updates WHERE state='pending' ORDER BY created LIMIT 1").fetchone()
        if row is None:
            return
        row = dict(row)
        db.execute("UPDATE delivery_updates SET state='submitting' WHERE id=? AND digest=? AND state='pending'",
                   (row['id'], row['digest']))
    folder = Path(config['state']) / row['id']
    journal = folder / ('delivery-update-' + row['digest'] + '.json')
    proof = {'id': row['id'], 'digest': row['digest'], 'thread_id': row['thread_id'], 'state': 'submitting'}
    state = 'review'
    created = False
    try:
        original = jobs.get(row['id'])
        if (original['state'] != 'completed' or original['thread_id'] != row['thread_id']
                or not original['turn_id'] or not folder.is_dir() or folder.is_symlink()
                or journal.exists() or journal.is_symlink()):
            raise ValueError('Original completed desktop binding required.')
        receipt = json.loads(row['receipt'])
        proof.update(input_sha256=original['digest'], turn_id=original['turn_id'])
        message = ('【微信送达更新 · RSI-' + row['id'][:12] + '】\n'
            '这是原请求的晚到状态，不是新微信输入，不生成完成结果或发送微信。'
            '按 harness/DESKTOP-WECHAT.md 的送达更新协议，只读查询后简短报告。\n'
            '原请求 ID：' + row['id'] + '\n原会话：' + row['thread_id']
            + '\n原执行轮次：' + original['turn_id'] + '\n状态提示：' + receipt['state']
            + '\n[原消息与回传记录](<' + (folder / 'original.json').as_posix() + '>)')
        if config.get('repository'):
            message += '\n协议绝对路径：' + (Path(config['repository']) / 'harness/DESKTOP-WECHAT.md').as_posix()
        with journal.open('x', encoding='utf-8') as stream:
            created = True
            stream.write(json.dumps(proof));stream.flush();os.fsync(stream.fileno())
        journal.chmod(0o600)
        result = subprocess.run([config['codex'], 'queue', '--thread', row['thread_id'], '--message', message],
            capture_output=True, text=True, encoding='utf-8', timeout=30,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        match = re.fullmatch(r'Queued message ([a-f0-9-]{36}) for thread ([a-f0-9-]{36})\.\s*', result.stdout)
        if result.returncode == 0 and match and match[2] == row['thread_id']:
            state = 'queued'
            proof['desktop_message_id'] = match[1]
    except Exception as error:
        proof['error_type'] = type(error).__name__
    finally:
        proof['state'] = state
        if created:
            journal.write_text(json.dumps(proof), encoding='utf-8')
        with jobs.connect() as db:
            db.execute('UPDATE delivery_updates SET state=? WHERE id=? AND digest=?',
                       (state, row['id'], row['digest']))
