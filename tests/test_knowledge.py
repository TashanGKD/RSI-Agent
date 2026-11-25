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
from trigger import owner_knowledge


class KnowledgeTests(unittest.TestCase):
    NOW = 1_700_000_000

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.inbox = self.root / 'inbox.sqlite'
        db = sqlite3.connect(self.inbox)
        db.executescript("CREATE TABLE meta(binding TEXT NOT NULL);"
                         "INSERT INTO meta VALUES('fixture');")
        db.commit()
        db.close()
        if os.name == 'posix':
            os.chmod(self.inbox, 0o600)
        self.notes = self.root / 'notes'
        self.notes.mkdir()
        self.index = owner_knowledge.index_path(self.inbox)

    def write(self, name, text):
        path = self.notes / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8', newline='\n')
        return path

    def build(self, now=None):
        return owner_knowledge.index(self.notes, self.inbox, now=self.NOW if now is None else now)

    def search(self, query, **changes):
        return owner_knowledge.search(self.index, query, now=self.NOW + 1, **changes)

    def test_index_and_search_returns_cited_bounded_snippets(self):
        self.write('deploy.md',
                   '# 部署说明\n\n## 位置\n\n本地 WSL 的接收器目录是 /var/lib/rsi-agent。\n\n'
                   '## 回滚\n\n保留上一版发布目录。\n')
        self.write('cook.md', '# 菜谱\n\n番茄炒蛋先炒蛋。\n')
        report = self.build()
        self.assertEqual((report['state'], report['files'], report['chunks']), ('indexed', 2, 3))
        self.assertEqual(report['index'], str(self.index))

        result = self.search('部署在哪里')
        self.assertEqual(result['state'], 'ok')
        self.assertEqual(result['results'][0]['path'], 'deploy.md')
        self.assertEqual(result['results'][0]['heading'], '位置')
        self.assertIn('WSL', result['results'][0]['text'])
        self.assertLessEqual(result['context_bytes'], owner_knowledge.MAX_CONTEXT_BYTES)
        self.assertEqual(result['stale_sources'], 0)

        other = self.search('番茄炒蛋')
        self.assertEqual([row['path'] for row in other['results']], ['cook.md'])
        self.assertEqual(self.search('量子计算')['results'], [])
        self.assertEqual(self.search('')['results'], [])

        context = owner_knowledge.context(self.index, 'WSL 接收器目录')
        self.assertEqual([message['role'] for message in context], ['system', 'user'])
        self.assertIn('资料', context[0]['content'])
        payload = json.loads(context[1]['content'])['knowledge_snippets']
        self.assertEqual((payload[0]['path'], payload[0]['heading']), ('deploy.md', '位置'))
        self.assertIn('WSL', payload[0]['text'])

    def test_changed_source_is_excluded_until_reindexed(self):
        self.write('deploy.md', '# 部署\n\n旧内容 WSL_ONLY\n')
        self.build()
        self.assertEqual([row['path'] for row in self.search('WSL_ONLY')['results']], ['deploy.md'])

        self.write('deploy.md', '# 部署\n\n新内容 RUSTDESK_ONLY，长度也已经改变。\n')
        status = owner_knowledge.status(self.index, now=self.NOW + 10)
        self.assertTrue(status['stale'])
        self.assertIn('deploy.md', status['changed'])
        self.assertEqual(self.search('RUSTDESK_ONLY')['results'], [])
        self.assertEqual(self.search('WSL_ONLY')['results'], [])

        self.build(now=self.NOW + 20)
        self.assertFalse(owner_knowledge.status(self.index, now=self.NOW + 21)['stale'])
        found = self.search('RUSTDESK_ONLY')['results']
        self.assertEqual([row['path'] for row in found], ['deploy.md'])
        self.assertIn('RUSTDESK_ONLY', found[0]['text'])

    def test_skip_rules_keep_oversize_secret_hidden_and_binary_files_out(self):
        self.write('good.md', '# 正常\n\n可以检索的内容。\n')
        self.write('.hidden.md', '# 隐藏\n\nHIDDEN_TOKEN\n')
        self.write('large.txt', 'L' * (owner_knowledge.MAX_FILE_BYTES + 1))
        self.write('secret.md', '# 凭据\n\n-----BEGIN RSA PRIVATE KEY-----\nSECRET_TOKEN\n')
        self.write('image.bin', 'BINARY_TOKEN')
        report = self.build()
        self.assertEqual((report['files'], report['chunks']), (1, 1))
        skipped = {item['path']: item['reason'] for item in report['skipped']}
        self.assertEqual(skipped['secret.md'], 'secret-like content')
        self.assertEqual(skipped['large.txt'], 'oversize')
        self.assertNotIn('.hidden.md', skipped)
        self.assertEqual(self.search('HIDDEN_TOKEN')['results'], [])
        self.assertEqual(self.search('SECRET_TOKEN')['results'], [])
        self.assertEqual(self.search('BINARY_TOKEN')['results'], [])

    def test_index_requires_the_owner_inbox_and_preserves_the_old_index_on_failure(self):
        plain = self.root / 'plain.sqlite'
        sqlite3.connect(plain).close()
        with self.assertRaisesRegex(ValueError, 'owner inbox'):
            owner_knowledge.index(self.notes, plain)

        self.write('first.md', '# 一\n\nFIRST_TOKEN\n')
        self.build()
        before = self.index.read_bytes()
        self.write('second.md', '# 二\n\nSECOND_TOKEN\n')
        with mock.patch.object(owner_knowledge, 'MAX_FILES', 1):
            with self.assertRaisesRegex(ValueError, 'file limit'):
                self.build(now=self.NOW + 5)
        self.assertEqual(self.index.read_bytes(), before)
        self.assertIn('FIRST_TOKEN', self.search('FIRST_TOKEN')['results'][0]['text'])
        self.assertEqual(self.search('SECOND_TOKEN')['results'], [])

    def test_results_are_capped_per_source_and_by_context_bytes(self):
        sections = ''.join('## 小节{}\n\n预算关键词 {}\n\n'.format(index, '值' * 40)
                           for index in range(4))
        self.write('many.md', '# 预算\n\n' + sections)
        self.build()
        with mock.patch.object(owner_knowledge, 'MAX_RESULTS', 2):
            self.assertLessEqual(len(self.search('预算关键词')['results']), 2)
        with mock.patch.object(owner_knowledge, 'MAX_RESULTS_PER_SOURCE', 1):
            self.assertEqual(len(self.search('预算关键词')['results']), 1)
        with mock.patch.object(owner_knowledge, 'MAX_CONTEXT_BYTES', 120):
            report = self.search('预算关键词')
            self.assertLessEqual(report['context_bytes'], 120)
            self.assertLessEqual(len(report['results']), 1)

    def test_missing_invalid_and_stale_indexes_do_not_raise(self):
        self.assertEqual(owner_knowledge.search(self.index, '任何')['state'], 'missing')
        self.assertEqual(owner_knowledge.context(self.index, '任何'), [])
        self.assertEqual(owner_knowledge.status(self.index)['state'], 'missing')

        self.index.write_text('not a database', encoding='utf-8')
        self.assertEqual(owner_knowledge.search(self.index, '任何')['state'], 'invalid')
        self.assertEqual(owner_knowledge.context(self.index, '任何'), [])
        self.assertEqual(owner_knowledge.status(self.index)['state'], 'invalid')

        self.index.unlink()
        self.write('only.md', '# 唯一\n\nSTALE_TOKEN\n')
        self.build()
        (self.notes / 'only.md').unlink()
        stale = self.search('STALE_TOKEN')
        self.assertEqual((stale['state'], stale['results']), ('stale', []))
        self.assertEqual(owner_knowledge.context(self.index, 'STALE_TOKEN'), [])

    def test_cli_index_status_and_search_are_read_only_after_building(self):
        self.write('deploy.md', '# 部署\n\nCLI_TOKEN 在本地 WSL。\n')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['knowledge', 'index', '--db', str(self.inbox),
                         '--root', str(self.notes)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['state'], 'indexed')
        before = self.index.read_bytes()

        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['knowledge', 'status', '--db', str(self.inbox)])
        self.assertEqual(code, 0)
        status = json.loads(output.getvalue())
        self.assertTrue(status['read_only'])
        self.assertEqual(status['sources'], 1)
        self.assertEqual(self.index.read_bytes(), before)

        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['knowledge', 'search', '--db', str(self.inbox), '--query', 'CLI_TOKEN'])
        self.assertEqual(code, 0)
        hidden = json.loads(output.getvalue())
        self.assertEqual(hidden['results'][0]['path'], 'deploy.md')
        self.assertNotIn('text', hidden['results'][0])
        self.assertEqual(self.index.read_bytes(), before)

        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['knowledge', 'search', '--db', str(self.inbox),
                         '--query', 'CLI_TOKEN', '--show-text'])
        self.assertEqual(code, 0)
        self.assertIn('CLI_TOKEN', json.loads(output.getvalue())['results'][0]['text'])
        self.assertEqual(self.index.read_bytes(), before)

    def test_unicode_paths_are_supported(self):
        notes = self.root / '知识库'
        notes.mkdir()
        (notes / '部署.md').write_text('# 部署\n\nUNICODE_PATH_TOKEN 在这里。\n',
                                       encoding='utf-8', newline='\n')
        report = owner_knowledge.index(notes, self.inbox, now=self.NOW)
        self.assertEqual(report['files'], 1)
        found = owner_knowledge.search(self.index, 'UNICODE_PATH_TOKEN', now=self.NOW + 1)
        self.assertEqual([row['path'] for row in found['results']], ['部署.md'])
        self.assertIn('UNICODE_PATH_TOKEN', found['results'][0]['text'])

    def test_symbolic_links_are_refused(self):
        outside = self.root / 'outside.md'
        outside.write_text('# 外部\n\nOUTSIDE_TOKEN\n', encoding='utf-8')
        link = self.notes / 'link.md'
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are unavailable in this environment')
        self.write('good.md', '# 正常\n\nINSIDE_TOKEN\n')
        report = self.build()
        self.assertEqual(report['files'], 1)
        self.assertEqual(report['skipped'][0]['reason'], 'symbolic link')
        self.assertEqual(self.search('OUTSIDE_TOKEN')['results'], [])
        root_link = self.root / 'root-link'
        os.symlink(self.notes, root_link, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'knowledge directory'):
            owner_knowledge.index(root_link, self.inbox)


if __name__ == '__main__':
    unittest.main()