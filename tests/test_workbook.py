import contextlib
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from rsi_agent import workbook
from rsi_agent.__main__ import main


class WorkbookTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name) / 'memory'
        self.root.mkdir()
        self.curated = self.root / 'CURRENT.md'
        self.curated.write_text('# Curated checkpoint\n', encoding='utf-8', newline='\n')

    def create(self, title='接入工作本', file_name='work-item.md', **changes):
        values = dict(source='用户要求在 2026-11-25 接入工作本。',
                      goal='生成当前视图并通过检查。',
                      next_step='运行生成器并核对输出。',
                      thought='保留 CURRENT.md 作为项目基线。',
                      time='2026-11-25',
                      file_name=file_name)
        values.update(changes)
        return workbook.create(self.root, title, **values)

    def test_new_refresh_and_check_close_the_loop(self):
        created = self.create()
        note = Path(created['note'])
        self.assertTrue(note.is_file())
        preview = workbook.refresh(self.root)
        self.assertFalse(preview['written'])
        self.assertFalse(preview['consistent'])
        result = workbook.refresh(self.root, execute=True)
        self.assertTrue(result['written'])
        self.assertTrue(result['consistent'])
        target = self.root / workbook.TARGET
        text = target.read_text(encoding='utf-8')
        self.assertTrue(text.startswith(workbook.GENERATED))
        self.assertIn('## 待推进 · 1', text)
        self.assertIn('[接入工作本](workbook/work-item.md)', text)
        self.assertEqual(self.curated.read_text(encoding='utf-8'), '# Curated checkpoint\n')
        self.assertTrue(workbook.check(self.root)['consistent'])

        note.write_text(note.read_text(encoding='utf-8')
                        .replace('- **现在怎么样**：待推进', '- **现在怎么样**：已办好')
                        .replace('- **下一步**：运行生成器并核对输出。',
                                 '- **下一步**：回归已通过；按实际使用决定是否增加编辑命令。')
                        + '\n- 2026-11-25：完成最小闭环。\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'differs'):
            workbook.check(self.root)
        workbook.refresh(self.root, execute=True)
        self.assertIn('## 已办好 · 1', target.read_text(encoding='utf-8'))
        self.assertTrue(workbook.check(self.root)['consistent'])

    def test_refresh_refuses_a_hand_written_generated_view(self):
        self.create()
        target = self.root / workbook.TARGET
        target.write_text('# hand written\n', encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'not owned'):
            workbook.refresh(self.root, execute=True)
        self.assertEqual(target.read_text(encoding='utf-8'), '# hand written\n')

    def test_refresh_requires_actual_notes(self):
        (self.root / 'workbook').mkdir()
        with self.assertRaisesRegex(ValueError, 'no work notes'):
            workbook.refresh(self.root)
        self.assertFalse((self.root / workbook.TARGET).exists())

    def test_check_rejects_a_missing_generated_view(self):
        self.create()
        with self.assertRaisesRegex(ValueError, 'missing or differs'):
            workbook.check(self.root)
        self.assertFalse((self.root / workbook.TARGET).exists())

    def test_collect_rejects_missing_field_and_unknown_state(self):
        created = self.create()
        path = Path(created['note'])
        original = path.read_text(encoding='utf-8')
        for old, new, pattern in [
            ('- **我的想法**：保留 CURRENT.md 作为项目基线。\n', '', 'eight current fields'),
            ('- **现在怎么样**：待推进', '- **现在怎么样**：进行中', 'known state'),
        ]:
            path.write_text(original.replace(old, new), encoding='utf-8', newline='\n')
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, pattern):
                workbook.collect(self.root)
        path.write_text(original, encoding='utf-8', newline='\n')

    def test_collect_rejects_duplicate_titles(self):
        self.create(file_name='first.md')
        second = self.create(title='另一件事', file_name='second.md')
        path = Path(second['note'])
        path.write_text(path.read_text(encoding='utf-8')
                        .replace('- **事情**：另一件事', '- **事情**：接入工作本'),
                        encoding='utf-8', newline='\n')
        with self.assertRaisesRegex(ValueError, 'distinct result titles'):
            workbook.collect(self.root)

    def test_new_requires_a_waiting_condition_and_does_not_write(self):
        for time in ('未定', '未安排复看时间'):
            with self.subTest(time=time), self.assertRaisesRegex(ValueError, 'waiting must explain'):
                self.create(state='等反馈', next_step='继续推进', time=time)
        self.assertFalse((self.root / 'workbook' / 'work-item.md').exists())

    def test_new_rejects_multiline_values_and_path_names(self):
        with self.assertRaisesRegex(ValueError, 'one line'):
            self.create(source='两行\n来源')
        with self.assertRaisesRegex(ValueError, 'plain .md'):
            self.create(file_name='../outside.md')
        with self.assertRaisesRegex(ValueError, 'plain .md'):
            self.create(file_name='bad:name.md')
        with self.assertRaisesRegex(ValueError, 'workbook markers'):
            self.create(source='<!-- rsi-work:end -->')
        self.assertFalse((Path(self.folder.name) / 'outside.md').exists())

    def test_new_does_not_overwrite_or_reuse_a_title(self):
        first = self.create(file_name='same.md')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            self.create(title='另一件事', file_name='same.md')
        with self.assertRaisesRegex(ValueError, 'distinct result titles'):
            self.create(file_name='another.md')
        with self.assertRaisesRegex(ValueError, 'distinct result titles'):
            self.create(title=' 接入工作本 ', file_name='trimmed.md')
        self.assertEqual(Path(first['note']).name, 'same.md')
        self.assertFalse((self.root / 'workbook' / 'another.md').exists())

    def test_new_derives_a_safe_unicode_file_name(self):
        created = self.create(file_name=None)
        self.assertEqual(Path(created['note']).name, '接入工作本.md')
        self.assertTrue((self.root / 'workbook' / '接入工作本.md').is_file())

    def test_render_escapes_table_and_link_markup(self):
        rows = [{'事情': 'A | B [x]', '怎么来的': 's', '这次想做到什么': 'g | h',
                 '我的想法': 't', '现在怎么样': '待推进', '下一步': 'n',
                 '时间': '2026-11-25', '过程笔记': 'p', 'file': 'a b.md'}]
        text = workbook.render(rows)
        self.assertIn('A \\| B \\[x\\]', text)
        self.assertIn('g \\| h', text)
        self.assertIn('workbook/a%20b.md', text)

    def test_symlink_note_is_refused(self):
        created = self.create()
        note = Path(created['note'])
        outside = Path(self.folder.name) / 'outside.md'
        note.replace(outside)
        try:
            os.symlink(outside, note)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks are unavailable in this environment')
        with self.assertRaisesRegex(ValueError, 'symbolic link'):
            workbook.collect(self.root)

    def test_set_updates_summary_and_appends_one_process_line(self):
        created = self.create()
        result = workbook.update_note(
            self.root, title='接入工作本', state='已办好',
            next_step='已完成；等待归档。', log='实现并通过定向测试。')
        self.assertEqual(result['state'], 'updated')
        self.assertTrue(result['archive_ready'])
        self.assertIn('log', result['changed'])
        note = Path(created['note'])
        text = note.read_text(encoding='utf-8')
        self.assertIn('- **现在怎么样**：已办好', text)
        self.assertIn('- **下一步**：已完成；等待归档。', text)
        self.assertIn('实现并通过定向测试。', text)
        with self.assertRaisesRegex(ValueError, 'differs'):
            workbook.check(self.root)
        workbook.refresh(self.root, execute=True)
        self.assertIn('## 已办好 · 1', (self.root / workbook.TARGET).read_text(encoding='utf-8'))

    def test_set_requires_a_selector_and_at_least_one_change(self):
        self.create()
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            workbook.update_note(self.root)
        with self.assertRaisesRegex(ValueError, 'at least one'):
            workbook.update_note(self.root, title='接入工作本')
        with self.assertRaisesRegex(ValueError, 'not found'):
            workbook.update_note(self.root, title='不存在', log='不应写入')

    def test_set_refuses_a_limit_violation_without_writing(self):
        created = self.create()
        note = Path(created['note'])
        before = note.read_text(encoding='utf-8')
        with mock.patch.object(workbook, 'MAX_ACTIVE_ITEMS', 0):
            with self.assertRaisesRegex(ValueError, 'active work limit'):
                workbook.update_note(self.root, title='接入工作本', thought='新判断')
        self.assertEqual(note.read_text(encoding='utf-8'), before)

    def test_set_refuses_a_note_changed_after_selection(self):
        created = self.create()
        path = Path(created['note'])
        row = workbook.collect(self.root, enforce=False)[0][0]
        stale = hashlib.sha256(path.read_bytes()).hexdigest()
        path.write_text(path.read_text(encoding='utf-8') + '\n', encoding='utf-8', newline='\n')
        before = path.read_text(encoding='utf-8')
        with mock.patch.object(workbook, 'choose', return_value=(path, row, stale)):
            with self.assertRaisesRegex(ValueError, 'changed by another writer'):
                workbook.update_note(self.root, title='接入工作本', thought='新判断')
        self.assertEqual(path.read_text(encoding='utf-8'), before)

    def test_new_respects_active_and_visible_limits(self):
        self.create(file_name='first.md')
        with mock.patch.object(workbook, 'MAX_ACTIVE_ITEMS', 1):
            with self.assertRaisesRegex(ValueError, 'active work limit'):
                self.create(title='第二件', file_name='second.md')
        self.assertFalse((self.root / 'workbook' / 'second.md').exists())
        with mock.patch.object(workbook, 'MAX_VISIBLE_ITEMS', 1):
            with self.assertRaisesRegex(ValueError, 'visible work limit'):
                self.create(title='第三件', file_name='third.md')
        self.assertFalse((self.root / 'workbook' / 'third.md').exists())

    def test_review_reports_limits_and_stale_view_without_writing(self):
        self.create()
        with mock.patch.object(workbook, 'MAX_ACTIVE_ITEMS', 0):
            result = workbook.review(self.root)
        self.assertEqual(result['active'], 1)
        self.assertEqual(result['visible'], 1)
        self.assertEqual(result['archived'], 0)
        self.assertEqual(result['view'], 'missing')
        self.assertTrue(any(problem['kind'] == 'active_items' for problem in result['over']))
        self.assertFalse((self.root / workbook.TARGET).exists())

    def test_summary_and_view_byte_limits_are_enforced(self):
        with mock.patch.object(workbook, 'MAX_SUMMARY_CHARS', 10):
            with self.assertRaisesRegex(ValueError, 'current summary exceeds'):
                self.create(file_name='long.md')
        self.assertFalse((self.root / 'workbook' / 'long.md').exists())

        self.create()
        with mock.patch.object(workbook, 'MAX_CURRENT_BYTES', 100):
            with self.assertRaisesRegex(ValueError, 'CURRENT.workbook.md exceeds'):
                workbook.refresh(self.root, execute=True)
            with mock.patch.object(workbook, 'MAX_SUMMARY_CHARS', 10):
                reviewed = workbook.review(self.root)
        self.assertFalse((self.root / workbook.TARGET).exists())
        self.assertTrue(any(problem['kind'] == 'current_bytes' for problem in reviewed['over']))

    def test_archive_previews_then_moves_a_closed_note_out_of_the_view(self):
        created = self.create(state='已办好', next_step='已完成；可归档。')
        workbook.refresh(self.root, execute=True)
        note = Path(created['note'])
        preview = workbook.archive(self.root, title='接入工作本')
        self.assertFalse(preview['written'])
        self.assertTrue(note.exists())
        archived = workbook.archive(self.root, title='接入工作本', execute=True)
        self.assertTrue(archived['written'])
        self.assertFalse(note.exists())
        target = Path(archived['target'])
        self.assertTrue(target.is_file())
        self.assertEqual(archived['visible'], 0)
        workbook.refresh(self.root, execute=True)
        text = (self.root / workbook.TARGET).read_text(encoding='utf-8')
        self.assertNotIn('接入工作本', text)
        self.assertIn('已归档笔记不进入本页', text)
        reviewed = workbook.review(self.root)
        self.assertEqual(reviewed['notes'], 0)
        self.assertEqual(reviewed['archived'], 1)
        self.assertEqual(reviewed['view'], 'current')

    def test_archive_refuses_active_work_and_an_existing_target(self):
        created = self.create()
        with self.assertRaisesRegex(ValueError, 'requires 已办好 or 不做了'):
            workbook.archive(self.root, title='接入工作本', execute=True)
        self.assertTrue(Path(created['note']).exists())

        closed = self.create(title='另一件事', file_name='closed.md', state='已办好',
                             next_step='已完成；可归档。')
        archive_dir = self.root / 'workbook' / workbook.ARCHIVE
        archive_dir.mkdir()
        (archive_dir / Path(closed['note']).name).write_text('occupied\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'archive target already exists'):
            workbook.archive(self.root, title='另一件事', execute=True)
        self.assertTrue(Path(closed['note']).exists())

    def test_cli_set_review_and_archive(self):
        self.create(state='已办好', next_step='已完成；可归档。', file_name='cli.md')
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['workbook', 'review', '--root', str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn('"active": 0', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['workbook', 'set', '--root', str(self.root), '--file', 'cli.md',
                         '--log', '通过 CLI 更新。'])
        self.assertEqual(code, 0)
        self.assertIn('"state": "updated"', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['workbook', 'archive', '--root', str(self.root), '--file', 'cli.md',
                         '--execute'])
        self.assertEqual(code, 0)
        self.assertIn('"state": "archived"', output.getvalue())
        self.assertFalse((self.root / 'workbook' / 'cli.md').exists())

    def test_cli_workbook_does_not_require_a_private_config(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['workbook', 'new', '--root', str(self.root), '--title', 'CLI 工作本',
                         '--source', '测试', '--goal', '生成视图', '--next', '刷新',
                         '--time', '2026-11-25', '--file', 'cli.md'])
        self.assertEqual(code, 0)
        self.assertIn('created', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['workbook', 'refresh', '--root', str(self.root), '--execute'])
        self.assertEqual(code, 0)
        self.assertIn('"written": true', output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()):
            code = main(['workbook', 'check', '--root', str(self.root)])
        self.assertEqual(code, 0)


if __name__ == '__main__':
    unittest.main()