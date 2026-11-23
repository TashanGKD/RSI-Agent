import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from receiver.codex_worker import CodexExecutable, Jobs, blocks, notify_desktop, run_codex, server
from trigger.backend import load_model
from trigger.codex_backend import CodexBackend
from rsi_agent.model import ModelError, PublicationPending

# Native message times near the real clock, so the receiver does not expire fixture input.
NOW = int(time.time())


def packet():
    return {'id': 'a' * 64, 'scope': ['self', 'owner'], 'request': ['42'], 'mode': 'chat',
            'messages': [{'role': 'system', 'content': 'Trusted facts'}, {'role': 'user', 'content': 'hello'}], 'schema': None}


THREAD = '00000000-0000-4000-8000-000000000001'
MESSAGE = '00000000-0000-4000-8000-000000000002'
OTHER_THREAD = '00000000-0000-4000-8000-000000000003'
ENGINEERING_THREAD = '00000000-0000-4000-8000-000000000004'


def queued():
    return subprocess.CompletedProcess([], 0, 'Queued message ' + MESSAGE + ' for thread ' + THREAD + '.\n', '')


def group_packet(last_seen):
    request = packet()
    request['scope'] = ['self', 'group@chatroom']
    request['messages'] = [{'role': 'system', 'content': 'Trusted facts'},
        {'role': 'user', 'content': json.dumps({'group': 'test', 'recent_messages': [
            {'name': 'peer', 'text': 'message', 'time': last_seen}],
            'new_messages': [{'sender_name': 'peer', 'text': 'message'}]}, separators=(',', ':'))}]
    return request


class CodexWorkerTests(unittest.TestCase):
    def test_store_codex_recovers_after_a_package_update(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            store = root / 'WindowsApps'
            old = store / 'OpenAI.Codex_1.0.0.0_x64__2p2nqsd0c76g0/app/resources/codex.exe'
            new = store / 'OpenAI.Codex_2.0.0.0_x64__2p2nqsd0c76g0/app/resources/codex.exe'
            for exe in (old, new):
                exe.parent.mkdir(parents=True)
                exe.touch()
            with patch('receiver.codex_worker.sys.platform', 'win32'):
                store_exe = CodexExecutable(old)
                explicit_exe = CodexExecutable(root / 'standalone' / 'codex.exe')
            with patch('receiver.codex_worker.registered_store_codex', return_value=None) as registered, \
                    patch('receiver.codex_worker.time.monotonic', return_value=100) as clock:
                self.assertEqual(store_exe.resolve(), old)
                registered.assert_not_called()
                old.unlink()
                self.assertIsNone(store_exe.resolve())
                self.assertIsNone(store_exe.resolve())
                registered.assert_called_once()
                registered.return_value = new
                clock.return_value = 116
                self.assertEqual(store_exe.resolve(), new)
                self.assertEqual(store_exe.resolve(), new)
                self.assertIsNone(explicit_exe.resolve())
                self.assertEqual(registered.call_count, 2)

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
    def test_stale_group_queue_without_turn_is_terminalized(self):
        with tempfile.TemporaryDirectory() as td:
            now = 2_000_000_000
            request = group_packet(now - 901)
            jobs = Jobs(td)
            jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        desktop_message_id=MESSAGE)
            with patch('receiver.codex_worker.time.time', return_value=now):
                restarted = Jobs(td)
            row = restarted.get(request['id'])
            self.assertEqual(row['state'], 'review')
            self.assertEqual(row['error'], 'GROUP_INPUT_EXPIRED; original group reply was not sent')
            with restarted.connect() as db:
                receipt = json.loads(db.execute('SELECT receipt FROM delivery_receipts WHERE id=?',
                                                 (request['id'],)).fetchone()['receipt'])
            self.assertEqual(receipt['code'], 'GROUP_INPUT_EXPIRED')

    def test_recent_group_queue_stays_queued(self):
        with tempfile.TemporaryDirectory() as td:
            now = 2_000_000_000
            request = group_packet(now - 899)
            jobs = Jobs(td)
            jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        desktop_message_id=MESSAGE)
            with patch('receiver.codex_worker.time.time', return_value=now):
                row = jobs.get(request['id'])
            self.assertEqual(row['state'], 'desktop_queued')

    def test_fresh_quote_after_old_text_context_stays_queued(self):
        # Context holds plain text only, so a fresh quote or card is dated by its own created time.
        with tempfile.TemporaryDirectory() as td:
            now = 2_000_000_000
            request = group_packet(now - 3600)
            content = json.loads(request['messages'][1]['content'])
            content['new_messages'] = [{'sender_name': 'peer', 'text': 'quoted card', 'created': now - 60}]
            request['messages'][1]['content'] = json.dumps(content, separators=(',', ':'))
            jobs = Jobs(td)
            jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        desktop_message_id=MESSAGE)
            with patch('receiver.codex_worker.time.time', return_value=now):
                self.assertEqual(jobs.get(request['id'])['state'], 'desktop_queued')
            with patch('receiver.codex_worker.time.time', return_value=now + 900):
                self.assertEqual(jobs.get(request['id'])['state'], 'review')

    def test_private_stale_queue_is_not_group_expired(self):
        with tempfile.TemporaryDirectory() as td:
            now = 2_000_000_000
            request = packet()
            jobs = Jobs(td)
            jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        desktop_message_id=MESSAGE)
            with patch('receiver.codex_worker.time.time', return_value=now):
                row = jobs.get(request['id'])
            self.assertEqual(row['state'], 'desktop_queued')

    def test_stale_group_with_a_desktop_turn_is_left_for_reconciliation(self):
        with tempfile.TemporaryDirectory() as td:
            now = 2_000_000_000
            request = group_packet(now - 901)
            jobs = Jobs(td)
            jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        turn_id='existing-turn', desktop_message_id=MESSAGE)
            with patch('receiver.codex_worker.time.time', return_value=now):
                row = jobs.get(request['id'])
            self.assertEqual(row['state'], 'desktop_queued')

    def test_group_expiry_receipt_releases_desktop_queue_without_replaying(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            request = dict(packet(), scope=['self', 'group@chatroom'])
            original = jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        desktop_message_id=MESSAGE)
            receipt = {'id': request['id'], 'state': 'not_sent',
                       'native_request_id': None, 'reply_sha256': None,
                       'code': 'GROUP_INPUT_EXPIRED'}

            self.assertEqual(jobs.report_delivery(receipt), {'state': 'recorded'})
            self.assertEqual(jobs.report_delivery(receipt), {'state': 'recorded'})
            row = jobs.get(request['id'])
            self.assertEqual(row['state'], 'review')
            self.assertEqual(row['error'], 'GROUP_INPUT_EXPIRED; original group reply was not sent')
            self.assertEqual(jobs.desktop_task(request['id'], THREAD)['state'], 'review')
            with self.assertRaises(ValueError):
                jobs.complete_desktop({'id': request['id'], 'input_sha256': original['digest'],
                    'thread_id': THREAD, 'turn_id': 'late-turn', 'text': 'Old answer'}, THREAD)

    def test_group_expiry_receipt_releases_existing_queue_on_receiver_start(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            request = dict(packet(), scope=['self', 'group@chatroom'])
            jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD,
                        desktop_message_id=MESSAGE)
            receipt = {'id': request['id'], 'state': 'not_sent',
                       'native_request_id': None, 'reply_sha256': None,
                       'code': 'GROUP_INPUT_EXPIRED'}
            with jobs.connect() as db:
                db.execute('INSERT INTO delivery_receipts VALUES(?,?)',
                           (request['id'], json.dumps(receipt, separators=(',', ':'))))
            restarted = Jobs(td)
            self.assertEqual(restarted.get(request['id'])['state'], 'review')

    def test_group_parts_show_actual_native_text_without_changing_original_digest(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            request = dict(packet(), scope=['self', 'group@chatroom'])
            original = jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD, desktop_message_id=MESSAGE)
            text = 'First paragraph.\nSecond paragraph.'
            jobs.complete_desktop({'id': request['id'], 'input_sha256': original['digest'],
                'thread_id': THREAD, 'turn_id': 'original-turn', 'text': text}, THREAD)
            rid = 'rsi-group-' + hashlib.sha256('\0'.join((*request['scope'], '42')).encode()).hexdigest()
            parts = [{'request_id': rid, 'expected_text': 'First paragraph.\n', 'actual_text': 'First paragraph.'},
                     {'request_id': rid + '-part-2', 'expected_text': 'Second paragraph.', 'actual_text': 'Second paragraph.'}]
            receipt = {'id': request['id'], 'state': 'sent', 'native_request_id': rid,
                       'reply_sha256': hashlib.sha256(text.encode()).hexdigest(), 'code': None, 'native_parts': parts}
            for wrong in ([dict(parts[0], actual_text='Different text'), parts[1]],
                          [parts[0], dict(parts[1], request_id=rid + '-part-3')],
                          [parts[0], dict(parts[1], expected_text='Changed original')],
                          [parts[0]], parts[::-1]):
                with self.assertRaises(ValueError):
                    jobs.report_delivery(dict(receipt, native_parts=wrong))
            with self.assertRaises(ValueError):
                jobs.report_delivery(dict(receipt, state='unknown'))
            self.assertEqual(jobs.report_delivery(receipt), {'state': 'recorded'})
            self.assertEqual(jobs.report_delivery(receipt), {'state': 'recorded'})
            shown = jobs.desktop_delivery(request['id'], THREAD, 'original-turn', THREAD)
            self.assertEqual(shown['texts'], ['First paragraph.', 'Second paragraph.'])
            self.assertEqual(shown['text'], 'First paragraph.\n\nSecond paragraph.')
            self.assertEqual(shown['text_source'], 'native_parts')
            self.assertEqual(shown['reply_sha256'], hashlib.sha256(text.encode()).hexdigest())
            self.assertEqual(jobs.get(request['id'])['result'], text)

    def test_trimmed_group_payloads_bind_source_slices_to_frozen_reply(self):
        from receiver.codex_worker import native_part_texts
        rid = 'rsi-group-test'
        first = {'request_id': rid, 'source_text': '第一段。 \n\n',
                 'expected_text': '第一段。', 'actual_text': '第一段。'}
        second = {'request_id': rid + '-part-2',
                  'expected_text': '第二段。', 'actual_text': '第二段。'}
        original = first['source_text'] + second['expected_text']
        receipt = {'state': 'sent', 'native_request_id': rid, 'native_parts': [first, second]}
        self.assertEqual(native_part_texts(receipt, original), ['第一段。', '第二段。'])
        self.assertEqual(native_part_texts(dict(receipt, native_parts=[first]), first['source_text']), ['第一段。'])
        for changed in (dict(first, source_text='第一段。\n'), dict(first, source_text=' 第一 段。'),
                        dict(first, actual_text='第一段。 ')):
            with self.assertRaises(ValueError):
                native_part_texts(dict(receipt, native_parts=[changed, second]), original)

    def test_partial_group_receipt_displays_only_the_proven_native_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            request = dict(packet(), scope=['self', 'group@chatroom'])
            original = jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD, desktop_message_id=MESSAGE)
            text = 'First.\nSecond.\nThird.'
            jobs.complete_desktop({'id': request['id'], 'input_sha256': original['digest'],
                'thread_id': THREAD, 'turn_id': 'original-turn', 'text': text}, THREAD)
            rid = 'rsi-group-' + hashlib.sha256('\0'.join((*request['scope'], '42')).encode()).hexdigest()
            parts = [{'request_id': rid, 'expected_text': 'First.\n', 'actual_text': 'First.'},
                     {'request_id': rid + '-part-2', 'expected_text': 'Second.\n', 'actual_text': None},
                     {'request_id': rid + '-part-3', 'expected_text': 'Third.', 'actual_text': None}]
            unknown = {'id': request['id'], 'state': 'unknown', 'native_request_id': rid,
                       'reply_sha256': hashlib.sha256(text.encode()).hexdigest(), 'code': None}
            jobs.report_delivery(unknown)
            partial = dict(unknown, state='partial', code='SEARCH_SELECTION_UNPROVEN', native_parts=parts)
            for invalid in (dict(unknown, state='partial'), dict(partial, state='sent'),
                            dict(partial, native_parts=[*parts[:2], dict(parts[2], actual_text='Third.')]),
                            dict(partial, native_parts=[dict(parts[0], actual_text=None), *parts[1:]]),
                            dict(partial, native_parts=parts[:2])):
                with self.assertRaises(ValueError):
                    jobs.report_delivery(invalid)
            self.assertEqual(jobs.report_delivery(partial), {'state': 'recorded'})
            self.assertEqual(jobs.report_delivery(partial), {'state': 'recorded'})
            with self.assertRaises(ValueError):
                jobs.report_delivery(unknown)
            shown = jobs.desktop_delivery(request['id'], THREAD, 'original-turn', THREAD)
            self.assertEqual((shown['state'], shown['text'], shown['texts']), ('partial', 'First.', ['First.']))
            self.assertEqual(shown['reply_sha256'], unknown['reply_sha256'])
            self.assertEqual(jobs.get(request['id'])['result'], text)

    def test_old_link_delivery_keeps_the_recorded_raw_payload(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            request = dict(packet(), scope=['self', 'group@chatroom'])
            request['id'] = hashlib.sha256(json.dumps(
                [request['scope'], request['request'], 'chat', 'link-reading'], sort_keys=True).encode()).hexdigest()
            original = jobs.accept(request)
            jobs.update(request['id'], state='desktop_queued', thread_id=THREAD, desktop_message_id=MESSAGE)
            raw = '{"speak":true,"text":"original answer","work_index":null}'
            jobs.complete_desktop({'id': request['id'], 'input_sha256': original['digest'],
                'thread_id': THREAD, 'turn_id': 'original-turn', 'text': raw}, THREAD)
            native_id = hashlib.sha256('\0'.join((*request['scope'], '42')).encode()).hexdigest()
            receipt = {'id': request['id'], 'state': 'unknown', 'native_request_id': 'rsi-group-' + native_id,
                       'reply_sha256': hashlib.sha256(raw.encode()).hexdigest(), 'code': None}
            jobs.report_delivery(receipt)
            with self.assertRaises(ValueError):
                jobs.report_delivery(dict(receipt, state='sent',
                    reply_sha256=hashlib.sha256(b'original answer').hexdigest()))
            sent = dict(receipt, state='sent')
            jobs.report_delivery(sent)
            self.assertEqual(jobs.report_delivery(sent)['state'], 'recorded')
            self.assertEqual(jobs.desktop_delivery(request['id'], THREAD, 'original-turn', THREAD),
                             dict(sent, text=raw))

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
            self.assertIn((repository / '.agents/skills/rsi-wechat-learn/SKILL.md').as_posix(), message)
            self.assertIn('先核原 ID、摘要和附件，再查同一 ID、thread、turn 的 V2 回执', message)
            self.assertEqual(jobs.get(packet()['id'])['state'], 'desktop_queued')

    def test_inline_chat_protocol_carries_the_absolute_helper_config_and_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            jobs = Jobs(root / 'state')
            original = jobs.accept(packet())
            repository = root / 'current checkout'
            config_file = root / 'config.json'
            config_file.write_text('{}', encoding='utf-8')
            config = {'codex': 'existing-codex', 'desktop_thread_id': THREAD,
                      'desktop_all_requests': True, 'repository': str(repository),
                      'config_path': str(config_file.resolve())}
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as cli:
                notify_desktop(config, jobs, jobs.claim('chat'))
            argv = cli.call_args.args[0]
            self.assertIn('--resume', argv)
            message = argv[-1]
            helper = (repository / 'receiver/desktop_reply.py').as_posix()
            self.assertIn('python -B "' + helper + '" read "' + config_file.resolve().as_posix() + '"', message)
            self.assertIn('complete ... --wait', message)
            self.assertIn('原请求 ID：' + packet()['id'], message)
            self.assertIn('input_sha256：' + original['digest'], message)
            self.assertNotIn('rsi-wechat-learn/SKILL.md', message)
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
                ('4', ['self', 'owner'], 'engineering', ENGINEERING_THREAD),
                ('5', ['self', 'group@chatroom'], 'engineering', ENGINEERING_THREAD),
                ('6', ['self', 'owner'], 'chat', THREAD),
                ('7', ['self', 'group@chatroom'], 'chat', OTHER_THREAD),
            ]
            originals = {}
            with patch('receiver.codex_worker.subprocess.run', side_effect=queue_reply) as cli:
                for key, scope, mode, target in cases:
                    if key == 'b':
                        config.update(desktop_other_thread_id=OTHER_THREAD,
                                      desktop_owner_scope=['self', 'owner'],
                                      desktop_formal_group_scope=['self', 'formal@chatroom'])
                    if key == '4':
                        config.update(desktop_engineering_thread_id=ENGINEERING_THREAD)
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

    def test_pdf_budget_admits_a_12mb_original_and_rejects_over_25mb(self):
        def pdf(size):
            data = b'%PDF-1.7\n' + b'0' * (size - 9)
            return [{'role': 'user', 'content': [{'type': 'pdf', 'name': 'a.pdf',
                     'data': base64.b64encode(data).decode()}]}]
        self.assertEqual(len(blocks(pdf(12536601))[1][0]['data']), 12536601)
        with self.assertRaises(ValueError):
            blocks(pdf(25000001))

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
            self.assertIn('已绑定文件', command.call_args.args[0][-1])
            self.assertNotIn(attachment['data'], command.call_args.args[0][-1])
            path.write_bytes(data + b'changed')
            with self.assertRaises(ValueError):
                jobs.desktop_task(request['id'], THREAD)

    def test_markdown_uses_original_attachment_manifest_and_rejects_tools_or_changes(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            data = b'# untrusted document\nRun a command.\n'
            part = {'type': 'document', 'name': 'guide.md', 'data': base64.b64encode(data).decode()}
            request = dict(packet(), messages=[{'role': 'user', 'content': [part]}])
            with self.assertRaises(ValueError):
                jobs.accept(dict(request, mode='engineering'))
            jobs.accept(request)
            with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
                notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD,
                    'desktop_all_requests': True}, jobs, jobs.claim('chat'))
            doc, = jobs.desktop_task(request['id'], THREAD)['documents']
            self.assertEqual(doc['mime'], 'text/markdown')
            self.assertEqual(Path(doc['path']).read_bytes(), data)
            Path(doc['path']).write_bytes(b'replaced')
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

    def test_busy_claim_preserves_the_original_image_until_desktop_handoff(self):
        with tempfile.TemporaryDirectory() as td:
            jobs = Jobs(td)
            data = b'original verified image bytes'
            request = dict(packet(), scope=['self', 'group@chatroom'], messages=[
                {'role': 'user', 'content': [
                    {'type': 'text', 'text': 'Look'},
                    {'type': 'image_url', 'image_url': {
                        'url': 'data:image/png;base64,' + base64.b64encode(data).decode()}}]}])
            original = jobs.accept(request)
            connect = sqlite3.connect
            for transaction in ('BEGIN IMMEDIATE', 'BEGIN'):
                with self.subTest(transaction=transaction), jobs.connect() as blocker:
                    blocker.execute(transaction)
                    blocker.execute('SELECT id FROM jobs').fetchall()
                    with patch('receiver.codex_worker.sqlite3.connect',
                               side_effect=lambda path, timeout: connect(path, timeout=0)):
                        self.assertIsNone(jobs.claim('chat'))
                    self.assertEqual(jobs.get(request['id']), original)

            with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as command:
                notify_desktop({'codex': 'existing-codex', 'desktop_thread_id': THREAD,
                                'desktop_all_requests': True}, jobs, jobs.claim('chat'))
            command.assert_called_once()
            task = jobs.desktop_task(request['id'], THREAD)
            self.assertEqual(task['input_sha256'], original['digest'])
            self.assertEqual(task['body'], request)
            self.assertEqual(task['desktop_message_id'], MESSAGE)
            self.assertEqual(Path(task['images'][0]['path']).read_bytes(), data)
            self.assertIsNone(jobs.claim('chat'))

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
                 'sender_name': 'Member', 'mentioned': True, 'kind': 1, 'created': NOW + 120,
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
        events.append(dict(event, server_id=45, created=NOW + 121, text='Later question'))
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
        events.append(dict(event, server_id=46, created=NOW + 122, text='A message that needs no reply'))
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

    def test_recycled_group_batch_cannot_send_a_late_result(self):
        from trigger.group_reply import GroupLoop
        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        event = {'account': 'self', 'peer': 'group@chatroom', 'sender': 'member',
                 'sender_name': 'Member', 'mentioned': True, 'kind': 1, 'created': NOW + 120,
                 'server_id': 44, 'text': 'Original group question'}
        events = [event, dict(event, server_id=45, created=NOW + 125)]
        sends = []

        def native(value):
            if value['op'] == 'read':
                return {'events': events}
            if value['op'] == 'submit':
                sends.append(value['server_id'])
                return {'state': 'succeeded', 'outcome': 'sent'}
            self.fail('Unexpected native action')

        loop = GroupLoop(self.root / 'recycle.sqlite', group, self.backend, native)
        loop.recycle_since = 100
        self.addCleanup(loop.close)
        with patch('trigger.group_reply.time.time', return_value=NOW + 126):
            with self.assertRaises(PublicationPending):
                loop.cycle()
        original = self.backend.last_input_key
        with patch('receiver.codex_worker.subprocess.run', return_value=queued()):
            notify_desktop({'codex': 'fixture-codex', 'desktop_thread_id': THREAD,
                            'desktop_all_requests': True}, self.jobs, self.jobs.claim('chat'))
        saved = self.jobs.get(original)
        events.append(dict(event, server_id=46, created=NOW + 1025, text='Fresh group question'))
        with patch('trigger.group_reply.time.time', return_value=NOW + 1025):
            with self.assertRaises(PublicationPending):
                loop.cycle()
        self.assertEqual(loop.value('model_batch'), '["44", "45"]')
        self.assertEqual(loop.counts(), {'new': 3})

        with patch('trigger.group_reply.time.time', return_value=NOW + 1026):
            with self.assertRaises(PublicationPending):
                loop.cycle()
        fresh = self.backend.last_input_key
        self.assertNotEqual(fresh, original)
        self.assertEqual(json.loads(self.jobs.get(fresh)['body'])['request'], ['46'])
        self.assertEqual(loop.counts(), {'new': 1, 'recycled': 2})

        # Publish from a restarted loop before the old Codex turn completes.
        restarted = GroupLoop(self.root / 'recycle.sqlite', group, self.backend, native)
        self.addCleanup(restarted.close)
        restarted.flush_expired_delivery()
        with self.assertRaisesRegex(ModelError, 'HTTP 409'):
            self.backend.exchange('/desktop-completions', {'id': original, 'input_sha256': saved['digest'],
                'thread_id': THREAD, 'turn_id': 'late-fixture-turn',
                'text': '{"speak":true,"text":"Old answer","work_index":null}'})
        self.assertEqual(self.jobs.get(original)['state'], 'review')
        self.assertEqual(self.jobs.get(original)['body'], saved['body'])
        expired = self.backend.exchange(f'/desktop-deliveries/{original}/{THREAD}/late-fixture-turn')[1]
        self.assertEqual(expired, {'id': original, 'state': 'not_sent', 'native_request_id': None,
                                   'reply_sha256': None, 'code': 'GROUP_INPUT_EXPIRED'})
        self.jobs.update(fresh, state='completed', result='{"speak":true,"text":"Fresh answer","work_index":null}')
        with patch('trigger.group_reply.time.time', return_value=NOW + 1027):
            self.assertEqual(loop.cycle()['state'], 'pending')
            self.assertEqual(loop.cycle()['state'], 'sent')
            self.assertEqual(loop.cycle()['state'], 'idle')
        self.assertEqual(sends, ['46'])
        self.assertEqual(loop.counts(), {'recycled': 2, 'sent': 1})

    def test_stalled_group_link_read_releases_only_its_original_batch(self):
        from trigger.group_reply import GroupLoop, REPLY_TTL
        from trigger.reply_io import request_id

        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        url = 'https://example.com/article'
        # Input times stay inside the receiver's 15-minute window; this test covers the link-read stall release.
        original = {'account': 'self', 'peer': group['peer'], 'sender': 'owner',
                    'sender_name': 'Owner', 'mentioned': False, 'kind': 1, 'created': NOW + 1100,
                    'server_id': 44, 'text': 'Read ' + url}
        page = {'state': 'ready', 'url': url, 'text': 'Observed public article.'}
        events, sends = [original], []

        def native(value):
            if value['op'] == 'read':
                return {'events': events}
            if value['op'] == 'submit':
                source = value['server_id']
                sends.append(source)
                return {'state': 'succeeded', 'outcome': 'sent',
                        'request_id': request_id('self', group['peer'], source, 'rsi-group'),
                        'reply_sha256': hashlib.sha256(value['text'].encode()).hexdigest()}
            self.fail('Unexpected native action')

        path = self.root / 'link-backlog.sqlite'
        loop = GroupLoop(path, group, self.backend, native)
        self.addCleanup(loop.close)
        config = {'codex': 'existing-codex', 'desktop_thread_id': THREAD, 'desktop_all_requests': True}
        answer = '{"speak":true,"text":"A reply based on the linked article","work_index":null}'
        with patch('trigger.group_reply.linked_pages', side_effect=lambda _, source, *args: [page] if source == '44' else []):
            with self.assertRaises(PublicationPending):
                loop.cycle()
            route = self.jobs.claim('chat')
            self.jobs.update(route['id'], state='completed', result=answer)

            queued_at = NOW + 1000
            with patch('receiver.codex_worker.time.time', return_value=queued_at):
                with self.assertRaises(PublicationPending):
                    loop.cycle()
                old = self.jobs.claim('chat')
                with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as cli:
                    notify_desktop(config, self.jobs, old)
                cli.assert_called_once()
            old = self.jobs.get(old['id'])
            events.extend(dict(original, server_id=identity, created=NOW + 1105, text='Later message')
                          for identity in (45, 46))
            events.append(dict(original, server_id=47, created=NOW + 1106, sender='member', text='Later group question'))
            exchange = self.backend.exchange

            def legacy_exchange(route, value=None, **kwargs):
                if route == '/requests' and value['id'] == old['id']:
                    return 202, {'state': 'desktop_queued'}
                return exchange(route, value, **kwargs)

            with patch('receiver.codex_worker.time.time', return_value=queued_at + REPLY_TTL - 1):
                with self.assertRaises(PublicationPending):
                    loop.cycle()
            self.assertEqual(loop.value('model_batch'), '["44"]')
            with patch('receiver.codex_worker.time.time', return_value=queued_at + REPLY_TTL):
                with patch.object(self.backend, 'exchange', side_effect=legacy_exchange):
                    with self.assertRaises(PublicationPending):
                        loop.cycle()
                self.assertEqual(loop.cycle()['state'], 'model_review')
            self.assertEqual(loop.counts(), {'model_review': 1, 'new': 3})
            self.assertIsNone(loop.value('model_batch'))
            self.assertEqual(self.jobs.get(old['id']), old)

            loop.close()
            restarted = GroupLoop(path, group, load_model(self.root / 'backend.json'), native)
            self.addCleanup(restarted.close)
            with self.assertRaises(PublicationPending):
                restarted.cycle()
            later = self.jobs.claim('chat')
            self.assertEqual(json.loads(later['body'])['request'], ['45', '46', '47'])
            queued_later = queued()
            queued_later.stdout = queued_later.stdout.replace(MESSAGE, '00000000-0000-4000-8000-000000000004')
            with patch('receiver.codex_worker.subprocess.run', return_value=queued_later) as cli:
                notify_desktop(config, self.jobs, later)
            cli.assert_called_once()
            self.backend.exchange('/desktop-completions', {'id': old['id'], 'input_sha256': old['digest'],
                'thread_id': THREAD, 'turn_id': 'late-link-turn', 'text': 'Original late link answer'})
            self.backend.exchange('/desktop-completions', {'id': later['id'], 'input_sha256': later['digest'],
                'thread_id': THREAD, 'turn_id': 'later-chat-turn',
                'text': '{"speak":true,"text":"Later answer","work_index":null}'})
            self.assertEqual(restarted.cycle()['state'], 'pending')
            self.assertEqual(restarted.cycle()['state'], 'sent')
            self.assertEqual(restarted.cycle()['state'], 'idle')

        result = self.jobs.get(old['id'])
        self.assertEqual(result['result'], 'Original late link answer')
        for key in ('body', 'digest', 'thread_id', 'desktop_message_id'):
            self.assertEqual(result[key], old[key])
        self.assertEqual(sends, ['47'])
        self.assertIsNone(self.jobs.claim('chat'))
        self.assertEqual(restarted.counts(), {'model_review': 1, 'quiet': 2, 'sent': 1})
        route = f"/desktop-deliveries/{later['id']}/{THREAD}/later-chat-turn"
        self.assertEqual(self.backend.exchange(route)[1]['state'], 'sent')

    def test_single_owner_article_keeps_its_original_route_and_replies_once(self):
        from trigger.group_reply import GroupLoop
        from trigger.reply_io import request_id
        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        url = 'https://mp.weixin.qq.com/s/article'
        page = {'state': 'ready', 'url': url, 'text': 'Observed public article.'}
        answer = '基于已读取的正文给出答复\n\n第二段'
        envelope = json.dumps({'speak': True, 'text': answer, 'work_index': None}, ensure_ascii=False)
        review = '{"speak":true,"text":"","work_index":0}'
        for native_id, already_routed, output in (('44', False, envelope), ('45', True, answer),
                                                  ('46', True, review)):
            with self.subTest(native_id=native_id, already_routed=already_routed):
                event = {'account': 'self', 'peer': group['peer'], 'sender': 'owner',
                         'sender_name': 'Owner', 'mentioned': False, 'kind': 49, 'created': NOW + 120,
                         'server_id': native_id, 'link': {'url': url, 'text': 'Original article card'}}
                sends = []

                def native(value):
                    if value['op'] == 'read':
                        return {'events': [event]}
                    if value['op'] == 'submit':
                        sends.append((value['server_id'], value['text']))
                        return {'state': 'succeeded', 'outcome': 'sent',
                                'request_id': request_id('self', group['peer'], native_id, 'rsi-group'),
                                'reply_sha256': hashlib.sha256(value['text'].encode()).hexdigest()}
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
                            result='{"speak":true,"text":"Read the article","work_index":null}')
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
                    turn = 'article-turn-' + native_id
                    self.backend.exchange('/desktop-completions', {'id': article_key, 'input_sha256': task['input_sha256'],
                        'thread_id': THREAD, 'turn_id': turn, 'text': output})
                    if output == review:
                        self.assertEqual(restarted.cycle()['state'], 'model_review')
                        self.assertIsNone(restarted.value('model_batch'))
                        self.assertEqual(sends, [])
                        self.assertEqual(self.jobs.get(article_key)['result'], output)
                        continue
                    self.assertEqual(restarted.cycle()['state'], 'pending')
                    self.assertEqual(restarted.cycle()['state'], 'sent')
                    self.assertEqual(restarted.cycle()['state'], 'idle')
                    self.assertEqual(sends, [(native_id, answer)])
                    _, receipt = self.backend.exchange(f'/desktop-deliveries/{article_key}/{THREAD}/{turn}')
                    self.assertEqual((receipt['state'], receipt.get('text')), ('sent', answer))
                    self.assertEqual(self.jobs.get(article_key)['result'], output)

    def test_quiet_link_does_not_create_a_child_or_discard_an_existing_one(self):
        from trigger.group_reply import GroupLoop
        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        page = {'state': 'ready', 'url': 'https://example.com/article', 'text': 'Observed page.'}
        for existing_child in (False, True):
            with self.subTest(existing_child=existing_child):
                native_id = '51' if existing_child else '50'
                event = {'account': 'self', 'peer': group['peer'], 'sender': 'member',
                         'sender_name': 'Member', 'mentioned': False, 'kind': 1, 'created': 120,
                         'server_id': native_id, 'text': 'Shared https://example.com/article'}
                def native(value):
                    if value['op'] == 'read':
                        return {'events': [event]}
                    raise AssertionError('Quiet batch cannot send')
                loop = GroupLoop(self.root / (native_id + '.sqlite'), group, self.backend, native)
                self.addCleanup(loop.close)
                with patch('trigger.group_reply.linked_pages', return_value=[page]):
                    with self.assertRaises(PublicationPending):
                        loop.cycle()
                    key = self.backend.last_input_key
                    self.jobs.update(key, state='completed', result='{"speak":false,"text":"","work_index":null}')
                    if existing_child:
                        with self.assertRaises(PublicationPending):
                            self.backend.read_pages([page])
                        child_key = self.backend.last_input_key
                        child = self.jobs.get(child_key)
                    expected = 'model_review' if existing_child else 'quiet'
                    self.assertEqual(loop.cycle()['state'], expected)
                    self.assertIsNone(loop.value('model_batch'))
                    self.assertEqual(self.backend.has_original_input([native_id], stage='link-reading'), existing_child)
                    if existing_child:
                        self.assertEqual(self.jobs.get(child_key), child)
                    loop.close()
                    restarted = GroupLoop(self.root / (native_id + '.sqlite'), group, self.backend, native)
                    self.addCleanup(restarted.close)
                    self.assertEqual(restarted.cycle()['state'], 'idle')

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
        from trigger.reply_io import request_id
        owner = {'account': 'self', 'peer': 'owner', 'scope': {'mode': 'owner-private-text', 'since': 100}}
        event = {'account': 'self', 'peer': 'owner', 'sender': 'owner', 'kind': 1,
                 'created': 120, 'server_id': 42, 'text': '检查实际项目并修复问题'}
        sends = []
        def native(value):
            if value['op'] == 'read':return {'events': [event]}
            if value['op'] == 'submit':
                sends.append(value)
                return {'state': 'succeeded', 'outcome': 'sent',
                        'request_id': request_id('self', 'owner', value['server_id']),
                        'reply_sha256': hashlib.sha256(value['text'].encode()).hexdigest()}
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
        receipt = self.backend.exchange(f'/desktop-deliveries/{key}/{THREAD}/original-visible-turn')[1]
        self.assertEqual((receipt['state'], receipt.get('text')), ('sent', result['text']))

    def test_group_engineering_reports_the_owner_task_not_a_later_peer_message(self):
        from trigger.group_reply import GroupLoop
        from trigger.reply_io import request_id
        group = {'account': 'self', 'peer': 'group@chatroom', 'owner_peer': 'owner',
                 'name': 'Fixture group', 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        events = [{'account': 'self', 'peer': group['peer'], 'sender': sender, 'sender_name': sender,
                   'mentioned': False, 'kind': 1, 'created': 120 + i, 'server_id': str(44 + i), 'text': text}
                  for i, (sender, text) in enumerate((('owner', 'Fix the requested project'), ('member', 'Later chat')))]
        sends = []

        def native(value):
            if value['op'] == 'read':
                return {'events': events}
            if value['op'] == 'submit':
                sends.append(value)
                rid = request_id('self', group['peer'], value['server_id'], 'rsi-group')
                parts = [{'request_id': rid, 'expected_text': 'Fixed and checked.\n', 'actual_text': 'Fixed and checked.'},
                         {'request_id': rid + '-part-2', 'expected_text': 'Draft PR ready.', 'actual_text': 'Draft PR ready.'}]
                return {'state': 'succeeded', 'outcome': 'sent', 'request_id': rid,
                        'reply_sha256': hashlib.sha256(value['text'].encode()).hexdigest(), 'native_parts': parts}
            raise AssertionError('No extra native operation')

        path = self.root / 'engineering-group.sqlite'
        loop = GroupLoop(path, group, self.backend, native)
        self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.jobs.update(self.backend.last_input_key, state='completed', result='{"speak":true,"text":"","work_index":0}')
        with self.assertRaises(PublicationPending):
            loop.cycle()
        key = self.backend.last_input_key
        with patch('receiver.codex_worker.subprocess.run', return_value=queued()) as cli:
            notify_desktop({'codex': 'fixture-codex', 'desktop_thread_id': THREAD}, self.jobs, self.jobs.claim('engineering'))
        cli.assert_called_once()
        task = self.backend.exchange('/desktop-requests/' + key)[1]
        self.assertEqual(task['body']['request'], ['44'])
        text = 'Fixed and checked.\nDraft PR ready.'
        self.backend.exchange('/desktop-completions', {'id': key, 'input_sha256': task['input_sha256'],
            'thread_id': THREAD, 'turn_id': 'group-engineering-turn', 'text': text})
        receipt = {'id': key, 'state': 'sent', 'native_request_id': request_id('self', group['peer'], '44', 'rsi-group'),
                   'reply_sha256': hashlib.sha256(text.encode()).hexdigest(), 'code': None}
        for changed in ({'native_request_id': request_id('self', group['peer'], '45', 'rsi-group')},
                        {'reply_sha256': '0' * 64},
                        {'state': 'quiet', 'native_request_id': None, 'reply_sha256': None}):
            with self.assertRaises(ValueError):
                self.jobs.report_delivery(dict(receipt, **changed))
        self.assertEqual(loop.cycle()['state'], 'pending')
        loop.close()
        restarted = GroupLoop(path, group, load_model(self.root / 'backend.json'), native)
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.cycle()['state'], 'sent')
        self.assertEqual(restarted.cycle()['state'], 'idle')
        self.assertEqual([v['server_id'] for v in sends], ['44'])
        receipt = self.backend.exchange(f'/desktop-deliveries/{key}/{THREAD}/group-engineering-turn')[1]
        self.assertEqual((receipt['state'], receipt.get('texts')), ('sent', ['Fixed and checked.', 'Draft PR ready.']))
        self.assertEqual(self.jobs.get(key)['result'], text)
        self.assertIsNone(self.jobs.claim('engineering'))


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
