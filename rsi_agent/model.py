"""OpenAI-compatible model port; credentials stay in private host files."""
import json
from pathlib import Path
from urllib.parse import urlsplit
import urllib.error
import urllib.request

from .wechat import private_file


class ModelError(ValueError):
    pass


class PublicationPending(ModelError):
    """The original Codex request is waiting for completion or transport."""


class OriginalReview(ModelError):
    """The worker retained the original request for review instead of retrying."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ModelClient:
    def __init__(self, path, opener=None):
        path = Path(path).expanduser().absolute()
        if not private_file(path):
            raise ModelError('A private model configuration owned by the caller is required.')
        config = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(config, dict) or set(config) != {'base_url', 'model', 'api_key_file'}
                or not all(isinstance(value, str) and value.strip() for value in config.values())):
            raise ModelError('Model configuration requires base_url, model and api_key_file.')
        url = urlsplit(config['base_url'])
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ModelError('An explicit HTTPS model base URL is required.')
        key_path = Path(config['api_key_file']).expanduser()
        key_path = key_path if key_path.is_absolute() else path.parent / key_path
        if not private_file(key_path):
            raise ModelError('A private API key file owned by the caller is required.')
        key = key_path.read_text(encoding='utf-8').strip()
        if not key or len(key) > 4096 or any(c.isspace() for c in key):
            raise ModelError('The API key file must contain one nonempty token.')
        self.base_url, self.model, self._key = config['base_url'].rstrip('/'), config['model'], key
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def complete(self, messages, *, tools=None, tool_choice=None, json_output=False):
        payload = {'model': self.model, 'messages': messages, 'max_tokens': 1024, 'stream': False}
        if json_output:
            payload['response_format'] = {'type': 'json_object'}
        if tools is not None:
            payload['tools'] = tools
        if tool_choice is not None:
            payload['tool_choice'] = tool_choice
        request = urllib.request.Request(self.base_url + '/chat/completions',
            data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self._key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read(2000001)
        except urllib.error.HTTPError as error:
            raise ModelError('Model endpoint returned HTTP ' + str(error.code) + '.') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ModelError('Model endpoint is unavailable.') from None
        try:
            if len(raw) > 2000000:
                raise ValueError()
            data = json.loads(raw)
            choice = data['choices'][0]
            message = choice['message']
            if not isinstance(message, dict) or not (isinstance(message.get('content'), str) or message.get('tool_calls')):
                raise ValueError()
            return {'model': data.get('model', self.model),
                    'message': {key: message[key] for key in ('role', 'content', 'tool_calls') if key in message},
                    'finish_reason': choice.get('finish_reason'), 'usage': data.get('usage', {})}
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError('Model endpoint returned an invalid completion.') from None

    def reply(self, prompt, history=()):
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode('utf-8')) > 32768:
            raise ModelError('A nonempty model prompt of at most 32768 bytes is required.')
        result = self.complete([{'role': 'system', 'content': '你是 RSI Agent，请用简洁中文回复。'},
                                *history, {'role': 'user', 'content': prompt}])
        text = result['message'].get('content')
        if not isinstance(text, str) or not text.strip():
            raise ModelError('Model did not return a text reply.')
        return text

    def check(self):
        if self.reply('只回复 RSI_SCNET_OK，不要解释。').strip() != 'RSI_SCNET_OK':
            raise ModelError('Model text probe did not match.')
        tool = {'type': 'function', 'function': {'name': 'rsi_probe', 'description': 'Interface probe; never executed.',
                'parameters': {'type': 'object', 'properties': {'value': {'type': 'string'}},
                               'required': ['value'], 'additionalProperties': False}}}
        result = self.complete([{'role': 'user', 'content': '请调用 rsi_probe 工具，value 参数为 ready。'}],
                               tools=[tool], tool_choice={'type': 'function', 'function': {'name': 'rsi_probe'}})
        try:
            function = result['message']['tool_calls'][0]['function']
            if function['name'] != 'rsi_probe' or json.loads(function['arguments']) != {'value': 'ready'}:
                raise ValueError()
        except (ValueError, KeyError, IndexError, TypeError):
            raise ModelError('Model tool-call probe did not match.') from None
        return {'state': 'ready', 'base_url': self.base_url, 'model': self.model,
                'text_verified': True, 'tool_call_verified': True, 'tool_executed': False}
