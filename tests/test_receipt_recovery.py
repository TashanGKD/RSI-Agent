"""Use only a disposable queue; no executor, account keys or GUI session."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rsi_agent.config import ROOT


@unittest.skipUnless(sys.platform == 'linux', 'requires native Linux queue ownership checks')
class ReceiptRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='rsi-receipt-recovery-')
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name).resolve()
        self.native = ROOT / 'components/secretary-workbench/wechat'
        sys.path.insert(0, str(self.native))
        self.addCleanup(sys.path.remove, str(self.native))
        from operations.public_api import PublicAPI
        self.state = self.base / 'runtime/operations-state'
        policy = {'account': 'wxid_fixture_operator', 'clients': {}}
        api = PublicAPI(self.state, policy)
        try:
            for state in ('succeeded', 'unknown'):
                job = api.s.submit({'client': 'fixture', 'request_id': state + '-original',
                    'peer': 'wxid_fixture_target', 'action': 'send_text',
                    'payload': {'text': 'Synthetic stored receipt; never executed.'}})
                result = {'state': 'accepted'} if state == 'succeeded' else {'automaticReplay': False}
                api.s.set_state(job['id'], state, result)
        finally:
            api.close()
        self.policy = self.state / 'config.json'
        self.policy.write_text(json.dumps(policy))
        self.policy.chmod(0o600)
        self.installation = self.base / 'installation.json'
        self.installation.write_text(json.dumps({'version': 1, 'wechat': {
            'runtime_root': str(self.state.parent), 'display': ':299',
            'xauthority': str(self.base / 'absent-Xauthority'), 'operations_enabled': False}}))
        self.installation.chmod(0o600)
        empty_bin = self.base / 'empty-bin'
        empty_bin.mkdir(mode=0o700)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith('WECHAT_')}
        self.env.update(PATH=str(empty_bin), DISPLAY=':299', XAUTHORITY=str(self.base / 'absent-Xauthority'),
                        PYTHONDONTWRITEBYTECODE='1')

    def invoke(self, request, native=False):
        command = ([sys.executable, '-B', '-m', 'operations.cli', 'request', '--execute',
                    '--root', str(self.state), '--config', str(self.policy)] if native else
                   [sys.executable, '-B', '-m', 'rsi_agent', '--config', str(self.installation),
                    'wechat', 'operations'])
        result = subprocess.run(command, cwd=self.native if native else ROOT, env=self.env,
                                input=json.dumps(request), capture_output=True, text=True, timeout=30)
        return result.returncode, json.loads(result.stdout)

    def snapshot(self):
        return {str(path.relative_to(self.state)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.state.rglob('*') if path.is_file()}

    def test_original_receipts_remain_available_without_desktop_keys_or_write_enable(self):
        before = self.snapshot()
        for state, outcome in (('succeeded', 'sent'), ('unknown', 'unknown')):
            with self.subTest(state=state):
                request = {'op': 'get', 'client': 'fixture', 'request_id': state + '-original'}
                original_exit, original = self.invoke(request, native=True)
                self.assertEqual(original_exit, 0)
                exit_code, receipt = self.invoke(request)
                self.assertEqual(exit_code, 0, receipt)
                self.assertEqual(receipt, original)
                self.assertEqual(receipt['request_id'], request['request_id'])
                self.assertEqual(receipt['state'], state)
                self.assertEqual(receipt['outcome']['status'], outcome)
                if state == 'unknown':
                    self.assertFalse(receipt['result']['automaticReplay'])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(list(self.state.glob('*-attempt.json')), [])

    def test_lookup_does_not_create_a_missing_queue(self):
        queue = self.state / 'queue.sqlite'
        queue.rename(self.state / 'preserved.sqlite')
        before = self.snapshot()
        exit_code, result = self.invoke({'op': 'get', 'client': 'fixture', 'request_id': 'unknown-original'})
        self.assertEqual(exit_code, 2)
        self.assertEqual(result['state'], 'blocked')
        self.assertFalse(queue.exists())
        self.assertEqual(self.snapshot(), before)

    def test_lookup_requires_private_queue_and_policy(self):
        for path in (self.state / 'queue.sqlite', self.policy):
            with self.subTest(path=path.name):
                path.chmod(0o644)
                try:
                    before = self.snapshot()
                    exit_code, result = self.invoke({'op': 'get', 'client': 'fixture', 'request_id': 'unknown-original'})
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(result['state'], 'blocked')
                    self.assertEqual(self.snapshot(), before)
                finally:
                    path.chmod(0o600)

    def test_mutations_stay_blocked_and_missing_receipt_does_not_allocate(self):
        before = self.snapshot()
        for op in ('submit', 'confirm', 'cancel', 'reconcile'):
            exit_code, result = self.invoke({'op': op, 'client': 'fixture', 'request_id': 'unknown-original'})
            self.assertEqual(exit_code, 2)
            self.assertEqual(result['state'], 'blocked')
        exit_code, result = self.invoke({'op': 'get', 'client': 'fixture', 'request_id': 'not-present'})
        self.assertEqual(exit_code, 2)
        self.assertIn('error', result, result)
        self.assertEqual(result['error']['code'], 'REQUEST_NOT_FOUND')
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
