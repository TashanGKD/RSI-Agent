from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from trigger.codex_backend import CodexBackend
from trigger.owner_reply import ReplyLoop
from trigger.group_reply import GroupLoop
from trigger import owner_knowledge


@unittest.skipUnless(sys.platform == 'linux', 'private native-bound inbox and Codex inputs')
class OwnerMemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.owner = {'account': 'self', 'peer': 'owner', 'scope': {'mode': 'owner-private-text', 'since': 100}}
        self.model = Mock(backend='local-codex')
        self.model.has_original_input.return_value = False
        self.model.reply.return_value = 'ordinary reply'
        self.events, self.effects, self.io_calls = [], {}, []
        self.loop = ReplyLoop(self.root / 'inbox.sqlite', self.owner, self.model, self.io)
        self.addCleanup(lambda: self.loop.close())

    def io(self, request):
        self.io_calls.append(request)
        if request['op'] == 'read':
            return {'events': list(self.events), 'batch_id': 'fixture', 'batch_hash': 'hash',
                    'ack_ids': [str(e['server_id']) for e in self.events]}
        if request['op'] == 'ack':
            return {'state': 'acked'}
        key = request['server_id']
        if request['op'] == 'submit':
            return self.effects.get(key, {'state': 'queued'})
        self.assertNotIn(key, self.effects)
        self.effects[key] = {'state': 'succeeded', 'outcome': 'sent'}
        return self.effects[key]

    def message(self, text, **changes):
        index = len(self.events) + 1
        self.events.append(dict({'account': 'self', 'peer': 'owner', 'sender': 'owner',
            'server_id': index, 'created': 120 + index, 'kind': 1, 'text': text}, **changes))
        return self.loop.cycle()

    def restart(self):
        self.loop.close()
        self.loop = ReplyLoop(self.root / 'inbox.sqlite', self.owner, self.model, self.io)

    def test_remember_review_correct_forget_survives_restart_without_reintroducing_old_context(self):
        self.message('记住 风格：PRIVATE_OLD_STYLE')
        self.model.reply.assert_not_called()
        self.restart()
        self.message('查看记忆')
        self.assertIn('PRIVATE_OLD_STYLE', self.loop.db.execute("select reply from inbox where id='2'").fetchone()[0])
        self.message('聊点别的')
        self.assertIn('PRIVATE_OLD_STYLE', str(self.model.reply.call_args))
        first_epoch = self.model.memory_epoch
        self.model.reply.return_value = 'PRIVATE_OLD_STYLE was used in this ordinary reply'
        self.message('再接一句')
        self.message('记住 风格：PRIVATE_NEW_STYLE')
        self.message('接着聊')
        self.assertNotIn('PRIVATE_OLD_STYLE', str(self.model.reply.call_args))
        self.assertIn('PRIVATE_NEW_STYLE', str(self.model.reply.call_args))
        self.assertGreater(self.model.memory_epoch, first_epoch)
        self.message('忘记 风格')
        self.restart()
        self.message('现在聊聊')
        self.assertNotIn('PRIVATE_OLD_STYLE', str(self.model.reply.call_args))
        self.assertNotIn('PRIVATE_NEW_STYLE', str(self.model.reply.call_args))
        self.message('查看记忆')
        self.assertIn('没有', self.loop.db.execute("select reply from inbox where id='9'").fetchone()[0])
        # Preserve raw originals; forgetting changes future retrieval, not old receipts.
        self.assertEqual(self.loop.db.execute("select text from inbox where id='1'").fetchone()[0], '记住 风格：PRIVATE_OLD_STYLE')
        self.assertEqual(self.loop.cycle()['state'], 'idle')
        self.assertEqual(len(self.effects), 9)

    def test_cache_and_note_mutation_are_atomic_and_retries_keep_the_original_id(self):
        self.loop.db.executescript("CREATE TRIGGER interrupt_reply BEFORE UPDATE OF reply ON inbox BEGIN SELECT RAISE(ABORT,'owned fixture interruption'); END;")
        with self.assertRaises(sqlite3.DatabaseError):
            self.message('记住 路径：fixture-project')
        self.assertEqual(self.loop.db.execute('select count(*) from owner_notes').fetchone()[0], 0)
        self.assertEqual(self.loop.db.execute('select epoch from owner_note_epoch').fetchone()[0], 0)
        self.assertEqual(self.loop.counts(), {'new': 1})
        self.loop.db.execute('DROP TRIGGER interrupt_reply')
        self.assertEqual(self.loop.cycle()['state'], 'sent')
        self.assertEqual(self.loop.db.execute('select epoch from owner_note_epoch').fetchone()[0], 1)
        self.restart()
        self.assertEqual(self.loop.cycle()['state'], 'idle')
        self.assertEqual(list(self.effects), ['1'])
        self.model.reply.assert_not_called()

    def test_foreign_identity_and_link_card_cannot_write_notes(self):
        self.message('记住 假：foreign', sender='impostor')
        self.assertFalse(self.effects)
        with patch('trigger.owner_reply.linked_pages', return_value=[]):
            self.message('', kind=49, link={'text': '记住 假：card-data', 'url': 'https://example.invalid'})
        self.assertEqual(self.loop.db.execute('select count(*) from owner_notes').fetchone()[0], 0)
        self.model.reply.assert_called_once()

    def test_an_already_frozen_generation_is_not_replaced_by_a_new_memory_command(self):
        self.model.has_original_input.return_value = True
        self.model.reply.return_value = 'original completed reply'
        self.message('记住 风格：must-not-replace-original')
        self.model.reply.assert_called_once()
        self.assertEqual(self.loop.db.execute('select count(*) from owner_notes').fetchone()[0], 0)
        self.assertEqual(self.loop.db.execute("select reply from inbox where id='1'").fetchone()[0], 'original completed reply')

    def test_over_budget_note_is_not_saved_or_reinjected_as_ordinary_history(self):
        self.message('记住 长文：' + 'NOT_STORED_' * 900)
        self.assertEqual(self.loop.db.execute('select count(*) from owner_notes').fetchone()[0], 0)
        self.model.reply.assert_not_called()
        self.message('接着聊')
        self.assertNotIn('NOT_STORED_', str(self.model.reply.call_args))

    def test_owner_private_knowledge_is_bounded_and_stale_aware(self):
        notes = self.root / 'notes'
        notes.mkdir()
        source = notes / 'deploy.md'
        source.write_text('# 部署\n\n## 位置\n\nPRIVATE_KNOWLEDGE_WSL 在本地。\n',
                          encoding='utf-8', newline='\n')
        owner_knowledge.index(notes, self.root / 'inbox.sqlite', now=123)
        self.message('部署位置 WSL')
        self.assertIn('PRIVATE_KNOWLEDGE_WSL', str(self.model.reply.call_args))
        self.assertIn('knowledge_snippets', str(self.model.reply.call_args))

        source.write_text('# 部署\n\n## 位置\n\nSTALE_KNOWLEDGE_TOKEN 已改动，等待重建。\n',
                          encoding='utf-8', newline='\n')
        self.message('部署位置 WSL 再问')
        self.assertNotIn('STALE_KNOWLEDGE_TOKEN', str(self.model.reply.call_args))
        owner_knowledge.index(notes, self.root / 'inbox.sqlite', now=124)
        self.message('部署位置 WSL 三问')
        self.assertIn('STALE_KNOWLEDGE_TOKEN', str(self.model.reply.call_args))

    def test_group_scope_never_opens_private_notes_or_receives_the_private_context(self):
        self.message('记住 风格：PRIVATE_OWNER_ONLY')
        self.message('问个问题')
        backend = CodexBackend.__new__(CodexBackend)
        backend.scope = ['self', 'owner']
        backend.memory_epoch = 1
        backend.complete = Mock(return_value={'message': {'content': '{"speak":false,"text":""}'}})
        backend.engineering = False
        group = {'account': 'self', 'peer': 'group@chatroom', 'name': 'Fixture group',
                 'scope': {'mode': 'invited-group-text', 'since': 100, 'introduction': False}}
        transport = Mock(return_value={'events': [{'account': 'self', 'peer': 'group@chatroom', 'sender': 'member',
            'sender_name': 'Member', 'server_id': 1, 'created': 120, 'kind': 1, 'text': '你好？', 'mentioned': True}],
            'ack_ids': ['1'], 'batch_id': 'group', 'batch_hash': 'hash', 'context': []})
        loop = GroupLoop(self.root / 'group.sqlite', group, backend, transport)
        self.addCleanup(loop.close)
        self.assertEqual(loop.cycle()['state'], 'quiet')
        self.assertEqual(backend.memory_epoch, 0)
        self.assertNotIn('PRIVATE_OWNER_ONLY', str(backend.complete.call_args))
        self.assertFalse(loop.db.execute("select 1 from sqlite_master where name='owner_notes'").fetchone())

    def test_changed_memory_context_only_reaches_new_codex_inputs(self):
        backend = CodexBackend.__new__(CodexBackend)
        preferences = self.root / 'preferences.md'
        preferences.write_text('Fixture preferences')
        backend.config = {'state': str(self.root), 'preferences_file': str(preferences)}
        backend.model = 'fixture'
        backend.exchange = Mock(return_value=(200, {'state': 'completed', 'text': 'reply'}))
        backend.bind('self', 'owner')
        backend.use_request(['native-1'])
        backend._run([{'role': 'user', 'content': 'original'}], 'chat')
        first = backend.exchange.call_args.args[1]
        self.assertTrue(backend.has_original_input(['native-1']))
        self.assertFalse(backend.has_original_input(['other']))
        backend.memory_epoch = 2
        revised = [{'role': 'system', 'content': 'corrected note'}, {'role': 'user', 'content': 'new context'}]
        backend._run(revised, 'chat')
        self.assertEqual(backend.exchange.call_args.args[1], first)
        backend.use_request(['native-2'])
        backend._run(revised, 'chat')
        second = backend.exchange.call_args.args[1]
        self.assertEqual(second['messages'][1:], revised)
        self.assertNotEqual(first['id'], second['id'])
