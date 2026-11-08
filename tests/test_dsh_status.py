import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from rsi_agent.dsh_status import snapshot


@unittest.skipUnless(sys.platform == 'linux', 'private Linux runtime state')
class StatusTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.canary = 'PRIVATE_CHAT_TOKEN_AND_NATIVE_ID'
        self.write('owner.json', {'state': str(self.root / 'owner'),
            'model': str(self.root / 'model.json'), 'enabled': True, 'binding_token': self.canary})
        self.write('groups.json', {'groups': []})
        self.write('model.json', {'state': str(self.root / 'dsh'),
            'engineering_workspace': str(self.root / 'engineering/workspace'), 'api_key': self.canary})
        self.write('release.json', {'commit': 'a' * 40, 'private': self.canary})
        self.write('owner/status.json', {'state': 'idle', 'checked_at': time.time(),
            'model_backend': 'deepseek-harness', 'text': self.canary})
        self.database = self.root / 'owner/inbox.sqlite'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE inbox(id TEXT, text TEXT, reply TEXT, state TEXT)')
            db.execute('INSERT INTO inbox VALUES(?,?,?,?)', (self.canary, self.canary, self.canary, 'pending'))
        self.database.chmod(0o600)
        self.service = patch('rsi_agent.dsh_status.service_state',
            return_value={'process_active': True, 'current_code': True})
        self.service.start()
        self.addCleanup(self.service.stop)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def read(self):
        return snapshot(self.root / 'owner.json', self.root / 'groups.json',
            self.root / 'release.json', self.root)

    def hashes(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.root.rglob('*') if p.is_file()}

    def test_idle_chat_does_not_hide_unresolved_engineering_or_retry_it(self):
        key = 'b' * 64
        self.write('engineering/engineering-current.json', {'request': key})
        self.write('dsh/calls/' + key + '.json', {'state': 'running', 'response': self.canary})
        before = self.hashes()
        result = self.read()
        self.assertEqual(result['workers'][0]['observation'], 'idle')
        self.assertTrue(result['workers'][0]['fresh'])
        self.assertEqual(result['workers'][0]['queue']['pending'], 1)
        self.assertEqual(result['engineering'], {'state': 'needs_review',
            'recorded_state': 'running', 'retry_allowed': False})
        self.assertNotIn(self.canary, json.dumps(result))
        self.assertNotIn(key, json.dumps(result))
        self.assertEqual(before, self.hashes())

    def test_stale_status_and_old_process_code_are_reported_separately(self):
        self.write('owner/status.json', {'state': 'idle', 'checked_at': time.time() - 1000})
        with patch('rsi_agent.dsh_status.service_state',
                   return_value={'process_active': True, 'current_code': False}):
            result = self.read()['workers'][0]
        self.assertFalse(result['fresh'])
        self.assertFalse(result['current_code'])
        self.assertTrue(result['process_active'])

    def test_unreadable_layer_does_not_discard_other_layers(self):
        self.write('groups.json', {'groups': [str(self.root / 'missing.json')]})
        result = self.read()
        self.assertEqual(result['release'], 'a' * 40)
        self.assertEqual(result['workers'][0]['observation'], 'idle')
        self.assertEqual(result['workers'][1]['observation'], 'unavailable')

    def test_missing_original_receipt_keeps_work_blocked(self):
        self.write('engineering/engineering-current.json', {'request': '../../private'})
        result = self.read()['engineering']
        self.assertEqual(result, {'state': 'needs_review', 'retry_allowed': False})

    def test_completed_sdk_output_is_visible_without_treating_it_as_published(self):
        key = 'b' * 64
        self.write('engineering/engineering-current.json', {'request': key})
        self.write('dsh/calls/' + key + '.json', {'state': 'sdk_completed', 'response': self.canary})
        result = self.read()['engineering']
        self.assertEqual(result, {'state': 'needs_review', 'recorded_state': 'sdk_completed', 'retry_allowed': False})
        self.assertNotIn(self.canary, json.dumps(result))

    def test_automatic_group_admission_status_is_sanitized(self):
        self.write('admission-status.json', {'state': 'enabled', 'checked_at': time.time(),
            'waiting_owner': 1, 'unaddressable': 0, 'private_names': self.canary})
        value = self.read()
        self.assertEqual(value['group_admission'], {'state': 'enabled', 'fresh': True,
            'waiting_owner': 1, 'unaddressable': 0})
        self.assertNotIn(self.canary, json.dumps(value))


if __name__ == '__main__':
    unittest.main()
