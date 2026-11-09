"""Regression evidence from review; every test uses a disposable synthetic book."""
import tempfile
import unittest
from datetime import datetime, date, timedelta
from pathlib import Path
from unittest.mock import patch

from contracts import today
from modules.notebook import NotebookService, ConflictError, ValidationError
from modules.notebook.reviews import followup_key


class FoundationReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        source = root / 'source.json'
        source.write_text('{"records":[]}')
        self.n = NotebookService(root / 'book.sqlite3', source, root)

    def task(self, **fields):
        return self.n.create_task({'title': '合成复核事项', **fields})

    def test_current_timed_followup_does_not_appear_before_its_instant(self):
        current_day = today()
        fixed = datetime.fromisoformat(current_day + 'T09:00:00+08:00')

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed.astimezone(tz) if tz else fixed.replace(tzinfo=None)

        with patch('modules.notebook.reviews.datetime', FrozenDatetime):
            t = self.task(state='等对方', needsReview=False,
                          followup={'at': current_day + 'T19:30:00+08:00'})
            self.assertFalse(t['followupDue'])
            self.assertEqual(self.n.due_followups()['items'], [])
            self.assertEqual(self.n.query('review'), [])
            self.assertEqual(self.n.due_followups(at=current_day + 'T19:29:59+08:00')['items'], [])
            self.assertEqual([x['objectId'] for x in self.n.due_followups(at=current_day + 'T19:30:00+08:00')['items']], [t['id']])

    def test_old_occurrence_cannot_replace_a_later_plan(self):
        day0 = today()
        day1 = (date.fromisoformat(day0) + timedelta(days=1)).isoformat()
        day3 = (date.fromisoformat(day0) + timedelta(days=3)).isoformat()
        t = self.task(state='待办', planDate=day0, confirm=True)
        old = self.n.query_schedule(day0, day0)['entries'][0]
        self.n.schedule_record(old['id'], {
            'expectedRevision': old['revision'], 'expectedObjectRevision': t['revision'],
            'state': '暂缓', 'postponeTo': {'date': day3},
        })
        old = self.n.get_schedule(old['id'])
        before = self.n.changes()['cursor']
        with self.assertRaises(ConflictError):
            self.n.schedule_record(old['id'], {
                'expectedRevision': old['revision'], 'expectedObjectRevision': old['objectRevision'],
                'state': '暂缓', 'postponeTo': {'date': day1},
            })
        self.assertEqual(self.n.get_task(t['id'])['planDate'], day3)
        self.assertEqual(self.n.changes()['cursor'], before)
        self.assertEqual(self.n.query_schedule(day1, day1)['entries'], [])

    def test_late_linked_source_is_historical_only_after_its_import(self):
        t = self.task()
        before = self.n.changes()['cursor']
        ref = {'sourceId': 'wechat:synthetic', 'nativeId': 'message-100',
               'conversation': '合成会话', 'sender': '合成联系人', 'at': '2000-01-01', 'precision': 'date'}
        self.n.append_record({'text': '晚导入的合成旧消息', 'objectIds': [t['id']], 'sourceRefs': [ref]})
        past = next(x for x in self.n.as_of(sequence=before)['objects'] if x['id'] == t['id'])
        now = next(x for x in self.n.as_of()['objects'] if x['id'] == t['id'])
        live = self.n.get_task(t['id'])
        self.assertEqual(past['evidence'], [])
        self.assertEqual(now['evidence'], live['evidence'])
        self.assertEqual(now['sourceContacts'], live['sourceContacts'])
        self.assertGreater(live['revision'], t['revision'])
        changes = self.n.changes(before, object_id=t['id'])['operations']
        self.assertEqual(len(changes), 1)
        self.assertEqual({x['kind'] for x in changes[0]['effects']}, {'record', 'object'})

    def test_new_pending_candidate_has_a_versioned_presentation_in_same_operation(self):
        t = self.task(recommendation={'state': '待办', 'reason': '合成建议'})
        self.assertTrue(t['needsReview'])
        p = t['presentation']
        self.assertEqual(p['version'], 1)
        self.assertEqual(p['objectId'], t['id'])
        op = self.n.changes(object_id=t['id'])['operations'][0]
        self.assertEqual({x['kind'] for x in op['effects']}, {'object', 'presentation'})
        seq = op['sequence']
        result = self.n.record(t['id'], {'expectedRevision': t['revision'], 'confirm': True,
                                       'presentationId': p['id'], 'presentationVersion': p['version']})
        self.assertFalse(result['needsReview'])
        past = next(x for x in self.n.as_of(sequence=seq)['objects'] if x['id'] == t['id'])
        self.assertTrue(past['needsReview'])
        self.assertEqual(past['presentation']['status'], 'pending')

    def test_followup_ack_is_available_in_historical_projection(self):
        t = self.task(needsReview=False, followup={'date': '2000-01-01'})
        before = self.n.changes()['cursor']
        self.assertTrue(t['followupDue'])
        receipt = self.n.acknowledge_followup(t['id'], {
            'expectedRevision': t['revision'], 'followupKey': followup_key(t), 'note': '合成核查回执',
        })
        old = next(x for x in self.n.as_of(sequence=before)['objects'] if x['id'] == t['id'])
        current = self.n.as_of()
        self.assertTrue(old['followupDue'])
        self.assertFalse(next(x for x in current['objects'] if x['id'] == t['id'])['followupDue'])
        self.assertEqual([r['id'] for r in current['followupReceipts']], [receipt['id']])

    def test_unlink_operation_remains_in_former_object_history(self):
        t = self.task()
        r = self.n.append_record({'text': '合成关联留言', 'objectIds': [t['id']]})
        cursor = self.n.changes()['cursor']
        self.n.set_record_processing(r['id'], 'completed', '合成移除关联', object_ids=[])
        global_ops = self.n.changes(cursor)['operations']
        object_ops = self.n.changes(cursor, object_id=t['id'])['operations']
        self.assertEqual(len(global_ops), 1)
        self.assertEqual([op['id'] for op in object_ops], [op['id'] for op in global_ops])

    def test_later_link_and_unlink_rebuild_source_projection_and_revision(self):
        t = self.task()
        r = self.n.append_record({'text': '合成晚关联来源', 'sourceRefs': [
            {'sourceId': 'wechat:synthetic', 'nativeId': 'message-200'}]})
        self.n.set_record_processing(r['id'], 'completed', '合成新增关联', object_ids=[t['id']])
        linked = self.n.get_task(t['id'])
        linked_sequence = self.n.changes()['cursor']
        historical_linked = next(x for x in self.n.as_of()['objects'] if x['id'] == t['id'])
        self.assertEqual(historical_linked['evidence'], linked['evidence'])
        self.assertGreater(linked['revision'], t['revision'])
        self.n.set_record_processing(r['id'], 'completed', '合成解除关联', object_ids=[])
        unlinked = self.n.get_task(t['id'])
        self.assertGreater(unlinked['revision'], linked['revision'])
        historical_unlinked = next(x for x in self.n.as_of()['objects'] if x['id'] == t['id'])
        self.assertEqual(historical_unlinked['sourceContacts'], unlinked['sourceContacts'])
        past = next(x for x in self.n.as_of(sequence=linked_sequence)['objects'] if x['id'] == t['id'])
        self.assertEqual(past['sourceContacts'], linked['sourceContacts'])

    def test_converting_existing_plan_to_recurrence_does_not_close_definition(self):
        t = self.task(state='待办', planDate=today(), confirm=True)
        entry = self.n.query_schedule(today(), today())['entries'][0]
        t = self.n.record(t['id'], {'expectedRevision': t['revision'], 'recurrence': {
            'frequency': 'daily', 'startDate': today(),
        }})
        entry = self.n.get_schedule(entry['id'])
        self.n.schedule_record(entry['id'], {
            'expectedRevision': entry['revision'], 'expectedObjectRevision': entry['objectRevision'],
            'state': '已完成',
        })
        definition = self.n.get_task(t['id'])
        self.assertEqual(definition['state'], '待办')
        self.assertTrue(definition['recurrence']['enabled'])

    def test_explicit_recurring_occurrence_completion_and_rule_pause_are_separate(self):
        t = self.task(state='待办', needsReview=False, recurrence={
            'frequency': 'daily', 'startDate': today(),
        })
        self.assertEqual(self.n.query_schedule(today(), today())['entries'], [])
        entry = self.n.create_schedule({'objectId': t['id'], 'date': today(),
                                       'expectedObjectRevision': t['revision'], 'requestId': 'INSTANCE-one'})
        duplicate = self.n.create_schedule({'objectId': t['id'], 'date': today(),
                                           'expectedObjectRevision': t['revision'], 'requestId': 'INSTANCE-one'})
        self.assertEqual(entry['id'], duplicate['id'])
        self.n.schedule_record(entry['id'], {
            'expectedRevision': entry['revision'], 'expectedObjectRevision': entry['objectRevision'],
            'state': '已完成',
        })
        definition = self.n.get_task(t['id'])
        self.assertEqual(definition['state'], '待办')
        self.assertTrue(definition['recurrence']['enabled'])
        paused = self.n.record(t['id'], {'expectedRevision': definition['revision'],
                                       'recurrence': dict(definition['recurrence'], enabled=False)})
        next_day = (date.fromisoformat(today()) + timedelta(days=1)).isoformat()
        with self.assertRaises(ValidationError):
            self.n.create_schedule({'objectId': t['id'], 'date': next_day,
                                    'expectedObjectRevision': paused['revision']})
        self.assertEqual(self.n.get_schedule(entry['id'])['state'], '已完成')

    def test_pending_recurring_instance_is_overdue_independent_of_definition_state(self):
        yesterday = (date.fromisoformat(today()) - timedelta(days=1)).isoformat()
        t = self.task(needsReview=False, recurrence={'frequency': 'daily', 'startDate': yesterday})
        self.assertEqual(t['state'], '其他')
        entry = self.n.create_schedule({'objectId': t['id'], 'date': yesterday,
                                       'expectedObjectRevision': t['revision']})
        self.assertEqual(entry['state'], '待办')
        self.assertEqual([x['id'] for x in self.n.query_schedule(today(), today())['overdue']], [entry['id']])


if __name__ == '__main__':
    unittest.main()
