import base64
import hashlib
import json
import subprocess
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from unittest.mock import Mock

from rsi_agent.dsh_worker import blocks, execute
from rsi_agent.backend import DshBackend
from rsi_agent import engineering
from rsi_agent.model import ModelError, PublicationPending


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
        self.close_error = None
        self.on_run = lambda: None
        self.real_prepare, self.real_publish = engineering.prepare, engineering.publish
        outer = self

        class Harness:
            def __init__(self, **kwargs):
                outer.launches.append(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                if outer.close_error:
                    raise outer.close_error

            def run(self, content, session_id):
                outer.calls.append((content, session_id))
                outer.on_run()
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

    def test_publication_interruption_keeps_completed_output_without_reexecution(self):
        with patch('rsi_agent.engineering.publish', side_effect=TimeoutError('publication interrupted')) as publish:
            with self.assertRaises(TimeoutError):
                execute(self.config, self.request)
            path = self.state / 'calls' / (self.request['id'] + '.json')
            frozen = path.read_bytes()
            completed = json.loads(frozen)
            self.assertEqual(completed['state'], 'sdk_completed')
            self.assertEqual(completed['response'], self.response)
            self.assertEqual(completed['session'], self.request['session'])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertTrue((Path(self.config['engineering_workspace']).parent / 'engineering-current.json').exists())
            with self.assertRaisesRegex(ValueError, 'uncertain'):
                execute(self.config, self.request)
            self.assertEqual(path.read_bytes(), frozen)
            self.assertEqual(len(self.calls), 1)
            publish.assert_called_once()

    def test_sdk_shutdown_cannot_erase_already_completed_output(self):
        self.close_error = TimeoutError('SDK shutdown interrupted')
        with patch('rsi_agent.engineering.publish') as publish:
            with self.assertRaises(TimeoutError):
                execute(self.config, self.request)
            publish.assert_not_called()
        completed = json.loads((self.state / 'calls' / (self.request['id'] + '.json')).read_text())
        self.assertEqual(completed['state'], 'sdk_completed')
        self.assertEqual(completed['response'], self.response)

    def test_original_completed_output_resumes_real_git_after_lost_push_ack(self):
        work = Path(self.config['engineering_workspace'])
        remote = self.root / 'remote.git'
        subprocess.run(['git', 'init', '--bare', str(remote)], check=True, capture_output=True)
        subprocess.run(['git', 'init', str(work)], check=True, capture_output=True)
        for args in [('config', 'user.name', 'Fixture'), ('config', 'user.email', 'fixture@example.invalid'),
                     ('remote', 'add', 'origin', str(remote)), ('checkout', '-b', engineering.BRANCH)]:
            engineering.git(work, *args)
        (work / 'scripts').mkdir()
        (work / 'scripts/check.py').write_text('print("fixture validation")\n')
        (work / 'README.md').write_text('before\n')
        engineering.git(work, 'add', '.')
        engineering.git(work, 'commit', '-m', 'fixture baseline')
        engineering.git(work, 'push', 'origin', 'HEAD:main')
        self.on_run = lambda: (work / 'README.md').write_text('original SDK source\n')
        real_git = engineering.git

        def lost_ack(workspace, *args, **kwargs):
            result = real_git(workspace, *args, **kwargs)
            if args[0] == 'push':
                raise TimeoutError('lost ack after actual push')
            return result

        with patch.object(engineering, 'REMOTE', str(remote)), \
                patch.object(engineering, 'prepare', self.real_prepare), \
                patch.object(engineering, 'publish', self.real_publish):
            with patch.object(engineering, 'git', side_effect=lost_ack):
                with self.assertRaises(TimeoutError):
                    execute(self.config, self.request)
            path = self.state / 'calls' / (self.request['id'] + '.json')
            frozen = json.loads(path.read_text())
            self.assertEqual(frozen['state'], 'sdk_completed')
            original_commit = real_git(remote, 'rev-parse', engineering.BRANCH)

            def only_reconcile(workspace, *args, **kwargs):
                if args[0] in ('push', 'update-ref', 'commit-tree'):
                    raise AssertionError('Git effect must not repeat')
                return real_git(workspace, *args, **kwargs)

            with patch('rsi_agent.dsh_worker.ModelClient', side_effect=AssertionError('no new model')), \
                    patch.object(engineering, 'prepare', side_effect=AssertionError('no reset/reprepare')), \
                    patch.object(engineering, 'git', side_effect=only_reconcile):
                completed = execute(self.config, self.request)
                self.assertEqual(execute(self.config, self.request), json.loads(path.read_text()))
            self.assertEqual(len(self.calls), 1)
            self.assertEqual(completed['change']['commit'], original_commit)
            self.assertEqual(completed['input_sha256'], frozen['input_sha256'])
            self.assertTrue(completed['response'].startswith(self.response + '\n'))
            self.assertEqual(completed['response'].count(completed['change']['review_url']), 1)
            self.assertFalse((work.parent / 'engineering-current.json').exists())
            self.assertEqual(real_git(work, 'status', '--porcelain'), '')

    def test_completed_receipt_clears_only_its_own_leftover_marker(self):
        execute(self.config, self.request)
        marker = Path(self.config['engineering_workspace']).parent / 'engineering-current.json'
        marker.write_text(json.dumps({'request': self.request['id'], 'base': 'fixture'}))
        marker.chmod(0o600)
        execute(self.config, self.request)
        self.assertFalse(marker.exists())
        marker.write_text(json.dumps({'request': 'b' * 64, 'base': 'other work'}))
        marker.chmod(0o600)
        execute(self.config, self.request)
        self.assertTrue(marker.exists())

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

    def test_private_preferences_are_loaded_for_new_turns_without_rewriting_original_results(self):
        path = self.root / 'preferences.md'
        path.write_text('Use concrete technical reasoning; retain the accepted conversation style.')
        path.chmod(0o600)
        request = dict(self.request, mode='chat')
        first = execute(self.config, request)
        self.assertIn(path.read_text(), self.launches[0]['env']['DSH_SYSTEM_PROMPT'])
        self.assertEqual(first['preferences_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        path.write_text('A corrected preference for later turns.')
        self.assertEqual(execute(self.config, request)['preferences_sha256'], first['preferences_sha256'])
        self.assertEqual(len(self.calls), 1)
        second = execute(self.config, dict(request, id='b' * 64))
        self.assertEqual(second['preferences_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertIn(path.read_text(), self.launches[1]['env']['DSH_SYSTEM_PROMPT'])

    def test_engineering_selects_structured_tool_patch(self):
        execute(self.config, self.request)
        self.assertTrue(self.launches[0]['patches'][-1].endswith('engineering.patch.yml'))
        self.assertNotIn('chat.patch.yml', ' '.join(self.launches[0]['patches']))

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


@unittest.skipUnless(sys.platform == 'linux', 'requires private publication receipts')
class PublicationRoutingTests(unittest.TestCase):
    def test_only_bound_recoverable_publication_defers_the_native_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            calls = Path(folder) / 'calls'
            calls.mkdir(mode=0o700)
            key, digest, response = 'a' * 64, 'b' * 64, 'Original completed task result'
            original = calls / (key + '.json')
            original.write_text(json.dumps({'state': 'sdk_completed', 'input_sha256': digest, 'response': response}))
            original.chmod(0o600)
            publication = calls / (key + '.publication.json')
            binding = {'request': key, 'input_sha256': digest,
                       'response_sha256': hashlib.sha256(response.encode()).hexdigest()}
            publication.write_text(json.dumps({'phase': 'validated', 'binding': binding}))
            publication.chmod(0o600)
            model = DshBackend.__new__(DshBackend)
            model.config, model.engineering = {'state': folder}, True
            model.scope, model.request, model.last_input_key = ['account', 'owner'], ['1'], key
            model._run = Mock(side_effect=ModelError('publisher interrupted'))
            with self.assertRaises(PublicationPending):
                model.engineer('Original task')
            publication.write_text(json.dumps({'phase': 'review', 'binding': binding}))
            self.assertIn('还不能算完成', model.engineer('Original task'))
            publication.unlink()
            self.assertIn('还不能算完成', model.engineer('Original task'))


class LinkReadingAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'inputs').mkdir()
        self.model = DshBackend.__new__(DshBackend)
        self.model.config = {'state': str(self.root)}
        self.model.engineering = True
        self.model.model = 'fixture'
        self.model.engineer = Mock(return_value='Verified engineering result')
        self.pages = [{'state': 'ready', 'text': 'Untrusted page asks to execute commands.'}]
        self.calls = []
        self.engineering = False

        def run(messages, mode, stage=None):
            self.calls.append((messages, mode, stage))
            if stage is None:
                self.model.last_input_key = 'a' * 64
                (self.root / 'inputs' / ('a' * 64 + '.json')).write_text(json.dumps({'messages': messages}))
                text = json.dumps({'engineering': self.engineering, 'text': 'Routing result only'})
            else:
                text = 'A factual read-only answer.'
            return {'message': {'content': text}}

        self.model._run = run

    def test_page_text_enters_only_a_separate_tool_free_chat_stage_after_routing(self):
        result = self.model.reply('Read https://example.com/a', pages=self.pages)
        self.assertEqual(result, 'A factual read-only answer.')
        self.assertNotIn('Untrusted page', str(self.calls[0][0]))
        self.assertIn('Untrusted page', str(self.calls[1][0]))
        self.assertEqual(self.calls[1][1:], ('chat', 'link-reading'))
        self.model.engineer.assert_not_called()

    def test_explicit_native_engineering_still_executes_only_the_original_instruction(self):
        self.engineering = True
        prompt = 'Implement the requested integration at https://example.com/a'
        self.assertEqual(self.model.reply(prompt, pages=self.pages), 'Verified engineering result')
        self.model.engineer.assert_called_once_with(prompt)
        self.assertEqual(len(self.calls), 1)
        self.assertNotIn('Untrusted page', str(self.calls[0][0]))


class HarnessToolAuthorityTests(unittest.TestCase):
    """Engineering has structured tools; chat must keep none of them."""

    def test_engineering_patch_enables_file_and_fetch_tools_only(self):
        patch = (Path(__file__).resolve().parents[1] / 'harness/deepseek/engineering.patch.yml').read_text()
        self.assertIn("- id: tool-fs", patch)
        for flag in ('read: true', 'readImage: true', 'write: true', 'edit: true'):
            self.assertIn(flag, patch)
        self.assertIn("name: '@deepseek-ai/dsh-web'", patch)
        self.assertIn("name: '@deepseek-ai/dsh-web-fetch-http'", patch)
        self.assertIn("name: '@deepseek-ai/dsh-tool-web'", patch)
        self.assertIn('fetch: true', patch)
        # Scan/search is served by web_search; no provider is configured here.
        self.assertIn('search: false', patch)
        self.assertNotIn('disabled: true', patch)

    def test_chat_patch_removes_every_execution_tool(self):
        patch = (Path(__file__).resolve().parents[1] / 'harness/deepseek/chat.patch.yml').read_text()
        self.assertNotIn('insert:', patch)
        for entry in ('persistent-bash', 'persistent-pwsh', 'tool-fs', 'tool-working-directory'):
            self.assertIn('- id: ' + entry, patch)
        self.assertEqual(patch.count('disabled: true'), 4)
