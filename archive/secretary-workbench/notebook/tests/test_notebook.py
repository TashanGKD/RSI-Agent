"""Isolated notebook contracts, including adversarial inputs before implementation.
Invariant: only validated local notebook fields may append events; errors must roll back.
Breaking inputs: '../secret' task IDs, state 'DROP TABLE tasks', actor with path field,
and an oversized note must all reject without any event or revision write.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from store import Store, ValidationError, ConflictError
try:
    from notebook import Notebook, STATES
except ImportError:
    Notebook = None
    STATES = []


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Notebook, 'Notebook operation layer must exist')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'main.json'
        self.data = {'records': [dict(recordId='T-1', action='反馈题目', status='交给AI处理'),
                                 dict(recordId='T-2', action='等意见', status='等对方')]}
        self.write_source()
        self.db = self.root / 'test.db'
        self.store = Notebook(self.db, self.source)
        self.store.refresh()

    def write_source(self):
        self.source.write_text(json.dumps(self.data, ensure_ascii=False))

    def record(self, rid='T-1', **changes):
        return self.store.record(rid, dict(expectedRevision=self.store.task(rid)['revision'], **changes))

    def reminder(self):
        return dict(kind='custom', at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat(), timezone='UTC')

    def test_in_progress_and_additional_reminder_presets_persist(self):
        task=self.record(state='进行中',reminder=dict(self.reminder(),kind='day2'))
        self.assertEqual(task['selectedState'],'待办')
        self.assertEqual(task['reminder']['kind'],'day2')
        self.record(reminder=dict(self.reminder(),kind='day7'))
        self.store.refresh()
        reopened=Notebook(self.db,self.source)
        self.assertEqual(reopened.task('T-1')['selectedState'],'待办')
        self.assertEqual(reopened.task('T-1')['reminder']['kind'],'day7')
        self.assertEqual(self.store.detail('T-1')['timeline'][-1]['state'],'待办')

    def test_pause_and_reminder_cancellation_are_independent(self):
        task=self.record(state='暂缓',reminder=dict(self.reminder(),kind='day2',timezone='Asia/Shanghai'))
        self.assertEqual(task['selectedState'],'暂缓')
        task=self.record(reminder=None)
        self.assertEqual(task['selectedState'],'暂缓')
        self.assertIsNone(task['reminder'])
        self.store.refresh()
        self.assertEqual(Notebook(self.db,self.source).task('T-1')['selectedState'],'暂缓')

    def test_human_review_is_separate_from_business_state_and_ai_updates(self):
        self.assertFalse(self.store.task('T-1')['reviewedByHuman'])
        self.record(state='待处理',actor={'name':'AI','kind':'ai'})
        self.assertFalse(self.store.task('T-1')['reviewedByHuman'])
        self.record(note='只补备注')
        self.assertFalse(self.store.task('T-1')['reviewedByHuman'])
        self.record(state='进行中')
        self.assertTrue(self.store.task('T-1')['reviewedByHuman'])
        self.record(state='等对方',actor={'name':'AI','kind':'ai'})
        self.assertTrue(self.store.task('T-1')['reviewedByHuman'])
        self.store.refresh()
        self.assertTrue(Notebook(self.db,self.source).task('T-1')['reviewedByHuman'])
        old=Store(self.db,self.source)
        old.confirm('T-2',dict(expectedRevision=0,state='待处理',note='既有批复',reminder=None))
        self.assertTrue(self.store.task('T-2')['reviewedByHuman'])

    def test_reject_path_id(self):
        with self.assertRaises(ValidationError):
            self.store.record('../secret', {'expectedRevision': 0, 'state': '待处理'})
        self.assertEqual(self.store.task('T-1')['revision'], 0)

    def test_reject_invalid_state_actor_unknown_and_oversized(self):
        for changes in [dict(state='DROP TABLE tasks'), dict(actor={'name':'AI','kind':'ai','path':'../secret'}),
                        dict(note='中'*4001), dict(assignee=[]), dict(unknown=True), dict(note='   '),
                        dict(actor={'name':'AI','kind':'admin'}), dict(state=[]), dict(expectedRevision=True)]:
            payload = dict(expectedRevision=0)
            payload.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                self.store.record('T-1', payload)
        self.assertEqual(self.store.task('T-1')['revision'], 0)
        self.assertEqual(self.store.detail('T-1')['timeline'], [])

    def test_reject_invalid_creation_and_rollback(self):
        for payload in [{}, {'title':' '}, {'title':'好','relatedRecordIds':['missing']},
                        {'title':'好','path':'/tmp/x'}, {'title':'好','proposedAt':'yesterday'},
                        {'title':'好','requestId':'../x'}, {'title':'好','state':{}}]:
            with self.subTest(payload=payload), self.assertRaises((ValidationError, KeyError)):
                self.store.create_task(payload)
        self.assertEqual(len(self.store.tasks()), 2)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notebook_events').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM local_items').fetchone()[0], 0)

    def test_create_defaults_related_refresh_restart(self):
        created = self.store.create_task(dict(title='修改方案并回复', note='新一轮要求', relatedRecordIds=['T-1']))
        self.assertEqual((created['selectedState'],created['assignee'],created['counterparty']), ('待判断','我','为自己'))
        self.assertEqual(created['relatedRecordIds'], ['T-1'])
        self.assertTrue(created['proposedAt'])
        self.store.refresh()
        reopened = Notebook(self.db, self.source)
        self.assertTrue(reopened.task(created['id'])['active'])
        self.assertEqual(len(reopened.tasks()), 3)
        self.assertEqual(reopened.detail('T-1')['relatedTasks'][0]['id'], created['id'])
        self.assertEqual(reopened.detail(created['id'])['timeline'][0]['body'], '新一轮要求')

    def test_notes_append_without_state_assignment_or_reminder_change(self):
        before = self.record(state='等对方', assignee='我', reminder=self.reminder())
        first = self.record(note='等吕老师具体意见')
        second = self.record(note='材料已补', actor={'name':'AI','kind':'ai'})
        for key in ['selectedState','assignee','reminder']:
            self.assertEqual(second[key], before[key])
        self.assertEqual(second['note'], '材料已补')
        reopened = Notebook(self.db,self.source)
        notes = [e['body'] for e in reopened.detail('T-1')['timeline'] if e.get('body')]
        self.assertEqual(notes, ['材料已补','等吕老师具体意见'])
        self.assertEqual(first['revision']+1,second['revision'])

    def test_actor_and_human_share_same_operations(self):
        t = self.store.create_task(dict(title='AI新增', actor={'name':'AI','kind':'ai'}))
        t = self.record(t['id'], state='待处理', assignee='AI', actor={'name':'我','kind':'human'})
        self.assertEqual((t['selectedState'],t['assignee']),('待办','AI'))
        detail = self.store.detail(t['id'])
        self.assertEqual({e['actor']['kind'] for e in detail['timeline']},{'human','ai'})

    def test_idempotency_current_readback_collision_and_conflict(self):
        payload = dict(title='新事项', requestId='create-1')
        task = self.store.create_task(payload)
        changed = self.record(task['id'], note='后续')
        self.assertEqual(self.store.create_task(payload), changed)
        with self.assertRaises(ConflictError):
            self.store.create_task(dict(payload,title='不同'))
        p = dict(expectedRevision=changed['revision'], note='幂等备注', requestId='record-1')
        updated = self.store.record(task['id'],p)
        self.assertEqual(self.store.record(task['id'],p),updated)
        with self.assertRaises(ConflictError): self.store.record('T-1',p)
        with self.assertRaises(ConflictError): self.store.record(task['id'],dict(p,note='冲突'))
        with self.assertRaises(ConflictError): self.store.record(task['id'],dict(expectedRevision=0,state='已完成'))
        self.assertEqual(len([e for e in self.store.detail(task['id'])['timeline'] if e.get('body')=='幂等备注']),1)

    def test_reminder_independent_closing_suppresses_and_reopen_stays_clear(self):
        t = self.record(state='等对方', reminder=self.reminder())
        self.assertEqual(t['selectedState'],'等对方')
        closed = self.record(state='已完成')
        self.assertIsNone(closed['reminder'])
        self.assertEqual(self.store.due_reminders(),[])
        reopened = self.record(state='待处理')
        self.assertIsNone(reopened['reminder'])
        self.assertTrue(any(e.get('reminder') for e in self.store.detail('T-1')['timeline']))

    def test_legacy_preserved_and_state_by_actual_event_time(self):
        old = Store(self.db,self.source)
        old.confirm('T-1',dict(expectedRevision=0,state='稍后提醒',note='旧备注',reminder=self.reminder()))
        with old.connect() as db:
            legacy = {table:[dict(r) for r in db.execute('SELECT * FROM '+table)] for table in ['decisions','history','progress_updates','source_versions']}
        t = self.store.task('T-1')
        self.assertEqual((t['selectedState'],t['assignee'],t['note']),('待办','我','旧备注'))
        self.assertIsNotNone(t['reminder'])
        self.record(state='已完成')
        event = dict(id='older-ai', at='2026-10-01T00:00:00Z',author='AI',body='旧催办',state='待处理',sources=[dict(label='原文',quote='旧催办')])
        self.data['records'][0]['progressUpdates']=[event]
        self.write_source(); self.store.refresh()
        self.assertEqual(self.store.task('T-1')['selectedState'],'已完成')
        with old.connect() as db:
            for table in ['decisions','history']:
                self.assertEqual([dict(r) for r in db.execute('SELECT * FROM '+table)],legacy[table])
        self.assertEqual(len(self.store.detail('T-1')['timeline']),3)

    def test_newer_legacy_ai_state_and_human_history_are_composed(self):
        self.record(state='已完成')
        with self.store.connect() as db:
            db.execute("UPDATE notebook_events SET at='2026-10-01T00:00:00Z'")
            db.execute("INSERT INTO history(id,at,state,note) VALUES('T-1','2026-10-02T00:00:00Z','等对方','历史人工')")
        self.assertEqual(self.store.task('T-1')['selectedState'],'等对方')
        event=dict(id='new-ai',at='2026-10-03T00:00:00Z',author='AI',body='AI完成',state='已结束',sources=[dict(label='依据',quote='已结束')])
        self.data['records'][0]['progressUpdates']=[event]
        self.write_source();self.store.refresh()
        self.assertEqual(self.store.task('T-1')['selectedState'],'不用管了')

    def test_legacy_confirm_preserves_assignment_reminder_and_prior_note(self):
        t=self.record(state='等对方',assignee='李老师',note='保留',reminder=self.reminder())
        t=self.store.confirm('T-1',dict(expectedRevision=t['revision'],state='待处理',note='',reminder=None))
        self.assertEqual(t['assignee'],'李老师')
        self.assertIsNotNone(t['reminder'])
        self.assertEqual(t['note'],'保留')
        t=self.store.confirm('T-1',dict(expectedRevision=t['revision'],state='交给AI处理',note='转AI',reminder=None))
        self.assertEqual((t['selectedState'],t['assignee']),('待办','AI'))

    def test_failed_record_reminder_rolls_back_note_and_state(self):
        before=self.store.task('T-1')
        with self.assertRaises(ValidationError): self.record(note='不得保存',state='等对方',reminder={'kind':'custom','at':'yesterday','timezone':'UTC'})
        self.assertEqual(self.store.task('T-1'),before)
        self.assertEqual(self.store.detail('T-1')['timeline'],[])

    def test_provenance_preserves_source_time_and_safe_links_for_local_and_source(self):
        evidence=self.root/'quote.md';evidence.write_text('资料')
        source=dict(label='原始材料',path=str(evidence),quote='原文')
        t=self.store.create_task(dict(title='有依据',note='记录',sourceTime='2026-09-20',sources=[source]))
        self.record('T-1',note='补充',sourceTime='2026-10-20T08:00:00-04:00',sources=[source])
        for rid in [t['id'],'T-1']:
            detail=self.store.detail(rid)
            event=detail['timeline'][0]
            self.assertIsNotNone(event['sourceTime'])
            self.assertNotIn('path',event['sources'][0])
            index=int(event['sources'][0]['url'].rsplit('/',1)[1])
            self.assertEqual(self.store.source(rid,index),evidence.resolve())
            self.assertNotIn(str(evidence),json.dumps(detail))
        t=self.record(t['id'],note='仅引文',sources=[dict(label='本人所知',quote='事实')])
        self.assertEqual(self.store.detail(t['id'])['timeline'][0]['sources'],[dict(label='本人所知',quote='事实')])

    def test_reject_unsafe_provenance_before_any_write(self):
        outside=self.root.parent/'outside-secret.md'
        # No file is created outside the isolated fixture; escape must reject regardless.
        bad=self.root/'bad.html';bad.write_text('<script>x</script>')
        for changes in [dict(sourceTime='yesterday'),dict(sourceTime='2026-10-20T10:00:00'),
                        dict(sources=[dict(label='x',path='../outside-secret.md',quote='x')]),
                        dict(sources=[dict(label='x',path=str(bad),quote='x')]),
                        dict(sources=[dict(label='x')]),dict(sources=[dict(label='x',quote='y',evil=True)])]:
            with self.subTest(changes=changes),self.assertRaises(ValidationError):
                self.record(note='不得保存',**changes)
        self.assertEqual(self.store.task('T-1')['revision'],0)
        self.assertEqual(self.store.detail('T-1')['timeline'],[])

    def test_ack_is_idempotent_system_event_and_keeps_waiting_state(self):
        self.record(state='等对方',reminder=self.reminder())
        with self.store.connect() as db:
            row=db.execute('SELECT seq,payload FROM notebook_events ORDER BY seq DESC LIMIT 1').fetchone()
            value=json.loads(row['payload']);value['reminder']['at']='2000-01-01T00:00:00+00:00'
            db.execute('UPDATE notebook_events SET payload=? WHERE seq=?',(json.dumps(value),row['seq']))
        self.assertEqual(len(self.store.due_reminders()),1)
        task=self.store.ack_reminder('T-1')
        self.assertEqual(task['selectedState'],'等对方')
        self.assertEqual(self.store.due_reminders(),[])
        self.assertEqual(self.store.ack_reminder('T-1'),task)
        self.assertEqual(self.store.detail('T-1')['timeline'][0]['actor'],{'name':'记事本','kind':'ai'})

    def test_note_only_does_not_confirm_unjudged_state(self):
        self.assertFalse(self.store.task('T-1')['confirmed'])
        task=self.record(note='补充信息')
        self.assertFalse(task['confirmed'])
        self.assertEqual((task['selectedState'],task['assignee']),('待办','AI'))

    def test_transaction_failure_after_event_insert_rolls_back_every_write(self):
        import sqlite3
        before=self.store.task('T-1')
        with self.store.connect() as db:
            db.execute("CREATE TRIGGER refuse_revision BEFORE UPDATE ON tasks BEGIN SELECT RAISE(ABORT,'fixture failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.record(note='必须回滚',state='已完成',requestId='rolled-back')
        self.assertEqual(self.store.task('T-1'),before)
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM notebook_events').fetchone()[0],0)
            db.execute('DROP TRIGGER refuse_revision')
        self.record(note='重试可保存',requestId='rolled-back')
        self.assertEqual(self.store.task('T-1')['note'],'重试可保存')

if __name__=='__main__': unittest.main()
