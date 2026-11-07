"""Round contract. Reject unknown kinds, forged recommendation enums and malformed contact lists without writes."""
import unittest
import test_notebook as base
from notebook import STATES
from store import ValidationError

class RoundTests(unittest.TestCase):
    setUp=base.NotebookTests.setUp
    write_source=base.NotebookTests.write_source
    record=base.NotebookTests.record
    reminder=base.NotebookTests.reminder
    def test_new_round_preserves_history_resets_review_and_separates_recommendation(self):
        self.record(state='进行中',note='本人旧判断')
        task=self.record(actor={'name':'秘书','kind':'ai'},reviewRound='20261022-R2',state='待判断',
            kind='action',completionCriterion='交出本轮意见',recommendation={'state':'待办','reason':'待交意见'},
            sourceContacts=[{'channel':'微信','conversationName':'方案群','senderName':'协作者丙','replyToName':'协作者丙','at':'2026-10-21T08:00:00Z'}])
        self.assertFalse(task['reviewedByHuman']);self.assertTrue(task['needsReview'])
        self.assertEqual(task['selectedState'],'待判断')
        self.assertEqual(task['recommendation']['state'],'待办')
        self.assertEqual(task['sourceContacts'][0]['conversationName'],'方案群')
        self.assertEqual(task['completionCriterion'],'交出本轮意见')
        self.assertTrue(any(e.get('body')=='本人旧判断' for e in self.store.detail('T-1')['timeline']))
        task=self.record(state='待办');self.assertFalse(task['needsReview'])
        self.assertEqual(task['reviewRound'],'20261022-R2')
        self.record(note='备注不会撤销确认');self.assertFalse(self.store.task('T-1')['needsReview'])

    def test_kind_confirmation_and_legacy_state_aliases(self):
        self.assertEqual(STATES,['待判断','待办','等对方','暂缓','已完成','不用管了'])
        task=self.record(actor={'name':'AI','kind':'ai'},reviewRound='R2',kind='project')
        self.assertTrue(task['needsReview'])
        task=self.record(kind='project');self.assertFalse(task['needsReview'])
        self.assertEqual(self.record(state='进行中')['selectedState'],'待办')
        self.assertEqual(self.record(state='已结束')['selectedState'],'不用管了')
        self.assertEqual(self.store.detail('T-1')['timeline'][0]['state'],'不用管了')

    def test_reject_round_fields_atomically(self):
        for data in [dict(kind='anything'),dict(recommendation={'state':'destroy','reason':'x'}),
                     dict(sourceContacts=[{'channel':'微信','path':'/etc/passwd'}]),
                     dict(sourceContacts='微信'),dict(reviewRound='x'*121),dict(proposedAt='tomorrow')]:
            with self.subTest(data=data),self.assertRaises(ValidationError): self.record(**data)
        self.assertEqual(self.store.task('T-1')['revision'],0)

    def test_create_with_classification_criterion_and_source(self):
        task=self.store.create_task(dict(title='组织教材',kind='project',state='待判断',
            reviewRound='R2',actor={'name':'AI','kind':'ai'},completionCriterion='阶段成果另列',
            recommendation={'state':'等对方','reason':'组织分工待明确'}))
        self.assertEqual(task['kind'],'project');self.assertTrue(task['needsReview'])
        self.assertEqual(task['selectedState'],'待判断')

    def test_paused_due_review_returns_once_without_reopening_closed(self):
        from unittest.mock import patch
        from datetime import datetime,timezone,timedelta
        now=datetime.now(timezone.utc)
        self.record(state='暂缓',reminder={'kind':'day1','at':(now+timedelta(days=1)).isoformat(),'timezone':'Asia/Shanghai'})
        self.assertFalse(self.store.task('T-1')['needsReview'])
        with patch('notebook.utcnow',return_value=now+timedelta(days=2)):
            self.assertTrue(self.store.task('T-1')['needsReview'])
        self.record(state='已完成')
        with patch('notebook.utcnow',return_value=now+timedelta(days=2)):
            self.assertFalse(self.store.task('T-1')['needsReview'])

    def test_reading_receipt_metadata_survives_source_reload(self):
        import json
        with self.store.connect() as db:
            db.execute('INSERT INTO metadata VALUES(?,?)',('notebook_coverage',json.dumps({'asOf':'2026-10-22T03:40:00+08:00','coverageText':'微信已读，附件未读'})))
        self.store.refresh()
        self.assertEqual(self.store.meta()['asOf'],'2026-10-22T03:40:00+08:00')
        self.assertEqual(self.store.meta()['coverageText'],'微信已读，附件未读')
