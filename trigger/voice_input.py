"""Read and transcribe an original voice message in the confirmed owner chat."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from rsi_agent.config import ROOT
from rsi_agent.wechat import private_file


MAX_AUDIO_BYTES = 2_000_000
MEDIA_GRACE_SECONDS = 25


def read_owner_voice(peer, server, since):
    from linux_tool import native, signed

    server = signed(server)
    table = 'Msg_' + hashlib.md5(peer.encode()).hexdigest()
    with native('message/message_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed voice message identity required.')
        rows = db.execute('SELECT m.create_time,m.local_type,n.user_name FROM ' + table +
                          ' m JOIN Name2Id n ON n.rowid=m.real_sender_id WHERE m.server_id=?',
                          (server,)).fetchall()
        if len(rows) != 1 or rows[0][2] != peer or int(rows[0][1]) & 0xffffffff != 34 or rows[0][0] < since:
            raise ValueError('Original inbound owner voice required.')
    with native('message/media_0.db') as (db, receipt):
        if receipt.get('consistency') != 'committed' or receipt.get('gap'):
            raise ValueError('Committed voice media required.')
        matches = db.execute('SELECT length(v.voice_data) FROM VoiceInfo v '
                             'JOIN Name2Id n ON n.rowid=v.chat_name_id WHERE n.user_name=? AND v.svr_id=?',
                             (peer, server)).fetchall()
        if not matches or len(matches) == 1 and not matches[0][0]:
            return {'state': 'audio_pending'}
        if len(matches) != 1 or not 0 < matches[0][0] <= MAX_AUDIO_BYTES:
            raise ValueError('Conflicting or oversized original voice media.')
        data = db.execute('SELECT v.voice_data FROM VoiceInfo v JOIN Name2Id n ON n.rowid=v.chat_name_id '
                          'WHERE n.user_name=? AND v.svr_id=?', (peer, server)).fetchone()[0]
    return {'state': 'audio_ready', 'data': base64.b64encode(data).decode(),
            'sha256': hashlib.sha256(data).hexdigest()}


class VoiceInput:
    def __init__(self, since, python, model):
        self.since = since
        self.python = python
        self.model = model

    @classmethod
    def load(cls, path, since):
        if not path.exists():
            return None
        if not private_file(path) or path.stat().st_uid != os.getuid() or path.stat().st_size > 4096:
            raise ValueError('Private voice intake configuration required.')
        data = json.loads(path.read_text())
        if (set(data) != {'since', 'python', 'model'} or type(data['since']) is not int or data['since'] < since
                or not all(isinstance(data[k], str) and Path(data[k]).is_absolute() for k in ('python', 'model'))):
            raise ValueError('Invalid owner voice intake configuration.')
        return cls(**data)

    def __call__(self, transport, server, created):
        try:
            result = transport({'op': 'voice', 'server_id': server})
            if result['state'] == 'audio_pending':
                return None if time.time() < created + MEDIA_GRACE_SECONDS else ''
            if result['state'] != 'audio_ready':
                return ''
            data = base64.b64decode(result['data'], validate=True)
            if not (0 < len(data) <= MAX_AUDIO_BYTES and hashlib.sha256(data).hexdigest() == result['sha256']):
                return ''
            from pwd import getpwnam
            user = getpwnam('wechat-gui')
            process = subprocess.run([self.python, '-B', '-m', 'trigger.voice_asr', self.model], cwd=ROOT,
                                     input=data, capture_output=True, timeout=25,
                                     user=user.pw_uid, group=user.pw_gid, extra_groups=[])
            if process.returncode or len(process.stdout) > 12000:
                return ''
            text = json.loads(process.stdout)['text'].strip()
            return text if '\0' not in text and len(text.encode()) <= 10000 else ''
        except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError):
            return ''
