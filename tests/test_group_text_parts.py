"""Group replies keep one original receipt across ordered native text parts."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

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

    def test_paragraph_break_precedes_a_later_sentence_break(self):
        first = '甲' * 139 + '。'
        second = '乙' * 129 + '。' + '丙' * 99 + '。'
        self.assertEqual(split_text(first + '\n\n' + second), [first + '\n\n', second])

    def test_long_paragraph_splits_only_after_complete_sentences(self):
        first = '甲' * 198 + '！”'
        second = 'A result with p=0.01 and e.g. Fig. 2 is described here, ' + '乙' * 199 + '。'
        self.assertEqual(split_text(first + ' ' + second), [first, ' ' + second])

    def test_oversized_sentence_and_its_link_stay_whole(self):
        url = 'https://example.org/?source=' + 'x' * 350
        sentence = '文' * 299 + '👩🏽\u200d🔬' + url + '。'
        self.assertEqual(split_text(sentence + '\r\n\r\n结论。'),
                         [sentence + '\r\n\r\n', '结论。'])

    def test_line_break_without_sentence_end_stays_inside_the_bubble(self):
        text = '甲' * 200 + ' \n' + '乙' * 110 + '。'
        self.assertEqual(split_text(text), [text])

    def test_full_budget_and_long_links_do_not_produce_empty_or_excess_parts(self):
        url = 'https://example.org/?q=' + 'x' * 300
        for text in ('a' * 6000, ('a' * 150 + '. ') * 39,
                     ('a' * 100 + '\n' + url + '\n') * 14,
                     ('\n' + url + '\n') * 17, 'a' + ' ' * 5900 + 'b', ' ' * 5900 + 'b'):
            self.assertLessEqual(len(text.encode()), 6000)
            parts = split_text(text)
            self.assertEqual(''.join(parts), text)
            self.assertLessEqual(len(parts), 20)
            self.assertTrue(all(p.strip() for p in parts))
            if url in text:
                self.assertEqual(sum(p.count(url) for p in parts), text.count(url))


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
        self.text = ('甲' * 299 + '。') + ('乙' * 299 + '。') + ('丙' * 79 + '。')
        self.members = {'wxid_fixture_self': 'Self', 'wxid_fixture_owner': 'Owner'}

    def call(self, op, server_id='1', **extra):
        with patch('trigger.group_io.group_info', return_value=self.members):
            return handle(self.installation, self.binding,
                {'op': op, 'server_id': server_id, '_binding': token(self.binding), **extra})

    def jobs(self):
        return self.api.s.list_jobs(CLIENT)

    def accept(self, job, **extra):
        text = job['payload']['text']
        self.api.s.set_state(job['id'], 'succeeded', {'state': 'accepted',
            'textComparison': {'expectedText': text, 'actualText': text}, **extra})

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

    def test_settled_partial_failure_releases_only_the_next_group_request(self):
        from operations import navigation
        from operations.dispatch import choose
        from trigger.group_reply import GroupLoop
        from trigger.reply_io import original_status

        self.call('submit', text=self.text)
        jobs = self.jobs()
        self.accept(jobs[0])
        failed = jobs[1]['id']
        self.api.s.set_state(failed, 'preparing')
        self.api.s.set_state(failed, 'failed', {
            'code': 'SEARCH_SELECTION_UNPROVEN', 'noSend': True, 'sideEffectStarted': False})
        navigation.save(self.api.s.root, self.api.s.by_id(failed), {'state': 'started'})

        def transport(request):
            if request['op'] == 'read':
                return {'events': [{'account': self.binding['account'], 'peer': self.binding['group_peer'],
                    'sender': 'member', 'sender_name': 'Member', 'mentioned': True, 'kind': 1,
                    'text': 'New question?', 'created': 150, 'server_id': '2'}]}
            return self.call(**request)

        group = {'account': self.binding['account'], 'owner_peer': self.binding['owner_peer'],
                 'peer': self.binding['group_peer'], 'name': 'Fixture', 'scope': self.binding['send_scope']}
        model = Mock(backend='local-codex', engineering=False, last_delivery_key='b' * 64)
        model.complete.return_value = {'message': {'content': '{"speak":true,"text":"New reply"}'}}
        loop = GroupLoop(self.root / 'inbox.sqlite', group, model, transport)
        self.addCleanup(loop.close)
        with loop.db:
            loop.save('introduction', 'not_requested')
            loop.db.execute('INSERT INTO inbox(id,created,text,reply,state,desktop_job) VALUES(?,?,?,?,?,?)',
                            ('1', 120, '{}', self.text, 'pending', 'a' * 64))

        next_id = CLIENT + '-' + hashlib.sha256(b'wxid_fixture_self\0fixture@chatroom\0' + b'2').hexdigest()

        def accept_next(api, job, policy):
            self.assertEqual(job['request_id'], next_id)
            self.assertEqual(choose(api.s)['request_id'], next_id)
            self.accept(job)
            return original_status(api, api.s.by_id(job['id']), CLIENT)

        with patch('trigger.group_io.advance', side_effect=accept_next) as advance:
            self.assertEqual(loop.cycle()['state'], 'attention')
            self.assertEqual(loop.cycle()['state'], 'attention')
            model.complete.assert_not_called()
            advance.assert_not_called()
            navigation.save(self.api.s.root, self.api.s.by_id(failed), {'state': 'settled'})
            before = self.jobs()
            self.assertEqual(loop.cycle()['state'], 'failed')
            self.assertEqual(loop.cycle()['state'], 'pending')
            self.assertEqual(loop.cycle()['state'], 'sent')
            advance.assert_called_once()

        self.assertEqual(self.jobs()[:3], before)
        self.assertEqual([job['state'] for job in self.jobs()], ['succeeded', 'failed', 'queued', 'succeeded'])
        self.assertEqual(loop.db.execute('SELECT state,reply FROM inbox WHERE id=?', ('1',)).fetchone()[:],
                         ('failed', self.text))
        model.complete.assert_called_once()
        partial, = [call.args[0] for call in model.publish_delivery.call_args_list if call.args[0]['state'] == 'partial']
        self.assertEqual(partial['native_request_id'], self.rid)
        self.assertEqual(partial['reply_sha256'], hashlib.sha256(self.text.encode()).hexdigest())
        self.assertEqual([part['actual_text'] for part in partial['native_parts']], ['甲' * 299 + '。', None, None])
        self.api.s.cancel(CLIENT, jobs[2]['request_id'])
        self.assertEqual(self.call('status')['native_parts'], partial['native_parts'])

    def test_queued_suffix_with_preparation_history_is_not_proven_unsent(self):
        from operations import navigation
        self.call('submit', text=self.text)
        jobs = self.jobs()
        self.accept(jobs[0])
        failed = jobs[1]['id']
        self.api.s.set_state(failed, 'preparing')
        self.api.s.set_state(failed, 'failed', {
            'code': 'SEARCH_SELECTION_UNPROVEN', 'noSend': True, 'sideEffectStarted': False})
        navigation.save(self.api.s.root, self.api.s.by_id(failed), {'state': 'settled'})
        self.api.s.event(jobs[2]['id'], 'preparing')
        result = self.call('status')
        self.assertEqual(result['outcome'], 'unknown')
        self.assertNotIn('native_parts', result)

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

    def test_group_loop_waits_for_cleanup_then_only_sends_the_next_part(self):
        from trigger.group_reply import GroupLoop
        self.call('submit', text=self.text)
        jobs = self.jobs()
        self.accept(jobs[0], navigationRecoveryPending=True)
        def transport(request):
            if request['op'] == 'read':
                return {'events': []}
            return self.call(request['op'], **({'text': request['text']} if 'text' in request else {}))
        group = {'account': self.binding['account'], 'owner_peer': self.binding['owner_peer'],
                 'peer': self.binding['group_peer'], 'name': 'Fixture', 'scope': self.binding['send_scope']}
        loop = GroupLoop(self.root / 'inbox.sqlite', group, Mock(), transport)
        self.addCleanup(loop.close)
        with loop.db:
            loop.save('introduction', 'not_requested')
            loop.db.execute('INSERT INTO inbox(id,created,text,reply,state) VALUES(?,?,?,?,?)',
                            ('1', 120, '{}', self.text, 'pending'))
        with patch('trigger.group_io.advance') as advance:
            self.assertEqual(loop.cycle()['state'], 'pending')
            advance.assert_not_called()
        self.accept(jobs[0])
        seen = []
        def accept_next(api, job, policy):
            seen.append(job['request_id'])
            self.accept(job)
            return {'state': 'succeeded'}
        with patch('trigger.group_io.advance', side_effect=accept_next):
            self.assertEqual(loop.cycle()['state'], 'pending')
            self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(seen, [j['request_id'] for j in jobs[1:]])

    def test_missing_root_membership_is_never_mistaken_for_a_legacy_sent_reply(self):
        self.call('submit', text=self.text)
        root = self.jobs()[0]
        self.accept(root)
        self.api.s.c.execute('DELETE FROM dispatch_metadata WHERE job_id=?', (root['id'],))
        with self.assertRaises(ValueError):
            self.call('status')

    def test_native_payloads_trim_boundaries_and_receipt_keeps_source(self):
        text = '甲' * 199 + '。 \n\n' + '乙' * 199 + '。  '
        self.call('submit', text=text)
        jobs = self.jobs()
        self.assertEqual([j['payload']['text'] for j in jobs], ['甲' * 199 + '。', '乙' * 199 + '。'])
        self.assertEqual(''.join(j['dispatch']['group_reply_source'] for j in jobs), text)
        for job in jobs:
            self.accept(job)
        result = self.call('status')
        self.assertEqual(result['outcome'], 'sent')
        self.assertEqual(''.join(p['source_text'] for p in result['native_parts']), text)
        self.assertEqual([p['actual_text'] for p in result['native_parts']],
                         ['甲' * 199 + '。', '乙' * 199 + '。'])
        self.assertEqual(result['reply_sha256'], hashlib.sha256(text.encode()).hexdigest())
        with self.assertRaises(ValueError):
            self.call('submit', text=text.rstrip())

    def test_short_reply_with_padding_preserves_original_digest(self):
        text = '  收到。 \n'
        self.call('submit', text=text)
        job, = self.jobs()
        self.assertEqual(job['payload']['text'], '收到。')
        self.assertEqual(job['request_id'], self.rid)
        self.accept(job)
        receipt = self.call('status')
        self.assertEqual(receipt['reply_sha256'], hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(receipt['native_parts'], [
            {'request_id': self.rid, 'expected_text': '收到。', 'actual_text': '收到。', 'source_text': text}])

    def test_existing_bubbles_with_terminal_lf_still_reconcile(self):
        from trigger.group_text import part_id
        chunks = ['甲' * 200 + '\n', '乙' * 200]
        self.api.call({'op': 'admit', 'client': CLIENT, 'batch_id': self.rid, 'ordered': True,
            'items': [{'job': {'client': CLIENT, 'request_id': part_id(self.rid, i),
                'peer': self.binding['group_peer'], 'action': 'send_text', 'payload': {'text': chunk},
                'execution_mode': 'verified_fast'}} for i, chunk in enumerate(chunks)]})
        for job in self.jobs():
            expected = job['payload']['text']
            self.accept(job, textComparison={'expectedText': expected, 'actualText': expected.removesuffix('\n')})
        result = self.call('submit', text=''.join(chunks))
        self.assertEqual(result['outcome'], 'sent')
        self.assertEqual([p['actual_text'] for p in result['native_parts']], ['甲' * 200, '乙' * 200])

    def test_missing_native_part_text_proof_is_not_reported_as_the_full_sent_body(self):
        self.call('submit', text=self.text)
        for job in self.jobs():
            self.api.s.set_state(job['id'], 'succeeded', {'state': 'accepted'})
        result = self.call('status')
        self.assertEqual(result['outcome'], 'unknown')
        self.assertEqual(result['code'], 'GROUP_PART_TEXT_PROOF_MISSING')

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
        native_parts = self.call('status')['native_parts']
        loop.save_delivery.assert_called_once_with('1', 'fixture-desktop', 'sent', self.rid,
            hashlib.sha256(self.text.encode()).hexdigest(), None, native_parts=native_parts, cleanup_pending=False)

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

    def test_full_valid_reply_is_admitted_within_batch_limit(self):
        text = ('a' * 150 + '. ') * 39
        result = self.call('submit', text=text)
        self.assertEqual(result['state'], 'queued')
        self.assertLessEqual(len(self.jobs()), 20)
        self.assertEqual(''.join(j.get('dispatch', {}).get('group_reply_source', j['payload']['text'])
                                 for j in self.jobs()), text)


if __name__ == '__main__':
    unittest.main()
