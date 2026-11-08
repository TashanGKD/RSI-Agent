import base64
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from rsi_agent.dsh_worker import blocks, execute
from rsi_agent.backend import DshBackend


class ImageBlocksTests(unittest.TestCase):
    def test_user_image_and_application_facts_remain_distinct(self):
        data = base64.b64encode(b'fixture image bytes').decode()
        system, content = blocks([{'role': 'system', 'content': 'Trusted runtime facts'},
            {'role': 'user', 'content': [{'type': 'text', 'text': 'Look at this'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + data}}]}])
        self.assertEqual(system, 'Trusted runtime facts')
        self.assertEqual(content[-1], {'type': 'image', 'mimeType': 'image/png', 'data': data})

    def test_remote_or_non_image_source_cannot_trigger_fetch(self):
        for url in ['https://example.com/private.png', 'file:///etc/passwd', 'data:text/plain;base64,YQ==']:
            with self.assertRaises(ValueError):
                blocks([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}])


@unittest.skipUnless(sys.platform == 'linux', 'requires private original framing cache')
class DecisionFramingTests(unittest.TestCase):
    def test_plain_reply_is_framed_once_from_original_inputs_without_replacing_it(self):
        with tempfile.TemporaryDirectory() as folder:
            state = Path(folder)
            (state / 'inputs').mkdir(mode=0o700)
            original = [{'role': 'system', 'content': 'Output JSON with speak/text/work_index.'},
                        {'role': 'user', 'content': 'original native question'}]
            (state / 'inputs' / ('a' * 64 + '.json')).write_text(json.dumps({'messages': original}))
            backend = DshBackend.__new__(DshBackend)
            backend.config = {'state': folder}
            backend.last_input_key = 'a' * 64
            prose = {'message': {'role': 'assistant', 'content': 'An already generated ordinary reply.'}}
            backend._run = Mock(return_value=prose)
            backend.provider = Mock()
            wanted = {'message': {'role': 'assistant', 'content': '{"speak":true,"text":"An already generated ordinary reply.","work_index":null}'}}
            backend.provider.complete.return_value = wanted
            self.assertEqual(backend.complete([{'role': 'user', 'content': 'changed live context'}], json_output=True), wanted)
            self.assertEqual(backend.complete([], json_output=True), wanted)
            backend.provider.complete.assert_called_once()
            request = backend.provider.complete.call_args
            self.assertEqual(request.args[0][:2], original)
            self.assertTrue(request.kwargs['json_output'])
            self.assertEqual(prose['message']['content'], 'An already generated ordinary reply.')


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux private journals and lock')
class HarnessDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        work = self.root / 'engineering-workspace'
        work.mkdir(mode=0o700)
        self.config = {'state': str(self.state), 'workspace': str(self.root),
                       'engineering_workspace': str(work), 'provider_config': 'fixture'}
        self.calls, self.launches, self.resumed = [], [], []
        self.response = 'verified result'
        outer = self

        class Harness:
            def __init__(self, **kwargs):
                outer.launches.append(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

            def run(self, content, session_id):
                outer.calls.append((content, session_id))
                return types.SimpleNamespace(finish_reason='completed', final_response=outer.response)

            def resume_session(self, session_id):
                outer.resumed.append(session_id)
                return types.SimpleNamespace(run=lambda content: self.run(content, session_id))

        self.sdk = patch.dict(sys.modules, {'deepseek_harness': types.SimpleNamespace(DeepSeekHarness=Harness)})
        self.sdk.start()
        self.addCleanup(self.sdk.stop)
        provider = patch('rsi_agent.dsh_worker.ModelClient', return_value=types.SimpleNamespace(
            model='fixture-model', base_url='https://fixture.example/v1', _key='fixture-not-a-key'))
        provider.start()
        self.addCleanup(provider.stop)
        for name in ('prepare', 'publish'):
            hook = patch('rsi_agent.engineering.' + name, return_value=None)
            hook.start()
            self.addCleanup(hook.stop)
        self.request = {'id': 'a' * 64, 'session': 'rsi-fixture', 'mode': 'engineering',
                        'messages': [{'role': 'user', 'content': 'Implement the bounded fixture task'}]}

    def test_completed_original_is_returned_without_rerunning_tools(self):
        first = execute(self.config, self.request)
        second = execute(self.config, self.request)
        self.assertEqual(first['response'], second['response'])
        self.assertEqual(len(self.calls), 1)

    def test_interrupted_original_and_changed_input_do_not_run_again(self):
        execute(self.config, self.request)
        path = self.state / 'calls' / (self.request['id'] + '.json')
        old = json.loads(path.read_text())
        old['state'] = 'running'
        path.write_text(json.dumps(old))
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            execute(self.config, self.request)
        changed = dict(self.request, messages=[{'role': 'user', 'content': 'A different task'}])
        with self.assertRaisesRegex(ValueError, 'input changed'):
            execute(self.config, changed)
        self.assertEqual(len(self.calls), 1)

    def test_chat_selects_tool_disabled_patch(self):
        execute(self.config, dict(self.request, mode='chat'))
        self.assertTrue(self.launches[0]['patches'][-1].endswith('chat.patch.yml'))
        self.assertIn('scnet.patch.yml', self.launches[0]['patches'][0])

    def test_next_input_explicitly_resumes_same_chat(self):
        execute(self.config, dict(self.request, mode='chat'))
        execute(self.config, dict(self.request, mode='chat', id='b' * 64))
        self.assertEqual(self.resumed, ['rsi-fixture'])
        self.assertEqual(len(self.calls), 2)

    def test_tool_markup_cannot_be_returned_as_an_executed_result(self):
        self.response = '<｜｜DSML｜｜ calls>unexecuted command'
        with self.assertRaisesRegex(ValueError, 'Unexecuted tool syntax'):
            execute(self.config, dict(self.request, mode='chat'))
        with self.assertRaisesRegex(ValueError, 'uncertain'):
            execute(self.config, dict(self.request, mode='chat'))
