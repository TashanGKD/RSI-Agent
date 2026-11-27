import contextlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import time
import unittest

from rsi_agent.__main__ import main
from trigger import owner_actions


class OwnerActionTests(unittest.TestCase):
    NOW = 1_700_000_000

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.config = self.root / owner_actions.CONFIG_NAME
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE inbox(id TEXT PRIMARY KEY,text TEXT NOT NULL);')
        owner_actions.initialize(self.db)
        self.counter = 0
        self.runs = self.root / 'runs.txt'

    def write_config(self, actions):
        self.config.write_text(json.dumps({'version': 1, 'actions': actions}, ensure_ascii=False),
                               encoding='utf-8')
        if os.name == 'posix':
            os.chmod(self.config, 0o600)

    def append_action(self, timeout=20):
        code = ("from pathlib import Path;"
                "p=Path(%r);p.write_text((p.read_text() if p.exists() else '')+'x')" % str(self.runs))
        return {'description': '测试追加', 'command': [sys.executable, '-c', code], 'timeout': timeout}

    def send(self, text, now=None):
        self.counter += 1
        key = str(self.counter)
        self.db.execute('INSERT OR REPLACE INTO inbox(id,text) VALUES(?,?)', (key, text))
        return owner_actions.command(self.db, {'id': key, 'text': text}, self.config,
                                     now=self.NOW if now is None else now)

    def stage(self, name='append'):
        reply = self.send('动作 准备 ' + name)
        match = re.search(r'[0-9a-f]{16}', reply)
        self.assertIsNotNone(match, reply)
        return match.group(0), reply

    def record(self, action_id):
        return self.db.execute('SELECT * FROM owner_actions WHERE id=?', (action_id,)).fetchone()

    def test_stage_confirm_executes_once_and_audits(self):
        self.write_config({'append': self.append_action()})
        action_id, reply = self.stage()
        self.assertIn('已准备动作', reply)
        self.assertEqual(self.record(action_id)['state'], 'pending')
        self.assertFalse(self.runs.exists())

        result = self.send('动作 确认 ' + action_id)
        self.assertIn('成功', result)
        self.assertEqual(self.record(action_id)['state'], 'succeeded')
        self.assertEqual(self.record(action_id)['exit_code'], 0)
        self.assertEqual(self.runs.read_text(), 'x')

        again = self.send('动作 确认 ' + action_id)
        self.assertIn('未重复执行', again)
        self.assertEqual(self.runs.read_text(), 'x')
        self.assertEqual(self.db.execute('SELECT count(*) FROM owner_actions').fetchone()[0], 1)

    def test_changed_definition_blocks_the_staged_action(self):
        self.write_config({'append': self.append_action()})
        action_id, _ = self.stage()
        changed = self.append_action()
        changed['description'] = '定义已变化'
        self.write_config({'append': changed})
        reply = self.send('动作 确认 ' + action_id)
        self.assertIn('定义已变化', reply)
        self.assertEqual(self.record(action_id)['state'], 'blocked')
        self.assertFalse(self.runs.exists())

    def test_cancel_and_expiry_never_execute(self):
        self.write_config({'append': self.append_action()})
        cancelled, _ = self.stage()
        self.assertIn('已取消', self.send('动作 取消 ' + cancelled))
        self.assertIn('未重复执行', self.send('动作 确认 ' + cancelled))
        self.assertEqual(self.record(cancelled)['state'], 'cancelled')
        self.assertFalse(self.runs.exists())

        expired, _ = self.stage()
        reply = self.send('动作 确认 ' + expired, now=self.NOW + owner_actions.STAGE_SECONDS + 1)
        self.assertIn('过期', reply)
        self.assertEqual(self.record(expired)['state'], 'expired')
        self.assertFalse(self.runs.exists())

    def test_timeout_is_terminal_and_not_retried(self):
        self.write_config({'slow': {'description': '慢动作',
                                    'command': [sys.executable, '-c', 'import time; time.sleep(10)'],
                                    'timeout': 1}})
        action_id, _ = self.stage('slow')
        started = time.monotonic()
        reply = self.send('动作 确认 ' + action_id)
        self.assertLess(time.monotonic() - started, 6)
        self.assertIn('超时', reply)
        self.assertEqual(self.record(action_id)['state'], 'timeout')
        self.assertIn('未自动重试', reply)
        self.assertIn('未重复执行', self.send('动作 确认 ' + action_id))

    def test_output_is_bounded_and_shell_is_not_used(self):
        self.write_config({
            'loud': {'description': '长输出', 'command': [sys.executable, '-c', 'print("X" * 100000)']},
            'literal': {'description': '无 shell', 'command': [
                sys.executable, '-c', 'import sys; print(sys.argv[1])', 'a; echo HACKED']},
        })
        loud, _ = self.stage('loud')
        reply = self.send('动作 确认 ' + loud)
        row = self.record(loud)
        self.assertEqual(row['state'], 'succeeded')
        self.assertLessEqual(len(row['stdout_excerpt']), owner_actions.MAX_EXCERPT_CHARS)
        self.assertTrue(row['truncated'])
        self.assertLessEqual(len(reply.encode()), owner_actions.MAX_REPLY_BYTES)
        self.assertIn('输出过长', reply)

        literal, _ = self.stage('literal')
        result = self.send('动作 确认 ' + literal)
        self.assertIn('a; echo HACKED', result)
        self.assertFalse((self.root / 'HACKED').exists())

    def test_pending_limit_and_duplicate_prepare_are_bounded(self):
        self.write_config({'a%02d' % index: {'description': '动作%d' % index,
                                             'command': [sys.executable, '-c', 'pass']}
                           for index in range(9)})
        first, _ = self.stage('a00')
        again, _ = self.stage('a00')
        self.assertEqual(first, again)
        for index in range(1, owner_actions.MAX_PENDING):
            self.stage('a%02d' % index)
        reply = self.send('动作 准备 a08')
        self.assertIn('太多', reply)
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM owner_actions WHERE state='pending'").fetchone()[0],
            owner_actions.MAX_PENDING)

    def test_invalid_or_missing_config_never_executes(self):
        self.assertIn('还没有配置', self.send('动作 列表'))
        self.assertIn('还没有配置', self.send('动作 准备 append'))
        self.config.write_text('{', encoding='utf-8')
        if os.name == 'posix':
            os.chmod(self.config, 0o600)
        self.assertIn('配置不可用', self.send('动作 列表'))
        self.assertIn('配置不可用', self.send('动作 准备 append'))
        self.write_config({'bad': {'description': '相对路径', 'command': ['python', '-V']}})
        self.assertIn('配置不可用', self.send('动作 列表'))
        self.write_config({'bad': {'description': '危险环境',
                                   'command': [sys.executable, '-V'], 'env': {'LD_PRELOAD': 'x'}}})
        self.assertIn('配置不可用', self.send('动作 列表'))

    def test_non_command_text_stays_with_the_model(self):
        self.assertIsNone(self.send('动作电影推荐'))
        self.assertIsNone(self.send('动作 电影推荐'))
        self.assertIn('用法', self.send('动作 准备'))
        self.assertIn('没有找到', self.send('动作 确认 deadbeefdeadbeef'))
        self.assertIn('用法', self.send('动作 帮助'))
        self.assertIn('用法', self.send('动作 取消'))

    def test_restart_marks_running_unknown_and_never_retries(self):
        self.write_config({'append': self.append_action()})
        action_id, _ = self.stage()
        self.db.execute("UPDATE owner_actions SET state='running',started_at=? WHERE id=?",
                        (self.NOW, action_id))
        self.db.commit()
        owner_actions.recover(self.db, now=self.NOW + 1)
        row = self.record(action_id)
        self.assertEqual(row['state'], 'unknown')
        self.assertIn('未自动重试', row['error'])
        self.assertIn('未重复执行', self.send('动作 确认 ' + action_id, now=self.NOW + 2))

    def test_review_is_read_only_and_hides_commands_by_default(self):
        inbox = self.root / 'inbox.sqlite'
        db = sqlite3.connect(inbox)
        try:
            db.executescript("CREATE TABLE meta(binding TEXT NOT NULL);"
                             "INSERT INTO meta VALUES('fixture');")
            db.row_factory = sqlite3.Row
            owner_actions.initialize(db)
            db.execute("INSERT INTO owner_actions(id,action,definition_sha256,state,source_id,"
                       "created,expires_at,stdout_excerpt) VALUES(?,?,?,?,?,?,?,?)",
                       ('0123456789abcdef', 'append', 'hash', 'succeeded', '1',
                        self.NOW, self.NOW + 60, 'VISIBLE_OUTPUT'))
            db.commit()
        finally:
            db.close()
        if os.name == 'posix':
            os.chmod(inbox, 0o600)
        self.write_config({'append': self.append_action()})
        report = owner_actions.review(inbox, now=self.NOW + 1)
        self.assertTrue(report['read_only'])
        self.assertEqual(report['configured'][0]['name'], 'append')
        self.assertNotIn('command', json.dumps(report))
        self.assertNotIn('VISIBLE_OUTPUT', json.dumps(report))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            main(['action', 'review', '--db', str(inbox), '--show-output'])
        shown = json.loads(output.getvalue())
        self.assertEqual(shown['actions'][0]['stdout'], 'VISIBLE_OUTPUT')

        plain = self.root / 'plain.sqlite'
        sqlite3.connect(plain).close()
        with self.assertRaisesRegex(ValueError, 'owner inbox'):
            owner_actions.review(plain)