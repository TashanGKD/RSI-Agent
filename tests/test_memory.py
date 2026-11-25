import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from rsi_agent.__main__ import main
from trigger import owner_memory


class OwnerMemoryStoreTests(unittest.TestCase):
    NOW = 1_700_000_000

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.executescript('CREATE TABLE inbox(id TEXT PRIMARY KEY,text TEXT NOT NULL);')
        owner_memory.initialize(self.db, now=self.NOW)
        self.addCleanup(self.db.close)
        self.counter = 0

    def send(self, text, now=None):
        self.counter += 1
        key = str(self.counter)
        self.db.execute('INSERT OR REPLACE INTO inbox(id,text) VALUES(?,?)', (key, text))
        return owner_memory.command(self.db, {'id': key, 'text': text},
                                    now=self.NOW if now is None else now)

    def item(self, name):
        return next(item for item in owner_memory.entries(self.db) if item['name'] == name)

    def test_initialize_migrates_legacy_named_notes_without_losing_them(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript(
            "CREATE TABLE owner_notes(name TEXT PRIMARY KEY,value TEXT NOT NULL,source_id TEXT NOT NULL);"
            "INSERT INTO owner_notes VALUES('旧条目','旧内容','native-1');"
            "CREATE TABLE owner_note_actions(source_id TEXT PRIMARY KEY);"
            "CREATE TABLE owner_note_epoch(epoch INTEGER NOT NULL,after_rowid INTEGER NOT NULL);"
            "INSERT INTO owner_note_epoch VALUES(1,1);")
        owner_memory.initialize(db, now=self.NOW)
        item = owner_memory.entries(db)[0]
        self.assertEqual((item['name'], item['value'], item['source_id']), ('旧条目', '旧内容', 'native-1'))
        self.assertEqual(item['kind'], '未分类')
        self.assertEqual(item['scope'], 'owner')
        self.assertEqual(item['sensitivity'], 'private')
        self.assertEqual(item['confidence'], 'explicit')
        self.assertEqual((item['created'], item['updated']), (self.NOW, self.NOW))
        self.assertIsNone(item['review_at'])
        self.assertEqual(owner_memory.position(db), (1, 1))

    def test_typed_note_keeps_type_created_time_and_legacy_default_is_always_injected(self):
        self.send('记住[偏好] 风格：技术讨论直接讲机制')
        first = self.item('风格')
        self.assertEqual(first['kind'], '偏好')
        self.assertEqual(first['scope'], 'owner')
        self.assertEqual(first['source_id'], '1')
        self.assertIsNone(first['review_at'])

        self.send('记住[关系] 风格：技术讨论直接讲机制')
        second = self.item('风格')
        self.assertEqual(second['kind'], '关系')
        self.assertEqual(second['created'], first['created'])
        self.assertEqual(second['source_id'], '2')
        self.send('记住 风格：技术讨论直接讲机制')
        self.assertEqual(self.item('风格')['kind'], '关系')

        self.send('记住 备注：旧格式仍然可用')
        self.assertEqual(self.item('备注')['kind'], '未分类')
        context = owner_memory.context(self.db, '随便聊聊', now=self.NOW + 1)
        self.assertIn('旧格式仍然可用', str(context))
        self.assertIn('技术讨论直接讲机制', str(context))

        view = self.send('查看记忆 风格')
        self.assertIn('关系', view)
        self.assertIn('技术讨论直接讲机制', view)

    def test_review_expiry_hides_only_from_automatic_context_and_can_be_refreshed(self):
        self.send('记住[事实] 部署位置：本地WSL')
        first = self.item('部署位置')
        self.assertEqual(first['review_at'], self.NOW + 180 * 86400)
        self.assertIn('本地WSL', str(owner_memory.context(self.db, '部署在哪', now=self.NOW + 1)))

        later = first['review_at'] + 1
        self.assertNotIn('本地WSL', str(owner_memory.context(self.db, '部署在哪', now=later)))
        view = self.send('查看记忆 部署位置', now=later)
        self.assertIn('待复核', view)
        epoch = owner_memory.position(self.db)[0]
        reply = self.send('记住[事实] 部署位置：本地WSL', now=later)
        self.assertIn('复核时间已更新', reply)
        self.assertGreater(owner_memory.position(self.db)[0], epoch)
        refreshed = self.item('部署位置')
        self.assertGreater(refreshed['review_at'], first['review_at'])
        self.assertIn('本地WSL', str(owner_memory.context(self.db, '部署在哪', now=later)))

    def test_non_core_memory_is_retrieved_by_query_and_core_is_bounded(self):
        for index in range(10):
            self.send('记住[偏好] 偏好{:02d}：值{}'.format(index, index))
        self.send('记住[事实] 部署位置：本地WSL')
        self.assertNotIn('部署位置', owner_memory.inspect(self.db, '今天天气', now=self.NOW + 1)['selected'])
        self.assertIn('部署位置', owner_memory.inspect(self.db, '部署在哪', now=self.NOW + 1)['selected'])

        report = owner_memory.inspect(self.db, '', now=self.NOW + 1)
        self.assertLessEqual(len(report['selected']), owner_memory.MAX_CONTEXT_ITEMS)
        self.assertLessEqual(report['context_bytes'], owner_memory.MAX_CONTEXT_BYTES)
        with mock.patch.object(owner_memory, 'MAX_CONTEXT_ITEMS', 2):
            self.assertLessEqual(len(owner_memory.inspect(self.db, now=self.NOW + 1)['selected']), 2)

    def test_context_byte_budget_drops_entries_instead_of_overflowing(self):
        self.send('记住[偏好] 长一：' + '甲' * 1200)
        self.send('记住[偏好] 长二：' + '乙' * 1200)
        report = owner_memory.inspect(self.db, now=self.NOW + 1)
        self.assertLessEqual(report['context_bytes'], owner_memory.MAX_CONTEXT_BYTES)
        self.assertEqual(len(report['selected']), 1)

    def test_secret_value_and_oversize_or_extra_notes_are_not_stored(self):
        self.assertIn('没保存', self.send('记住[事实] 密码：sk-' + 'a' * 24))
        self.assertEqual(owner_memory.entries(self.db), [])
        self.assertIn('没保存', self.send('记住 长文：' + '字' * 1201))
        self.assertEqual(owner_memory.entries(self.db), [])
        self.assertIn('类型可用', self.send('记住[不存在] 名字：值'))
        self.assertEqual(owner_memory.entries(self.db), [])

        for index in range(owner_memory.MAX_NOTES):
            self.send('记住 条目{:02d}：值{}'.format(index, index))
        self.assertEqual(len(owner_memory.entries(self.db)), owner_memory.MAX_NOTES)
        self.assertIn('记忆空间不够', self.send('记住 多出来：值'))
        self.assertEqual(len(owner_memory.entries(self.db)), owner_memory.MAX_NOTES)

    def test_forget_and_scope_filter_keep_other_stores_out_of_owner_context(self):
        self.send('记住[偏好] 风格：本人私聊')
        self.db.execute(
            "INSERT INTO owner_notes(name,value,source_id,kind,scope,sensitivity,confidence,created,updated,review_at) "
            "VALUES('别的会话','群资料','native-9','事实','group','private','explicit',?,?,NULL)",
            (self.NOW, self.NOW))
        report = owner_memory.inspect(self.db, '群资料', now=self.NOW + 1)
        self.assertNotIn('别的会话', [item['name'] for item in report['items']])
        self.assertNotIn('群资料', str(owner_memory.context(self.db, '群资料', now=self.NOW + 1)))
        self.assertIn('其他会话', self.send('记住 别的会话：本人覆盖'))
        self.assertEqual(owner_memory.entries(self.db, scope='group')[0]['value'], '群资料')

        epoch = owner_memory.position(self.db)[0]
        self.assertIn('已从当前命名记忆里移除', self.send('忘记 风格'))
        self.assertEqual(owner_memory.entries(self.db, scope='owner'), [])
        self.assertGreater(owner_memory.position(self.db)[0], epoch)
        self.assertIn('没有', self.send('查看记忆'))
        self.assertEqual(owner_memory.entries(self.db, scope='group')[0]['name'], '别的会话')

    def test_cli_review_is_read_only_and_hides_values_by_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'inbox.sqlite'
            db = sqlite3.connect(path)
            db.row_factory = sqlite3.Row
            db.executescript('CREATE TABLE inbox(id TEXT PRIMARY KEY,text TEXT NOT NULL);')
            owner_memory.initialize(db, now=self.NOW)
            db.execute("INSERT INTO inbox VALUES('1','记住[偏好] 风格：直接讲机制')")
            owner_memory.command(db, {'id': '1', 'text': '记住[偏好] 风格：直接讲机制'}, now=self.NOW)
            db.commit()
            db.close()
            if os.name == 'posix':
                os.chmod(path, 0o600)

            before = path.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(['memory', 'review', '--db', str(path), '--query', '机制'])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertTrue(report['read_only'])
            self.assertEqual((report['notes'], report['fresh'], report['stale']), (1, 1, 0))
            self.assertIn('风格', report['selected'])
            self.assertNotIn('value', report['items'][0])
            self.assertEqual(path.read_bytes(), before)

            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = main(['memory', 'review', '--db', str(path), '--show-values'])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())['items'][0]['value'], '直接讲机制')


if __name__ == '__main__':
    unittest.main()