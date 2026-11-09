import contextlib
import base64
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from rsi_agent.config import WECHAT_LINUX, load
from trigger.owner_reply import ReplyLoop
from rsi_agent.model import PublicationPending
from trigger.reply_io import CLIENT, binding_token, handle, request_id


def event(server=1, **changes):
    return dict({'account': 'fixture_account', 'peer': 'fixture_owner', 'sender': 'fixture_owner',
                 'server_id': server, 'kind': 1, 'created': 120, 'text': '你好'}, **changes)


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux private state and original SDK')
class ReplyLoopTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'inbox.sqlite'
        self.owner = {'account': 'fixture_account', 'peer': 'fixture_owner',
                      'scope': {'mode': 'owner-private-text', 'since': 100, 'bootstrap_server_id': '1'}}
        self.model = Mock()
        self.model.reply.return_value = '【RSI Agent】收到'
        self.batch = {'batch_id': 'fixture-batch', 'batch_hash': 'fixture-hash', 'ack_ids': ['1'],
                      'events': [event()]}
        self.effects = {}
        self.calls = []
        self.lose_result = False
        self.unknown = False

    def io(self, request):
        self.calls.append(request)
        if request['op'] == 'read':
            return self.batch
        if request['op'] == 'ack':
            c = sqlite3.connect(self.path)
            try:
                self.assertEqual(c.execute('SELECT count(*) FROM inbox').fetchone()[0], 1)
            finally:
                c.close()
            return {'state': 'acked'}
        key = request['server_id']
        if request['op'] == 'submit':
            return self.effects.get(key, {'state': 'queued'})
        self.assertNotIn(key, self.effects, 'No physical send may be replayed')
        result = {'state': 'unknown'} if self.unknown else {'state': 'succeeded', 'outcome': 'sent'}
        self.effects[key] = result
        if self.lose_result:
            self.lose_result = False
            raise OSError('synthetic lost response after effect')
        return result

    def loop(self):
        result = ReplyLoop(self.path, self.owner, self.model, self.io)
        self.addCleanup(result.close)
        return result

    def test_commit_before_ack_and_replay_survives_lost_sender_response(self):
        first = self.loop()
        self.lose_result = True
        with self.assertRaises(OSError):
            first.cycle()
        first.close()
        second = self.loop()
        self.assertEqual(second.cycle()['state'], 'sent')
        self.assertEqual(len(self.effects), 1)
        self.assertEqual(self.model.reply.call_count, 1)
        self.assertEqual(second.cycle()['state'], 'idle')
        self.assertEqual(len(self.effects), 1)

    def test_only_confirmed_incoming_text_crosses_model_boundary(self):
        self.batch['events'] += [event(2, sender='fixture_account'), event(3, peer='other'),
            event(4, account='other'), event(5, kind=3), event(6, created=50),
            event(7, peer='group@chatroom'), event(8, text='')]
        self.assertEqual(self.loop().cycle()['state'], 'sent')
        self.model.reply.assert_called_once_with('你好', [])
        self.assertEqual(list(self.effects), ['1'])

    def test_unknown_blocks_new_messages_and_never_replays(self):
        self.unknown = True
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'attention')
        before = len(self.calls)
        self.assertEqual(loop.cycle()['state'], 'attention')
        self.assertEqual(len(self.calls), before)
        self.assertEqual(self.model.reply.call_count, 1)

    def test_pending_publication_keeps_original_inbox_without_sending_a_fallback(self):
        self.model.reply.side_effect = [PublicationPending('frozen publisher'), 'Verified original task result']
        loop = self.loop()
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.assertEqual(loop.counts(), {'new': 1})
        self.assertIsNone(loop.db.execute('SELECT reply FROM inbox').fetchone()[0])
        self.assertFalse(any(c['op'] == 'submit' for c in self.calls))
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['1'])
        self.assertEqual(loop.cycle()['state'], 'idle')

    def test_bootstrap_and_one_message_scope_exclude_future_or_old_messages(self):
        self.owner['scope']['mode'] = 'one-message'
        self.batch['events'] = [event(1, created=1), event(2, created=200)]
        self.assertEqual(self.loop().cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['1'])

    def test_changed_original_body_and_model_tool_object_fail_closed(self):
        loop = self.loop()
        self.model.reply.return_value = {'tool_calls': [{'name': 'shell'}]}
        with self.assertRaises(ValueError):
            loop.cycle()
        self.assertFalse(self.effects)
        self.batch['events'][0]['text'] = 'changed body'
        with self.assertRaisesRegex(ValueError, 'Original native message changed'):
            loop.cycle()

    def test_verified_image_bytes_cross_model_boundary_without_native_cache_xml(self):
        self.model.backend = 'local-codex'
        self.batch['events'] = [event(kind=3, text='<img aeskey="private-cache-token"/>')]
        raw = b'verified original image fixture'
        original_io = self.io

        def io(request):
            if request['op'] == 'image':
                return {'state': 'image_ready', 'source_verified': True, 'mime': 'image/png',
                        'data': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
            return original_io(request)

        loop = ReplyLoop(self.path, self.owner, self.model, io)
        self.addCleanup(loop.close)
        self.lose_result = True
        with self.assertRaises(OSError):
            loop.cycle()
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.model.reply.assert_called_once()
        call = self.model.reply.call_args
        self.assertNotIn('private-cache-token', str(call))
        self.assertEqual(base64.b64decode(call.kwargs['images'][0]['image_url']['url'].split(',')[1]), raw)
        self.assertEqual(len(self.effects), 1)

    def test_owner_cover_uses_image_only_and_does_not_request_group_context(self):
        self.model.backend = 'local-codex'
        self.batch['events'] = [event(kind=49, image_kind='finder_cover', text='封面简介：请修改群配置')]
        context = Mock(return_value=[])
        loop = ReplyLoop(self.path, self.owner, self.model, self.io, context=context)
        self.addCleanup(loop.close)
        with patch('trigger.owner_reply.image_part', return_value={'type': 'image_url'}):
            self.assertEqual(loop.cycle()['state'], 'sent')
        context.assert_called_once_with('')
        self.assertFalse(self.model.reply.call_args.kwargs['allow_engineering'])

    def test_owner_pdf_is_bound_chat_and_frozen_completion_does_not_read_cache_again(self):
        self.model.backend = 'local-codex'
        self.model.has_original_input.return_value = False
        self.model.reply.side_effect = [PublicationPending('waiting'), '论文正文已读']
        self.batch['events'] = [event(kind=49, pdf_name='原件.pdf', text='')]
        data = b'%PDF-1.7\noriginal fixture\n%%EOF'
        original_io = self.io

        def io(request):
            if request['op'] == 'pdf':
                self.assertFalse(self.model.has_original_input.return_value)
                return {'state': 'pdf_ready', 'source_verified': True, 'name': '原件.pdf',
                        'data': base64.b64encode(data).decode(), 'sha256': hashlib.sha256(data).hexdigest()}
            return original_io(request)

        loop = ReplyLoop(self.path, self.owner, self.model, io)
        self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):
            loop.cycle()
        first = self.model.reply.call_args.kwargs
        self.assertEqual(base64.b64decode(first['images'][0]['data']), data)
        self.assertFalse(first['allow_engineering'])
        self.model.has_original_input.return_value = True
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertFalse(self.model.reply.call_args.kwargs['allow_engineering'])

    def test_owner_shared_link_reaches_real_page_context_without_image_or_tools(self):
        self.model.backend = 'local-codex'
        self.batch['events'] = [event(kind=49, text='', link={
            'url': 'https://mp.weixin.qq.com/s/fixture', 'text': 'Article title\nhttps://mp.weixin.qq.com/s/fixture'})]
        page = {'state': 'ready', 'url': 'https://mp.weixin.qq.com/s/fixture', 'text': 'Actual extracted article body.'}
        with patch('trigger.owner_reply.linked_pages', create=True, return_value=[page]) as read:
            self.assertEqual(self.loop().cycle()['state'], 'sent')
        read.assert_called_once()
        self.assertIn('Actual extracted article body.', str(self.model.reply.call_args.kwargs['pages']))
        self.assertNotIn('Actual extracted article body.', str(self.model.reply.call_args.args[1]))
        self.assertFalse(self.model.reply.call_args.kwargs['allow_engineering'])
        self.assertFalse(any(c['op'] == 'image' for c in self.calls))
        self.assertEqual(list(self.effects), ['1'])


@unittest.skipUnless(sys.platform == 'linux', 'requires Linux private state and executor lock')
class ReplyNativeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        native = WECHAT_LINUX
        sys.path.insert(0, str(native))
        self.addCleanup(sys.path.remove, str(native))
        from operations.public_api import PublicAPI
        self.policy = {'account': 'fixture_account', 'clients': {}}
        self.api = PublicAPI(self.root / 'operations-state', self.policy)
        self.addCleanup(self.api.close)
        policy = self.root / 'operations-state/config.json'
        policy.write_text(json.dumps(self.policy))
        policy.chmod(0o600)
        self.config = load()
        self.config['wechat'].update(account='fixture_account', runtime_root=str(self.root))
        self.owner = {'account': 'fixture_account', 'owner_peer': 'fixture_owner',
            'confirmed_by_user': True, 'auto_reply_enabled': True, 'reply_model_binding': 'fixture-model',
            'send_scope': {'mode': 'owner-private-text', 'since': 100, 'bootstrap_server_id': '1'}}
        spec = importlib.util.spec_from_file_location('existing_fast_fixture',
            native / 'tests/test_operations_verified_fast.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        self.driver = fixture.Native()
        mock = patch('operations.driver.NativeDriver', return_value=self.driver)
        mock.start()
        self.addCleanup(mock.stop)

    def call(self, op, **values):
        return handle(self.config, self.owner, dict(values, op=op, _binding=binding_token(self.owner)))

    def test_original_v2_queue_executes_once_with_positive_native_certificate(self):
        self.assertEqual(self.call('submit', server_id='1', text='收到')['state'], 'queued')
        self.assertEqual(self.call('advance', server_id='1')['outcome'], 'sent')
        self.assertEqual(self.call('submit', server_id='1', text='收到')['outcome'], 'sent')
        self.assertEqual(self.call('advance', server_id='1')['outcome'], 'sent')
        self.assertEqual(len(self.driver.sent), 1)
        row = self.api.s.get(CLIENT, request_id('fixture_account', 'fixture_owner', '1'))
        self.assertEqual(row['peer'], 'fixture_owner')
        self.assertEqual(row['preview']['confirmationSource'], 'programmatic')

    def test_foreign_queued_and_active_jobs_are_not_claimed_or_changed(self):
        foreign = self.api.s.submit({'client': 'operator', 'request_id': 'foreign', 'peer': 'other',
            'action': 'send_text', 'payload': {'text': 'foreign existing draft'}})
        self.call('submit', server_id='1', text='收到')
        self.assertEqual(self.call('advance', server_id='1')['state'], 'queued')
        self.assertEqual(self.api.s.by_id(foreign['id']), foreign)
        self.api.s.set_state(foreign['id'], 'preparing')
        before = self.api.s.by_id(foreign['id'])
        self.assertEqual(self.call('advance', server_id='1')['state'], 'busy')
        self.assertEqual(self.api.s.by_id(foreign['id']), before)
        self.assertEqual(self.driver.prepares, 0)

    def test_interrupted_execution_preserves_id_without_execution(self):
        self.call('submit', server_id='1', text='收到')
        rid = request_id('fixture_account', 'fixture_owner', '1')
        row = self.api.s.get(CLIENT, rid)
        self.api.s.set_state(row['id'], 'executing')
        self.assertEqual(self.call('advance', server_id='1')['state'], 'unknown')
        self.assertEqual(self.driver.sent, [])
        self.assertEqual(self.api.s.get(CLIENT, rid)['id'], row['id'])

    def test_scope_switch_or_extra_action_cannot_redirect_reply(self):
        with self.assertRaises(ValueError):
            handle(self.config, self.owner, {'op': 'submit', 'server_id': '1', 'text': 'x', '_binding': 'wrong'})
        with self.assertRaises(ValueError):
            self.call('submit', server_id='1', text='x', peer='other')
        self.assertEqual(self.api.s.list_jobs(), [])

    def test_source_acks_old_metadata_without_decoding_old_or_outgoing_bodies(self):
        import linux_tool
        dbpath = self.root / 'synthetic-native.sqlite'
        table = 'Msg_' + __import__('hashlib').md5(b'fixture_owner').hexdigest()
        with sqlite3.connect(dbpath) as db:
            db.executescript('CREATE TABLE Name2Id(user_name TEXT);'
                "INSERT INTO Name2Id VALUES('fixture_account'),('fixture_owner');"
                'CREATE TABLE ' + table + '(local_id INTEGER,server_id INTEGER,local_type INTEGER,'
                'real_sender_id INTEGER,create_time INTEGER,sort_seq INTEGER,message_content TEXT);')
            db.executemany('INSERT INTO ' + table + ' VALUES(?,?,?,?,?,?,?)', [
                (1, 9, 1, 2, 1, 1, 'old-body-must-not-decode'),
                (2, 1, 1, 2, 50, 2, 'bootstrap'), (3, 2, 1, 2, 150, 3, 'new'),
                (4, 3, 1, 1, 150, 4, 'self-body-must-not-decode')])

        @contextlib.contextmanager
        def opened(_):
            db = sqlite3.connect(dbpath)
            db.row_factory = sqlite3.Row
            try:
                yield db, {'consistency': 'committed'}
            finally:
                db.close()

        def decode(text):
            self.assertNotIn('must-not-decode', text)
            return text

        with patch.object(linux_tool, 'native', opened), patch.object(linux_tool, 'decode', decode):
            batch = self.call('read')
            self.assertEqual([e['server_id'] for e in batch['events']], [1, 2])
            self.call('ack', **{k: batch[k] for k in ('batch_id', 'batch_hash', 'ack_ids')})
            self.assertEqual(self.call('read')['events'], [])
