"""One confirmed private conversation, a durable inbox, and the existing V2 sender."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

from .config import ROOT
from .model import ModelError
from .media import image_part, MediaPending, MediaUnavailable
from .wechat import private_file


class Transport:
    module = 'rsi_agent.reply_io'
    def __init__(self, config):
        self.config = config

    def __call__(self, request=None):
        command = ['runuser', '-u', 'wechat-gui', '--', sys.executable, '-B', '-m',
            self.module, '--installation', self.config['installation'],
            '--binding', self.config['binding']]
        if request is None:
            command.append('--check')
        else:
            request = dict(request, _binding=self.config['binding_token'])
        result = subprocess.run(command, cwd=ROOT, input=json.dumps(request) if request else None,
            capture_output=True, text=True, timeout=180)
        limit = 15000000 if request and request.get('op') == 'image' else 1500000
        if result.returncode or len(result.stdout.encode()) > limit:
            raise ValueError('Owner reply transport is unavailable; preserve the original request.')
        value = json.loads(result.stdout)
        if value.get('state') in ('blocked', 'error'):
            raise ValueError('Owner reply transport is blocked; preserve the original request.')
        if request is None and value.get('binding_token') != self.config['binding_token']:
            raise ValueError('Confirmed owner reply identity or scope changed.')
        return value


class ReplyLoop:
    def __init__(self, path, owner, model, transport, context=None):
        path = Path(path)
        if path.is_symlink():
            raise ValueError('Private owner reply state required.')
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            os.close(fd)
        if not private_file(path):
            raise ValueError('Private owner reply state required.')
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('CREATE TABLE IF NOT EXISTS meta(binding TEXT NOT NULL);'
            'CREATE TABLE IF NOT EXISTS inbox(id TEXT PRIMARY KEY,created INTEGER NOT NULL,'
            'text TEXT NOT NULL,reply TEXT,state TEXT NOT NULL DEFAULT "new");')
        if 'kind' not in {r[1] for r in self.db.execute('PRAGMA table_info(inbox)')}:
            self.db.execute('ALTER TABLE inbox ADD COLUMN kind INTEGER NOT NULL DEFAULT 1')
        identity = json.dumps([owner['account'], owner['peer'], owner['scope']], sort_keys=True)
        old = self.db.execute('SELECT binding FROM meta').fetchone()
        if old and old[0] != identity:
            raise ValueError('Original owner reply state binding changed.')
        if not old:
            with self.db:
                self.db.execute('INSERT INTO meta VALUES(?)', (identity,))
        self.owner, self.model, self.io = owner, model, transport
        self.context = context
        self.images = getattr(model, 'backend', None) == 'deepseek-harness'
        if self.images:
            model.bind(owner['account'], owner['peer'])

    def close(self):
        self.db.close()

    def counts(self):
        return dict(self.db.execute('SELECT state,count(*) FROM inbox GROUP BY state').fetchall())

    def cycle(self):
        if self.db.execute("SELECT 1 FROM inbox WHERE state='attention'").fetchone():
            return {'state': 'attention', 'counts': self.counts()}
        batch = self.io({'op': 'read'})
        scope = self.owner['scope']
        with self.db:
            for event in batch.get('events', []):
                bootstrap = str(event['server_id']) == scope.get('bootstrap_server_id')
                media = self.images and (event.get('kind') == 3 or (
                    event.get('kind') == 49 and event.get('image_kind') == 'finder_cover'))
                if (event.get('account') != self.owner['account'] or event.get('peer') != self.owner['peer']
                        or event.get('sender') != self.owner['peer'] or (event.get('kind') != 1 and not media)
                        or (not bootstrap and (scope['mode'] == 'one-message' or event['created'] < scope['since']))):
                    continue
                text = event.get('text')
                if event['kind'] == 3:
                    text = ''  # Native media XML can contain cache credentials.
                if not isinstance(text, str) or (event['kind'] == 1 and not text.strip()) or '\0' in text or len(text.encode()) > 32768:
                    continue
                key = str(event['server_id'])
                old = self.db.execute('SELECT text FROM inbox WHERE id=?', (key,)).fetchone()
                if old and old['text'] != text:
                    raise ValueError('Original native message changed; reply is blocked.')
                self.db.execute('INSERT OR IGNORE INTO inbox(id,created,text,kind) VALUES(?,?,?,?)',
                                (key, event['created'], text, event['kind']))
        # Consumer commit precedes source ACK; a lost ACK is harmless on replay.
        if batch.get('batch_id'):
            self.io({key: batch[key] for key in ('batch_id', 'batch_hash', 'ack_ids')} | {'op': 'ack'})
        row = self.db.execute("SELECT * FROM inbox WHERE state IN ('new','pending') ORDER BY created,id LIMIT 1").fetchone()
        if row is None:
            return {'state': 'idle', 'counts': self.counts()}
        reply = row['reply']
        if reply is None:
            images = []
            image_error = None
            if self.images:
                self.model.use_request([row['id']])
            if row['kind'] in (3, 49):
                try:
                    images = [image_part(self.io, row['id'])]
                except MediaPending:
                    return {'state': 'media_pending', 'counts': self.counts()}
                except MediaUnavailable:
                    image_error = '这张图还没读出来，不能按我已经看见来回答。单独再发一张原图，我再看看。'
            history = []
            for old in reversed(self.db.execute("SELECT text,reply FROM inbox WHERE state='sent' ORDER BY created DESC,id DESC LIMIT 3").fetchall()):
                history.extend([{'role': 'user', 'content': old['text']}, {'role': 'assistant', 'content': old['reply']}])
            if self.context:
                history = self.context(row['text'] if row['kind'] == 1 else '') + history
            reply = image_error or (self.model.reply(row['text'] or '看看这张图，接着对话回答。', history,
                images=images, allow_engineering=False)
                if images else self.model.reply(row['text'], history))
            if not isinstance(reply, str) or not reply.strip() or '\0' in reply or len(reply.encode()) > 16384:
                raise ValueError('Model reply does not satisfy the text-only sender contract.')
            with self.db:
                self.db.execute("UPDATE inbox SET reply=?,state='pending' WHERE id=?", (reply, row['id']))
        outcome = self.io({'op': 'submit', 'server_id': row['id'], 'text': reply})
        if outcome['state'] in ('queued', 'confirmed'):
            outcome = self.io({'op': 'advance', 'server_id': row['id']})
        sent = outcome['state'] == 'succeeded' and outcome.get('outcome') == 'sent'
        state = 'sent' if sent and not outcome.get('cleanup_pending') else (
            'pending' if outcome['state'] in ('queued', 'confirmed', 'busy') else 'attention')
        with self.db:
            self.db.execute('UPDATE inbox SET state=? WHERE id=?', (state, row['id']))
        return {'state': state, 'counts': self.counts(), 'sender_code': outcome.get('code')}


def run(path, mode):
    os.umask(0o077)
    if not path or not private_file(path):
        raise ValueError('Explicit private owner reply configuration required.')
    config = json.loads(Path(path).read_text())
    if set(config) != {'installation', 'binding', 'model', 'state', 'enabled', 'binding_token'} or type(config['enabled']) is not bool:
        raise ValueError('Invalid owner reply configuration.')
    from .backend import load_model
    model, transport = load_model(config['model']), Transport(config)
    owner = transport()
    if mode == 'check':
        return {'state': 'prepared', 'model': model.model, 'owner_confirmed': True,
                'enabled': config['enabled'] and owner['enabled'], 'network_probe': False}
    if not config['enabled'] or not owner['enabled']:
        raise ValueError('Owner reply activation has not been authorized in private configuration.')
    state = Path(config['state'])
    if (state.is_symlink() or not state.is_dir() or state.stat().st_mode & 0o077
            or state.stat().st_uid != os.getuid()):
        raise ValueError('Private owner reply directory required.')
    import fcntl
    fd = os.open(state / 'worker.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    loop = None
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        from .group_context import owner_context
        loop = ReplyLoop(state / 'inbox.sqlite', owner, model, transport, context=owner_context)
        previous = None
        while not stopped:
            # The private switches can stop future input without changing identities or IDs.
            if not json.loads(Path(path).read_text()).get('enabled') or not transport()['enabled']:
                break
            try:
                result = loop.cycle()
            except ModelError:
                result = {'state': 'model_unavailable', 'counts': loop.counts()}
            except (OSError, ValueError, subprocess.SubprocessError):
                result = {'state': 'transport_attention', 'counts': loop.counts()}
            temporary = state / 'status.tmp'
            temporary.write_text(json.dumps(dict(result, checked_at=time.time(),
                model_backend=getattr(model, 'backend', 'direct-scnet'), model=model.model)) + '\n')
            temporary.chmod(0o600)
            os.replace(temporary, state / 'status.json')
            if result != previous:
                if mode == 'run':
                    print(json.dumps(result), flush=True)
                previous = result
            if mode == 'once' or (owner['scope']['mode'] == 'one-message' and result.get('counts', {}).get('sent')):
                return result
            for _ in range(6):
                if stopped:
                    break
                time.sleep(0.5)
        return {'state': 'stopped'}
    finally:
        if loop is not None:
            loop.close()
        os.close(fd)
