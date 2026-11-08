import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import Mock, patch

from rsi_agent import __main__ as cli
from rsi_agent.model import ModelClient, ModelError


class ModelTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / 'model.json'
        self.config.write_text(json.dumps({'base_url': 'https://api.scnet.cn/api/llm/v1/',
            'model': 'fixture-model', 'api_key_file': 'key.txt'}))
        (self.root / 'key.txt').write_text('fixture-private-key\n')
        private = patch('rsi_agent.model.private_file', return_value=True)
        private.start()
        self.addCleanup(private.stop)
        self.opener = Mock()
        self.client = ModelClient(self.config, opener=self.opener)

    @staticmethod
    def completion(message, reason='stop'):
        return io.BytesIO(json.dumps({'model': 'fixture-model', 'choices': [
            {'message': message, 'finish_reason': reason}], 'usage': {'total_tokens': 4}}).encode())

    def test_unicode_history_and_reply_use_one_versioned_endpoint(self):
        self.opener.open.return_value = self.completion({'role': 'assistant', 'content': '收到🧪',
                                                        'reasoning_content': 'not returned by this port'})
        history = [{'role': 'user', 'content': '上文'}]
        self.assertEqual(self.client.reply('中文\n{"peer":"a","peer":"b"}', history), '收到🧪')
        request = self.opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://api.scnet.cn/api/llm/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'), 'Bearer fixture-private-key')
        body = json.loads(request.data)
        self.assertEqual(body['messages'][1], history[0])
        self.assertEqual(body['messages'][-1]['content'], '中文\n{"peer":"a","peer":"b"}')
        self.assertFalse(body['stream'])

    def test_probe_requires_text_and_real_tool_call_shape_without_execution(self):
        self.opener.open.side_effect = [self.completion({'content': 'RSI_SCNET_OK'}),
            self.completion({'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'fixture-call', 'type': 'function', 'function': {
                    'name': 'rsi_probe', 'arguments': '{"value":"ready"}'}}]}, 'tool_calls')]
        result = self.client.check()
        self.assertEqual(result['state'], 'ready')
        self.assertTrue(result['text_verified'] and result['tool_call_verified'])
        self.assertFalse(result['tool_executed'])
        self.assertNotIn('fixture-private-key', json.dumps(result))
        body = json.loads(self.opener.open.call_args.args[0].data)
        self.assertEqual(body['tool_choice']['function']['name'], 'rsi_probe')

    def test_http_errors_never_include_provider_body_or_credentials(self):
        self.opener.open.side_effect = urllib.error.HTTPError('https://api.scnet.cn/', 401,
            'fixture-private-key', {}, io.BytesIO(b'fixture-private-key'))
        with self.assertRaisesRegex(ModelError, '^Model endpoint returned HTTP 401\\.$') as error:
            self.client.reply('hi')
        self.assertNotIn('fixture-private-key', str(error.exception))

    def test_invalid_completion_and_tool_only_text_reply_are_rejected(self):
        for raw in (b'not json', b'{"choices":[]}', b'x' * 2000001):
            with self.subTest(size=len(raw)):
                self.opener.open.return_value = io.BytesIO(raw)
                with self.assertRaises(ModelError):
                    self.client.reply('hi')
        self.opener.open.return_value = self.completion({'content': None, 'tool_calls': [{'id': 'fixture'}]})
        with self.assertRaisesRegex(ModelError, 'text reply'):
            self.client.reply('hi')

    def test_invalid_prompt_does_not_contact_provider(self):
        for prompt in ('', ' ', '中' * 12000):
            with self.assertRaises(ModelError):
                self.client.reply(prompt)
        self.opener.open.assert_not_called()

    def test_cli_model_reply_does_not_load_wechat_configuration(self):
        with patch('rsi_agent.model.ModelClient', return_value=self.client), \
                patch('rsi_agent.__main__.load') as wechat, patch('sys.stdin', io.StringIO('你好')):
            self.opener.open.return_value = self.completion({'content': '已接通'})
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(cli.main(['--config', str(self.config), 'model', 'reply']), 0)
            self.assertEqual(json.loads(output.getvalue())['text'], '已接通')
            wechat.assert_not_called()


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux private-file ownership semantics')
class ModelPrivateFilesTests(unittest.TestCase):
    def test_shared_key_is_refused_before_network_access(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = root / 'config.json'
            config.write_text(json.dumps({'base_url': 'https://api.scnet.cn/api/llm/v1',
                'model': 'fixture', 'api_key_file': 'key.txt'}))
            config.chmod(0o600)
            key = root / 'key.txt'
            key.write_text('fixture-private-key')
            key.chmod(0o644)
            opener = Mock()
            with self.assertRaisesRegex(ModelError, 'private API key'):
                ModelClient(config, opener=opener)
            opener.open.assert_not_called()
