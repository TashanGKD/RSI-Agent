"""Group replies keep one original receipt across ordered native text parts."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from rsi_agent.config import WECHAT_LINUX
from trigger.group_io import CLIENT, handle, token
from trigger.group_text import split_text


class SplitTests(unittest.TestCase):
    def test_short_text_is_unchanged_and_long_text_is_lossless(self):
        self.assertEqual(split_text('收到，谢谢！'), ['收到，谢谢！'])
        text = ('这是需要完整保留的研究结论。\n\n' * 70) + '最后一句。'
        parts = split_text(text)
        self.assertGreater(len(parts), 1)
        self.assertEqual(''.join(parts), text)
        self.assertTrue(all(len(p.encode('utf-16-le')) // 2 <= 300 for p in parts))

    def test_emoji_combining_marks_and_crlf_are_not_broken(self):
        for atom in ('👩🏽\u200d🔬', '🇨🇳', 'e\u0301', '❤️', '\r\n'):
            text = '文' * 299 + atom + '尾' * 310
            parts = split_text(text)
            self.assertEqual(''.join(parts), text)
            self.assertTrue(any(atom in p for p in parts), repr(atom))

    def test_url_is_kept_clickable_even_when_it_exceeds_the_readability_budget(self):
        url = 'https://example.org/?source=' + 'x' * 350
        text = '来源：\n' + url + '\n结论。'
        parts = split_text(text)
        self.assertEqual(''.join(parts), text)
        self.assertIn(url, parts)


@unittest.skipUnless(sys.platform == 'linux', 'requires private Linux V2 fixture state')
class GroupPartsTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        sys.path.insert(0, str(WECHAT_LINUX))
        self.addCleanup(sys.path.remove, str(WECHAT_LINUX))
        from operations.public_api import PublicAPI
        self.binding = {'account': 'wxid_fixture_self', 'owner_peer': 'wxid_fixture_owner',
            'group_peer': 'fixture@chatroom', 'auto_reply_enabled': True,
            'send_scope': {'mode': 'invited-group-text', 'since': 100, 'name': 'Fixture'},
            'reply_model_binding': 'fixture'}
        self.installation = {'wechat': {'runtime_root': str(self.root)}}
        self.policy = {'account': self.binding['account'], 'clients': {CLIENT: {
            'peers': ['fixture@chatroom'], 'actions': ['send_text']}}}
        self.api = PublicAPI(self.root / 'operations-state', self.policy)
        self.addCleanup(self.api.close)
        config = self.api.s.root / 'config.json'
        config.write_text(json.dumps(self.policy))
        config.chmod(0o600)
        self.rid = CLIENT + '-' + hashlib.sha256(b'wxid_fixture_self\0fixture@chatroom\0' + b'1').hexdigest()
        self.text = '甲' * 300 + '乙' * 300 + '丙' * 80
        self.members = {'wxid_fixture_self': 'Self', 'wxid_fixture_owner': 'Owner'}

    def call(self, op, **extra):
        with patch('trigger.group_io.group_info', return_value=self.members):
            return handle(self.installation, self.binding,
                {'op': op, 'server_id': '1', '_binding': token(self.binding), **extra})

    def jobs(self):
        return self.api.s.list_jobs(CLIENT)

    def accept(self, job, **extra):
        self.api.s.set_state(job['id'], 'succeeded', {'state': 'accepted', **extra})

    def test_ordered_admission_restart_full_digest_and_completion(self):
        initial = self.call('submit', text=self.text)
        self.assertEqual(initial['parts_total'], 3)
        jobs = self.jobs()
        self.assertEqual(''.join(j['payload']['text'] for j in jobs), self.text)
        self.assertEqual(jobs[0]['request_id'], self.rid)
        self.assertEqual(jobs[1]['dispatch']['after'], [self.rid])
        self.accept(jobs[0])
        with patch('trigger.group_text.split_text', side_effect=AssertionError('must reuse frozen batch')):
            result = self.call('submit', text=self.text)
        self.assertEqual(result['state'], 'queued')
        self.assertEqual(result['outcome'], 'pending')
        self.assertEqual(result['parts_sent'], 1)
        self.assertEqual(result['reply_sha256'], hashlib.sha256(self.text.encode()).hexdigest())
        with patch('trigger.group_io.advance') as advance:
            def accept_one(api, job, policy):
                self.assertEqual(job['request_id'], jobs[1]['request_id'])
                self.accept(job)
                return {'state': 'succeeded', 'outcome': 'sent'}
            advance.side_effect = accept_one
            result = self.call('advance')
        self.assertEqual(result['parts_sent'], 2)
        self.assertEqual(result['outcome'], 'pending')
        self.accept(jobs[2])
        result = self.call('status')
        self.assertEqual((result['state'], result['outcome'], result['request_id']),
                         ('succeeded', 'sent', self.rid))
        with self.assertRaises(ValueError):
            self.call('submit', text=self.text + '改')
        self.assertEqual(len(self.jobs()), 3)

    def test_partial_failure_or_unknown_stops_the_original(self):
        self.call('submit', text=self.text)
        jobs = self.jobs()
        self.accept(jobs[0])
        for state, result in [('unknown', {}), ('failed', {'noSend': True, 'sideEffectStarted': False})]:
            self.api.s.set_state(jobs[1]['id'], state, result)
            with patch('trigger.group_io.advance') as advance:
                result = self.call('advance')
                advance.assert_not_called()
            self.assertEqual(result['outcome'], 'unknown')
            self.assertFalse(result['recoverable_preinput_failure'])
            self.assertEqual(result['parts_sent'], 1)
            self.assertEqual(self.jobs()[2]['state'], 'queued')

    def test_cleanup_debt_and_read_only_status_never_advance_a_part(self):
        self.call('submit', text=self.text)
        self.accept(self.jobs()[0], navigationRecoveryPending=True)
        before = (self.api.s.root / 'queue.sqlite').read_bytes()
        with patch('trigger.group_io.advance') as advance:
            result = self.call('advance')
            advance.assert_not_called()
            self.call('status')
        self.assertTrue(result['cleanup_pending'])
        self.assertNotEqual(result['outcome'], 'sent')
        self.assertEqual((self.api.s.root / 'queue.sqlite').read_bytes(), before)

    def test_legacy_long_original_is_never_split_or_replayed(self):
        job = self.api.s.submit({'client': CLIENT, 'request_id': self.rid, 'peer': 'fixture@chatroom',
            'action': 'send_text', 'payload': {'text': self.text}, 'execution_mode': 'verified_fast'})
        self.accept(job)
        result = self.call('submit', text=self.text)
        self.assertEqual(result['outcome'], 'sent')
        self.assertEqual(len(self.jobs()), 1)
        self.assertNotIn('dispatch', self.jobs()[0])

    def test_missing_status_does_not_create_jobs(self):
        with self.assertRaises(KeyError):
            self.call('status')
        self.assertEqual(self.jobs(), [])

    def test_partial_send_is_not_reported_as_complete_to_the_desktop(self):
        from trigger.owner_reply import ReplyLoop
        from unittest.mock import Mock
        loop = ReplyLoop(self.root / 'inbox.sqlite', {'account': 'wxid_fixture_self',
            'peer': 'fixture@chatroom', 'scope': {'mode': 'owner-private-text', 'since': 100}}, Mock(), Mock())
        self.addCleanup(loop.close)
        loop.save_delivery = Mock()
        row = {'id': '1', 'desktop_job': 'fixture-desktop', 'reply': self.text}
        self.call('submit', text=self.text)
        self.accept(self.jobs()[0])
        loop.record_delivery(row, self.call('status'))
        loop.save_delivery.assert_not_called()
        for job in self.jobs()[1:]:
            self.accept(job)
        loop.record_delivery(row, self.call('status'))
        loop.save_delivery.assert_called_once_with('1', 'fixture-desktop', 'sent', self.rid,
                                                  hashlib.sha256(self.text.encode()).hexdigest(), None)

    def test_corrupt_or_missing_batch_is_not_reconstructed(self):
        self.call('submit', text=self.text)
        jobs = self.jobs()
        self.api.s.c.execute('DELETE FROM jobs WHERE id=?', (jobs[-1]['id'],))
        with self.assertRaises(ValueError):
            self.call('submit', text=self.text)
        self.api.s.c.execute('DELETE FROM jobs WHERE id=?', (jobs[0]['id'],))
        with self.assertRaises(ValueError):
            self.call('submit', text=self.text)
        self.assertEqual(len(self.jobs()), 1)

    def test_oversized_batch_is_rejected_atomically_before_any_send(self):
        text = ('a' * 150 + '. ') * 39
        with self.assertRaises(ValueError):
            self.call('submit', text=text)
        self.assertEqual(self.jobs(), [])


if __name__ == '__main__':
    unittest.main()
