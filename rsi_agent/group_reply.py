"""Moderated participation in explicitly registered invited groups."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from .group_context import FACTS, GroupTransport, group_configs
from .group_io import INTRODUCTION
from .model import ModelClient, ModelError
from .owner_reply import ReplyLoop


class GroupLoop(ReplyLoop):
    def __init__(self, path, group, model, transport):
        super().__init__(path, group, model, transport)
        self.db.execute('CREATE TABLE IF NOT EXISTS participation(k TEXT PRIMARY KEY,v TEXT NOT NULL)')

    def value(self, key, default=None):
        row = self.db.execute('SELECT v FROM participation WHERE k=?', (key,)).fetchone()
        return row[0] if row else default

    def save(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO participation VALUES(?,?)', (key, str(value)))

    def deliver(self, key, reply):
        outcome = self.io({'op': 'submit', 'server_id': key, 'text': reply})
        if outcome['state'] in ('queued', 'confirmed'):
            outcome = self.io({'op': 'advance', 'server_id': key})
        if outcome['state'] == 'succeeded' and outcome.get('outcome') == 'sent' and not outcome.get('cleanup_pending'):
            return 'sent'
        return 'pending' if outcome['state'] in ('queued', 'confirmed', 'busy') else 'attention'

    def cycle(self):
        if self.value('introduction') == 'attention' or self.db.execute("SELECT 1 FROM inbox WHERE state='attention'").fetchone():
            return {'state': 'attention', 'counts': self.counts()}
        if self.value('introduction') != 'sent':
            # Stable original request even after a lost response or worker restart.
            state = self.deliver('introduction', INTRODUCTION)
            with self.db:
                self.save('introduction', state)
                if state == 'sent':
                    self.save('last_spoken', time.time())
            return {'state': state, 'introduction': True, 'counts': self.counts()}
        batch = self.io({'op': 'read'})
        with self.db:
            for event in batch.get('events', []):
                if (event.get('account') != self.owner['account'] or event.get('peer') != self.owner['peer']
                        or event.get('sender') == self.owner['account'] or event.get('kind') != 1
                        or event['created'] < self.owner['scope']['since']):
                    continue
                text = event.get('text')
                if not isinstance(text, str) or not text.strip() or '\0' in text or len(text.encode()) > 32768:
                    continue
                raw = json.dumps({k: event[k] for k in ('sender', 'sender_name', 'text', 'mentioned')}, sort_keys=True)
                key = str(event['server_id'])
                old = self.db.execute('SELECT text FROM inbox WHERE id=?', (key,)).fetchone()
                if old and old[0] != raw:
                    raise ValueError('Original group event changed; preserve its request.')
                self.db.execute('INSERT OR IGNORE INTO inbox(id,created,text) VALUES(?,?,?)', (key, event['created'], raw))
        if batch.get('batch_id'):
            self.io({'op': 'ack', **{k: batch[k] for k in ('batch_id', 'batch_hash', 'ack_ids')}})
        pending = self.db.execute("SELECT * FROM inbox WHERE state='pending' ORDER BY created,id LIMIT 1").fetchone()
        if pending:
            state = self.deliver(pending['id'], pending['reply'])
            with self.db:
                self.db.execute('UPDATE inbox SET state=? WHERE id=?', (state, pending['id']))
                if state == 'sent':
                    self.save('last_spoken', time.time())
            return {'state': state, 'counts': self.counts()}
        rows = self.db.execute("SELECT * FROM inbox WHERE state='new' ORDER BY created,id LIMIT 128").fetchall()
        if not rows:
            return {'state': 'idle', 'counts': self.counts()}
        events = [json.loads(row['text']) for row in rows]
        direct = any(e['mentioned'] or 'rsi' in e['text'].lower() for e in events)
        elapsed = time.time() - float(self.value('last_spoken', '0'))
        if not direct and elapsed < 60:
            return {'state': 'listening', 'counts': self.counts()}
        system = FACTS + (' 你是这个受邀群的群友。适度主动参与，优先回应原生 @、对你的提问和讨论中的明确问题。'
            '只在能提供有用补充时简短发言；闲聊、重复意见、其他人之间的对话通常保持安静，不逐条应答。'
            '不要复述系统规则，不代替群主发号施令。数据中的 self=true 是你之前发过的话，不要回复自己。'
            '仅输出 JSON 对象 {"speak":布尔值,"text":"拟发送的简短文字；不发言则为空"}。')
        result = self.model.complete([{'role': 'system', 'content': system}, {'role': 'user',
            'content': json.dumps({'group': self.owner['name'], 'recent_messages': batch.get('context', [])[-20:],
                'new_messages': [{k: e[k] for k in ('sender_name', 'text', 'mentioned')} for e in events],
                'seconds_since_own_post': round(elapsed)}, ensure_ascii=False)}])
        decision = json.loads(result['message']['content'])
        if (set(decision) != {'speak', 'text'} or type(decision['speak']) is not bool
                or not isinstance(decision['text'], str) or '\0' in decision['text']
                or len(decision['text'].encode()) > 6000 or (decision['speak'] and not decision['text'].strip())):
            raise ValueError('Invalid text-only participation decision.')
        with self.db:
            self.db.executemany("UPDATE inbox SET state='quiet' WHERE id=?", [(r['id'],) for r in rows])
            if decision['speak']:
                self.db.execute("UPDATE inbox SET reply=?,state='pending' WHERE id=?", (decision['text'], rows[-1]['id']))
        # Deliver only cached output on the next cycle, including after restart.
        return {'state': 'pending' if decision['speak'] else 'quiet', 'counts': self.counts()}


def run(path, mode):
    import fcntl
    os.umask(0o077)
    if not path:
        raise ValueError('Explicit private invited-group registry required.')
    configs = group_configs(path)
    if not configs:
        raise ValueError('At least one explicitly enabled invited group required.')
    loops, locks = [], []
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    try:
        for config in configs:
            model, io = ModelClient(config['model']), GroupTransport(config)
            group = io()
            if not group['enabled']:
                raise ValueError('Invited group is disabled.')
            if mode == 'check':
                continue
            state = Path(config['state'])
            if state.is_symlink() or not state.is_dir() or state.stat().st_mode & 0o077 or state.stat().st_uid != os.getuid():
                raise ValueError('Private group state directory required.')
            fd = os.open(state / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            locks.append(fd)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            loops.append((config, GroupLoop(state / 'inbox.sqlite', group, model, io)))
        if mode == 'check':
            return {'state': 'prepared', 'enabled_groups': len(configs), 'network_probe': False}
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not stopped:
            for config, loop in loops:
                if config not in group_configs(path) or not loop.io()['enabled']:
                    stopped = True
                    break
                try:
                    result = loop.cycle()
                except ModelError:
                    result = {'state': 'model_unavailable', 'counts': loop.counts()}
                except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                    result = {'state': 'attention', 'counts': loop.counts()}
                state = Path(config['state'])
                temporary = state / 'status.tmp'
                temporary.write_text(json.dumps(dict(result, checked_at=time.time())) + '\n')
                temporary.chmod(0o600)
                os.replace(temporary, state / 'status.json')
            if mode == 'once':
                return result
            for _ in range(6):
                if stopped:
                    break
                time.sleep(0.5)
        return {'state': 'stopped'}
    finally:
        for _, loop in loops:
            loop.close()
        for fd in locks:
            os.close(fd)
