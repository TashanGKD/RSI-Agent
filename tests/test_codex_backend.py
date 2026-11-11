import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from receiver.codex_worker import Jobs, blocks, notify_desktop, run_codex, server
from trigger.backend import load_model
from trigger.codex_backend import CodexBackend
from rsi_agent.model import ModelError, PublicationPending


def packet():
    return {'id': 'a' * 64, 'scope': ['self', 'owner'], 'request': ['42'], 'mode': 'chat',
            'messages': [{'role': 'system', 'content': 'Trusted facts'}, {'role': 'user', 'content': 'hello'}], 'schema': None}


THREAD = '00000000-0000-4000-8000-000000000001'
MESSAGE = '00000000-0000-4000-8000-000000000002'
OTHER_THREAD = '00000000-0000-4000-8000-000000000003'


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
            with patch('receiver.codex_worker.subprocess.Popen', side_effect=spawn):
                run_codex(config, jobs, row)
            result = jobs.get(request['id'])
            self.assertEqual((result['state'], result['result']), ('completed', 'original result'))
            self.assertEqual((result['thread_id'], result['turn_id']), ('original-thread', 'original-turn'))
            self.assertIn('turn/completed', (root / request['id'] / 'events.jsonl').read_text())


class DesktopRelayTests(unittest.TestCase):
    def test_handoff_binds_the_configured_repository_protocol_and_helper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jobs = Jobs(root / 'state')
            jobs.accept(packet())
            repository = root / 'current checkout'
            config = {'codex': 'existing-codex', 'desktop_thread_id': THREAD,
                      'desktop_all_requests': True, 'repository': str(repository)}
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as cli:
                notify_desktop(config, jobs, jobs.claim('chat'))
            message = cli.call_args.args[0][-1]
            self.assertIn((repository / 'harness/DESKTOP-WECHAT.md').as_posix(), message)
            self.assertIn('python -B "' + (repository / 'receiver/desktop_reply.py').as_posix() + '"', message)
            self.assertEqual(jobs.get(packet()['id'])['state'], 'desktop_queued')

    def test_chat_cli_checks_the_binding_and_reuses_only_the_frozen_completion(self):
        from urllib.error import HTTPError
        from urllib.request import ProxyHandler, Request, build_opener

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jobs = Jobs(root)
            request = dict(packet(), messages=[{'role': 'user', 'content': [
                {'type': 'text', 'text': '看看这张图'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,YQ=='}}]}])
            jobs.accept(request)
            config = {'codex': sys.executable, 'port': 0, 'token': 'a' * 64, 'state': str(root),
                      'desktop_thread_id': THREAD, 'desktop_all_requests': True}
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
                notify_desktop(config, jobs, jobs.claim('chat'))
            folder = root / request['id']
            with server(config, jobs, threading.Event()) as http:
                worker = threading.Thread(target=http.serve_forever)
                worker.start()
                try:
                    path = root / 'config.json'
                    path.write_text(json.dumps(dict(config, port=http.server_port)))
                    old_checkout = root / 'old checkout'
                    old_package = old_checkout / 'receiver'
                    old_package.mkdir(parents=True)
                    (old_package / '__init__.py').write_text("raise RuntimeError('obsolete receiver')")
                    helper = Path(__file__).resolve().parents[1] / 'receiver/desktop_reply.py'

                    def command(action, thread=THREAD, turn=MESSAGE, reply='', identity=request['id']):
                        return subprocess.run([sys.executable, '-B', str(helper), action,
                            str(path), identity, thread, turn], cwd=old_checkout,
                            input=reply.encode(), capture_output=True, timeout=5)

                    rejected = command('read', thread=OTHER_THREAD)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertFalse((folder / 'desktop-execution.json').exists())
                    read = command('read')
                    self.assertEqual(read.returncode, 0, read.stderr)
                    original = json.loads(read.stdout)
                    self.assertEqual(original['body']['messages'][0]['content'][0]['text'], '看看这张图')
                    self.assertNotIn(b'base64', read.stdout)
                    self.assertEqual(Path(original['images'][0]['path']).read_bytes(), b'a')
                    self.assertNotEqual(command('complete', turn=OTHER_THREAD, reply='wrong turn').returncode, 0)
                    self.assertFalse((folder / 'desktop-completion.json').exists())
                    for _ in range(2):
                        result = command('complete', reply='原回复\r\n第二行\r\n')
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout)['state'], 'completed')
                    self.assertNotEqual(command('complete', reply='另一个回复').returncode, 0)
                    self.assertEqual(jobs.get(request['id'])['result'], '原回复\n第二行')
                    self.assertEqual(json.loads(command('read').stdout)['state'], 'completed')
                    self.assertEqual(json.loads(command('status').stdout)['state'], 'pending')
                    self.assertNotEqual(command('status', thread=OTHER_THREAD).returncode, 0)
                    self.assertNotEqual(command('status', turn=OTHER_THREAD).returncode, 0)
                    native_id = hashlib.sha256('\0'.join(('self', 'owner', '42')).encode()).hexdigest()
                    receipt = {'id': request['id'], 'state': 'unknown', 'native_request_id': 'rsi-owner-' + native_id,
                               'reply_sha256': hashlib.sha256('原回复\n第二行'.encode()).hexdigest(), 'code': None}

                    def report(value):
                        req = Request(f'http://127.0.0.1:{http.server_port}/delivery-receipts',
                                      data=json.dumps(value).encode(),
                                      headers={'Authorization': 'Bearer ' + config['token']})
                        with build_opener(ProxyHandler({})).open(req, timeout=3) as response:
                            return json.load(response)

                    with self.assertRaises(HTTPError):
                        report(dict(receipt, reply_sha256='0' * 64))
                    report(receipt)
                    unknown = json.loads(command('status').stdout)
                    self.assertEqual(unknown['state'], 'unknown')
                    self.assertNotIn('text', unknown)
                    sent = dict(receipt, state='sent')
                    report(sent)
                    report(sent)
                    with self.assertRaises(HTTPError):
                        report(dict(receipt, state='not_sent'))
                    delivered = json.loads(command('status').stdout)
                    self.assertEqual((delivered['state'], delivered['text']), ('sent', '原回复\n第二行'))

                    legacy = dict(request, id='b' * 64)
                    jobs.accept(legacy)
                    with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
                        notify_desktop(config, jobs, jobs.claim('chat'))
                    legacy_read = command('read', identity=legacy['id'])
                    self.assertEqual(legacy_read.returncode, 0, legacy_read.stderr)
                    old_reply = '旧回执\r\n'
                    old_completion = dict(id=legacy['id'], input_sha256=json.loads(legacy_read.stdout)['input_sha256'],
                                          thread_id=THREAD, turn_id=MESSAGE, text=old_reply)
                    legacy_receipt = root / legacy['id'] / 'desktop-completion.json'
                    old_bytes = json.dumps(old_completion).encode()
                    legacy_receipt.write_bytes(old_bytes)
                    result = command('complete', reply=old_reply, identity=legacy['id'])
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(jobs.get(legacy['id'])['result'], old_reply)
                    self.assertEqual(legacy_receipt.read_bytes(), old_bytes)
                finally:
                    http.shutdown()
                    worker.join()

    def test_split_routes_keep_original_target_through_authenticated_completion(self):
        from urllib.error import HTTPError
        from urllib.request import ProxyHandler, Request, build_opener
        from receiver.codex_worker import process_job

        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            config = {'codex': sys.executable, 'port': 0, 'token': 'a' * 64,
                      'desktop_thread_id': THREAD, 'desktop_all_requests': True}

            def queue_reply(command, **_):
                target = command[3]
                return subprocess.CompletedProcess(command, 0,
                    f'Queued message {MESSAGE} for thread {target}.\n', '')

            cases = [
                ('a', ['self', 'legacy@chatroom'], 'engineering', THREAD),  # Already queued under the prior route.
                ('b', ['self', 'owner'], 'chat', THREAD),
                ('c', ['self', 'friend'], 'chat', OTHER_THREAD),
                ('d', ['self', 'group@chatroom'], 'chat', OTHER_THREAD),
                ('e', ['self', 'group@chatroom'], 'engineering', OTHER_THREAD),
                ('f', ['self', 'formal@chatroom'], 'chat', OTHER_THREAD),
                ('1', ['other-account', 'formal@chatroom'], 'chat', OTHER_THREAD),
                ('2', ['self', 'owner'], 'engineering', THREAD),
                ('3', ['self', 'formal@chatroom'], 'engineering', OTHER_THREAD),
            ]
            originals = {}
            with patch('receiver.codex_worker.subprocess.run', side_effect=queue_reply) as cli:
                for key, scope, mode, target in cases:
                    if key == 'b':
                        config.update(desktop_other_thread_id=OTHER_THREAD,
                                      desktop_owner_scope=['self', 'owner'],
                                      desktop_formal_group_scope=['self', 'formal@chatroom'])
                    request = dict(packet(), id=key * 64, scope=scope, mode=mode)
                    if mode == 'chat' and scope[1].endswith('@chatroom'):
                        request['messages'][-1]['content'] = json.dumps({'group': 'Same group title', 'new_messages': []})
                    originals[key] = jobs.accept(request)
                    process_job(config, jobs, jobs.claim(mode))
                    command = cli.call_args.args[0]
                    self.assertEqual(command[2:4], ['--thread', target])
                    self.assertEqual('正式工作群' in command[-1], key == 'f')
                    self.assertEqual(jobs.get(request['id'])['thread_id'], target)
                self.assertEqual(cli.call_count, len(cases))

            with server(config, Jobs(td), threading.Event()) as http:
                worker = threading.Thread(target=http.serve_forever)
                worker.start()
                self.addCleanup(worker.join)
                try:
                    client = build_opener(ProxyHandler({}))

                    def exchange(path, payload=None):
                        data = json.dumps(payload).encode() if payload is not None else None
                        request = Request(f'http://127.0.0.1:{http.server_port}{path}', data=data,
                                          headers={'Authorization': 'Bearer ' + config['token']})
                        with client.open(request, timeout=3) as response:
                            return json.load(response)

                    for key, scope, _, target in cases:
                        original = originals[key]
                        result = exchange('/desktop-requests/' + original['id'])
                        self.assertEqual((result['thread_id'], result['body']['scope']), (target, scope))
                        self.assertEqual(result['input_sha256'], original['digest'])
                        output = {'id': original['id'], 'input_sha256': original['digest'],
                                  'thread_id': target, 'turn_id': 'turn-' + key, 'text': 'original reply'}
                        wrong = OTHER_THREAD if target == THREAD else THREAD
                        with self.assertRaises(HTTPError) as rejection:
                            exchange('/desktop-completions', dict(output, thread_id=wrong))
                        self.assertEqual(rejection.exception.code, 409)
                        self.assertEqual(exchange('/desktop-completions', output)['state'], 'completed')
                finally:
                    http.shutdown()

    def test_pdf_stays_bound_to_its_original_desktop_chat_and_rejects_changed_files(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            data = b'%PDF-1.7\noriginal document fixture\n%%EOF'
            attachment = {'type': 'pdf', 'name': '论文.pdf', 'data': base64.b64encode(data).decode()}
            request = dict(packet(), messages=[{'role': 'user', 'content': [
                {'type': 'text', 'text': '看一下这篇论文'}, attachment]}])
            with self.assertRaises(ValueError):
                jobs.accept(dict(request, mode='engineering'))
            for invalid in (dict(attachment, name='../论文.pdf'), dict(attachment, data='YQ==')):
                with self.assertRaises(ValueError):
                    jobs.accept(dict(request, messages=[{'role': 'user', 'content': [invalid]}]))
            jobs.accept(request)
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as command:
                notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD,
                    'desktop_all_requests': True}, jobs, jobs.claim('chat'))
            task = jobs.desktop_task(request['id'], THREAD)
            document, = task['documents']
            path = Path(document['path'])
            self.assertEqual(task['body'], request)
            self.assertEqual(task['images'], [])
            self.assertEqual(document['name'], '论文.pdf')
            self.assertEqual(document['sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(path.read_bytes(), data)
            self.assertIn('已绑定论文 PDF', command.call_args.args[0][-1])
            self.assertNotIn(attachment['data'], command.call_args.args[0][-1])
            path.write_bytes(data + b'changed')
            with self.assertRaises(ValueError):
                jobs.desktop_task(request['id'], THREAD)

    def test_unified_route_never_falls_back_when_its_target_is_missing(self):
        from receiver.codex_worker import process_job
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td);jobs.accept(packet())
            with patch('receiver.codex_worker.run_codex') as background:
                with self.assertRaises(ValueError):
                    process_job({'desktop_all_requests': True}, jobs, jobs.claim('chat'))
                background.assert_not_called()

    def test_chat_and_task_share_one_visible_target_without_background_generation(self):
        from receiver.codex_worker import process_job
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            config = {'codex': 'existing-codex', 'desktop_thread_id': THREAD, 'desktop_all_requests': True}
            with patch('receiver.codex_worker.run_codex', side_effect=AssertionError('No parallel background turn')), \
                    patch('receiver.codex_worker.subprocess.run', return_value=queued()) as command:
                for mode, key in [('chat', 'a'), ('engineering', 'b')]:
                    request = dict(packet(), id=key * 64, mode=mode)
                    jobs.accept(request);process_job(config, jobs, jobs.claim(mode))
                    result = jobs.get(request['id'])
                    self.assertEqual((result['state'], result['thread_id']), ('desktop_queued', THREAD))
                self.assertEqual(command.call_count, 2)
                chat, engineering = (call.args[0][-1] for call in command.call_args_list)
                for call in command.call_args_list:
                    self.assertEqual(call.args[0][2:4], ['--thread', THREAD])
                self.assertTrue(chat.startswith('【微信输入 · 微信私聊 · '))
                self.assertTrue(engineering.startswith('【微信任务 · 微信私聊 · '))
                self.assertIn('发送状态和已发送的原文', chat.split('\n\n', 1)[0])
                self.assertNotIn('用一句话结束本轮', engineering)

    def test_chat_images_are_original_bound_local_files_and_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            data = b'original verified image bytes'
            request = dict(packet(), scope=['self', 'group@chatroom'], messages=[{'role': 'user', 'content': [
                {'type': 'text', 'text': '{"group":"Fixture group","new_messages":[{"sender_name":"Member","text":"看看这张"}]}'},
                {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}}]}])
            jobs.accept(request)
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as command:
                notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD, 'desktop_all_requests': True},
                               jobs, jobs.claim('chat'))
            task = jobs.desktop_task(request['id'], THREAD)
            image = task['images'][0];path = Path(image['path'])
            self.assertEqual(path.read_bytes(), data);self.assertEqual(task['body'], request)
            self.assertIn('Fixture group', command.call_args.args[0][-1])
            self.assertIn('> Member：看看这张', command.call_args.args[0][-1])
            self.assertNotIn('base64,', command.call_args.args[0][-1])
            path.write_bytes(b'changed')
            with self.assertRaises(ValueError):jobs.desktop_task(request['id'], THREAD)

    def test_chat_completion_preserves_schema_native_text_limit_and_original_result(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            schema = {'properties': {'speak': {'type': 'boolean'}, 'text': {'type': 'string'},
                                     'work_index': {'type': ['integer', 'null']}}}
            request = dict(packet(), scope=['self', 'group@chatroom'], schema=schema)
            jobs.accept(request)
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
                notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD, 'desktop_all_requests': True},
                               jobs, jobs.claim('chat'))
            task = jobs.desktop_task(request['id'], THREAD)
            result = {'id': request['id'], 'input_sha256': task['input_sha256'], 'thread_id': THREAD,
                      'turn_id': 'dedicated-turn', 'text': ''}
            for text in ['not JSON', '{"speak":true,"text":"","work_index":null}',
                         '{"speak":true,"text":"reply","work_index":true}', '{"text":"missing decision"}',
                         json.dumps({'speak': True, 'text': '汉' * 2001, 'work_index': None})]:
                with self.assertRaises(ValueError):jobs.complete_desktop(dict(result, text=text), THREAD)
            result['text'] = json.dumps({'speak': True, 'text': '汉' * 2000, 'work_index': None}, ensure_ascii=False)
            self.assertEqual(jobs.complete_desktop(result, THREAD)['state'], 'completed')
            self.assertEqual(jobs.complete_desktop(result, THREAD)['state'], 'completed')
            self.assertEqual(jobs.get(request['id'])['result'], result['text'])
            with self.assertRaises(ValueError):jobs.complete_desktop(dict(result, turn_id='replacement-turn'), THREAD)

    def test_task_queues_once_without_a_model_turn_and_completion_is_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td);request = dict(packet(), mode='engineering');jobs.accept(request)
            config = {'codex': 'existing-codex', 'desktop_thread_id': THREAD}
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as command:
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
            with patch('receiver.codex_worker.subprocess.run', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
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
        self.cli = self.root / 'fixture-codex'
        self.cli.touch()
        self.http = server({'token': 'c' * 64, 'port': 0, 'desktop_thread_id': THREAD,
                            'codex': str(self.cli)}, self.jobs, threading.Event())
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
        for name, text in [('token', 'c' * 64), ('preferences', 'Concise natural conversation')]:
            p = self.root / name;p.write_text(text);p.chmod(0o600)
        state = self.root / 'native';state.mkdir(mode=0o700)
        self.config = {'backend': 'local-codex', 'endpoint': 'http://127.0.0.1:' + str(self.http.server_port),
            'token_file': str(self.root / 'token'), 'preferences_file': str(self.root / 'preferences'),
            'state': str(state), 'model': 'configured-codex', 'engineering': True}
        path = self.root / 'backend.json';path.write_text(json.dumps(self.config));path.chmod(0o600)
        self.backend = load_model(path, verify_runtime=True)
        self.backend.bind('self', 'owner');self.backend.use_request(['42'])

    def test_missing_cli_reports_unready_and_retains_the_original(self):
        self.cli.unlink()
        with self.assertRaisesRegex(ModelError, 'worker is not ready'):
            self.backend.check_runtime()
        with self.assertRaises(PublicationPending):
            self.backend.reply('Original message')
        key = self.backend.last_input_key
        original = self.jobs.get(key)
        self.assertEqual(original['state'], 'queued')
        self.cli.touch()
        self.backend.check_runtime()
        with self.assertRaises(PublicationPending):
            self.backend.reply('Changed live context')
        self.assertEqual(self.jobs.get(key)['digest'], original['digest'])
        self.assertEqual(self.jobs.get(key)['body'], original['body'])

    def test_reply_loader_rejects_retired_and_non_codex_configurations(self):
        path = self.root / 'retired.json'
        path.touch(mode=0o600)
        for value in ({'backend': 'deepseek-harness'}, {'backend': 'unknown'},
                      {'base_url': 'https://example.test/v1', 'model': 'standalone', 'api_key_file': 'token'}):
            with self.subTest(backend=value.get('backend')):
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(ModelError, 'local Codex'):
                    load_model(path)

    def test_plain_owner_text_uses_only_codex_and_retries_the_frozen_original(self):
        with patch('rsi_agent.model.ModelClient', side_effect=AssertionError('No SCNET fallback')):
            self.backend.check_runtime()
            with self.assertRaises(PublicationPending):
                self.backend.reply('hello without a prefix')
            key = self.backend.last_input_key;frozen = self.jobs.get(key)['body']
            self.jobs.update(key, state='completed', result='{"engineering":false,"text":"自然接话"}')
            self.assertEqual(self.backend.reply('later changed live context'), '自然接话')
            self.assertEqual(self.jobs.get(key)['body'], frozen)
            self.assertNotIn('provider_config', self.config)

    def test_native_plain_chat_waits_for_new_desktop_completion_and_sends_once(self):
        from trigger.owner_reply import ReplyLoop
        from trigger.reply_io import request_id
        owner = {'account': 'self', 'peer': 'owner', 'scope': {'mode': 'owner-private-text', 'since': 100}}
        event = {'account': 'self', 'peer': 'owner', 'sender': 'owner', 'kind': 1,
                 'created': 120, 'server_id': 42, 'text': '现在都进专用会话'}
        sends = []
        def native(value):
            if value['op'] == 'read':return {'events': [event]}
            if value['op'] == 'submit':
                sends.append(value)
                return {'state': 'succeeded', 'outcome': 'sent', 'request_id': request_id('self', 'owner', 42),
                        'reply_sha256': hashlib.sha256(value['text'].encode()).hexdigest()}
            raise AssertionError('No additional sender')
        loop = ReplyLoop(self.root / 'desktop-chat.sqlite', owner, self.backend, native);self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):loop.cycle()
        key = self.backend.last_input_key
        with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
            notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD, 'desktop_all_requests': True},
                           self.jobs, self.jobs.claim('chat'))
        with self.assertRaises(PublicationPending):loop.cycle()
        _, task = self.backend.exchange('/desktop-requests/' + key)
        self.assertEqual(task['body']['messages'][-1]['content'], event['text'])
        self.assertEqual(sends, [])
        result = {'id': key, 'input_sha256': task['input_sha256'], 'thread_id': THREAD,
                  'turn_id': 'dedicated-chat-turn', 'text': '{"engineering":false,"text":"这条从专用会话回复"}'}
        self.backend.exchange('/desktop-completions', result)
        route = f"/desktop-deliveries/{key}/{THREAD}/{result['turn_id']}"
        self.assertEqual(self.backend.exchange(route)[1]['state'], 'pending')
        self.assertEqual(loop.cycle()['state'], 'sent')
        with patch.object(self.backend, 'publish_delivery', side_effect=PublicationPending('offline')):
            self.assertEqual(loop.cycle()['state'], 'idle')
        self.assertEqual(self.backend.exchange(route)[1]['state'], 'pending')
        loop.close()
        restarted = ReplyLoop(self.root / 'desktop-chat.sqlite', owner, self.backend, native)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.cycle()['state'], 'idle')
        receipt = self.backend.exchange(route)[1]
        self.assertEqual((receipt['state'], receipt['text']), ('sent', '这条从专用会话回复'))
        self.assertEqual([s['text'] for s in sends], ['这条从专用会话回复'])

    def test_group_model_review_releases_only_the_original_batch(self):
        from trigger.group_reply import GroupLoop
        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        event = {'account': 'self', 'peer': 'group@chatroom', 'sender': 'member',
                 'sender_name': 'Member', 'mentioned': True, 'kind': 1, 'created': 120,
                 'server_id': 44, 'text': 'Original question'}
        events = [event]
        sends = []
        def native(value):
            if value['op'] == 'read':
                return {'events': events}
            if value['op'] == 'submit':
                sends.append(value['server_id'])
                return {'state': 'succeeded', 'outcome': 'sent'}
            raise AssertionError('Unexpected native action')
        loop = GroupLoop(self.root / 'group-inbox.sqlite', group, self.backend, native)
        self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):
            loop.cycle()
        original_key = self.backend.last_input_key
        original_packet = self.jobs.get(original_key)['body']
        events.append(dict(event, server_id=45, created=121, text='Later question'))
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.assertEqual(loop.value('model_batch'), '["44"]')
        self.jobs.update(original_key, state='review')
        self.assertEqual(loop.cycle()['state'], 'model_review')
        self.assertIsNone(loop.value('model_batch'))
        self.assertEqual(loop.counts(), {'model_review': 1, 'new': 1})
        with self.assertRaises(PublicationPending):
            loop.cycle()
        later_key = self.backend.last_input_key
        self.assertNotEqual(later_key, original_key)
        self.assertEqual(json.loads(self.jobs.get(later_key)['body'])['request'], ['45'])
        self.jobs.update(later_key, state='completed',
                         result='{"speak":true,"text":"Later answer","work_index":null}')
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(loop.cycle()['state'], 'idle')
        self.assertEqual(sends, ['45'])
        self.assertEqual(self.jobs.get(original_key)['body'], original_packet)
        self.assertEqual(self.jobs.get(original_key)['state'], 'review')
        events.append(dict(event, server_id=46, created=122, text='A message that needs no reply'))
        with self.assertRaises(PublicationPending):
            loop.cycle()
        quiet_key = self.backend.last_input_key
        with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
            notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD, 'desktop_all_requests': True},
                           self.jobs, self.jobs.claim('chat'))
        _, task = self.backend.exchange('/desktop-requests/' + quiet_key)
        self.backend.exchange('/desktop-completions', {'id': quiet_key, 'input_sha256': task['input_sha256'],
            'thread_id': THREAD, 'turn_id': 'quiet-turn', 'text': '{"speak":false,"text":"","work_index":null}'})
        self.assertEqual(loop.cycle()['state'], 'quiet')
        self.assertEqual(loop.cycle()['state'], 'idle')
        receipt = self.backend.exchange(f'/desktop-deliveries/{quiet_key}/{THREAD}/quiet-turn')[1]
        self.assertEqual(receipt['state'], 'quiet')
        self.assertNotIn('text', receipt)
        self.assertEqual(sends, ['45'])

    def test_single_owner_article_keeps_its_original_route_and_replies_once(self):
        from trigger.group_reply import GroupLoop
        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        url = 'https://mp.weixin.qq.com/s/article'
        page = {'state': 'ready', 'url': url, 'text': 'Observed public article.'}
        answer = '基于已读取的正文给出答复'
        for native_id, already_routed in (('45', True), ('44', False)):
            with self.subTest(already_routed=already_routed):
                event = {'account': 'self', 'peer': group['peer'], 'sender': 'owner',
                         'sender_name': 'Owner', 'mentioned': False, 'kind': 49, 'created': 120,
                         'server_id': native_id, 'link': {'url': url, 'text': 'Original article card'}}
                sends = []

                def native(value):
                    if value['op'] == 'read':
                        return {'events': [event]}
                    if value['op'] == 'submit':
                        sends.append((value['server_id'], value['text']))
                        return {'state': 'succeeded', 'outcome': 'sent'}
                    raise AssertionError('Unexpected native action')

                path = self.root / (native_id + '.sqlite')
                loop = GroupLoop(path, group, self.backend, native)
                self.addCleanup(loop.close)
                identity = [['self', group['peer']], [native_id], 'chat']
                route_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
                article_key = hashlib.sha256(json.dumps([*identity, 'link-reading'], sort_keys=True).encode()).hexdigest()
                with patch('trigger.group_reply.linked_pages', return_value=[page]):
                    if already_routed:
                        # An original request frozen by the prior implementation.
                        self.backend.use_request([native_id])
                        with self.assertRaises(PublicationPending):
                            self.backend.complete([{'role': 'user', 'content': 'Frozen route'}], json_output=True)
                        with loop.db:
                            loop.save('model_batch', json.dumps([native_id]))
                        frozen = self.jobs.get(route_key)['body']
                        with self.assertRaises(PublicationPending):
                            loop.cycle()
                        self.assertFalse((Path(self.config['state']) / 'inputs' / (article_key + '.json')).exists())
                        self.jobs.update(route_key, state='completed',
                            result='{"speak":false,"text":"","work_index":null}')
                    with self.assertRaises(PublicationPending):
                        loop.cycle()
                    self.assertEqual(self.backend.last_input_key, article_key)
                    if already_routed:
                        self.assertEqual(self.jobs.get(route_key)['body'], frozen)
                    else:
                        self.assertFalse(self.backend.has_original_input([native_id]))

                    with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as cli:
                        notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD,
                                        'desktop_all_requests': True}, self.jobs, self.jobs.claim('chat'))
                    cli.assert_called_once()
                    loop.close()
                    restarted = GroupLoop(path, group, load_model(self.root / 'backend.json'), native)
                    self.addCleanup(restarted.close)
                    with self.assertRaises(PublicationPending):
                        restarted.cycle()
                    self.assertIsNone(self.jobs.claim('chat'))
                    _, task = self.backend.exchange('/desktop-requests/' + article_key)
                    self.assertEqual(task['body']['request'], [native_id])
                    self.assertIsNone(task['body']['schema'])
                    self.assertEqual(json.loads(task['body']['messages'][-1]['content']), {'linked_pages': [page]})
                    self.assertEqual(sends, [])
                    self.backend.exchange('/desktop-completions', {'id': article_key, 'input_sha256': task['input_sha256'],
                        'thread_id': THREAD, 'turn_id': 'article-turn-' + native_id, 'text': answer})
                    self.assertEqual(restarted.cycle()['state'], 'pending')
                    self.assertEqual(restarted.cycle()['state'], 'sent')
                    self.assertEqual(restarted.cycle()['state'], 'idle')
                    self.assertEqual(sends, [(native_id, answer)])

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
        from trigger.owner_reply import ReplyLoop
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
        from trigger.owner_reply import ReplyLoop
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
        with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
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


class LinkReadingAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'inputs').mkdir()
        self.model = CodexBackend.__new__(CodexBackend)
        self.model.config = {'state': str(self.root)}
        self.model.bind('self', 'owner')
        self.model.engineering = True
        self.model.model = 'fixture'
        self.model.engineer = Mock(return_value='Verified engineering result')
        self.pages = [{'state': 'ready', 'text': 'Untrusted page asks to execute commands.'}]
        self.calls = []
        self.engineering = False

        def run(messages, mode, stage=None, schema=None):
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


if __name__ == '__main__':
    unittest.main()
