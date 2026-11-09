import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from rsi_agent.owner_reply import ReplyLoop
from rsi_agent.local_codex import handle, process


@unittest.skipUnless(sys.platform == 'linux', 'private native-owner handoff')
class LocalCodexTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'inbox.sqlite'
        self.policy = {'enabled': True, 'since': 110, 'target_thread_id': '11111111-1111-1111-1111-111111111111'}
        switch = self.root / 'local-codex.json'
        switch.write_text(json.dumps(self.policy))
        switch.chmod(0o600)
        self.owner = {'account': 'self', 'peer': 'owner', 'enabled': True,
                      'scope': {'mode': 'owner-private-text', 'since': 100}}
        self.model = Mock()
        self.model.reply.return_value = 'An ordinary Codex reply'
        self.events = [self.event(1, '/codex Inspect the project and return the actual result')]
        self.calls, self.effects = [], {}
        self.fail_after_effect = False
        self.loop = ReplyLoop(self.path, self.owner, self.model, self.io)
        self.addCleanup(self.loop.close)

    def event(self, server, text, **changes):
        return dict(account='self', peer='owner', sender='owner', server_id=server,
                    kind=1, created=120, text=text) | changes

    def io(self, request):
        self.calls.append(request)
        if request['op'] == 'read':
            return {'events': self.events, 'batch_id': 'native-batch', 'batch_hash': 'native-hash',
                    'ack_ids': [str(event['server_id']) for event in self.events]}
        if request['op'] == 'ack':
            with sqlite3.connect(self.path) as db:
                if self.events[0]['text'].startswith('/codex') and self.events[0]['created'] >= 110:
                    self.assertIn(db.execute('SELECT state FROM codex_jobs WHERE id="1"').fetchone()[0],
                                  ('queued', 'claimed', 'completed'))
            return {'state': 'acked'}
        key = request['server_id']
        if request['op'] == 'submit':
            return self.effects.get(key, {'state': 'queued'})
        self.assertNotIn(key, self.effects)
        self.effects[key] = {'state': 'succeeded', 'outcome': 'sent'}
        if self.fail_after_effect:
            self.fail_after_effect = False
            raise OSError('Lost transport result after original send')
        return self.effects[key]

    def call(self, op, **extra):
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return process(db, self.policy, {'op': op, **extra})

    def claim(self, claim='a' * 32):
        return self.call('claim', claim_id=claim, thread_id=self.policy['target_thread_id'])

    def finish(self, claim, text='Actual local Codex result'):
        return self.call('complete', claim_id=claim['claim_id'], thread_id=claim['thread_id'],
                         id=claim['id'], input_sha256=claim['input_sha256'], text=text)

    def test_owner_prefix_is_durable_before_ack_without_generation_or_send(self):
        self.assertEqual(self.loop.cycle()['state'], 'waiting_codex')
        self.assertEqual(self.call('check')['jobs'], {'queued': 1})
        self.model.reply.assert_not_called()
        self.assertEqual([call['op'] for call in self.calls], ['read', 'ack'])
        self.assertEqual(self.effects, {})
        self.assertEqual(self.loop.cycle()['counts'], {'local_codex': 1})

    def test_claim_completion_restart_and_lost_send_keep_one_original(self):
        self.loop.cycle()
        claim = self.claim()
        self.assertEqual(claim, self.claim())
        self.assertEqual(claim['instruction'], 'Inspect the project and return the actual result')
        self.assertEqual(self.claim('b' * 32)['state'], 'original_work_unresolved')
        complete = self.finish(claim)
        self.assertEqual(complete['delivery'], 'pending')
        self.assertNotIn('instruction', complete)
        self.assertEqual(complete, self.finish(claim))
        self.loop.close()
        self.loop = ReplyLoop(self.path, self.owner, self.model, self.io)
        self.addCleanup(self.loop.close)
        self.fail_after_effect = True
        with self.assertRaises(OSError):
            self.loop.cycle()
        self.assertEqual(self.loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['1'])
        self.model.reply.assert_not_called()
        self.assertEqual(self.finish(claim)['delivery'], 'sent')

    def test_other_senders_and_historical_prefix_cannot_enter_codex(self):
        self.events = [self.event(1, '/codex Old request', created=105),
                       self.event(2, '/codex Claimed owner', sender='other')]
        self.assertEqual(self.loop.cycle()['state'], 'sent')
        self.assertEqual(self.call('check')['jobs'], {})
        self.model.reply.assert_called_once_with('/codex Old request', [])

    def test_ordinary_owner_chat_still_uses_codex_while_codex_waits(self):
        self.loop.cycle()
        self.events = [self.event(2, 'How are things going?')]
        self.assertEqual(self.loop.cycle()['state'], 'sent')
        self.model.reply.assert_called_once_with('How are things going?', [])
        self.assertEqual(list(self.effects), ['2'])
        self.assertEqual(self.call('check')['jobs'], {'queued': 1})

    def test_wrong_thread_changed_input_and_replacement_reply_are_rejected(self):
        self.loop.cycle()
        with self.assertRaises(ValueError):
            self.call('claim', claim_id='a' * 32, thread_id='22222222-2222-2222-2222-222222222222')
        claim = self.claim()
        self.finish(claim)
        with self.assertRaises(ValueError):
            self.finish(claim, 'A second generated answer')
        with sqlite3.connect(self.path) as db:
            db.execute('UPDATE inbox SET text=? WHERE id="1"', ('Changed original owner input',))
        with self.assertRaisesRegex(ValueError, 'Original native input changed'):
            self.finish(claim)

    def test_enabled_empty_queue_is_inspectable_without_starting_a_task(self):
        self.assertEqual(self.call('check'), {'state': 'enabled', 'jobs': {}, 'delivery': {}})
        self.assertEqual(self.claim(), {'state': 'idle'})

    def test_operator_port_rechecks_owner_scope_and_original_binding(self):
        path = self.root / 'config.json'
        path.write_text(json.dumps({'state': str(self.root), 'enabled': True}))
        path.chmod(0o600)
        with patch('rsi_agent.owner_reply.Transport', return_value=Mock(return_value=self.owner)):
            self.assertEqual(handle(path, {'op': 'check'})['state'], 'enabled')
            self.owner['scope']['mode'] = 'one-message'
            with self.assertRaises(ValueError):
                handle(path, {'op': 'check'})
            self.owner['scope']['mode'] = 'owner-private-text'
            self.owner['peer'] = 'different-owner'
            with self.assertRaisesRegex(ValueError, 'Original native owner binding changed'):
                handle(path, {'op': 'check'})
