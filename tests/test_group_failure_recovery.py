"""Frozen pre-input failure: keep its receipt/cache, resume only future intake."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from rsi_agent.config import WECHAT_LINUX
from trigger.group_io import CLIENT, handle, token
from trigger.group_reply import GroupLoop


@unittest.skipUnless(sys.platform == 'linux', 'requires native private Linux state')
class GroupFailureRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        sys.path.insert(0, str(WECHAT_LINUX))
        self.addCleanup(sys.path.remove, str(WECHAT_LINUX))
        from operations.public_api import PublicAPI
        from operations import navigation
        self.binding = {'account': 'wxid_fixture_self', 'owner_peer': 'wxid_fixture_owner',
            'group_peer': 'fixture@chatroom', 'auto_reply_enabled': True,
            'send_scope': {'mode': 'invited-group-text', 'since': 100, 'name': 'Fixture'},
            'reply_model_binding': 'fixture'}
        self.installation = {'wechat': {'runtime_root': str(self.root)}}
        self.state = self.root / 'operations-state'
        policy = {'account': self.binding['account'], 'clients': {}}
        self.api = PublicAPI(self.state, policy)
        self.addCleanup(self.api.close)
        config = self.state / 'config.json'
        config.write_text(json.dumps(policy))
        config.chmod(0o600)
        self.reply = 'Original cached reply; never resend.'
        rid = CLIENT + '-' + hashlib.sha256(('wxid_fixture_self\0fixture@chatroom\0' + '1').encode()).hexdigest()
        job = self.api.s.submit({'client': CLIENT, 'request_id': rid, 'peer': 'fixture@chatroom',
            'action': 'send_text', 'payload': {'text': self.reply}, 'execution_mode': 'verified_fast'})
        self.key = job['id']
        self.api.s.set_state(self.key, 'preparing')
        self.failure = {'code': 'SEARCH_SELECTION_UNPROVEN', 'noSend': True, 'sideEffectStarted': False}
        self.api.s.set_state(self.key, 'failed', self.failure)
        self.nav = navigation.save(self.state, self.job(), {'state': 'settled'})
        self.members = {self.binding['account']: 'Self', self.binding['owner_peer']: 'Owner'}
        self.calls = []
        self.model = Mock()
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"New reply"}'}}
        self.group = {'account': self.binding['account'], 'peer': 'fixture@chatroom', 'name': 'Fixture',
                      'scope': self.binding['send_scope']}

    def job(self):
        return self.api.s.by_id(self.key)

    def status(self):
        with patch('trigger.group_io.group_info', return_value=self.members):
            return handle(self.installation, self.binding,
                {'op': 'status', 'server_id': '1', '_binding': token(self.binding)})

    def io(self, request):
        self.calls.append(request)
        if request['op'] == 'status':
            self.assertEqual(request['server_id'], '1')
            return self.status()
        if request['op'] == 'read':
            return {'events': [{'account': self.binding['account'], 'peer': 'fixture@chatroom',
                'sender': 'member', 'sender_name': 'Member', 'mentioned': True, 'kind': 1,
                'text': 'A new question?', 'created': 150, 'server_id': '2'}]}
        self.assertEqual(request['op'], 'submit')
        self.assertEqual(request['server_id'], '2')
        return {'state': 'succeeded', 'outcome': 'sent'}

    def loop(self):
        loop = GroupLoop(self.root / 'inbox.sqlite', self.group, self.model, self.io)
        self.addCleanup(loop.close)
        with loop.db:
            loop.save('introduction', 'sent')
            loop.db.execute('INSERT INTO inbox(id,created,text,reply,state) VALUES(?,?,?,?,?)',
                ('1', 120, 'Original frozen body', self.reply, 'attention'))
        return loop

    def test_clean_terminal_failure_preserves_original_and_resumes_new_input(self):
        self.assert_intake_resumes_without_resending_original()

    def test_restored_preparation_attention_resumes_new_input(self):
        self.api.s.c.execute("DELETE FROM events WHERE job_id=? AND state='failed'", (self.key,))
        self.api.s.set_state(self.key, 'needs_attention', {'reason': 'preparation_failed'})
        recovery = dict(self.failure, code='NAVIGATION_PREPARATION_FAILED', automaticReplay=False)
        self.api.s.set_state(self.key, 'failed', recovery)
        self.assertFalse(self.status()['recoverable_preinput_failure'])
        self.api.s.c.execute('UPDATE jobs SET result=? WHERE id=?',
            (json.dumps(dict(recovery, navigationRestored=True)), self.key))
        self.assert_intake_resumes_without_resending_original()

    def assert_intake_resumes_without_resending_original(self):
        loop = self.loop()
        before = self.job()
        self.assertEqual(loop.cycle()['state'], 'failed')
        self.assertEqual(loop.db.execute("SELECT text,reply,state FROM inbox WHERE id='1'").fetchone()[:],
            ('Original frozen body', self.reply, 'failed'))
        self.assertEqual(self.calls, [{'op': 'status', 'server_id': '1'}])
        self.model.complete.assert_not_called()
        loop.close()
        loop = GroupLoop(self.root / 'inbox.sqlite', self.group, self.model, self.io)
        self.addCleanup(loop.close)
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(self.job(), before)
        self.assertEqual([r['server_id'] for r in self.calls if r['op'] == 'submit'], ['2'])
        self.model.complete.assert_called_once()

    def test_unknown_or_cleanup_debt_cannot_resume_intake(self):
        loop = self.loop()
        for state, result in [('unknown', self.failure), ('needs_attention', self.failure),
                ('failed', dict(self.failure, noSend=False)), ('failed', dict(self.failure, sideEffectStarted=True)),
                ('failed', dict(self.failure, navigationRecoveryPending=True))]:
            with self.subTest(state=state, result=result):
                self.api.s.c.execute('UPDATE jobs SET state=?,result=? WHERE id=?',
                    (state, json.dumps(result), self.key))
                self.assertEqual(loop.cycle()['state'], 'attention')
        self.assertTrue(all(r['op'] == 'status' for r in self.calls))
        self.model.complete.assert_not_called()

    def test_missing_or_unsettled_navigation_and_any_input_artifact_stay_blocked(self):
        from operations import navigation
        loop = self.loop()
        nav = navigation.path(self.state, self.job())
        raw = nav.read_bytes()
        nav.unlink()
        self.assertEqual(loop.cycle()['state'], 'attention')
        navigation.save(self.state, self.job(), {'state': 'started'})
        self.assertEqual(loop.cycle()['state'], 'attention')
        nav.write_bytes(raw)
        for suffix in ('composer.json', 'attempt.json', 'execution-check.json', 'step-1.json', 'navigation.tmp'):
            path = self.state / (self.key + '-' + suffix)
            path.write_text('{}')
            try:
                self.assertEqual(loop.cycle()['state'], 'attention', suffix)
            finally:
                path.unlink()
        self.assertTrue(all(r['op'] == 'status' for r in self.calls))

    def test_preview_confirmation_and_changed_cache_or_journal_are_not_clean_proof(self):
        loop = self.loop()
        self.api.s.c.execute('UPDATE jobs SET preview=? WHERE id=?', ('{}', self.key))
        self.assertFalse(self.status()['recoverable_preinput_failure'])
        self.api.s.c.execute('UPDATE jobs SET preview=NULL WHERE id=?', (self.key,))
        self.api.s.event(self.key, 'confirmed')
        self.assertEqual(loop.cycle()['state'], 'attention')
        self.api.s.c.execute("DELETE FROM events WHERE job_id=? AND state='confirmed'", (self.key,))
        with loop.db:
            loop.db.execute("UPDATE inbox SET reply='Changed cached output' WHERE id='1'")
        self.assertEqual(loop.cycle()['state'], 'attention')
        path = self.state / (self.key + '-navigation.json')
        nav = dict(self.nav, peer='other@chatroom')
        path.write_text(json.dumps(nav))
        with self.assertRaises(ValueError):
            self.status()

    def test_status_is_read_only_and_missing_original_is_not_allocated(self):
        def snapshot():
            return {p.name: p.read_bytes() for p in self.state.rglob('*') if p.is_file()}
        before = snapshot()
        self.assertTrue(self.status()['recoverable_preinput_failure'])
        self.assertEqual(snapshot(), before)
        with patch('trigger.group_io.group_info', return_value=self.members):
            with self.assertRaises(KeyError):
                handle(self.installation, self.binding,
                    {'op': 'status', 'server_id': '99', '_binding': token(self.binding)})
        self.assertEqual(snapshot(), before)


if __name__ == '__main__':
    unittest.main()
