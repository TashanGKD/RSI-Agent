import contextlib
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from rsi_agent.group_context import FACTS, owner_context
from rsi_agent.group_io import mentioned, read_group
from rsi_agent.group_reply import GroupLoop
from rsi_agent.config import WORKBENCH
from rsi_agent.model import PublicationPending


@unittest.skipUnless(sys.platform == 'linux', 'requires private Linux state')
class GroupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'inbox.sqlite'
        self.group = {'account': 'self', 'peer': 'invited@chatroom', 'name': 'Fixture group',
                      'scope': {'mode': 'invited-group-text', 'since': 100}}
        self.model = Mock()
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"有用的补充"}'}}
        self.batch = {'batch_id': 'batch', 'batch_hash': 'hash', 'ack_ids': ['1'], 'context': [],
            'events': [self.event()]}
        self.effects, self.calls = {}, []
        self.lose_result, self.unknown = False, False

    def event(self, server=1, **changes):
        return dict({'account': 'self', 'peer': 'invited@chatroom', 'sender': 'member',
            'sender_name': 'Member', 'text': 'RSI 请补充一下？', 'mentioned': True,
            'kind': 1, 'created': 120, 'server_id': server}, **changes)

    def io(self, request):
        self.calls.append(request)
        if request['op'] == 'read':
            return self.batch
        if request['op'] == 'ack':
            with sqlite3.connect(self.path) as db:
                self.assertGreater(db.execute('SELECT count(*) FROM inbox').fetchone()[0], 0)
            return {'state': 'acked'}
        key = request['server_id']
        if request['op'] == 'status':
            return self.effects[key]
        if request['op'] == 'submit':
            return self.effects.get(key, {'state': 'queued'})
        self.assertNotIn(key, self.effects)
        result = {'state': 'unknown'} if self.unknown else {'state': 'succeeded', 'outcome': 'sent'}
        self.effects[key] = result
        if self.lose_result:
            self.lose_result = False
            raise OSError('lost response after physical send')
        return result

    def loop(self, introduction=False):
        result = GroupLoop(self.path, self.group, self.model, self.io)
        self.addCleanup(result.close)
        if not introduction:
            with result.db:
                result.save('introduction', 'sent')
        return result

    def test_cached_batch_reply_survives_lost_response_and_restart(self):
        self.batch['events'].append(self.event(2, text='还有一个问题？'))
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.lose_result = True
        with self.assertRaises(OSError):
            loop.cycle()
        loop.close()
        second = self.loop()
        self.assertEqual(second.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['2'])
        self.assertEqual(self.model.complete.call_count, 1)
        self.assertEqual(second.counts(), {'quiet': 1, 'sent': 1})
        self.assertEqual(second.cycle()['state'], 'idle')

    def test_quiet_decision_never_submits(self):
        self.model.complete.return_value = {'message': {'content': '{"speak":false,"text":""}'}}
        self.assertEqual(self.loop().cycle()['state'], 'quiet')
        self.assertFalse(self.effects)
        self.assertFalse(any(c['op'] == 'submit' for c in self.calls))

    def test_trigger_gate_silences_ambient_chat_before_codex(self):
        self.batch['events'] = [self.event(text='收到，谢谢。', mentioned=False)]
        loop = self.loop()
        loop.reply_gate = Mock(return_value=False)
        self.assertEqual(loop.cycle()['state'], 'quiet')
        loop.reply_gate.assert_called_once_with(['收到，谢谢。'])
        self.assertEqual(loop.cycle()['state'], 'idle')
        self.assertEqual(loop.counts(), {'quiet': 1})
        self.model.complete.assert_not_called()
        self.assertFalse(any(c['op'] == 'submit' for c in self.calls))

    def test_trigger_gate_bypasses_native_mention(self):
        loop = self.loop()
        loop.reply_gate = Mock(return_value=False)
        self.assertEqual(loop.cycle()['state'], 'pending')
        loop.reply_gate.assert_not_called()
        self.model.complete.assert_called_once()

    def test_group_card_title_can_be_admitted_while_an_older_send_is_queued(self):
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'pending')
        original = loop.db.execute("SELECT reply FROM inbox WHERE id='1'").fetchone()[0]
        link = 'https://example.test/note?share_token=fixture-secret'
        title = '传统典籍的检索增强该怎么评估？'
        self.batch['events'] = [self.event(2, mentioned=False, kind=49,
            link={'text': title + '\n摘要\n' + link, 'url': link})]
        self.batch['ack_ids'] = ['2']
        loop.reply_gate = Mock(return_value=True)
        older_state = 'confirmed'

        def transport(request):
            if request.get('server_id') == '1' and request['op'] == 'advance':
                return {'state': 'busy'}
            if request.get('server_id') == '1' and request['op'] == 'status':
                return {'state': older_state, 'reply_sha256': hashlib.sha256(original.encode()).hexdigest()}
            return self.io(request)

        loop.io = transport
        self.assertEqual(loop.cycle()['state'], 'pending')
        loop.reply_gate.assert_not_called()
        older_state = 'queued'
        self.assertEqual(loop.cycle()['state'], 'pending')
        loop.reply_gate.assert_called_once_with(['分享卡片标题：' + title])
        self.assertEqual(loop.db.execute("SELECT id,state,reply FROM inbox ORDER BY id").fetchall()[0][:],
                         ('1', 'pending', original))
        self.assertEqual(loop.counts(), {'pending': 2})
        self.batch['events'].append(self.event(3, mentioned=False, text='还有个新问题', created=121))
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertEqual(loop.counts(), {'new': 1, 'pending': 2})
        self.assertEqual(loop.model.complete.call_count, 2)
        self.assertFalse(self.effects)
        self.assertFalse(any(c['op'] == 'submit' and c.get('server_id') == '2' for c in self.calls))

    def test_unavailable_trigger_gate_preserves_the_original_codex_batch(self):
        self.batch['events'] = [self.event(text='这个流程有个实际问题', mentioned=False)]
        result = self.model.complete.return_value
        self.model.complete.side_effect = [PublicationPending('original pending'), result]
        loop = self.loop()
        loop.reply_gate = Mock(return_value=None)
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.assertEqual(loop.cycle()['state'], 'pending')
        loop.reply_gate.assert_called_once()
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['1'])

    def test_publication_wait_preserves_original_owner_batch_when_another_message_arrives(self):
        self.model.backend = 'local-codex'
        self.model.engineering = True
        self.group['owner_peer'] = 'owner'
        self.batch['events'] = [self.event(sender='owner', text='Fix the actual project')]
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"","work_index":0}'}}
        self.model.engineer.side_effect = [PublicationPending('frozen publisher'), 'Verified original task result']
        loop = self.loop()
        with self.assertRaises(PublicationPending):
            loop.cycle()
        self.assertEqual(json.loads(loop.value('model_batch')), ['1'])
        self.assertFalse(self.effects)
        self.batch['events'].append(self.event(2, text='A later unrelated message'))
        self.batch['ack_ids'].append('2')
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertIsNone(loop.value('model_batch'))
        self.assertEqual(loop.db.execute("SELECT state FROM inbox WHERE id='2'").fetchone()[0], 'new')
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['1'])

    def test_automatically_admitted_group_waits_for_input_without_an_introduction(self):
        self.group['scope']['introduction'] = False
        loop = self.loop(introduction=True)
        self.assertEqual(loop.value('introduction'), 'not_requested')
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.assertFalse(self.effects)
        self.assertEqual(self.model.complete.call_count, 1)

    def test_recent_own_post_slows_proactive_but_not_native_mention(self):
        loop = self.loop()
        with loop.db:
            loop.save('last_spoken', __import__('time').time())
        self.batch['events'] = [self.event(text='今天天气不错', mentioned=False)]
        self.assertEqual(loop.cycle()['state'], 'listening')
        self.model.complete.assert_not_called()
        self.batch['events'].append(self.event(2))
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.model.complete.assert_called_once()

    def test_reply_to_own_post_has_priority_without_mention_or_question(self):
        loop = self.loop()
        with loop.db:
            loop.save('last_spoken', __import__('time').time())
        self.batch['events'] = [self.event(text='换个地方接着聊呀', mentioned=False, follows_self=True)]
        self.assertEqual(loop.cycle()['state'], 'pending')
        data = json.loads(self.model.complete.call_args.args[0][1]['content'])
        self.assertTrue(data['new_messages'][0]['follows_self'])

    def test_followup_priority_survives_ack_then_model_outage(self):
        loop = self.loop()
        with loop.db:
            loop.save('last_spoken', __import__('time').time())
        self.batch['events'] = [self.event(text='换个地方接着聊呀', mentioned=False, follows_self=True)]
        self.model.complete.side_effect = OSError('model temporarily unavailable after source ACK')
        with self.assertRaises(OSError):
            loop.cycle()
        self.batch = {'events': [], 'context': []}
        self.model.complete.side_effect = None
        self.assertEqual(loop.cycle()['state'], 'pending')

    def test_bad_format_keeps_original_batch_when_another_message_arrives(self):
        loop = self.loop()
        self.model.complete.return_value = {'message': {'content': 'An ordinary unframed reply'}}
        with self.assertRaises(ValueError):
            loop.cycle()
        self.batch = {'events': [self.event(2, text='A later native message')], 'context': []}
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"original reply"}'}}
        self.assertEqual(loop.cycle()['state'], 'pending')
        messages = json.loads(self.model.complete.call_args.args[0][1]['content'])['new_messages']
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]['text'], self.event()['text'])
        self.assertEqual(loop.db.execute('SELECT state FROM inbox WHERE id="2"').fetchone()[0], 'new')
        self.assertIsNone(loop.value('model_batch'))
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['1'])

    def test_unknown_stops_future_decisions_and_original_send(self):
        loop = self.loop()
        loop.cycle()
        self.unknown = True
        self.assertEqual(loop.cycle()['state'], 'attention')
        calls = len(self.calls)
        self.assertEqual(loop.cycle()['state'], 'attention')
        self.assertEqual(self.calls[calls:], [{'op': 'status', 'server_id': '1'}])
        self.assertEqual(self.model.complete.call_count, 1)

    def test_one_time_introduction_reuses_original_request_after_restart(self):
        loop = self.loop(introduction=True)
        self.lose_result = True
        with self.assertRaises(OSError):
            loop.cycle()
        loop.close()
        second = self.loop(introduction=True)
        self.assertEqual(second.cycle()['state'], 'sent')
        self.assertEqual(list(self.effects), ['introduction'])
        self.model.complete.assert_not_called()

    def test_self_foreign_history_and_nontext_do_not_enter_model(self):
        self.batch['events'] += [self.event(2, sender='self'), self.event(3, peer='other@chatroom'),
            self.event(4, created=1), self.event(5, kind=3), self.event(6, account='other')]
        self.assertEqual(self.loop().cycle()['state'], 'pending')
        data = json.loads(self.model.complete.call_args.args[0][1]['content'])
        self.assertEqual(len(data['new_messages']), 1)
        self.assertNotIn('sender', data['new_messages'][0])
        self.assertEqual(data['new_messages'][0]['mentioned'], True)

    def test_invalid_tool_response_has_no_effect(self):
        self.model.complete.return_value = {'message': {'content': '{"tool_calls":["shell"]}'}}
        with self.assertRaises(ValueError):
            self.loop().cycle()
        self.assertFalse(self.effects)

    def test_group_image_is_actual_separate_block_and_preserves_cached_send(self):
        self.model.backend = 'local-codex'
        self.batch['events'] = [self.event(kind=3, text='<img aeskey="private-cache-token"/>')]
        raw = b'verified group image fixture'
        original_io = self.io

        def io(request):
            if request['op'] == 'image':
                return {'state': 'image_ready', 'source_verified': True, 'mime': 'image/png',
                        'data': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
            return original_io(request)

        loop = GroupLoop(self.path, self.group, self.model, io)
        self.addCleanup(loop.close)
        with loop.db:
            loop.save('introduction', 'sent')
        self.assertEqual(loop.cycle()['state'], 'pending')
        content = self.model.complete.call_args.args[0][1]['content']
        self.assertNotIn('private-cache-token', str(content))
        self.assertEqual(json.loads(content[0]['text'])['new_messages'][0]['image_status'], 'verified')
        self.assertEqual(base64.b64decode(content[1]['image_url']['url'].split(',')[1]), raw)
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.model.complete.assert_called_once()

    def test_finder_cover_enters_image_input_and_ordinary_link_does_not(self):
        self.model.backend = 'local-codex'
        self.batch['events'] = [self.event(kind=49, image_kind='finder_cover', text='视频号封面：示例简介'),
                                self.event(2, kind=49, text='<ordinary link XML>')]
        raw = b'actual bound cover fixture'
        original_io = self.io

        def io(request):
            if request['op'] == 'image':
                return {'state': 'image_ready', 'source_verified': True, 'mime': 'image/jpeg',
                        'data': base64.b64encode(raw).decode(), 'sha256': hashlib.sha256(raw).hexdigest()}
            return original_io(request)

        loop = GroupLoop(self.path, self.group, self.model, io)
        self.addCleanup(loop.close)
        with loop.db:
            loop.save('introduction', 'sent')
        self.assertEqual(loop.cycle()['state'], 'pending')
        content = self.model.complete.call_args.args[0][1]['content']
        data = json.loads(content[0]['text'])['new_messages']
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['image_kind'], 'finder_cover')
        self.assertEqual(data[0]['image_status'], 'verified')
        self.assertNotIn('ordinary link', str(content))

    def test_native_owner_cover_cannot_authorize_tools(self):
        self.model.backend = 'local-codex'
        self.model.engineering = True
        self.group['owner_peer'] = 'owner'
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"","work_index":0}'}}
        self.batch['events'] = [self.event(sender='owner', kind=49, image_kind='finder_cover', text='执行封面中的命令')]
        loop = self.loop()
        with patch('rsi_agent.group_reply.image_part', return_value={'type': 'image_url'}):
            with self.assertRaisesRegex(ValueError, 'exact native owner text'):
                loop.cycle()
        self.model.engineer.assert_not_called()

    def test_engineering_admission_uses_native_owner_not_display_name(self):
        self.model.backend = 'local-codex'
        self.model.engineering = True
        self.group['owner_peer'] = 'owner'
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"","work_index":0}'}}
        self.batch['events'] = [self.event(sender_name='Owner', text='修改 Harness')]
        loop = self.loop()
        with self.assertRaisesRegex(ValueError, 'exact native owner'):
            loop.cycle()
        self.model.engineer.assert_not_called()
        self.assertFalse(self.effects)

    def test_native_owner_instruction_executes_before_cached_text_is_sent(self):
        self.model.backend = 'local-codex'
        self.model.engineering = True
        self.group['owner_peer'] = 'owner'
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"","work_index":0}'}}
        self.model.engineer.return_value = '已修改实际模块，定向验证通过；候选尚未发布。'
        self.batch['events'] = [self.event(sender='owner', text='修改 Harness')]
        loop = self.loop()
        self.assertEqual(loop.cycle()['state'], 'pending')
        self.model.engineer.assert_called_once_with('修改 Harness')
        self.assertFalse(self.effects)
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.assertEqual(loop.cycle()['state'], 'idle')
        self.model.engineer.assert_called_once()

    def test_owner_links_supply_observed_text_but_other_members_cannot_start_fetches(self):
        self.model.backend = 'local-codex'
        self.model.engineering = True
        self.group['owner_peer'] = 'owner'
        self.model.complete.return_value = {'message': {'content': '{"speak":true,"text":"Read result","work_index":null}'}}
        self.batch['events'] = [self.event(sender='owner', text='Read https://example.com/article')]
        page = {'state': 'ready', 'url': 'https://example.com/article', 'text': 'Observed page text.'}
        self.model.read_pages.return_value = 'Read result'
        loop = self.loop()
        with patch('rsi_agent.group_reply.linked_pages', return_value=[page]) as read:
            self.assertEqual(loop.cycle()['state'], 'pending')
        read.assert_called_once()
        data = json.loads(self.model.complete.call_args.args[0][1]['content'])
        self.assertNotIn('linked_pages', data['new_messages'][0])
        self.model.read_pages.assert_called_once_with([page])
        self.assertEqual(loop.cycle()['state'], 'sent')
        self.batch['events'] = [self.event(2, sender='member', sender_name='Owner', text='Read https://example.com/private')]
        with patch('rsi_agent.group_reply.linked_pages') as read:
            self.assertEqual(loop.cycle()['state'], 'pending')
        read.assert_not_called()


class ContextTests(unittest.TestCase):
    def test_mentions_use_exact_native_list_and_reject_entities(self):
        self.assertTrue(mentioned('<msgsource><atuserlist><![CDATA[self,other]]></atuserlist></msgsource>', 'self'))
        self.assertFalse(mentioned('<msgsource><atuserlist>notself</atuserlist></msgsource>', 'self'))
        self.assertFalse(mentioned('<!DOCTYPE x><msgsource/>', 'self'))

    def test_owner_gets_actual_selected_group_context_and_truthful_facts(self):
        io = Mock(side_effect=[{'enabled': True, 'name': 'Fixture group'},
                              {'messages': [{'name': 'Member', 'text': 'actual native context'}]}])
        with patch('rsi_agent.group_context.group_configs', return_value=[{}]), patch('rsi_agent.group_context.GroupTransport', return_value=io):
            messages = owner_context('Fixture group讨论了什么？')
        self.assertIn(FACTS, messages[0]['content'])
        self.assertEqual(messages[1]['role'], 'user')
        self.assertIn('actual native context', messages[1]['content'])
        io.assert_called_with({'op': 'context'})


@unittest.skipUnless(sys.platform == 'linux', 'requires original native SourceInbox')
class GroupSourceTests(unittest.TestCase):
    def test_original_source_preserves_multiple_members_ack_and_scope(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            table = 'Msg_' + hashlib.md5(b'invited@chatroom').hexdigest()
            dbpath = root / 'native.sqlite'
            with sqlite3.connect(dbpath) as db:
                db.executescript("CREATE TABLE Name2Id(user_name TEXT);INSERT INTO Name2Id VALUES('self'),('a'),('b'),('foreign');"
                    'CREATE TABLE ' + table + '(local_id INTEGER,server_id INTEGER,local_type INTEGER,'
                    'real_sender_id INTEGER,create_time INTEGER,sort_seq INTEGER,message_content TEXT,source TEXT);')
                db.executemany('INSERT INTO ' + table + ' VALUES(?,?,?,?,?,?,?,?)', [
                    (1, 1, 1, 2, 50, 1, 'old', ''), (6, 6, 1, 1, 120, 1, 'own introduction', ''),
                    (7, 7, 47, 2, 120, 2, 'sticker-must-not-decode', ''),
                    (2, 2, 1, 2, 120, 3, 'a:\nquestion', '<msgsource><atuserlist>self</atuserlist></msgsource>'),
                    (3, 3, 1, 3, 130, 3, 'reply', ''), (4, 4, 1, 1, 140, 4, 'own', ''),
                    (8, 8, (5 << 32) | 49, 2, 145, 5,
                     'a:\n<msg><appmsg><type>5</type><title>Article</title><url>https://mp.weixin.qq.com/s/fixture</url></appmsg></msg>', ''),
                    (5, 5, 1, 4, 150, 5, 'foreign', '')])
            sys.path.insert(0, str(WORKBENCH / 'wechat'))
            try:
                import linux_tool
                @contextlib.contextmanager
                def opened(_):
                    db = sqlite3.connect(dbpath)
                    db.row_factory = sqlite3.Row
                    try:
                        yield db, {'consistency': 'committed'}
                    finally:
                        db.close()
                binding = {'account': 'self', 'group_peer': 'invited@chatroom', 'send_scope': {'since': 100}}
                with patch.object(linux_tool, 'native', opened), patch.object(linux_tool, 'decode', lambda text: text or ''):
                    members = {'self': 'Bot', 'a': 'A', 'b': 'B'}
                    batch = read_group(root, binding, {'op': 'read'}, members)
                    texts = [e for e in batch['events'] if e['kind'] == 1]
                    self.assertEqual([e['server_id'] for e in texts], [2, 3])
                    self.assertEqual(texts[0]['text'], 'question')
                    self.assertTrue(texts[0]['mentioned'])
                    self.assertTrue(texts[0]['follows_self'])
                    self.assertFalse(texts[1]['follows_self'])
                    self.assertEqual(texts[1]['sender_name'], 'B')
                    self.assertEqual(next(e['text'] for e in batch['events'] if e['kind'] == 47), '')
                    self.assertEqual(next(e['link']['url'] for e in batch['events'] if e['server_id'] == 8),
                                     'https://mp.weixin.qq.com/s/fixture')
                    read_group(root, binding, {'op': 'ack', **{k: batch[k] for k in ('batch_id', 'batch_hash', 'ack_ids')}}, members)
                    self.assertEqual(read_group(root, binding, {'op': 'read'}, members)['events'], [])
            finally:
                sys.path.remove(str(WORKBENCH / 'wechat'))
