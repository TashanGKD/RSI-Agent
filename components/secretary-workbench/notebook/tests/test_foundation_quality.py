"""Independent quality-review regressions, using disposable synthetic notebooks."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from contracts import today
from contracts.source_refs import FIELDS
from modules.notebook import NotebookService


class FoundationQualityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.json'
        self.source.write_text('{"records":[]}', encoding='utf-8')
        self.n = NotebookService(self.root / 'book.sqlite3', self.source, self.root)

    def task(self, **fields):
        return self.n.create_task({'title': '合成质量复核事项', **fields})

    def test_removing_recurrence_cannot_reopen_a_completed_occurrence_on_note(self):
        t = self.task(state='待办', needsReview=False, planDate=today())
        entry = self.n.query_schedule(today(), today())['entries'][0]
        t = self.n.record(t['id'], {'expectedRevision': t['revision'],
            'recurrence': {'frequency': 'daily', 'startDate': today()}})
        t = self.n.record(t['id'], {'expectedRevision': t['revision'], 'recurrence': None})
        entry = self.n.get_schedule(entry['id'])
        self.n.schedule_record(entry['id'], {'expectedRevision': entry['revision'],
            'expectedObjectRevision': entry['objectRevision'], 'state': '已完成'})
        self.assertEqual(self.n.get_schedule(entry['id'])['state'], '已完成')
        t = self.n.get_task(t['id'])
        self.n.record(t['id'], {'expectedRevision': t['revision'], 'note': '合成普通补充备注'})
        self.assertEqual(self.n.get_schedule(entry['id'])['state'], '已完成')
        self.assertEqual(self.n.get_task(t['id'])['state'], '已完成')

        with self.subTest('completed occurrence keeps its own time when detached'):
            t = self.task(state='待办', needsReview=False, planDate=today(),
                          eventWindow={'start': today() + 'T10:00:00+08:00'})
            entry = next(e for e in self.n.query_schedule(today(), today())['entries']
                         if e['objectId'] == t['id'])
            t = self.n.record(t['id'], {'expectedRevision': t['revision'],
                'recurrence': {'frequency': 'daily', 'startDate': today()}})
            entry = self.n.get_schedule(entry['id'])
            self.n.schedule_record(entry['id'], {'expectedRevision': entry['revision'],
                'expectedObjectRevision': entry['objectRevision'], 'state': '已完成',
                'startTime': '12:00'})
            t = self.n.get_task(t['id'])
            t = self.n.record(t['id'], {'expectedRevision': t['revision'], 'recurrence': None})
            self.assertEqual(self.n.get_schedule(entry['id'])['state'], '已完成')
            self.assertEqual(self.n.get_schedule(entry['id'])['startTime'], '12:00')
            self.n.record(t['id'], {'expectedRevision': t['revision'], 'note': '取消循环后补充备注'})
            self.assertEqual(self.n.get_schedule(entry['id'])['startTime'], '12:00')

    def test_change_page_keeps_one_high_watermark_during_a_concurrent_commit(self):
        self.task()
        writer = NotebookService(self.n.db_file, self.source, self.root)
        real_connect = self.n._connect
        committed = []

        class ConnectionProxy:
            def __init__(self, db):
                self.db = db

            def execute(proxy, sql, *args):
                # Deterministically commit after the high-watermark read and
                # before the operation query, with a distinct writer connection.
                if not committed and sql.startswith('SELECT * FROM notebook_operations WHERE'):
                    committed.append(writer.create_task({'title': '合成并发提交'}))
                return proxy.db.execute(sql, *args)

            def __getattr__(self, name):
                return getattr(self.db, name)

        @contextmanager
        def interleaved_connect():
            with real_connect() as db:
                yield ConnectionProxy(db)

        with patch.object(self.n, '_connect', interleaved_connect):
            first = self.n.changes()
        self.assertEqual(len(committed), 1)
        first_ids = {op['id'] for op in first['operations']}
        self.assertTrue(all(op['sequence'] <= first['highWatermark']
                            for op in first['operations']))
        self.assertEqual(first['cursor'], first['highWatermark'])
        second = self.n.changes(first['cursor'])
        self.assertFalse(first_ids & {op['id'] for op in second['operations']})
        self.assertEqual(len(second['operations']), 1)
        self.assertEqual(second['operations'][0]['effects'][0]['id'], committed[0]['id'])

    def test_presentation_effects_capture_the_actual_object_before_and_after(self):
        t = self.task(needsReview=False)
        cursor = self.n.changes()['cursor']
        self.n.present(t['id'], {'expectedRevision': t['revision'], 'note': '合成本轮呈报'})
        op = self.n.changes(cursor)['operations'][0]
        effect = next(e for e in op['effects'] if e['kind'] == 'object')
        self.assertEqual(effect['before'], t)
        current = self.n.get_task(t['id'])
        self.assertEqual(effect['after'], current)
        self.assertTrue(current['needsReview'])
        cursor = op['sequence']
        self.n.record(t['id'], {'expectedRevision': current['revision'], 'confirm': True,
            'presentationId': current['presentation']['id'],
            'presentationVersion': current['presentation']['version']})
        op = self.n.changes(cursor)['operations'][0]
        effect = next(e for e in op['effects'] if e['kind'] == 'object')
        self.assertEqual(effect['before'], current)
        self.assertEqual(effect['after'], self.n.get_task(t['id']))
        self.assertEqual(effect['before']['presentation']['status'], 'pending')
        self.assertEqual(effect['after']['presentation']['status'], 'acknowledged')

    def test_restoring_source_contacts_accepts_the_derived_historical_projection(self):
        t = self.task(summary='历史摘要')
        ref = {'sourceId': 'wechat:synthetic', 'nativeId': 'message-one',
               'sender': '合成联系人', 'conversation': '合成会话'}
        self.n.append_record({'text': '合成关联原文', 'objectIds': [t['id']], 'sourceRefs': [ref]})
        sequence = self.n.changes()['cursor']
        t = self.n.get_task(t['id'])
        self.assertTrue(any('channel' in r for r in t['sourceContacts']))
        t = self.n.record(t['id'], {'expectedRevision': t['revision'], 'summary': '新摘要',
            'sourceContacts': [{'sourceId': 'wechat:synthetic', 'nativeId': 'manual-reference'}]})
        preview = self.n.restore_preview(t['id'], sequence=sequence,
                                         fields=['sourceContacts', 'summary'])
        self.assertTrue(all(set(r) <= FIELDS for r in preview['patch']['sourceContacts']))
        restored = self.n.restore(t['id'], {'sequence': sequence,
            'fields': ['sourceContacts', 'summary'], 'expectedRevision': preview['expectedRevision'],
            'requestId': 'QUALITY-restore-source'})
        self.assertEqual(restored['summary'], '历史摘要')
        self.assertTrue(any(r['nativeId'] == 'message-one' for r in restored['sourceContacts']))
        self.assertFalse(any(r['nativeId'] == 'manual-reference' for r in restored['sourceContacts']))
        self.assertEqual(len(self.n.list_records()), 1)


if __name__ == '__main__':
    unittest.main()
