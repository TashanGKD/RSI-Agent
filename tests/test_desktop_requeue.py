"""Requeue only a request whose desktop turn ended before the request was read."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from receiver import desktop_requeue
from receiver.codex_worker import GROUP_INPUT_MAX_AGE, Jobs, encoded, group_input_time, notify_desktop

THREAD = '00000000-0000-4000-8000-000000000001'
TURN = '00000000-0000-4000-8000-000000000002'


class RequeueTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.jobs = Jobs(self.root / 'state')
        self.config = {'port': 0, 'token': 'a' * 64, 'state': str(self.root / 'state'), 'codex': sys.executable,
                       'desktop_thread_id': THREAD, 'desktop_all_requests': True}
        self.jobs.accept({'id': 'a' * 64, 'scope': ['account', 'owner'], 'request': ['1'], 'mode': 'chat',
                          'messages': [{'role': 'user', 'content': 'private input'}], 'schema': None})
        ack = subprocess.CompletedProcess([], 0, f'Queued message {"0" * 8}-0000-4000-8000-000000000009 for thread {THREAD}.\n', '')
        with patch('receiver.codex_worker.subprocess.run', return_value=ack) as queue:
            notify_desktop(self.config, self.jobs, self.jobs.claim('chat'))
        self.message = queue.call_args.args[0][-1]
        desktop_requeue._scanned.clear()

    def rollout(self, ending):
        records = [{'type': 'session_meta', 'payload': {'id': THREAD}},
                   {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': TURN}},
                   {'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                       'content': [{'type': 'input_text', 'text': self.message}]}}]
        if ending:
            records.append({'type': 'event_msg', 'payload': dict(ending, turn_id=TURN)})
        path = self.root / 'sessions' / f'rollout-x-{THREAD}.jsonl'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b'\n'.join(map(encoded, records)) + b'\n')

    def run_requeue(self):
        ack = subprocess.CompletedProcess([], 0, f'Queued message {"0" * 8}-0000-4000-8000-000000000010 for thread {THREAD}.\n', '')
        with patch('receiver.desktop_requeue.subprocess.run', return_value=ack) as queue:
            result = desktop_requeue.requeue_interrupted(self.config, self.jobs, group_input_time, GROUP_INPUT_MAX_AGE,
                                                         now=time.time() + 120, sessions=self.root / 'sessions')
        return result, queue

    def test_interrupted_turn_is_requeued_once_with_the_identical_text(self):
        self.rollout({'type': 'turn_aborted', 'reason': 'interrupted'})
        result, queue = self.run_requeue()
        self.assertEqual(result, 'a' * 64)
        self.assertEqual(queue.call_args.args[0][-1], self.message)
        record = json.loads((self.root / 'state' / ('a' * 64) / 'desktop-requeue.json').read_text())
        self.assertEqual(record['state'], 'queued')
        desktop_requeue._scanned.clear()
        self.assertEqual(self.run_requeue()[0], None)

    def test_model_error_turn_is_requeued(self):
        self.rollout({'type': 'task_complete', 'error': {'message': 'unexpected status 401'}})
        self.assertEqual(self.run_requeue()[0], 'a' * 64)

    def test_running_or_normally_completed_turns_are_left_alone(self):
        for ending in (None, {'type': 'task_complete', 'error': None}):
            with self.subTest(ending=ending):
                self.rollout(ending)
                desktop_requeue._scanned.clear()
                result, queue = self.run_requeue()
                self.assertIsNone(result)
                queue.assert_not_called()

    def test_a_request_that_was_already_read_is_never_requeued(self):
        self.rollout({'type': 'turn_aborted', 'reason': 'interrupted'})
        (self.root / 'state' / ('a' * 64) / 'desktop-execution.json').write_text('{}')
        result, queue = self.run_requeue()
        self.assertIsNone(result)
        queue.assert_not_called()


if __name__ == '__main__':
    unittest.main()
