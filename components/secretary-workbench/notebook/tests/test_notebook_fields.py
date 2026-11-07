"""Current editable fields append history; no source payload or ordinary note overwrite."""
import unittest
try:
    import test_notebook as basis
except ModuleNotFoundError:
    from . import test_notebook as basis
from notebook import Notebook
from store import ValidationError


class NotebookFieldTests(unittest.TestCase):
    setUp=basis.NotebookTests.setUp
    write_source=basis.NotebookTests.write_source
    record=basis.NotebookTests.record
    def test_field_changes_persist_with_previous_values_and_summary_provenance(self):
        before=self.store.task('T-1')
        updated=self.record(title='复核本轮并回复',counterparty='协作者丙／吕老师',timeRequirement='2026年10月25日前',
            summary='本轮已回复，下一轮等意见',relatedRecordIds=['T-2'],
            actor={'name':'AI','kind':'ai'},sourceTime='2026-10-21T08:00:00Z',note='按原文明确本轮边界')
        self.assertEqual(updated['title'],'复核本轮并回复')
        self.assertEqual(updated['people'],['协作者丙','吕老师'])
        self.assertEqual(updated['deadlineDate'],'2026-10-25')
        self.assertEqual(updated['lastKnownState'],'本轮已回复，下一轮等意见')
        self.assertEqual(updated['lastKnownStateUpdatedBy'],'AI')
        self.assertEqual(updated['lastKnownStateSourceTime'],'2026-10-21T08:00:00Z')
        self.assertEqual(updated['relatedRecordIds'],['T-2'])
        self.assertEqual(updated['selectedState'],before['selectedState'])
        self.assertEqual(updated['progressCount'],before['progressCount']+1)
        event=self.store.detail('T-1')['timeline'][0]
        self.assertEqual(event['previous']['title'],before['title'])
        self.assertEqual(event['previous']['summary'],before['lastKnownState'])
        self.record(note='人工新备注，不覆盖摘要')
        self.store.refresh()
        reopened=Notebook(self.db,self.source)
        self.assertEqual(reopened.task('T-1')['lastKnownState'],updated['lastKnownState'])
        self.assertEqual(reopened.task('T-1')['title'],updated['title'])
        self.assertEqual(reopened.detail('T-2')['relatedTasks'][0]['id'],'T-1')
        self.assertEqual(reopened.task('T-1')['lastProgressAt'],reopened.detail('T-1')['timeline'][0]['at'])

    def test_bad_fields_and_relations_rollback(self):
        before=self.store.task('T-1')
        for changes in [dict(title=''),dict(counterparty=[]),dict(summary=' '*3),dict(summary='字'*4001),
                        dict(relatedRecordIds=['T-1']),dict(relatedRecordIds=['T-2','T-2']),
                        dict(relatedRecordIds=['../secret']),dict(relatedRecordIds=['missing'])]:
            with self.subTest(changes=changes),self.assertRaises((ValidationError,KeyError)):
                self.record(**changes)
        self.assertEqual(self.store.task('T-1'),before)

    def test_deadline_clears_when_no_longer_explicit_and_create_summary(self):
        t=self.record(timeRequirement='2026年10月25日')
        self.assertEqual(t['deadlineDate'],'2026-10-25')
        t=self.record(timeRequirement='时间待定，尽快')
        self.assertIsNone(t['deadlineDate'])
        t=self.store.create_task({'title':'新交付','summary':'等对方给材料','state':'等对方'})
        self.assertEqual(t['lastKnownState'],'等对方给材料')
        self.assertEqual(t['lastKnownStateUpdatedBy'],'我')
