import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from receiver.codex_worker import Jobs, encoded, notify_desktop, server
from receiver.desktop_reply import chat_binding, save_once


class DesktopReconcileTests(unittest.TestCase):
    def test_cli_distinguishes_queue_and_turn_and_only_reads_the_original(self):
        thread = '00000000-0000-4000-8000-000000000001'
        turn = '00000000-0000-4000-8000-000000000002'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            jobs = Jobs(root)
            config = {'port': 0, 'token': 'a' * 64, 'state': str(root), 'codex': sys.executable,
                      'desktop_thread_id': thread, 'desktop_all_requests': True}
            messages = []
            for index, identity in enumerate(('a' * 64, 'b' * 64), 1):
                jobs.accept({'id': identity, 'scope': ['account', 'owner'], 'request': [str(index)],
                    'mode': 'chat', 'messages': [{'role': 'user', 'content': 'private input'}], 'schema': None})
                queue_id = f'00000000-0000-4000-8000-{index:012}'
                ack = subprocess.CompletedProcess([], 0, f'Queued message {queue_id} for thread {thread}.\n', '')
                with patch('receiver.codex_worker.subprocess.run', return_value=ack) as queue:
                    notify_desktop(config, jobs, jobs.claim('chat'))
                messages.append(queue.call_args.args[0][-1])
            queued, completed = 'a' * 64, 'b' * 64
            rollout = root / 'session.jsonl'
            records = [
                {'type': 'session_meta', 'payload': {'id': thread}},
                {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': turn}},
                {'type': 'response_item', 'payload': {'type': 'function_call_output', 'output': messages[0]}},
                {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': messages[1]}]}},
                {'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': turn}},
            ]
            rollout.write_bytes(b'\n'.join(map(encoded, records)) + b'\n')
            original = jobs.desktop_task(completed, thread)
            binding = chat_binding(original, completed, thread, turn)
            save_once(root / completed / 'desktop-execution.json', dict(binding, phase='running'))
            completion = dict(binding, text='private reply')
            save_once(root / completed / 'desktop-completion.json', completion)
            jobs.complete_desktop(completion, thread)
            native_id = hashlib.sha256('\0'.join(('account', 'owner', '2')).encode()).hexdigest()
            jobs.report_delivery({'id': completed, 'state': 'sent', 'native_request_id': 'rsi-owner-' + native_id,
                                  'reply_sha256': hashlib.sha256(b'private reply').hexdigest(), 'code': None})

            def snapshot():
                return {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}

            with server(config, jobs, threading.Event()) as http:
                config_path = root / 'config.json'
                config_path.write_bytes(encoded(dict(config, port=http.server_port)))
                attempts = []
                def post(handler):
                    attempts.append(handler.path)
                    handler.send_error(405)
                worker = threading.Thread(target=http.serve_forever)
                worker.start()
                before = snapshot()
                try:
                    with patch.object(http.RequestHandlerClass, 'do_POST', post):
                        for identity, evidence in (
                            (queued, ('not_observed', None, 'unverified', 'unverified')),
                            (completed, ('observed', turn, 'accepted', 'sent')),
                        ):
                            result = subprocess.run([sys.executable, '-B', '-m', 'receiver.desktop_reconcile',
                                str(config_path), identity, '--rollout', str(rollout)],
                                capture_output=True, timeout=8)
                            self.assertEqual(result.returncode, 0, result.stderr.decode())
                            report = json.loads(result.stdout)
                            self.assertEqual(report['id'], identity)
                            self.assertTrue(report['queue_acknowledged'])
                            self.assertEqual((report['turn_evidence'], report['observed_turn_id'],
                                report['completion'], report['v2']['state']), evidence)
                            self.assertNotIn(b'private input', result.stdout)
                            self.assertNotIn(b'private reply', result.stdout)
                    self.assertEqual(attempts, [])
                    self.assertEqual(snapshot(), before)
                finally:
                    http.shutdown()
                    worker.join()
