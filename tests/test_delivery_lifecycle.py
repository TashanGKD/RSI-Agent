import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, Request, build_opener

from receiver.codex_worker import Jobs, server
from receiver.delivery_updates import notify

THREAD = '00000000-0000-4000-8000-000000000001'
MESSAGE = '00000000-0000-4000-8000-000000000002'


class DeliveryLifecycleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.jobs = Jobs(self.root)
        self.packet = {'id': 'a' * 64, 'scope': ['self', 'owner'], 'request': ['42'], 'mode': 'chat',
            'messages': [{'role': 'user', 'content': 'hello'}], 'schema': None}
        accepted = self.jobs.accept(self.packet)
        self.jobs.update(self.packet['id'], state='desktop_queued', thread_id=THREAD, desktop_message_id=MESSAGE)
        self.jobs.complete_desktop({'id': self.packet['id'], 'input_sha256': accepted['digest'],
            'thread_id': THREAD, 'turn_id': 'original-turn', 'text': 'reply'}, THREAD)
        self.folder = self.root / self.packet['id']
        self.folder.mkdir()
        self.receipt = {'id': self.packet['id'], 'state': 'sent', 'code': None,
            'native_request_id': 'rsi-owner-' + hashlib.sha256('\0'.join(('self', 'owner', '42')).encode()).hexdigest(),
            'reply_sha256': hashlib.sha256(b'reply').hexdigest(), 'cleanup_pending': True}

    def age_original(self):
        with self.jobs.connect() as db:
            db.execute('UPDATE jobs SET updated=? WHERE id=?', (time.time() - 40, self.packet['id']))

    def test_cleanup_can_settle_but_cannot_regress_or_replace_sent_text(self):
        self.jobs.report_delivery(self.receipt)
        view = self.jobs.desktop_delivery(self.packet['id'], THREAD, 'original-turn', THREAD)
        self.assertTrue(view['cleanup_pending'])
        settled = dict(self.receipt, cleanup_pending=False)
        self.jobs.report_delivery(settled)
        self.jobs.report_delivery(settled)
        self.assertFalse(self.jobs.desktop_delivery(self.packet['id'], THREAD, 'original-turn', THREAD)['cleanup_pending'])
        for invalid in (self.receipt, dict(settled, cleanup_pending='false'), dict(settled, state='not_sent')):
            with self.assertRaises(ValueError):
                self.jobs.report_delivery(invalid)

    def test_late_receipt_notifies_original_thread_once_and_never_generates_reply(self):
        self.age_original()
        self.jobs.report_delivery(self.receipt)
        self.jobs.report_delivery(self.receipt)
        result = subprocess.CompletedProcess([], 0, f'Queued message {MESSAGE} for thread {THREAD}.\n', '')
        config = {'state': str(self.root), 'codex': 'existing-codex'}
        with patch('receiver.delivery_updates.subprocess.run', return_value=result) as command:
            notify(config, self.jobs)
            notify(config, self.jobs)
        command.assert_called_once()
        args = command.call_args.args[0]
        self.assertEqual(args[:4], ['existing-codex', 'queue', '--thread', THREAD])
        self.assertIn('原执行轮次：original-turn', args[-1])
        self.assertIn('不是新微信输入', args[-1])
        self.assertEqual(self.jobs.get(self.packet['id'])['result'], 'reply')

    def test_immediate_receipt_needs_no_extra_desktop_turn(self):
        self.jobs.report_delivery(self.receipt)
        with patch('receiver.delivery_updates.subprocess.run') as command:
            notify({'state': str(self.root), 'codex': 'existing-codex'}, self.jobs)
        command.assert_not_called()

    def test_settled_success_stays_in_ledger_without_a_notice(self):
        self.age_original()
        settled = dict(self.receipt, cleanup_pending=False)
        self.jobs.report_delivery(settled)
        with patch('receiver.delivery_updates.subprocess.run') as command:
            notify({'state': str(self.root), 'codex': 'existing-codex'}, self.jobs)
        command.assert_not_called()
        view = self.jobs.desktop_delivery(self.packet['id'], THREAD, 'original-turn', THREAD)
        self.assertEqual(view['state'], 'sent')
        self.assertFalse(view['cleanup_pending'])
        with self.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM delivery_updates').fetchone()[0], 0)

    def test_failure_and_pending_cleanup_still_notify_with_resume(self):
        self.age_original()
        failed = dict(self.receipt, state='not_sent', code='DRAFT_PROTECTED', cleanup_pending=False)
        self.jobs.report_delivery(failed)
        result = subprocess.CompletedProcess([], 0, f'Queued message {MESSAGE} for thread {THREAD}.\n', '')
        with patch('receiver.delivery_updates.subprocess.run', return_value=result) as command:
            notify({'state': str(self.root), 'codex': 'existing-codex'}, self.jobs)
        command.assert_called_once()
        self.assertIn('--resume', command.call_args.args[0])

    def test_uncertain_notice_and_interrupted_submission_are_not_requeued(self):
        self.age_original()
        self.jobs.report_delivery(self.receipt)
        with patch('receiver.delivery_updates.subprocess.run', side_effect=subprocess.TimeoutExpired('queue', 30)) as command:
            notify({'state': str(self.root), 'codex': 'existing-codex'}, self.jobs)
            notify({'state': str(self.root), 'codex': 'existing-codex'}, Jobs(self.root))
        command.assert_called_once()
        with self.jobs.connect() as db:
            db.execute("UPDATE delivery_updates SET state='submitting'")
        Jobs(self.root)
        with self.jobs.connect() as db:
            self.assertEqual(db.execute('SELECT state FROM delivery_updates').fetchone()[0], 'review')

    def test_receiver_health_does_not_claim_pipeline_without_fresh_native_checks(self):
        config = {'port': 0, 'token': 'a' * 64, 'codex': sys.executable}
        http = server(config, self.jobs, threading.Event())
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(http.server_close)
        self.addCleanup(http.shutdown)
        opener = build_opener(ProxyHandler({}))
        def request(path, body=None):
            req = Request(f'http://127.0.0.1:{http.server_port}' + path,
                data=json.dumps(body).encode() if body else None,
                headers={'Authorization': 'Bearer ' + config['token']})
            with opener.open(req, timeout=3) as response:
                return json.load(response)
        self.assertFalse(request('/health')['pipeline_ready'])
        proof = {'state': 'idle', 'checks': {'account': True, 'client': True, 'layout': True}}
        request('/runtime-heartbeat', proof)
        self.assertTrue(request('/health')['pipeline_ready'])
        request('/runtime-heartbeat', dict(proof, state='attention'))
        self.assertFalse(request('/health')['pipeline_ready'])
        request('/runtime-heartbeat', proof)
        with patch('receiver.codex_worker.time.time', return_value=time.time() + 91):
            self.assertFalse(request('/health')['pipeline_ready'])


if __name__ == '__main__':
    unittest.main()
