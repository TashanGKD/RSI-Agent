"""State transitions use isolated fixtures; real human decisions are never touched."""
import unittest
from datetime import datetime, timedelta, timezone
import test_store as fixtures
from store import ValidationError


class SecretaryTests(unittest.TestCase):
    setUp = fixtures.StoreTests.setUp
    write_source = fixtures.StoreTests.write_source
    payload = fixtures.StoreTests.payload
    progress = fixtures.StoreTests.progress
    import_progress = fixtures.StoreTests.import_progress
    def state_event(self, state, at=None):
        return self.progress('SECRETARY-1', state=state, suggestedState=None,
                             at=at or datetime.now(timezone.utc).isoformat())

    def test_reject_invalid_ai_state_without_partial_import(self):
        before = self.store.task('T-1')
        for value in ['已完成<script>', 1, {}, '稍后提醒']:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                self.import_progress(self.state_event(value))
            self.assertEqual(self.store.task('T-1'), before)

    def test_reject_dangling_self_duplicate_and_path_relations(self):
        for value in [['MISSING'], ['T-1'], ['../T-2'], ['T-2', 'T-2'], 'T-2']:
            with self.subTest(value=value):
                self.data['records'][0]['relatedRecordIds'] = value
                self.write_source()
                with self.assertRaises(ValidationError):
                    self.store.refresh()
                self.assertEqual(self.store.task('T-1')['revision'], 0)

    def test_reject_future_ai_state_event(self):
        with self.assertRaises(ValidationError):
            self.import_progress(self.state_event('已完成',
                (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()))

    def test_ai_state_change_requires_saved_evidence(self):
        with self.assertRaises(ValidationError):
            self.import_progress(self.state_event('已完成') | {'sources':[]})

    def test_explicit_ai_closure_and_later_human_decision_share_state(self):
        prior = self.store.confirm('T-1', self.payload('等对方'))
        with self.store.connect() as db:
            human_before = [tuple(x) for x in db.execute('SELECT * FROM history')]
        self.import_progress(self.state_event('已完成'))
        closed = self.store.task('T-1')
        self.assertEqual(closed['selectedState'], '已完成')
        self.assertEqual(closed['stateUpdatedBy'], 'AI')
        self.assertEqual(closed['note'], prior['note'])
        with self.store.connect() as db:
            self.assertEqual([tuple(x) for x in db.execute('SELECT * FROM history')], human_before)
        timeline = self.store.detail('T-1')['timeline']
        self.assertEqual(timeline[0]['state'], '已完成')
        human = self.payload('已结束')
        human['expectedRevision'] = closed['revision']
        ended = self.store.confirm('T-1', human)
        self.assertEqual(ended['selectedState'], '已结束')
        self.assertEqual(ended['stateUpdatedBy'], '我')
        self.store.refresh()
        self.assertEqual(self.store.task('T-1')['selectedState'], '已结束')

    def test_ai_closure_suppresses_old_reminder_without_erasing_it(self):
        p = self.payload('稍后提醒')
        p['reminder'] = {'kind':'day1', 'at':(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), 'timezone':'UTC'}
        self.store.confirm('T-1', p)
        with self.store.connect() as db:
            db.execute("UPDATE decisions SET reminder_at='2000-01-01T00:00:00Z' WHERE id='T-1'")
        self.import_progress(self.state_event('已完成'))
        self.assertIsNone(self.store.task('T-1')['reminder'])
        self.assertEqual(self.store.due_reminders(), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute("SELECT state FROM decisions WHERE id='T-1'").fetchone()[0], '稍后提醒')

    def test_completed_atomic_item_and_waiting_next_stage_are_linked(self):
        self.data['records'][0]['relatedRecordIds'] = ['T-2']
        self.data['records'][1]['relatedRecordIds'] = ['T-1']
        event = self.state_event('已完成')
        self.import_progress(event)
        detail = self.store.detail('T-1')
        self.assertEqual(detail['task']['selectedState'], '已完成')
        self.assertEqual(detail['relatedTasks'][0]['id'], 'T-2')
        self.assertEqual(detail['relatedTasks'][0]['selectedState'], '等对方')
        self.assertEqual(self.store.task('T-1')['relatedRecordIds'], ['T-2'])
        self.assertEqual(self.store.refresh(), {'added':0,'changed':0,'retained':2})
        self.assertEqual(self.store.detail('T-1')['timeline'][0]['state'], '已完成')


if __name__ == '__main__':
    unittest.main()
