"""Offline rejection tests cover symlinks, oversized inputs, and identity conflicts."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest

if importlib.util.find_spec('bridge.store'):
    from bridge.store import Store
else:
    Store = None


def message(mid='123', text='秘书：你好', **kw):
    value = dict(message_id=mid, from_user_id='peer', to_user_id='account',
                 message_type=1, message_state=2,
                 item_list=[{'type': 1, 'text_item': {'text': text}}], context_token='ctx')
    value.update(kw)
    return value


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Store, 'Store implementation is required')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / 'private' / 'queue.db'
        self.store = Store(self.path, 'account', 'peer')
        self.addCleanup(self.store.close)

    def test_reject_symlink_database_and_parent(self):
        other = Path(self.tmp.name).resolve() / 'other.db'
        other.write_text('untouched')
        link = Path(self.tmp.name).resolve() / 'linked.db'
        link.symlink_to(other)
        with self.assertRaises(ValueError):
            Store(link, 'account', 'peer')
        parent = Path(self.tmp.name).resolve() / 'linkdir'
        parent.symlink_to(self.path.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            Store(parent / 'second.db', 'account', 'peer')
        self.assertEqual(other.read_text(), 'untouched')

    def test_reject_oversized_input_atomically(self):
        self.store.ingest([], 'old')
        for messages in ([message()] * 501, [message(text='秘书：' + 'x' * 32769)],
                         [message(extra='x' * (4 * 1024 * 1024))]):
            with self.assertRaises(ValueError):
                self.store.ingest(messages, 'new')
            self.assertEqual(self.store.cursor(), 'old')
            self.assertIsNone(self.store.claim_job())

    def test_binding_filters_and_context_refresh(self):
        rows = [message('own', from_user_id='account'), message('foreign', from_user_id='other'),
                message('wrongto', to_user_id='other'), message('bot', message_type=2),
                message('partial', message_state=1), message('blank', text='hello'),
                message(None), message('group', group_id='group')]
        self.store.ingest(rows, 'cursor1')
        self.assertIsNone(self.store.claim_job())
        self.assertEqual(self.store.context(), 'ctx')
        self.store.ingest([message('plain2', text='ordinary', context_token='fresh')], 'cursor2')
        self.assertEqual(self.store.context(), 'fresh')
        self.assertEqual(self.store.cursor(), 'cursor2')

    def test_boolean_protocol_enums_do_not_trigger(self):
        self.store.ingest([message('booltype', message_type=True),
                           message('boolitem', item_list=[{'type': True, 'text_item': {'text': '秘书：bad'}}])], 'c')
        self.assertIsNone(self.store.claim_job())

    def test_invalid_unicode_rejected_without_advancing_cursor(self):
        with self.assertRaises(ValueError):
            self.store.ingest([message(text='秘书：' + chr(0xd800))], 'bad')
        self.assertEqual(self.store.cursor(), '')

    def test_bare_keyword_and_whitespace_trigger_without_substring_matching(self):
        cases = [('秘书', '秘书'), ('  秘书  ', '秘书'), ('/secretary', '/secretary'),
                 ('  秘书：你好  ', '你好'), ('秘书: hello', 'hello'),
                 ('  /secretary hello  ', 'hello'), ('秘书：', '秘书'), ('秘书:   ', '秘书'),
                 ('引用秘书：你好', None), ('我的秘书今天休息', None), ('/secretaryish', None)]
        for index, (text, expected) in enumerate(cases):
            self.store.ingest([message(str(index), text)], str(index))
            job = self.store.claim_job()
            if expected is None:
                self.assertIsNone(job, text)
            else:
                self.assertIsNotNone(job, text)
                self.assertEqual(job['text'], expected)
                self.store.fail_job(job['id'], 'test fixture finished')

    def test_recheck_trigger_is_explicit_and_idempotent(self):
        self.assertTrue(callable(getattr(self.store, 'recheck_trigger', None)))
        self.store.ingest([message('old', '秘书'), message('plain', '普通句子')], 'c')
        # Reproduce a message persisted by the earlier prefix-only parser.
        self.store.db.execute("DELETE FROM jobs WHERE id='old'")
        result = self.store.recheck_trigger('old')
        self.assertEqual((result['id'], result['text'], result['status']), ('old', '秘书', 'pending'))
        self.assertEqual(self.store.recheck_trigger('old'), result)
        self.assertIsNone(self.store.recheck_trigger('plain'))
        with self.assertRaises(ValueError):
            self.store.recheck_trigger('missing')
        job = self.store.claim_job()
        self.assertEqual(job['id'], 'old')
        self.assertEqual(self.store.recheck_trigger('old')['status'], 'running')
        self.assertIsNone(self.store.claim_job())
        self.assertEqual(self.store.cursor(), 'c')

    def test_keyword_job_is_idempotent_and_conflict_never_reexecutes(self):
        self.store.ingest([message()], 'c1')
        self.store.ingest([message()], 'c2')
        job = self.store.claim_job()
        self.assertEqual((job['id'], job['text'], job['status'], job['attempts']),
                         ('123', '你好', 'running', 1))
        self.store.ingest([message(text='秘书：different')], 'c3')
        self.assertIsNone(self.store.claim_job())
        self.assertEqual(self.store.snapshot()['conflicts'], 1)
        self.assertEqual(self.store.cursor(), 'c3')

    def test_completion_atomically_enqueues_single_reply(self):
        self.store.ingest([message()], 'c')
        job = self.store.claim_job()
        self.store.complete_job(job['id'], 'answer')
        self.store.complete_job(job['id'], 'answer')
        with self.assertRaises(ValueError):
            self.store.complete_job(job['id'], 'different')
        out = self.store.claim_outbox()
        self.assertEqual(out['text'], 'answer')
        self.assertEqual(out['kind'], 'text')
        self.assertTrue(out['client_id'])
        self.assertIsNone(self.store.claim_outbox())
        self.assertEqual(self.store.snapshot()['jobs'], {'completed': 1})

    def test_request_id_content_conflicts(self):
        one = self.store.enqueue_text('one', 'request')
        two = self.store.enqueue_text('one', 'request')
        self.assertEqual(one['client_id'], two['client_id'])
        with self.assertRaises(ValueError):
            self.store.enqueue_text('two', 'request')
        for text, rid in [('', 'x'), ('ok', ''), ('ok', 'x' * 513), ('x' * 32769, 'x')]:
            with self.assertRaises(ValueError):
                self.store.enqueue_text(text, rid)

    def test_image_metadata_is_fixed_and_file_must_exist(self):
        image = Path(self.tmp.name).resolve() / 'image.png'
        image.write_bytes(b'fake-image-test-only')
        out = self.store.enqueue_image(image, 'image')
        self.assertEqual(out['kind'], 'image')
        self.assertEqual(out['size'], image.stat().st_size)
        self.assertEqual(len(out['sha256']), 64)
        image.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.store.enqueue_image(image, 'image')
        with self.assertRaises(ValueError):
            self.store.enqueue_image(image.parent / 'missing', 'missing')

    def test_fifo_image_rejected_without_blocking(self):
        fifo = self.path.parent / 'fifo'
        os.mkfifo(fifo, 0o600)
        script = ("from bridge.store import Store; import sys; "
                  "s=Store(sys.argv[1], 'account', 'peer'); "
                  "s.enqueue_image(sys.argv[2], 'fifo')")
        try:
            result = subprocess.run([sys.executable, '-c', script, str(self.path), str(fifo)],
                                    capture_output=True, timeout=1)
        except subprocess.TimeoutExpired:
            self.fail('opening a FIFO must not block')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'ValueError', result.stderr)

    def test_cursor_bound_is_65536_bytes_and_atomic(self):
        self.store.ingest([], '界' * 21845 + 'x')
        old = self.store.cursor()
        for cursor in ('界' * 21846, 'x' * 65537, 'bad' + chr(0)):
            with self.assertRaises(ValueError):
                self.store.ingest([message()], cursor)
            self.assertEqual(self.store.cursor(), old)
            self.assertIsNone(self.store.claim_job())

    def test_context_bound_is_16384_bytes_and_atomic(self):
        self.store.ingest([message('old', text='ordinary', context_token='界' * 5461 + 'x')], 'old')
        old_context = self.store.context()
        for token in ('界' * 5462, 'x' * 16385, 'bad' + chr(0)):
            with self.assertRaises(ValueError):
                self.store.ingest([message(), message('new', context_token=token)], 'new')
            self.assertEqual(self.store.cursor(), 'old')
            self.assertEqual(self.store.context(), old_context)
            self.assertIsNone(self.store.claim_job())

    def test_image_bound_is_eight_million_bytes(self):
        image = self.path.parent / 'image.png'
        with image.open('wb') as handle:
            handle.truncate(8_000_000)
        self.assertEqual(self.store.enqueue_image(image, 'exact')['size'], 8_000_000)
        before = self.store.snapshot()
        with image.open('ab') as handle:
            handle.write(b'x')
        with self.assertRaises(ValueError):
            self.store.enqueue_image(image, 'over')
        self.assertEqual(self.store.snapshot(), before)

    def test_acknowledge_preserves_receipt_and_never_requeues(self):
        self.assertTrue(callable(getattr(self.store, 'acknowledge_delivery', None)))
        for status in ('unknown', 'accepted'):
            self.store.enqueue_text('delivered', 'ack-' + status)
            out = self.store.claim_outbox()
            old_receipt = {'transport': 'response', 'ret': None}
            self.store.finish_outbox(out['id'], status, old_receipt)
            result = self.store.acknowledge_delivery(out['id'], 'User confirmed on phone')
            self.assertEqual(result['status'], 'accepted')
            receipt = json.loads(self.store.db.execute('SELECT receipt FROM outbox WHERE id=?', (out['id'],)).fetchone()[0])
            self.assertEqual(receipt, {'phone_delivery_verified': True,
                                      'evidence': 'User confirmed on phone',
                                      'previous_status': status, 'previous_receipt': old_receipt})
            repeated = self.store.acknowledge_delivery(out['id'], 'User confirmed on phone')
            self.assertEqual(repeated, result)
            self.assertIsNone(self.store.claim_outbox())

    def test_acknowledge_rejects_invalid_states_evidence_and_conflicts(self):
        self.assertTrue(callable(getattr(self.store, 'acknowledge_delivery', None)))
        out = self.store.enqueue_text('pending', 'ack-invalid')
        with self.assertRaises(ValueError):
            self.store.acknowledge_delivery(out['id'], 'phone')
        self.store.claim_outbox()
        with self.assertRaises(ValueError):
            self.store.acknowledge_delivery(out['id'], 'phone')
        self.store.finish_outbox(out['id'], 'failed', {})
        with self.assertRaises(ValueError):
            self.store.acknowledge_delivery(out['id'], 'phone')
        with self.assertRaises(ValueError):
            self.store.acknowledge_delivery(99999, 'phone')
        self.store.enqueue_text('unknown', 'ack-valid')
        out = self.store.claim_outbox()
        self.store.finish_outbox(out['id'], 'unknown', None)
        for evidence in ('', 'x' * 4097, 'bad' + chr(0), {'text': 'phone'}):
            with self.assertRaises(ValueError):
                self.store.acknowledge_delivery(out['id'], evidence)
        self.assertEqual(self.store.snapshot()['outbox']['unknown'], 1)
        self.store.acknowledge_delivery(out['id'], 'phone')
        with self.assertRaises(ValueError):
            self.store.acknowledge_delivery(out['id'], 'different evidence')

    def test_unknown_and_failed_sends_never_replayed(self):
        for state in ('accepted', 'unknown', 'failed'):
            self.store.enqueue_text(state, state)
            out = self.store.claim_outbox()
            self.store.finish_outbox(out['id'], state, {'message_id': 'receipt'})
        self.store.recover_running()
        self.assertIsNone(self.store.claim_outbox())
        self.assertEqual(self.store.snapshot()['outbox'], {'accepted': 1, 'failed': 1, 'unknown': 1})

    def test_recovery_requires_explicit_worker_call_and_caps_generation_retries(self):
        self.store.ingest([message()], 'c')
        self.store.enqueue_text('out', 'r')
        self.store.claim_outbox()
        for attempt in range(1, 4):
            job = self.store.claim_job()
            self.assertEqual(job['attempts'], attempt)
            second = Store(self.path, 'account', 'peer')
            self.assertIsNone(second.claim_job())
            second.close()
            self.store.recover_running()
        self.assertIsNone(self.store.claim_job())
        self.assertIsNone(self.store.claim_outbox())
        self.assertEqual(self.store.snapshot()['jobs'], {'failed': 1})
        self.assertEqual(self.store.snapshot()['outbox'], {'unknown': 1})

    def test_all_messages_opt_in_keeps_auth_and_prefix_boundaries(self):
        all_store = Store(self.path.parent / 'all.db', 'account', 'peer', all_messages=True)
        self.addCleanup(all_store.close)
        all_store.ingest([message('plain', '  ordinary text  '),
                          message('prefix', '秘书：trimmed prompt'),
                          message('empty', '   '),
                          message('image', item_list=[{'type': 2, 'image_item': {'media': 'x'}}]),
                          message('foreign', 'plain foreign', from_user_id='other'),
                          message('incomplete', 'partial', message_state=1)], 'c')
        one = all_store.claim_job()
        two = all_store.claim_job()
        self.assertEqual((one['id'], one['text']), ('plain', '  ordinary text  '))
        self.assertEqual((two['id'], two['text']), ('prefix', '秘书：trimmed prompt'))
        self.assertEqual(all_store.claim_job()['text'], '   ')
        self.assertEqual(all_store.claim_job()['id'], 'image')
        self.assertIsNone(all_store.claim_job())
        self.store.ingest([message('default-plain', 'ordinary text')], 'd')
        self.assertIsNone(self.store.claim_job())
        with self.assertRaises(ValueError):
            Store(self.path.parent / 'invalid.db', 'account', 'peer', all_messages='true')

    def test_media_only_messages_trigger_and_items_remain_bound(self):
        s=Store(self.path.parent/'media.db','account','peer',all_messages=True)
        self.addCleanup(s.close)
        for index,item in enumerate([
            {'type':2,'image_item':{'media':{'encrypt_query_param':'private'}}},
            {'type':3,'voice_item':{'text':'明天提醒我'}},
            {'type':4,'file_item':{'file_name':'../../data.txt'}},
            {'type':99,'future_item':{'unknown':True}},
        ]):
            mid='media'+str(index)
            s.ingest([message(mid,item_list=[item])],mid)
            job=s.claim_job();self.assertEqual(job['id'],mid)
            self.assertEqual(job['text'],'')
            self.assertEqual(s.message_items(mid),[item])
            s.fail_job(mid,'fixture')
        s.ingest([message('foreign-media',from_user_id='other',item_list=[{'type':2}])],'c')
        self.assertIsNone(s.claim_job())
        with self.assertRaises(ValueError):s.message_items('foreign-media')

    def test_media_recheck_preserves_completed_and_rejects_changed_id(self):
        s=Store(self.path.parent/'media2.db','account','peer',all_messages=True)
        self.addCleanup(s.close)
        original=message('m',item_list=[{'type':2,'image_item':{'aeskey':'original'}}])
        s.ingest([original],'1');job=s.claim_job();s.complete_job(job['id'],'done')
        s.ingest([message('m',item_list=[{'type':2,'image_item':{'aeskey':'changed'}}])],'2')
        self.assertEqual(s.snapshot()['conflicts'],1)
        self.assertEqual(s.recheck_trigger('m')['status'],'completed')
        self.assertEqual(s.message_items('m'),original['item_list'])
        self.assertIsNone(s.claim_job())

    def test_media_boolean_and_empty_items_do_not_trigger(self):
        s=Store(self.path.parent/'media3.db','account','peer',all_messages=True)
        self.addCleanup(s.close)
        s.ingest([message('bool',item_list=[{'type':True,'image_item':{}}]),message('empty',item_list=[])],'1')
        self.assertIsNone(s.claim_job())

    def test_defer_waiting_does_not_exhaust_attempts_or_recovery(self):
        self.assertTrue(callable(getattr(self.store, 'defer_job', None)))
        self.store.ingest([message()], 'c')
        for _ in range(5):
            job = self.store.claim_job()
            self.assertEqual(job['attempts'], 1)
            self.store.defer_job(job['id'])
            self.store.defer_job(job['id'])
            self.store.recover_running()
        job = self.store.claim_job()
        self.assertEqual(job['attempts'], 1)
        self.store.fail_job(job['id'], 'execution failure', retryable=True)
        job = self.store.claim_job()
        self.assertEqual(job['attempts'], 2)
        self.store.defer_job(job['id'], 'native thread busy')
        job = self.store.claim_job()
        self.assertEqual(job['attempts'], 2)
        self.store.complete_job(job['id'], 'done')
        with self.assertRaises(ValueError):
            self.store.defer_job(job['id'])

    def test_defer_rejects_invalid_reason_and_missing_job(self):
        self.assertTrue(callable(getattr(self.store, 'defer_job', None)))
        self.store.ingest([message()], 'c')
        job = self.store.claim_job()
        for reason in ('', 'x' * 4097, 'bad' + chr(0), None):
            with self.assertRaises(ValueError):
                self.store.defer_job(job['id'], reason)
        self.assertEqual(self.store.snapshot()['jobs'], {'running': 1})
        with self.assertRaises(ValueError):
            self.store.defer_job('missing')

    def test_fail_job_retryability(self):
        self.store.ingest([message()], 'c')
        for attempt in range(1, 4):
            job = self.store.claim_job()
            self.assertEqual(job['attempts'], attempt)
            self.store.fail_job(job['id'], 'failed', retryable=True)
        self.assertIsNone(self.store.claim_job())
        self.store.ingest([message('nonretry')], 'c2')
        job = self.store.claim_job()
        self.store.fail_job(job['id'], 'failed')
        self.assertIsNone(self.store.claim_job())

    def test_private_files_bound_identity_and_redacted_snapshot(self):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.store.ingest([message(text='秘书：SUPER-PRIVATE', context_token='SECRET-TOKEN')], 'SECRET-CURSOR')
        snap = repr(self.store.snapshot())
        for secret in ('SUPER-PRIVATE', 'SECRET-TOKEN', 'SECRET-CURSOR', 'peer', 'account'):
            self.assertNotIn(secret, snap)
        with self.assertRaises(ValueError):
            Store(self.path, 'account', 'other')

    def test_dialogue_before_job_excludes_current_and_future(self):
        self.store.ingest([message('first', '秘书：FIRST'),
                           message('second', '秘书：SECOND'),
                           message('third', '秘书：FIRST')], 'batch')
        first = self.store.claim_job()
        self.assertEqual(first['id'], 'first')
        self.assertEqual(self.store.recent_dialogue(before_job_id='first'), [])
        self.store.complete_job(first['id'], 'FIRST REPLY')
        out = self.store.claim_outbox()
        self.store.finish_outbox(out['id'], 'accepted', {})
        self.assertEqual(self.store.recent_dialogue(before_job_id='second'), [
            {'role': 'user', 'content': 'FIRST'},
            {'role': 'assistant', 'content': 'FIRST REPLY'}])
        self.assertEqual(self.store.recent_dialogue(before_job_id='third'), [
            {'role': 'user', 'content': 'FIRST'},
            {'role': 'assistant', 'content': 'FIRST REPLY'},
            {'role': 'user', 'content': 'SECOND'}])
        self.assertEqual(self.store.recent_dialogue(limit=1, before_job_id='third'), [
            {'role': 'user', 'content': 'SECOND'}])
        self.assertEqual(self.store.recent_dialogue()[-1], {'role': 'user', 'content': 'FIRST'})
        with self.assertRaises(ValueError):
            self.store.recent_dialogue(before_job_id='does-not-exist')

    def test_dialogue_contains_only_trigger_and_accepted_reply(self):
        self.store.ingest([message('normal', 'hidden ordinary text'), message()], 'c')
        self.store.complete_job(self.store.claim_job()['id'], 'answer')
        self.assertEqual(self.store.recent_dialogue(), [{'role': 'user', 'content': '你好'}])
        out = self.store.claim_outbox()
        self.store.finish_outbox(out['id'], 'accepted', {})
        self.assertEqual(self.store.recent_dialogue(), [
            {'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': 'answer'}])


if __name__ == '__main__':
    unittest.main()
