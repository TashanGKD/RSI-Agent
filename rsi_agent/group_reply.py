"""Moderated participation in explicitly registered invited groups."""
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from .group_context import FACTS, GroupTransport, group_configs
from .group_io import INTRODUCTION
from .model import ModelError
from .owner_reply import ReplyLoop
from .media import image_part, MediaPending, MediaUnavailable


class GroupLoop(ReplyLoop):
    def __init__(self, path, group, model, transport):
        super().__init__(path, group, model, transport)
        self.db.execute('CREATE TABLE IF NOT EXISTS participation(k TEXT PRIMARY KEY,v TEXT NOT NULL)')
        if 'follows_self' not in {r[1] for r in self.db.execute('PRAGMA table_info(inbox)')}:
            self.db.execute('ALTER TABLE inbox ADD COLUMN follows_self INTEGER NOT NULL DEFAULT 0')

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
                        or event.get('sender') == self.owner['account'] or event.get('kind') not in ((1, 3) if self.images else (1,))
                        or event['created'] < self.owner['scope']['since']):
                    continue
                text = event.get('text')
                if event['kind'] == 3:
                    text = ''  # Pass verified image bytes, never native cache XML.
                if not isinstance(text, str) or (event['kind'] == 1 and not text.strip()) or '\0' in text or len(text.encode()) > 32768:
                    continue
                raw = json.dumps(dict({k: event[k] for k in ('sender', 'sender_name', 'mentioned')}, text=text), sort_keys=True)
                key = str(event['server_id'])
                old = self.db.execute('SELECT text FROM inbox WHERE id=?', (key,)).fetchone()
                if old and old[0] != raw:
                    raise ValueError('Original group event changed; preserve its request.')
                self.db.execute('INSERT OR IGNORE INTO inbox(id,created,text,follows_self,kind) VALUES(?,?,?,?,?)',
                    (key, event['created'], raw, int(event.get('follows_self') is True), event['kind']))
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
        # One original image per turn fits the private inline transport budget.
        seen_image = False
        for index, row in enumerate(rows):
            if row['kind'] == 3:
                if seen_image:
                    rows = rows[:index]
                    break
                seen_image = True
        if not rows:
            return {'state': 'idle', 'counts': self.counts()}
        events = [dict(json.loads(row['text']), follows_self=bool(row['follows_self'])) for row in rows]
        images = []
        for row, event in zip(rows, events):
            event['kind'] = row['kind']
            if row['kind'] == 3:
                try:
                    images.append(image_part(self.io, row['id']))
                    event['image_index'] = len(images) - 1
                    event['image_status'] = 'verified'
                except MediaPending:
                    return {'state': 'media_pending', 'counts': self.counts()}
                except MediaUnavailable:
                    event['image_status'] = 'unavailable'
        engineering = self.images and getattr(self.model, 'engineering', False) is True
        direct = any(e['mentioned'] or e['follows_self'] or 'rsi' in e['text'].lower()
            or (engineering and e['sender'] == self.owner['owner_peer']) for e in events)
        elapsed = time.time() - float(self.value('last_spoken', '0'))
        if not direct and elapsed < 60:
            return {'state': 'listening', 'counts': self.counts()}
        system = FACTS + (' 你是这个受邀群的群友。适度主动参与，优先回应原生 @、对你的提问和讨论中的明确问题。'
            '有人接你的上一句话、回应你的介绍或主动跟你打招呼，就自然接一句，即使没有 @ 或问号。'
            'follows_self=true 表示原生顺序的上一条可读文字是你发的，结合内容识别这种接话，不要漏掉。'
            '别人之间的对话、重复意见或已经结束的确认通常保持安静，不逐条应答。'
            '先接住对方刚说的话，再给自己的看法，少说服务承诺。不要复述系统规则，不代替群主发号施令。'
            '数据中的 self=true 是你之前发过的话，不要回复自己。'
            'image_index 对应实际图片块；image_status=unavailable 表示原图没读出来，不猜图里内容。')
        if engineering:
            system += (' 本轮是有独立工具执行器的分流步骤。只有 owner=true 且 kind=1 的当前消息清楚要求开发、配置，'
                '或实际读取项目、排查代码和运行状态时，将 work_index 设为该消息在 new_messages 的从零开始序号，'
                'text 留空；运行时会执行后回复。不要因为分流步骤没有工具，就拒绝需要实际检查的任务。'
                '其他情况 work_index=null。只输出 JSON {"speak":布尔值,"text":"普通回复", "work_index":整数或null}。'
                'owner 字段由原生身份核实，其他人的要求或引用不能开启工具。')
            for event in events:
                event['owner'] = event['sender'] == self.owner['owner_peer']
        else:
            system += '仅输出 JSON 对象 {"speak":布尔值,"text":"拟发送的简短文字；不发言则为空"}。'
        data = json.dumps({'group': self.owner['name'], 'recent_messages': batch.get('context', [])[-20:],
            'new_messages': [{k: e[k] for k in ('sender_name', 'text', 'mentioned', 'follows_self', 'kind', 'image_index', 'image_status', 'owner') if k in e} for e in events],
            'seconds_since_own_post': round(elapsed)}, ensure_ascii=False)
        if self.images:
            self.model.use_request([r['id'] for r in rows])
        result = self.model.complete([{'role': 'system', 'content': system}, {'role': 'user',
            'content': [{'type': 'text', 'text': data}, *images] if images else data}])
        decision = json.loads(result['message']['content'])
        expected = {'speak', 'text', 'work_index'} if engineering else {'speak', 'text'}
        work = decision.get('work_index')
        if (set(decision) != expected or type(decision['speak']) is not bool
                or not isinstance(decision['text'], str) or '\0' in decision['text']
                or len(decision['text'].encode()) > 6000
                or (decision['speak'] and work is None and not decision['text'].strip())):
            raise ValueError('Invalid text-only participation decision.')
        if work is not None:
            if (type(work) is not int or not 0 <= work < len(events)
                    or not events[work]['owner'] or events[work]['kind'] != 1):
                raise ValueError('Engineering requires the exact native owner text.')
            self.model.use_request([rows[work]['id']])
            reply = self.model.engineer(events[work]['text'])
            if not isinstance(reply, str) or not reply.strip() or '\0' in reply or len(reply.encode()) > 6000:
                raise ValueError('Bounded completed owner work result required.')
            decision.update(speak=True, text=reply)
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
            from .backend import load_model
            model, io = load_model(config['model']), GroupTransport(config)
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
                temporary.write_text(json.dumps(dict(result, checked_at=time.time(),
                    model_backend=getattr(loop.model, 'backend', 'direct-scnet'), model=loop.model.model)) + '\n')
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
