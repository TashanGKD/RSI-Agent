import contextlib
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

    def test_unknown_stops_future_decisions_and_original_send(self):
        loop = self.loop()
        loop.cycle()
        self.unknown = True
        self.assertEqual(loop.cycle()['state'], 'attention')
        calls = len(self.calls)
        self.assertEqual(loop.cycle()['state'], 'attention')
        self.assertEqual(len(self.calls), calls)
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
                    (1, 1, 1, 2, 50, 1, 'old', ''), (2, 2, 1, 2, 120, 2, 'a:\nquestion', '<msgsource><atuserlist>self</atuserlist></msgsource>'),
                    (3, 3, 1, 3, 130, 3, 'reply', ''), (4, 4, 1, 1, 140, 4, 'own', ''),
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
                    self.assertEqual([e['server_id'] for e in batch['events']], [2, 3])
                    self.assertEqual(batch['events'][0]['text'], 'question')
                    self.assertTrue(batch['events'][0]['mentioned'])
                    self.assertEqual(batch['events'][1]['sender_name'], 'B')
                    read_group(root, binding, {'op': 'ack', **{k: batch[k] for k in ('batch_id', 'batch_hash', 'ack_ids')}}, members)
                    self.assertEqual(read_group(root, binding, {'op': 'read'}, members)['events'], [])
            finally:
                sys.path.remove(str(WORKBENCH / 'wechat'))
