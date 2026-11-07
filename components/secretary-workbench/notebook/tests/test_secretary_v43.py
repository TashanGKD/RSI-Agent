"""Strict brain plans against the public notebook tools, in isolated workspaces."""
import copy
import tempfile
import unittest
from pathlib import Path
from datetime import date, timedelta
from modules.notebook import NotebookService
from modules.secretary import SecretaryService, SecretaryValidationError


class SecretaryV43Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.nb = NotebookService(self.root/'notebook/notebook.sqlite3', self.root/'source.json', self.root)
        self.task = self.nb.create_task({'title': '测试交付', 'state': '待办'})
        self.today = date.today().isoformat()
        self.ref = {'sourceId': 'wechat:fixture', 'nativeId': '原生编号', 'sender': '甲', 'conversation': '群'}
        self.message = self.nb.append_record({'text': '测试：明天复看，截止保留；已核对保存资料。', 'objectIds': [self.task['id']], 'sourceRefs': [self.ref]})
        self.task = self.nb.get_task(self.task['id'])

    def run_plan(self, operations, port=None):
        service = SecretaryService(port or self.nb, self.root, model_runner=lambda _: {'summary': '已核查。', 'operations': operations})
        return service.run(service.prepare(self.message['id'])['id'])

    def test_direct_observed_completed_work_is_not_pending_candidate(self):
        result=self.run_plan([{'action':'create','key':'delivered','task':{'title':'已交本轮材料','state':'已完成','assignee':'服务对象甲','proposedAt':None,'note':'材料已交，付款未核','work':{'start':'2026-10-14','participants':['服务对象甲'],'organizations':['他山协会']}}}])
        self.assertEqual('completed',result['status'],result)
        task=self.nb.get_task(result['result']['created'][0]);self.assertEqual(task['state'],'已完成');self.assertFalse(task['needsReview'])
        self.assertEqual(self.nb.query_work(start='2026-10-14',end='2026-10-14')['objects'][0]['id'],task['id'])

    def test_typed_fields_and_null_clear_are_not_text(self):
        fields = {'deadlineDate': '2026-12-31', 'followup': {'date': '2026-12-01', 'condition': '对方回复'},
                  'eventWindow': None, 'recurrence': {'frequency': 'weekly', 'weekdays': [0], 'startDate': '2026-10-26'},
                  'sourceContacts': [self.ref]}
        result = self.run_plan([{'action': 'record', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'patch': fields}])
        self.assertEqual('completed', result['status'], result)
        saved = self.nb.get_task(self.task['id'])
        self.assertEqual('2026-12-31', saved['deadlineDate'])
        self.assertEqual('2026-12-01', saved['followup']['date'])
        self.assertIn(self.ref, saved['sourceContacts'])
        for key in ('deadlineDate', 'eventWindow', 'followup', 'recurrence'):
            self.assertEqual({key: None}, SecretaryService._fields({key: None}))

    def test_invented_contact_rejects_whole_plan(self):
        result = self.run_plan([{'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
            {'action': 'record', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
             'patch': {'sourceContacts': [dict(self.ref, sender='编造')]}}])
        self.assertEqual('failed', result['status'])
        self.assertIn('source', result['error'])
        self.assertEqual(1, len(self.nb.list_tasks()))

    def test_normal_context_hydrates_latest_human_notes_and_related_inputs(self):
        self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'note': '人工最新更正：先等样品'})
        independent = self.nb.append_record({'text': '另一条独立输入', 'objectIds': [self.task['id']]})
        seen = []
        service = SecretaryService(self.nb, self.root, model_runner=lambda c: seen.append(c) or {'summary': '保留状态。', 'operations': []})
        self.assertEqual('completed', service.run(service.prepare(self.message['id'])['id'])['status'])
        context = seen[0]
        self.assertTrue(any('人工最新更正' in e['note'] for e in context['latestTaskHistory'][self.task['id']]))
        self.assertTrue(any(e['id'] == independent['id'] for e in context['relatedInputs']))
        self.assertIn('followups', context)
        self.assertIn('schedule', context)
        self.assertIn('availableSourceContacts', context)

    def test_explicit_schedule_creation_uses_object_version_and_is_idempotent(self):
        op = {'action': 'create_schedule', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
              'schedule': {'date': self.today, 'startTime': '13:00', 'endTime': '14:00', 'note': '明确约定'}}
        result = self.run_plan([op])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(1, len(self.nb.query_schedule(self.today, self.today, assignee='')['entries']))
        service = SecretaryService(self.nb, self.root, model_runner=lambda _: self.fail('must reuse receipt'))
        self.assertEqual('completed', service.run(result['id'])['status'])
        self.assertEqual(1, len(self.nb.query_schedule(self.today, self.today, assignee='')['entries']))

    def test_schedule_followup_keeps_original_date_and_occurrence(self):
        entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        tomorrow = (date.fromisoformat(self.today) + timedelta(days=1)).isoformat()
        result = self.run_plan([{'action': 'schedule_record', 'scheduleId': entry['id'], 'expectedRevision': entry['revision'],
            'expectedObjectRevision': entry['objectRevision'], 'patch': {'state': '暂缓', 'followup': {'date': tomorrow}, 'note': '只是复看'}}])
        self.assertEqual('completed', result['status'], result)
        saved = self.nb.get_schedule(entry['id'])
        self.assertEqual(self.today, saved['date'])
        self.assertEqual(self.today, self.nb.get_task(self.task['id'])['planDate'])
        self.assertEqual(1, len(self.nb.query_schedule(self.today, tomorrow, assignee='')['entries']))

    def test_presentation_and_ai_followup_receipt_preserve_human_authority(self):
        task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'followup': {'date': self.today}})
        due = self.nb.due_followups(date=self.today)['items'][0]
        result = self.run_plan([{'action': 'acknowledge_followup', 'taskId': task['id'], 'expectedRevision': task['revision'],
            'followupKey': due['followupKey'], 'text': '已核对保存资料，未获得新回复；仍等对方。'},
            {'action': 'present', 'taskId': task['id'], 'expectedRevision': task['revision'],
             'patch': {'note': '有新的明确依据待本人批阅', 'recommendation': {'state': '等对方', 'reason': '已提交，待回信'}}}])
        self.assertEqual('completed', result['status'], result)
        current = self.nb.get_task(task['id'])
        self.assertEqual('pending', current['presentation']['status'])
        self.assertIsNone(current['presentation']['acknowledgedBy'])
        receipts = self.nb.as_of(sequence=self.nb.changes()['highWatermark'])['followupReceipts']
        self.assertEqual('ai', receipts[0]['actor']['kind'])

    def test_runner_reads_policy_guide_and_transports_explicit_tool_operations(self):
        import sys
        from unittest.mock import patch
        from modules.secretary import CodexModelRunner
        import modules.secretary.service as module
        root = self.root / 'runner'
        root.mkdir()
        (root/'POLICY.md').write_text('CANONICAL_POLICY_MARKER')
        (root/'GUIDE.md').write_text('BOUNDED_GUIDE_MARKER')
        capture = root/'prompt.txt'
        executable = root/'fake-codex'
        raw = {'summary': '已安排。', 'operations': [{'action': 'create_schedule', 'key': None,
            'taskId': 'observed', 'expectedRevision': 3, 'expectedObjectRevision': None,
            'scheduleId': None, 'followupKey': None, 'fieldsJson': '{"date":"2026-12-01"}',
            'objectIds': [], 'relation': None, 'text': None}]}
        executable.write_text('#!' + sys.executable + '\nimport sys,json\nfrom pathlib import Path\n'
            + 'Path(' + repr(str(capture)) + ').write_text(sys.stdin.read())\n'
            + 'Path(sys.argv[sys.argv.index("-o")+1]).write_text(' + repr(__import__('json').dumps(raw)) + ')\n')
        executable.chmod(0o700)
        with patch.object(module, '__file__', str(root/'service.py')):
            reply = CodexModelRunner(executable=str(executable), timeout=5)({'input': {}})
        self.assertIn('CANONICAL_POLICY_MARKER', capture.read_text())
        self.assertIn('BOUNDED_GUIDE_MARKER', capture.read_text())
        self.assertEqual({'date': '2026-12-01'}, reply['operations'][0]['schedule'])
        self.assertNotIn('objectIds', reply['operations'][0])

    def test_schedule_conflict_replans_against_latest_human_note(self):
        entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        seen = []
        def runner(context):
            seen.append(context)
            if len(seen) == 1:
                self.nb.record(self.task['id'], {'expectedRevision': entry['objectRevision'], 'note': '人工已更正：保持原安排'})
                return {'summary': '尝试旧版本。', 'operations': [{'action': 'schedule_record', 'scheduleId': entry['id'],
                    'expectedRevision': entry['revision'], 'expectedObjectRevision': entry['objectRevision'], 'patch': {'state': '已完成'}}]}
            self.assertTrue(any('人工已更正' in e['note'] for e in context['latestTaskHistory'][self.task['id']]))
            self.assertGreater(context['schedule']['entries'][0]['objectRevision'], entry['objectRevision'])
            return {'summary': '保留人工安排。', 'operations': []}
        service = SecretaryService(self.nb, self.root, model_runner=runner)
        job = service.prepare(self.message['id'])
        self.assertEqual('failed', service.run(job['id'])['status'])
        self.assertEqual('completed', service.run(job['id'])['status'])
        self.assertEqual(2, len(seen))
        self.assertEqual('待办', self.nb.get_schedule(entry['id'])['state'])

    def test_schedule_write_receipt_loss_recovers_same_request_once(self):
        actual = self.nb
        class LostReceiptPort:
            broken = False
            def __getattr__(self, name):
                return getattr(actual, name)
            def create_schedule(self, body):
                result = actual.create_schedule(body)
                if not self.broken:
                    self.broken = True
                    raise RuntimeError('receipt lost after commit')
                return result
        port = LostReceiptPort()
        service = SecretaryService(port, self.root, model_runner=lambda _: {'summary': '安排。', 'operations': [
            {'action': 'create_schedule', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'schedule': {'date': self.today}}]})
        job = service.prepare(self.message['id'])
        self.assertEqual('failed', service.run(job['id'])['status'])
        self.assertEqual('completed', service.run(job['id'])['status'])
        self.assertEqual(1, len(actual.query_schedule(self.today, self.today, assignee='')['entries']))
        self.assertEqual(1, len(service.get_job(job['id'])['steps']))

    def test_existing_future_occurrence_rejects_old_postpone_before_create(self):
        entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        tomorrow = (date.fromisoformat(self.today) + timedelta(days=1)).isoformat()
        later = self.nb.create_schedule({'objectId': self.task['id'], 'date': tomorrow, 'expectedObjectRevision': entry['objectRevision']})
        result = self.run_plan([{'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
            {'action': 'schedule_record', 'scheduleId': entry['id'], 'expectedRevision': self.nb.get_schedule(entry['id'])['revision'],
             'expectedObjectRevision': later['objectRevision'], 'patch': {'state': '暂缓', 'postponeTo': {'date': tomorrow}}}])
        self.assertEqual('failed', result['status'])
        self.assertIn('latest', result['error'])
        self.assertEqual(1, len(self.nb.list_tasks()))

    def test_new_source_contacts_must_exactly_match_known_input_metadata(self):
        service = SecretaryService(self.nb, self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        for invented in [dict(self.ref, sender='编造'), {'sourceId': 'wechat:other', 'nativeId': '不存在'}, dict(self.ref, url='https://example.com/invented')]:
            with self.subTest(invented=invented), self.assertRaisesRegex(SecretaryValidationError, 'evidence-provided'):
                service._validate({'summary': '测试。', 'operations': [{'action': 'record', 'taskId': self.task['id'],
                    'expectedRevision': self.task['revision'], 'patch': {'sourceContacts': [invented]}}]}, context)

    def test_large_related_metadata_has_bounded_context_with_visible_omissions(self):
        for index in range(8):
            refs = [{'sourceId': 'wechat:fixture', 'nativeId': str(index) + '-' + str(j),
                     'sender': '甲' * 1000, 'conversation': '群' * 1000} for j in range(20)]
            self.nb.append_record({'text': '相关输入' * 1000, 'objectIds': [self.task['id']], 'sourceRefs': refs})
        service = SecretaryService(self.nb, self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        import json
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False, separators=(',', ':')).encode()), 240000)
        self.assertGreater(context['coverage']['sourceContacts']['omitted'], 0)
        self.assertIn('sourceRefsAreExcerpts', context['coverage']['relatedInputs'])

    def test_schedule_duplicate_outside_upcoming_context_preflights_before_create(self):
        far = (date.fromisoformat(self.today) + timedelta(days=60)).isoformat()
        self.nb.create_schedule({'objectId': self.task['id'], 'date': far, 'expectedObjectRevision': self.task['revision']})
        self.task = self.nb.get_task(self.task['id'])
        # An independent input can identify a catalog object outside focused expansion.
        self.message = self.nb.append_record({'text': '独立申请安排'})
        result = self.run_plan([{'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
            {'action': 'create_schedule', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'schedule': {'date': far}}])
        self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(self.nb.list_tasks()))

    def test_new_candidate_scheduling_reads_fresh_actual_context_in_same_run(self):
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                return {'summary': '保存明确约定并安排。', 'operations': [
                    {'action': 'create', 'key': 'new', 'task': {'title': '明确约定的会面', 'kind': 'action'}},
                    {'action': 'create_schedule', 'taskId': '$new', 'expectedRevision': 1, 'schedule': {'date': self.today}}]}
            candidate_id = context['completedPrefix']['created'][0]
            current = next(t for t in context['tasks'] if t['id'] == candidate_id)
            self.assertEqual('其他', current['state'])
            self.assertEqual(candidate_id, context['completedPrefix']['steps'][0]['objectId'])
            return {'summary': '已核对真实新对象后安排。', 'operations': [
                {'action': 'create_schedule', 'taskId': candidate_id, 'expectedRevision': current['revision'], 'schedule': {'date': self.today}}]}
        service = SecretaryService(self.nb, self.root, model_runner=runner)
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(2, len(contexts))
        self.assertEqual(2, len(self.nb.list_tasks()))
        self.assertEqual(1, len(self.nb.query_schedule(self.today, self.today, assignee='')['entries']))
        self.assertEqual('待办', self.nb.get_task(result['result']['created'][0])['state'])

    def test_privacy_placeholders_are_exposed_as_coverage_gaps(self):
        actual = self.nb
        class RedactedPort:
            def __getattr__(self, name):
                return getattr(actual, name)
            def detail(self, rid):
                result = actual.detail(rid)
                result['timeline'].insert(0, {'id': 'redacted', 'actor': {'kind': 'human', 'name': '我'},
                    'note': '原文保留Mac，线上仅保存事项摘要。', 'localOnly': True})
                return result
        service = SecretaryService(RedactedPort(), self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        self.assertGreater(context['coverage']['latestTaskHistory']['privacyPlaceholderCount'], 0)
        self.assertFalse(context['coverage']['latestTaskHistory']['originalTextComplete'])
        self.assertTrue(context['latestTaskHistory'][self.task['id']][0]['originalTextUnavailable'])

    def test_large_followup_context_is_bounded_and_reports_omissions(self):
        actual = self.nb
        class ManyFollowups:
            def __getattr__(self, name):
                return getattr(actual, name)
            def due_followups(self):
                rows = [{'objectId': 'task' + str(i), 'followupKey': 'key' + str(i), 'objectRevision': 1,
                    'followup': {'date': '2020-01-01', 'condition': '待核查' * 600}, 'conditionResult': 'unknown'} for i in range(80)]
                return {'items': rows[:40], 'conditionsUnknown': rows[40:], 'executed': False}
        service = SecretaryService(ManyFollowups(), self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        import json
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False, separators=(',', ':')).encode()), 240000)
        self.assertLess(context['followups']['coverage']['items']['included'], 40)

    def test_raw_source_bridge_fails_closed_for_online_port_without_any_append(self):
        from modules.sources import SourceRegistry
        actual = self.nb
        class OnlinePort:
            base_url = 'https://notebook.invalid'
            appends = []
            def __getattr__(self, name):
                return getattr(actual, name)
            def append_record(self, body):
                self.appends.append(copy.deepcopy(body))
                raise AssertionError('raw original must never reach online append')
        source = SourceRegistry(self.root)
        imported = source.import_records('wechat', 'privacy', [{'nativeId': 'one', 'text': '完整私密原话不准传到线上'}])
        record = source.query(imported['sourceId'])['records'][0]
        port = OnlinePort()
        service = SecretaryService(port, self.root, source_port=source, model_runner=lambda _: self.fail('must fail before model'))
        with self.assertRaisesRegex(SecretaryValidationError, 'raw saved-source'):
            service.prepare({'sourceId': imported['sourceId'], 'recordId': record['id']})
        self.assertEqual([], port.appends)

    def test_existing_unexpanded_target_reads_latest_human_history_before_mutation(self):
        target = self.nb.create_task({'title': '代号北辰对象', 'state': '等对方'})
        target = self.nb.record(target['id'], {'expectedRevision': target['revision'], 'note': '本人最新决定：仍等对方，暂不关闭'})
        self.message = self.nb.append_record({'text': '这条独立输入没有标题词汇'})
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                self.assertNotIn(target['id'], context['coverage']['expandedTaskIds'])
                return {'summary': '初步拟关闭。', 'operations': [{'action': 'record', 'taskId': target['id'],
                    'expectedRevision': target['revision'], 'patch': {'state': '已完成'}}]}
            self.assertEqual('等对方', self.nb.get_task(target['id'])['state'])
            self.assertTrue(any('本人最新决定' in e['note'] for e in context['latestTaskHistory'][target['id']]))
            return {'summary': '读到最新本人决定，保留等待。', 'operations': []}
        service = SecretaryService(self.nb, self.root, model_runner=runner)
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(2, len(contexts))
        self.assertEqual('等对方', self.nb.get_task(target['id'])['state'])
        self.assertEqual([], result['steps'])

    def test_source_bridge_rechecks_remote_boundary_for_persisted_local_job(self):
        from modules.sources import SourceRegistry
        source = SourceRegistry(self.root)
        imported = source.import_records('wechat', 'privacy', [{'nativeId': 'one', 'text': '私密保存原话'}])
        record = source.query(imported['sourceId'])['records'][0]
        service = SecretaryService(self.nb, self.root, source_port=source, model_runner=lambda _: self.fail('must not call model'))
        job = service.prepare({'sourceId': imported['sourceId'], 'recordId': record['id']})
        actual = self.nb
        class RemotePort:
            base_url = 'https://notebook.invalid'
            writes = []
            def __getattr__(self, name):
                return getattr(actual, name)
            def append_record(self, body):
                self.writes.append(body)
                raise AssertionError('must not export raw source')
        service.notebook = RemotePort()
        result = service.run(job['id'])
        self.assertEqual('failed', result['status'])
        self.assertIn('raw saved-source', result['error'])
        self.assertEqual([], service.notebook.writes)

    def test_freshness_continuations_share_bounded_budget_and_never_force_unread_target(self):
        targets = [self.nb.create_task({'title': '代号' + str(i), 'state': '等对方'}) for i in range(3)]
        self.message = self.nb.append_record({'text': '独立输入，没有目标名称'})
        contexts = []
        def runner(context):
            target = targets[len(contexts)]
            contexts.append(context)
            return {'summary': '切换到未读对象。', 'operations': [{'action': 'record', 'taskId': target['id'],
                'expectedRevision': target['revision'], 'patch': {'state': '已完成'}}]}
        service = SecretaryService(self.nb, self.root, model_runner=runner)
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('failed', result['status'])
        self.assertEqual(3, len(contexts))
        self.assertEqual(2, result['replanAttempts'])
        self.assertEqual([], result['steps'])
        self.assertTrue(all(self.nb.get_task(t['id'])['state'] == '等对方' for t in targets))

    def test_target_refresh_keeps_previously_created_prefix_once(self):
        target = self.nb.create_task({'title': '代号北辰', 'state': '等对方'})
        self.message = self.nb.append_record({'text': '独立输入且有明确会面约定'})
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                return {'summary': '新候选与安排。', 'operations': [
                    {'action': 'create', 'key': 'new', 'task': {'title': '明确会面约定'}},
                    {'action': 'create_schedule', 'taskId': '$new', 'expectedRevision': 1, 'schedule': {'date': self.today}}]}
            if len(contexts) == 2:
                # Prefix is saved. Selecting an additional unhydrated existing target needs another context.
                self.assertEqual(3, len(self.nb.list_tasks()))
                return {'summary': '考虑旧项。', 'operations': [{'action': 'record', 'taskId': target['id'],
                    'expectedRevision': target['revision'], 'patch': {'note': '待核对'}}]}
            self.assertEqual(1, len(context['completedPrefix']['created']))
            self.assertIn(target['id'], context['latestTaskHistory'])
            return {'summary': '读后保留原状。', 'operations': []}
        service = SecretaryService(self.nb, self.root, model_runner=runner)
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(3, len(contexts))
        self.assertEqual(1, len(result['result']['created']))
        self.assertEqual(3, len(self.nb.list_tasks()))
        self.assertEqual(1, len(result['steps']))

    def test_legacy_plan_fields_cannot_reopen_closed_historical_occurrence(self):
        today_entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        tomorrow = (date.fromisoformat(self.today) + timedelta(days=1)).isoformat()
        future = self.nb.create_schedule({'objectId': self.task['id'], 'date': tomorrow, 'expectedObjectRevision': today_entry['objectRevision']})
        closed = self.nb.schedule_record(today_entry['id'], {'expectedRevision': self.nb.get_schedule(today_entry['id'])['revision'],
            'expectedObjectRevision': future['objectRevision'], 'state': '已完成'})
        self.task = self.nb.get_task(self.task['id'])
        for action in ('arrange', 'record'):
            service = SecretaryService(self.nb, self.root, model_runner=lambda _: None)
            context = service._context(service._get(service.prepare(self.message['id'])['id']))
            with self.subTest(action=action), self.assertRaisesRegex(SecretaryValidationError, 'closed occurrence'):
                service._validate({'summary': '不准覆盖历史。', 'operations': [
                    {'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
                    {'action': action, 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'patch': {'planDate': self.today}}]}, context)
        self.assertEqual('已完成', self.nb.get_schedule(closed['id'])['state'])
        self.assertEqual(tomorrow, self.nb.get_task(self.task['id'])['planDate'])
        self.assertEqual(1, len(self.nb.list_tasks()))

    def test_recurrence_creation_preflights_effective_inherited_clock_before_prefix(self):
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'recurrence': {
            'frequency': 'daily', 'startDate': self.today, 'startTime': '09:00', 'endTime': '10:00'}})
        result = self.run_plan([{'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
            {'action': 'create_schedule', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
             'schedule': {'date': self.today, 'startTime': '11:00'}}])
        self.assertEqual('failed', result['status'])
        self.assertEqual([], result['steps'])
        self.assertEqual(1, len(self.nb.list_tasks()))

    def test_history_budget_prioritizes_latest_substantive_human_note_for_each_target(self):
        targets = []
        for index in range(8):
            task = self.nb.create_task({'title': '长历史对象' + str(index), 'state': '等对方'})
            for j in range(8):
                task = self.nb.record(task['id'], {'expectedRevision': task['revision'], 'note': ('本人最新决定：保持等待，不要关闭。' if j == 7 else '旧说明') + '长' * 1000})
            targets.append(task)
        self.message = self.nb.append_record({'text': '共同输入', 'objectIds': [t['id'] for t in targets]})
        service = SecretaryService(self.nb, self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        for task in targets:
            self.assertTrue(any('本人最新决定' in e['note'] for e in context['latestTaskHistory'][task['id']]))
            self.assertTrue(context['coverage']['latestTaskHistory']['tasks'][task['id']]['latestHumanDecisionIncluded'])
            self.assertIn(task['id'], context['coverage']['hydratedTaskIds'])

    def test_unread_latest_human_note_forces_targeted_refresh_within_shared_budget(self):
        targets = []
        for index in range(8):
            task = self.nb.create_task({'title': '超长历史对象' + str(index), 'state': '等对方'})
            task = self.nb.record(task['id'], {'expectedRevision': task['revision'], 'note': '本人最新决定：保持等待。' + '长' * 11000})
            targets.append(task)
        self.message = self.nb.append_record({'text': '共同输入', 'objectIds': [t['id'] for t in targets]})
        target_id = targets[-1]['id']
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                self.assertNotIn(target_id, context['coverage'].get('hydratedTaskIds', []))
                current = next(t for t in context['tasks'] if t['id'] == target_id)
                return {'summary': '初步拟关闭。', 'operations': [{'action': 'record', 'taskId': target_id,
                    'expectedRevision': current['revision'], 'patch': {'state': '已完成'}}]}
            self.assertIn(target_id, context['coverage']['hydratedTaskIds'])
            self.assertTrue(any('本人最新决定' in e['note'] and len(e['note']) > 11000 for e in context['latestTaskHistory'][target_id]))
            return {'summary': '读到最新决定，保留等待。', 'operations': []}
        service = SecretaryService(self.nb, self.root, model_runner=runner)
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(2, len(contexts))
        self.assertEqual('等对方', self.nb.get_task(target_id)['state'])
        self.assertEqual([], result['steps'])

    def test_optional_clear_values_match_public_notebook_contract(self):
        from modules.secretary.values import schedule_fields
        for fields in ({'followup': {'date': self.today, 'at': ''}},
                       {'eventWindow': {'start': self.today + 'T09:00+08:00', 'end': ''}}):
            with self.subTest(fields=fields):
                self.nb.validate_fields(dict(fields, expectedRevision=self.task['revision']))
                self.assertEqual(fields, SecretaryService._fields(copy.deepcopy(fields)))
        self.assertEqual({'date': self.today, 'startTime': ''}, schedule_fields({'date': self.today, 'startTime': ''}, create=True))

    def test_event_window_preflight_uses_existing_effective_plan_date_before_prefix(self):
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'planDate': self.today})
        tomorrow = (date.fromisoformat(self.today) + timedelta(days=1)).isoformat()
        result = self.run_plan([{'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
            {'action': 'arrange', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
             'patch': {'eventWindow': {'start': tomorrow + 'T09:00+08:00'}}}])
        self.assertEqual('failed', result['status'])
        self.assertEqual([], result['steps'])
        self.assertEqual(1, len(self.nb.list_tasks()))

    def test_merged_field_validation_preserves_public_move_and_explicit_window_clear_semantics(self):
        tomorrow = (date.fromisoformat(self.today) + timedelta(days=1)).isoformat()
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'planDate': self.today,
            'eventWindow': {'start': self.today + 'T09:00+08:00', 'end': self.today + 'T10:00+08:00'}})
        result = self.run_plan([{'action': 'arrange', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
            'patch': {'planDate': tomorrow}}])
        self.assertEqual('completed', result['status'], result)
        saved = self.nb.get_task(self.task['id'])
        self.assertEqual(tomorrow, saved['planDate'])
        self.assertIsNone(saved['eventWindow'])

    def test_changed_followup_invalidates_old_receipt_before_any_prefix_save(self):
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'followup': {'date': self.today}})
        due = self.nb.due_followups()['items'][0]
        result = self.run_plan([{'action': 'create', 'key': 'prefix', 'task': {'title': '不得先写'}},
            {'action': 'record', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'patch': {'followup': None}},
            {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'] + 1,
             'followupKey': due['followupKey'], 'text': '已经核对旧复看，但旧约定已被本计划改变。'}])
        self.assertEqual('failed', result['status'])
        self.assertEqual([], result['steps'])
        self.assertEqual(1, len(self.nb.list_tasks()))
        self.assertIsNotNone(self.nb.get_task(self.task['id'])['followup'])

    def test_followup_review_date_condition_and_closure_changes_invalidate_eligible_keys(self):
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'followup': {'date': self.today}})
        due = self.nb.due_followups()['items'][0]
        service = SecretaryService(self.nb, self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        for fields in ({'followup': None}, {'reviewDate': None}, {'condition': '新复看条件'}, {'state': '已完成'}):
            with self.subTest(fields=fields), self.assertRaises(SecretaryValidationError):
                service._validate({'summary': '旧回执不得误用。', 'operations': [
                    {'action': 'record', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'patch': fields},
                    {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'] + 1,
                     'followupKey': due['followupKey'], 'text': '已核查保存资料。'}]}, context)

    def test_schedule_followup_change_invalidates_old_receipt_before_prefix_save(self):
        entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        self.task = self.nb.record(self.task['id'], {'expectedRevision': entry['objectRevision'], 'followup': {'date': self.today}})
        entry = self.nb.get_schedule(entry['id'])
        due = self.nb.due_followups()['items'][0]
        result = self.run_plan([{'action': 'create', 'key': 'prefix', 'task': {'title': '不得先写'}},
            {'action': 'schedule_record', 'scheduleId': entry['id'], 'expectedRevision': entry['revision'],
             'expectedObjectRevision': self.task['revision'], 'patch': {'followup': None}},
            {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'] + 1,
             'followupKey': due['followupKey'], 'text': '已核查保存资料。'}])
        self.assertEqual('failed', result['status'])
        self.assertEqual([], result['steps'])
        self.assertEqual(1, len(self.nb.list_tasks()))
        self.assertIsNotNone(self.nb.get_task(self.task['id'])['followup'])

    def test_duplicate_followup_acknowledgements_reject_entire_plan(self):
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'followup': {'date': self.today}})
        due = self.nb.due_followups()['items'][0]
        ack = {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
            'followupKey': due['followupKey'], 'text': '已核查保存资料，无新回复。'}
        result = self.run_plan([{'action': 'create', 'key': 'prefix', 'task': {'title': '不得先写'}}, copy.deepcopy(ack), copy.deepcopy(ack)])
        self.assertEqual('failed', result['status'])
        self.assertEqual([], result['steps'])
        self.assertEqual(1, len(self.nb.list_tasks()))
        self.assertEqual(1, len(self.nb.due_followups()['items']))

    def test_plain_note_preserves_eligible_followup_key_at_new_object_revision(self):
        self.task = self.nb.record(self.task['id'], {'expectedRevision': self.task['revision'], 'followup': {'date': self.today}})
        due = self.nb.due_followups()['items'][0]
        result = self.run_plan([
            {'action': 'record', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'], 'patch': {'note': '核查了已有材料，无新回复。'}},
            {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'] + 1,
             'followupKey': due['followupKey'], 'text': '核查完成，原约定仍保持。'}])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual([], self.nb.due_followups()['items'])

    def test_latest_schedule_closure_invalidates_object_followup_before_prefix(self):
        entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        self.task = self.nb.record(self.task['id'], {'expectedRevision': entry['objectRevision'], 'followup': {'date': self.today}})
        entry = self.nb.get_schedule(entry['id'])
        due = self.nb.due_followups()['items'][0]
        result = self.run_plan([{'action': 'create', 'key': 'prefix', 'task': {'title': '不得先写'}},
            {'action': 'schedule_record', 'scheduleId': entry['id'], 'expectedRevision': entry['revision'],
             'expectedObjectRevision': self.task['revision'], 'patch': {'state': '已完成'}},
            {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'] + 1,
             'followupKey': due['followupKey'], 'text': '已经核查原复看，但事项已在同计划关闭。'}])
        self.assertEqual('failed', result['status'])
        self.assertEqual([], result['steps'])
        self.assertEqual(1, len(self.nb.list_tasks()))
        self.assertEqual('待办', self.nb.get_task(self.task['id'])['state'])

    def test_historical_occurrence_closure_preserves_still_open_object_followup(self):
        entry = self.nb.create_schedule({'objectId': self.task['id'], 'date': self.today, 'expectedObjectRevision': self.task['revision']})
        tomorrow = (date.fromisoformat(self.today) + timedelta(days=1)).isoformat()
        future = self.nb.create_schedule({'objectId': self.task['id'], 'date': tomorrow, 'expectedObjectRevision': entry['objectRevision']})
        self.task = self.nb.record(self.task['id'], {'expectedRevision': future['objectRevision'], 'followup': {'date': self.today}})
        entry = self.nb.get_schedule(entry['id'])
        due = self.nb.due_followups()['items'][0]
        result = self.run_plan([
            {'action': 'schedule_record', 'scheduleId': entry['id'], 'expectedRevision': entry['revision'],
             'expectedObjectRevision': self.task['revision'], 'patch': {'state': '已完成'}},
            {'action': 'acknowledge_followup', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'] + 1,
             'followupKey': due['followupKey'], 'text': '核对历史交付，未来一轮仍待办；本次复看处理完成。'}])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual('待办', self.nb.get_task(self.task['id'])['state'])
        self.assertIsNotNone(self.nb.get_task(self.task['id'])['followup'])
        self.assertEqual([], self.nb.due_followups()['items'])

    def test_actual_notebook_capabilities_reach_normal_context_with_evidence_limits(self):
        from modules.notebook.public_api import capabilities
        actual = self.nb
        declaration = capabilities()
        class CapabilityPort:
            def __getattr__(self, name):
                return getattr(actual, name)
            def capabilities(self):
                return copy.deepcopy(declaration)
        seen = []
        service = SecretaryService(CapabilityPort(), self.root, model_runner=lambda c: seen.append(c) or {'summary': '已核对实际工具声明。', 'operations': []})
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(declaration, seen[0]['notebookCapabilities'])
        coverage = seen[0]['coverage']['notebookCapabilities']
        self.assertTrue(coverage['available'])
        self.assertFalse(coverage['endToEndVerified'])
        self.assertIn('migration baseline', coverage['historyLimit'])
        self.assertIn('declaration', coverage['evidenceNature'])

    def test_capability_declaration_is_bounded_with_explicit_omissions(self):
        actual = self.nb
        class LargeCapabilityPort:
            def __getattr__(self, name):
                return getattr(actual, name)
            def capabilities(self):
                return {'version': '4.3', 'operations': {'history': 'as-of migration baseline onward'},
                    'oversized': '大' * 100000}
        service = SecretaryService(LargeCapabilityPort(), self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        self.assertEqual('4.3', context['notebookCapabilities']['version'])
        self.assertEqual('as-of migration baseline onward', context['notebookCapabilities']['operations']['history'])
        self.assertNotIn('oversized', context['notebookCapabilities'])
        self.assertEqual(1, context['coverage']['notebookCapabilities']['omittedFields'])
        self.assertLessEqual(len(__import__('json').dumps(context['notebookCapabilities'], ensure_ascii=False).encode()), 8192)

    def test_missing_or_404_capabilities_are_coverage_gaps_but_other_errors_fail(self):
        actual = self.nb
        service = SecretaryService(actual, self.root, model_runner=lambda _: None)
        context = service._context(service._get(service.prepare(self.message['id'])['id']))
        self.assertFalse(context['coverage']['notebookCapabilities']['available'])
        class CapabilityErrorPort:
            error = KeyError('legacy route missing')
            def __getattr__(self, name):
                return getattr(actual, name)
            def capabilities(self):
                raise self.error
        port = CapabilityErrorPort()
        service = SecretaryService(port, self.root, model_runner=lambda _: None)
        job = service._get(service.prepare(self.message['id'])['id'])
        context = service._context(job)
        self.assertFalse(context['coverage']['notebookCapabilities']['available'])
        for error in (PermissionError('authentication failed'), ConnectionError('network unavailable')):
            port.error = error
            with self.subTest(error=type(error).__name__), self.assertRaises(type(error)):
                service._context(job)

    def test_all_schedule_ops_preflight_before_any_writes(self):
        result = self.run_plan([{'action': 'create', 'key': 'first', 'task': {'title': '不得先写'}},
            {'action': 'create_schedule', 'taskId': self.task['id'], 'expectedRevision': self.task['revision'],
             'schedule': {'date': self.today, 'startTime': '20:00', 'endTime': '19:00'}}])
        self.assertEqual('failed', result['status'])
        self.assertEqual(1, len(self.nb.list_tasks()))
