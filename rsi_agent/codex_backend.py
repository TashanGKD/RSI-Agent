"""Frozen native model requests forwarded to this computer's Codex worker."""
import hashlib
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .backend import DshBackend
from .config import ROOT
from .model import ModelError, PublicationPending
from .wechat import private_file


class CodexBackend(DshBackend):
    backend = 'local-codex'

    def __init__(self, path):
        self.path = str(path)
        if not private_file(path):
            raise ModelError('Private local Codex configuration required.')
        self.config = json.loads(Path(path).read_text())
        required = {'backend', 'endpoint', 'token_file', 'state', 'model', 'preferences_file', 'engineering'}
        if set(self.config) != required or self.config['backend'] != self.backend:
            raise ModelError('Invalid local Codex configuration.')
        endpoint = urlsplit(self.config['endpoint'])
        if (endpoint.scheme != 'http' or endpoint.hostname != '127.0.0.1' or not endpoint.port
                or endpoint.username or endpoint.password or endpoint.path not in ('', '/')
                or endpoint.query or endpoint.fragment):
            raise ModelError('Local Codex requires the explicit authenticated loopback tunnel.')
        for name in ('token_file', 'preferences_file'):
            if not private_file(self.config[name]):
                raise ModelError('Private local Codex token/preferences required.')
        self.token = Path(self.config['token_file']).read_text().strip()
        if len(self.token) != 64 or any(c not in '0123456789abcdef' for c in self.token):
            raise ModelError('Invalid local Codex transport token.')
        state = Path(self.config['state'])
        if (not state.is_absolute() or not state.is_dir() or state.is_symlink()
                or state.stat().st_uid != os.getuid() or state.stat().st_mode & 0o077):
            raise ModelError('Private local Codex state required.')
        if type(self.config['engineering']) is not bool or not isinstance(self.config['model'], str):
            raise ModelError('Explicit local Codex model and task policy required.')
        self.model, self.engineering = self.config['model'], self.config['engineering']
        self.scope, self.request = None, None
        self.http = build_opener(ProxyHandler({}))

    def exchange(self, route, value=None):
        data = None if value is None else json.dumps(value, ensure_ascii=False).encode()
        request = Request(self.config['endpoint'].rstrip('/') + route, data=data,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            with self.http.open(request, timeout=8) as response:
                body = json.loads(response.read(1000001))
                return response.status, body
        except HTTPError as error:
            raise ModelError('Local Codex rejected the original request: HTTP ' + str(error.code)) from None
        except (OSError, URLError, ValueError):
            # Keep the native input and batch while this computer/tunnel is offline.
            raise PublicationPending('Original local Codex request is waiting for its worker.') from None

    def check_runtime(self):
        _, result = self.exchange('/health')
        if result.get('backend') != self.backend or result.get('ready') is not True:
            raise ModelError('Local Codex worker is not ready.')

    def _run(self, messages, mode, stage=None, schema=None):
        if not self.scope or not self.request:
            raise ModelError('Native account, peer and original request IDs required.')
        identity = [self.scope, self.request, mode]
        if stage:
            identity.append(stage)
        key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        self.last_input_key = key
        folder = Path(self.config['state']) / 'inputs'
        folder.mkdir(mode=0o700, exist_ok=True)
        if folder.is_symlink() or folder.stat().st_mode & 0o077:
            raise ModelError('Private frozen Codex inputs required.')
        path = folder / (key + '.json')
        if not path.exists():
            preferences = Path(self.config['preferences_file']).read_text()
            packet = {'id': key, 'mode': mode, 'scope': self.scope, 'request': self.request,
                'messages': [{'role': 'system', 'content': preferences}, *messages], 'schema': schema}
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w') as stream:
                stream.write(json.dumps(packet, ensure_ascii=False));stream.flush();os.fsync(stream.fileno())
        if not private_file(path):
            raise ModelError('Original Codex input is not private.')
        status, value = self.exchange('/requests', json.loads(path.read_text()))
        if status == 202:
            raise PublicationPending('Original local Codex generation is queued or running.')
        if value.get('state') != 'completed' or not isinstance(value.get('text'), str):
            raise ModelError('Original local Codex result needs inspection; do not regenerate it.')
        return {'model': self.model, 'message': {'role': 'assistant', 'content': value['text']},
                'finish_reason': 'stop', 'usage': {}}

    def complete(self, messages, *, tools=None, tool_choice=None, json_output=False):
        if tools is not None or tool_choice is not None:
            raise ModelError('Ordinary Codex conversation has no execution tools.')
        schema = None
        if json_output:
            group = self.scope and self.scope[1].endswith('@chatroom')
            fields = {'speak': {'type': 'boolean'}, 'text': {'type': 'string'}} if group else {
                'engineering': {'type': 'boolean'}, 'text': {'type': 'string'}}
            if group and self.engineering:
                fields['work_index'] = {'type': ['integer', 'null']}
            schema = {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
        return self._run(messages, 'chat', schema=schema)

    def engineer(self, prompt):
        if not self.engineering or not self.scope or not self.request:
            raise ModelError('Native owner task admission is required.')
        system = (ROOT / 'harness/CODEX-ENGINEERING.md').read_text(encoding='utf-8')
        return self._run([{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}],
                         'engineering')['message']['content']
