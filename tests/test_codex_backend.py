import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from rsi_agent.codex_worker import Jobs, blocks, notify_desktop, run_codex, server
from rsi_agent.codex_backend import CodexBackend
from rsi_agent.model import ModelError, PublicationPending


def packet():
    return {'id': 'a' * 64, 'scope': ['self', 'owner'], 'request': ['42'], 'mode': 'chat',
            'messages': [{'role': 'system', 'content': 'Trusted facts'}, {'role': 'user', 'content': 'hello'}], 'schema': None}


THREAD = '00000000-0000-4000-8000-000000000001'
MESSAGE = '00000000-0000-4000-8000-000000000002'


def queued():
    return subprocess.CompletedProcess([], 0, 'Queued message ' + MESSAGE + ' for thread ' + THREAD + '.\n', '')


class CodexWorkerTests(unittest.TestCase):
    def test_images_are_inline_inputs_and_other_roles_remain_distinct(self):
        image = 'data:image/png;base64,' + base64.b64encode(b'verified bytes').decode()
        system, inputs = blocks([{'role': 'system', 'content': 'facts'},
            {'role': 'assistant', 'content': 'earlier reply'}, {'role': 'user', 'content': [
                {'type': 'text', 'text': 'Look'}, {'type': 'image_url', 'image_url': {'url': image}}]}])
        self.assertEqual(system, 'facts');self.assertEqual(inputs[-1], {'type': 'image', 'url': image})
        self.assertEqual(inputs[0]['text'], 'assistant: earlier reply')
        for url in ('https://example.com/image.png', 'file:///private.png', 'data:text/plain;base64,YQ=='):
            with self.assertRaises(ValueError):
                blocks([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': url}}]}])

    def test_original_completion_survives_reopen_changed_input_and_interruption(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td);request = packet();jobs.accept(request)
            self.assertIsNotNone(jobs.claim('chat'));self.assertIsNone(jobs.claim('chat'))
            jobs.update(request['id'], state='completed', result='fixed original')
            reopened = Jobs(td);reopened.review_interrupted()
            self.assertEqual(reopened.accept(request)['result'], 'fixed original')
            with self.assertRaises(ValueError):
                reopened.accept(dict(request, messages=[{'role': 'user', 'content': 'changed'}]))
            other = dict(request, id='b' * 64);jobs.accept(other);jobs.claim('chat')
            reopened.review_interrupted();self.assertEqual(reopened.get(other['id'])['state'], 'review')
            self.assertIsNone(reopened.claim('chat'))

    def test_actual_stdio_turn_freezes_before_process_shutdown(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td);user = root / 'user.toml';user.write_text('[mcp_servers.fixture]\ncommand="unused"\n')
            fake = root / 'fake.py'
            fake.write_text('''import json,sys
for line in sys.stdin:
 v=json.loads(line);method=v['method'];result={}
 if method=='thread/start':result={'thread':{'id':'original-thread'}}
 if method=='turn/start':result={'turn':{'id':'original-turn'}}
 if 'id' in v:print(json.dumps({'id':v['id'],'result':result}),flush=True)
 if method=='turn/start':
  print(json.dumps({'method':'item/completed','params':{'item':{'type':'agentMessage','phase':'final_answer','text':'original result'}}}),flush=True)
  print(json.dumps({'method':'item/completed','params':{'item':{'type':'agentMessage','phase':'commentary','text':'not a final answer'}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'turn':{'status':'completed'}}}),flush=True)
''')
            config = {'state': str(root), 'user_config': str(user), 'codex': sys.executable}
            jobs = Jobs(root);request = packet();jobs.accept(request);row = jobs.claim('chat')
            original = subprocess.Popen
            def spawn(command, **kwargs):
                self.assertIn('features.shell_tool=false', command)
                self.assertIn('mcp_servers.fixture.enabled=false', command)
                return original([sys.executable, '-B', str(fake)], **kwargs)
            with patch('rsi_agent.codex_worker.subprocess.Popen', side_effect=spawn):
                run_codex(config, jobs, row)
            result = jobs.get(request['id'])
            self.assertEqual((result['state'], result['result']), ('completed', 'original result'))
            self.assertEqual((result['thread_id'], result['turn_id']), ('original-thread', 'original-turn'))
            self.assertIn('turn/completed', (root / request['id'] / 'events.jsonl').read_text())


class DesktopRelayTests(unittest.TestCase):
    def test_task_queues_once_without_a_model_turn_and_completion_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td);request = dict(packet(), mode='engineering');jobs.accept(request)
            config = {'codex': 'existing-codex', 'desktop_thread_id': THREAD}
            with patch('rsi_agent.codex_worker.subprocess.run', return_value=queued()) as command:
                notify_desktop(config, jobs, jobs.claim('engineering'))
            command.assert_called_once();self.assertEqual(command.call_args.args[0][1], 'queue')
            row = jobs.get(request['id']);self.assertEqual(row['state'], 'desktop_queued')
            self.assertEqual(row['desktop_message_id'], MESSAGE);self.assertIsNone(jobs.claim('engineering'))
            reopened = Jobs(td);reopened.review_interrupted()
            original = reopened.desktop_task(request['id'], THREAD)
            self.assertEqual(original['body'], request);self.assertEqual(original['state'], 'desktop_queued')
            result = {'id': request['id'], 'input_sha256': row['digest'], 'thread_id': THREAD,
                      'turn_id': 'actual-desktop-turn', 'text': 'Verified original task result'}
            for changed in ({'input_sha256': 'f' * 64}, {'thread_id': MESSAGE}):
                with self.assertRaises(ValueError):reopened.complete_desktop(dict(result, **changed), THREAD)
            self.assertEqual(reopened.complete_desktop(result, THREAD)['state'], 'completed')
            self.assertEqual(reopened.complete_desktop(result, THREAD)['state'], 'completed')
            with self.assertRaises(ValueError):reopened.complete_desktop(dict(result, text='a second result'), THREAD)

    def test_uncertain_queue_acceptance_is_reviewed_without_requeueing(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td);request = dict(packet(), mode='engineering');jobs.accept(request)
            with patch('rsi_agent.codex_worker.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
                with self.assertRaises(ValueError):
                    notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD}, jobs, jobs.claim('engineering'))
            jobs.review_interrupted();self.assertEqual(jobs.get(request['id'])['state'], 'review')
            self.assertIsNone(jobs.claim('engineering'));command.assert_called_once()
            with self.assertRaises(ValueError):jobs.desktop_task(request['id'], THREAD)


@unittest.skipUnless(sys.platform == 'linux', 'native private backend configuration requires Linux')
class CodexBackendTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name);self.root.chmod(0o700)
        self.jobs = Jobs(self.root / 'worker')
        self.http = server({'token': 'c' * 64, 'port': 0, 'desktop_thread_id': THREAD}, self.jobs, threading.Event())
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
        for name, text in [('token', 'c' * 64), ('preferences', 'Concise natural conversation')]:
            p = self.root / name;p.write_text(text);p.chmod(0o600)
        state = self.root / 'native';state.mkdir(mode=0o700)
        self.config = {'backend': 'local-codex', 'endpoint': 'http://127.0.0.1:' + str(self.http.server_port),
            'token_file': str(self.root / 'token'), 'preferences_file': str(self.root / 'preferences'),
            'state': str(state), 'model': 'configured-codex', 'engineering': True}
        path = self.root / 'backend.json';path.write_text(json.dumps(self.config));path.chmod(0o600)
        self.backend = CodexBackend(path);self.backend.bind('self', 'owner');self.backend.use_request(['42'])

    def test_plain_owner_text_uses_only_codex_and_retries_the_frozen_original(self):
        with patch('rsi_agent.backend.ModelClient', side_effect=AssertionError('No SCNET fallback')):
            self.backend.check_runtime()
            with self.assertRaises(PublicationPending):
                self.backend.reply('hello without a prefix')
            key = self.backend.last_input_key;frozen = self.jobs.get(key)['body']
            self.jobs.update(key, state='completed', result='{"engineering":false,"text":"自然接话"}')
            self.assertEqual(self.backend.reply('later changed live context'), '自然接话')
            self.assertEqual(self.jobs.get(key)['body'], frozen)
            self.assertNotIn('provider_config', self.config)

    def test_native_group_schema_keeps_original_work_index_and_image(self):
        self.backend.bind('self', 'group@chatroom');self.backend.use_request(['44', '45'])
        image = 'data:image/png;base64,' + base64.b64encode(b'fixture').decode()
        messages = [{'role': 'system', 'content': 'Native owner flags'}, {'role': 'user', 'content': [
            {'type': 'text', 'text': 'group context'}, {'type': 'image_url', 'image_url': {'url': image}}]}]
        with self.assertRaises(PublicationPending):
            self.backend.complete(messages, json_output=True)
        value = json.loads(self.jobs.get(self.backend.last_input_key)['body'])
        self.assertEqual(set(value['schema']['properties']), {'speak', 'text', 'work_index'})
        self.assertEqual(value['request'], ['44', '45']);self.assertEqual(value['messages'][-1], messages[-1])
        with self.assertRaises(ModelError):self.backend.complete(messages, tools=[{}])

    def test_owner_engineering_is_a_separate_frozen_task_not_a_chat_tool(self):
        with self.assertRaises(PublicationPending):self.backend.engineer('Inspect the actual project')
        row = self.jobs.get(self.backend.last_input_key);value = json.loads(row['body'])
        self.assertEqual(value['mode'], 'engineering');self.assertEqual(value['scope'], ['self', 'owner'])
        self.jobs.update(value['id'], state='completed', result='Actual result with review link')
        self.assertEqual(self.backend.engineer('Do not replace the original'), 'Actual result with review link')

    def test_prefix_free_native_owner_loop_commits_then_sends_only_original_completion(self):
        from rsi_agent.owner_reply import ReplyLoop
        owner = {'account': 'self', 'peer': 'owner', 'scope': {'mode': 'owner-private-text', 'since': 100}}
        event = {'account': 'self', 'peer': 'owner', 'sender': 'owner', 'kind': 1,
                 'created': 120, 'server_id': 42, 'text': '你好，不带前缀'}
        sent = []
        def native(value):
            if value['op'] == 'read':
                return {'batch_id': 'original', 'batch_hash': 'hash', 'ack_ids': ['42'], 'events': [event]}
            if value['op'] == 'ack':return {'state': 'acked'}
            if value['op'] == 'submit':
                sent.append(value);return {'state': 'succeeded', 'outcome': 'sent'}
            raise AssertionError('No second native send')
        loop = ReplyLoop(self.root / 'inbox.sqlite', owner, self.backend, native)
        self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):loop.cycle()
        self.assertEqual(sent, []);self.assertTrue(loop.images)
        key = self.backend.last_input_key
        self.jobs.update(key, state='completed', result='{"engineering":false,"text":"接上啦"}')
        self.assertEqual(loop.cycle()['state'], 'sent');self.assertEqual(loop.cycle()['state'], 'idle')
        self.assertEqual(len(sent), 1);self.assertEqual(sent[0]['text'], '接上啦')

    def test_native_owner_task_waits_for_this_desktop_result_then_original_sender(self):
        from rsi_agent.owner_reply import ReplyLoop
        owner = {'account': 'self', 'peer': 'owner', 'scope': {'mode': 'owner-private-text', 'since': 100}}
        event = {'account': 'self', 'peer': 'owner', 'sender': 'owner', 'kind': 1,
                 'created': 120, 'server_id': 42, 'text': '检查实际项目并修复问题'}
        sends = []
        def native(value):
            if value['op'] == 'read':return {'events': [event]}
            if value['op'] == 'submit':
                sends.append(value);return {'state': 'succeeded', 'outcome': 'sent'}
            raise AssertionError('No additional sender action')
        loop = ReplyLoop(self.root / 'inbox.sqlite', owner, self.backend, native);self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):loop.cycle()
        self.jobs.update(self.backend.last_input_key, state='completed', result='{"engineering":true,"text":""}')
        with self.assertRaises(PublicationPending):loop.cycle()
        key = self.backend.last_input_key
        with patch('rsi_agent.codex_worker.subprocess.run', return_value=queued()):
            notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD}, self.jobs, self.jobs.claim('engineering'))
        with self.assertRaises(PublicationPending):loop.cycle()
        self.assertEqual(sends, [])
        _, task = self.backend.exchange('/desktop-requests/' + key)
        self.assertEqual(task['body']['messages'][-1]['content'], event['text'])
        result = {'id': key, 'input_sha256': task['input_sha256'], 'thread_id': THREAD,
                  'turn_id': 'original-visible-turn', 'text': '已实际修好并通过验证，草稿 PR 已保留'}
        self.backend.exchange('/desktop-completions', result)
        self.backend.exchange('/desktop-completions', result)
        with self.assertRaises(ModelError):self.backend.exchange('/desktop-completions', dict(result, text='different output'))
        self.assertEqual(loop.cycle()['state'], 'sent');self.assertEqual(loop.cycle()['state'], 'idle')
        self.assertEqual(len(sends), 1);self.assertEqual(sends[0]['text'], result['text'])


if __name__ == '__main__':
    unittest.main()
