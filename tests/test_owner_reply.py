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
        if request['op'] == 'status':
            return self.effects.get(key, {'state': 'unknown'})
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

    def test_friend_has_private_reply_without_owner_context_or_tools(self):
        self.owner.update(peer='fixture_friend', scope={'mode': 'friend-private-chat', 'since': 100})
        self.batch['events'] = [
            event(1, peer='fixture_friend', sender='fixture_friend', text='查看记忆'),
            event(2, peer='fixture_friend', sender='fixture_owner'),
            event(3, peer='fixture_friend', sender='fixture_friend', created=99),
        ]
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertFalse(loop.memory_enabled)
        self.assertIsNone(loop.local_codex)
        self.assertFalse(self.model.engineering)
        self.model.reply.assert_called_once_with('查看记忆', [], allow_engineering=False)
        self.assertEqual(list(self.effects), ['1'])

    def test_unknown_blocks_new_messages_and_never_replays(self):
        self.unknown = True
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'attention')
        before = len(self.calls)
        self.assertEqual(loop.cycle()['state'], 'attention')
        self.assertEqual(self.calls[before:], [{'op': 'status', 'server_id': '1'}])
        self.assertEqual(self.model.reply.call_count, 1)

    def test_owner_releases_proven_unsent_original_without_regenerating_it(self):
        self.unknown = True
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'attention')
        frozen = loop.db.execute('SELECT reply FROM inbox WHERE id="1"').fetchone()[0]
        proof = {'state': 'failed', 'outcome': 'not_sent', 'recoverable_preinput_failure': True,
                 'reply_sha256': hashlib.sha256(frozen.encode()).hexdigest()}
        loop.io = Mock(return_value=proof)
        self.assertEqual(loop.cycle()['state'], 'failed')
        loop.io.assert_called_once_with({'op': 'status', 'server_id': '1'})
        self.assertEqual(self.model.reply.call_count, 1)
        self.assertEqual(loop.db.execute('SELECT reply,state FROM inbox WHERE id="1"').fetchone()[:], (frozen, 'failed'))
        self.assertEqual(loop.cycle()['state'], 'idle')

    def test_accepted_original_recovers_only_cleanup_then_releases_inbox(self):
        self.unknown = True
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'attention')
        frozen = loop.db.execute('SELECT reply FROM inbox WHERE id="1"').fetchone()[0]
        proof = {'state': 'succeeded', 'outcome': 'sent', 'cleanup_pending': True,
                 'reply_sha256': hashlib.sha256(frozen.encode()).hexdigest()}
        loop.io = Mock(side_effect=[proof, dict(proof, cleanup_pending=False)])
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual([c.args[0]['op'] for c in loop.io.call_args_list], ['status', 'cleanup'])
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

    def test_failed_image_goes_to_original_codex_turn_not_a_canned_resend(self):
        self.model.backend = 'local-codex'
        self.model.has_original_input.side_effect = [False, True]
        self.model.last_delivery_key = 'a' * 64
        self.model.reply.side_effect = [PublicationPending('original queued'), '这张图读取失败了。']
        self.batch['events'] = [event(kind=3, text='<img aeskey="private-cache-token"/>')]
        image_reads = []

        def io(request):
            if request['op'] == 'image':
                image_reads.append(request['server_id'])
                return {'state': 'media_attention', 'code': 'IMAGE_CANDIDATE_AMBIGUOUS'}
            return self.io(request)

        loop = ReplyLoop(self.path, self.owner, self.model, io)
        self.addCleanup(loop.close)
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.assertEqual(loop.counts(), {'new': 1})
        self.assertFalse(self.effects)
        call = self.model.reply.call_args
        diagnostic = json.loads(call.args[1][-1]['content'])
        self.assertEqual(diagnostic, {'attachment_status': 'unavailable',
            'code': 'IMAGE_CANDIDATE_AMBIGUOUS', 'source_id': '1', 'kind': 'image'})
        self.assertNotIn('private-cache-token', str(call))
        self.assertFalse(call.kwargs['allow_engineering'])
        self.assertEqual(call.kwargs['images'], [])
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(image_reads, ['1'])
        row = loop.db.execute('SELECT * FROM inbox').fetchone()
        self.assertEqual(row['desktop_job'], 'a' * 64)
        self.assertEqual(row['reply'], '这张图读取失败了。')
        self.assertEqual(list(self.effects), ['1'])
        self.assertEqual(loop.cycle()['state'], 'idle')

    def test_new_owner_voice_is_transcribed_once_and_keeps_original_chat_reply(self):
        self.model.backend = 'local-codex'
        self.model.reply.side_effect = [PublicationPending('waiting'), 'Voice reply']
        self.batch['events'] = [event(1, kind=34, text='native-media-xml'),
                                event(2, kind=34, text='', created=110),
                                event(3, kind=34, text='', sender='other')]
        voice = Mock(since=115, return_value='Explain this result')
        loop = self.loop()
        loop.voice = voice
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.assertEqual(loop.cycle()['state'], 'sent')
        voice.assert_called_once_with(self.io, '1', 120)
        self.model.use_request.assert_called_with(['1'])
        self.assertEqual(self.model.reply.call_count, 2)
        for call in self.model.reply.call_args_list:
            self.assertIn('Explain this result', call.args[0])
            self.assertNotIn('native-media-xml', call.args[0])
            self.assertFalse(call.kwargs['allow_engineering'])
        self.assertEqual(list(self.effects), ['1'])

    def test_unavailable_owner_voice_does_not_strand_later_text(self):
        self.model.backend = 'local-codex'
        self.batch = {'events': [event(1, kind=34, text=''), event(2, created=121)]}
        voice = Mock(since=115, return_value='')
        loop = self.loop()
        loop.voice = voice
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.model.reply.assert_not_called()
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(self.model.reply.call_args.args[0], '你好')
        self.assertEqual(self.model.reply.call_count, 1)
        self.assertEqual(list(self.effects), ['1', '2'])

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

    def test_owner_markdown_is_chat_data_and_does_not_grant_tools(self):
        self.model.backend = 'local-codex'
        self.model.has_original_input.return_value = False
        self.batch['events'] = [event(kind=49, document_name='guide.md', text='')]
        from unittest.mock import patch
        part = {'type': 'document', 'name': 'guide.md', 'data': 'fixture'}
        with patch('trigger.owner_reply.document_part', return_value=part):
            self.assertEqual(self.loop().cycle()['state'], 'sent')
        self.assertEqual(self.model.reply.call_args.kwargs['images'], [part])
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

    def test_owner_status_accepts_only_restored_original_preinput_failure(self):
        from operations import navigation, composer
        self.call('submit', server_id='1', text='Frozen reply')
        job = self.api.s.get(CLIENT, request_id('fixture_account', 'fixture_owner', '1'))
        self.api.s.set_state(job['id'], 'preparing')
        self.api.s.set_state(job['id'], 'failed', {'code': 'SEND_PREPARATION_FAILED',
            'noSend': True, 'sideEffectStarted': False})
        job = self.api.s.by_id(job['id'])
        navigation.save(self.api.s.root, job, {'state': 'settled'})
        parked = composer.save(self.api.s.root, job, {'state': 'restored'})
        diagnostic = self.api.s.root / (job['id'] + '-preparation-failure.json')
        diagnostic.write_text(json.dumps({'phase': 'stage-text', 'ownedCleanupVerified': True}))
        diagnostic.chmod(0o600)
        self.assertTrue(self.call('status', server_id='1')['recoverable_preinput_failure'])
        composer.save(self.api.s.root, job, dict(parked, state='parked'))
        self.assertFalse(self.call('status', server_id='1')['recoverable_preinput_failure'])
        self.assertEqual(self.driver.prepares, 0)
        self.assertEqual(self.driver.sent, [])

    def test_failed_image_read_is_settled_before_the_next_reply(self):
        image = self.api.s.submit({'client': 'rsi-vision', 'request_id': 'image', 'peer': 'fixture_owner',
            'action': 'save_attachment', 'payload': {'source_id': '9', 'source_mode': 'inbound', 'representation': 'visible'}})
        failure = {'reason': 'precondition_changed', 'detail': 'Official windows differ.', 'sideEffectStarted': False}
        self.api.s.set_state(image['id'], 'needs_attention', failure)
        self.call('submit', server_id='1', text='收到')
        self.assertEqual(self.call('advance', server_id='1')['outcome'], 'sent')
        settled = self.api.s.by_id(image['id'])
        self.assertEqual(settled['state'], 'failed')
        self.assertEqual((settled['result']['code'], settled['result']['originalFailure']), ('IMAGE_EXPORT_NOT_PROVEN', failure))
        self.assertEqual(self.driver.cleaned, [image['id']])
        self.assertEqual(len(self.driver.sent), 1)

    def test_unsettled_image_read_still_holds_the_queue_without_sending(self):
        image = self.api.s.submit({'client': 'rsi-vision', 'request_id': 'image', 'peer': 'fixture_owner',
            'action': 'save_attachment', 'payload': {'source_id': '9', 'source_mode': 'inbound', 'representation': 'visible'}})
        self.api.s.set_state(image['id'], 'needs_attention', {'reason': 'execution_result_unknown'})
        self.driver.unknown = True
        self.call('submit', server_id='1', text='收到')
        self.assertEqual(self.call('advance', server_id='1')['state'], 'busy')
        self.assertEqual(self.api.s.by_id(image['id'])['state'], 'needs_attention')
        self.assertEqual(self.driver.sent, [])

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

    def test_voice_media_requires_exact_committed_owner_message(self):
        import linux_tool
        message = sqlite3.connect(':memory:')
        media = sqlite3.connect(':memory:')
        self.addCleanup(message.close)
        self.addCleanup(media.close)
        table = 'Msg_' + hashlib.md5(b'fixture_owner').hexdigest()
        message.executescript("CREATE TABLE Name2Id(user_name TEXT);"
            "INSERT INTO Name2Id VALUES('fixture_account'),('fixture_owner');"
            f'CREATE TABLE {table}(server_id,create_time,local_type,real_sender_id);'
            f'INSERT INTO {table} VALUES(10,120,34,2),(11,120,34,1),(12,120,34,2);')
        media.executescript("CREATE TABLE Name2Id(user_name TEXT);"
            "INSERT INTO Name2Id VALUES('fixture_owner'),('other');"
            'CREATE TABLE VoiceInfo(voice_data,chat_name_id,svr_id);')
        raw = b'\x02#!SILK_V3fixture'
        media.executemany('INSERT INTO VoiceInfo VALUES(?,?,?)', [(raw, 1, 10), (raw, 2, 12)])

        @contextlib.contextmanager
        def opened(rel):
            yield (media if rel.endswith('media_0.db') else message), {'consistency': 'committed'}

        with patch.object(linux_tool, 'native', opened):
            result = self.call('voice', server_id='10')
            self.assertEqual(base64.b64decode(result['data']), raw)
            self.assertEqual(result['sha256'], hashlib.sha256(raw).hexdigest())
            with self.assertRaisesRegex(ValueError, 'Original inbound owner voice'):
                self.call('voice', server_id='11')
            self.assertEqual(self.call('voice', server_id='12'), {'state': 'audio_pending'})
            self.owner.update(friend_peer='other', send_scope={'mode': 'friend-private-chat', 'since': 100})
            with self.assertRaisesRegex(ValueError, 'Unsupported owner reply transport fields'):
                self.call('voice', server_id='10')

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
