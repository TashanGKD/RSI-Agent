import copy
import json
import tempfile
import time
import unittest
from pathlib import Path

try:
    from modules.secretary import SecretaryService, SecretaryValidationError
except ImportError:
    SecretaryService = None
    SecretaryValidationError = ValueError


class NotebookFixture:
    def __init__(self):
        self.tasks = {}
        self.records = {}
        self.seen = {}
        self.writes = []
        self.fail_once = False

    def list_tasks(self):
        return copy.deepcopy(list(self.tasks.values()))

    def get_task(self, task_id):
        return copy.deepcopy(self.tasks[task_id])

    def list_records(self):
        return copy.deepcopy(list(self.records.values()))

    def record_detail(self, record_id):
        return copy.deepcopy(self.records[record_id])

    def append_record(self, body):
        if body.get('requestId') in self.seen:
            return self.seen[body['requestId']]
        record = dict(id='r' + str(len(self.records) + 1), text=body['text'],
                      objectIds=body.get('objectIds', []), attachments=[], actor=body.get('actor') or {'name': '我', 'kind': 'human'},
                      at='2026-10-22T12:00:00Z', processing='pending', receipts=[])
        self.records[record['id']] = record
        if body.get('requestId'):
            self.seen[body['requestId']] = record
        return copy.deepcopy(record)

    def set_record_processing(self, record_id, status, receipt='', object_ids=None):
        record = self.records[record_id]
        record['processing'] = status
        record['receipts'].append(dict(status=status, text=receipt, objectIds=object_ids or []))
        return copy.deepcopy(record)

    def create_task(self, body):
        if body['requestId'] in self.seen:
            return copy.deepcopy(self.seen[body['requestId']])
        task = dict(id='t' + str(len(self.tasks) + 1), revision=1, state='其他',
                    kind='action', domain='', relatedRecordIds=[], planDate=None,
                    reviewDate=None, condition=None)
        task.update({k: v for k, v in body.items() if k not in ('actor', 'requestId')})
        self.tasks[task['id']] = task
        self.seen[body['requestId']] = task
        self.writes.append(('create', copy.deepcopy(body)))
        return copy.deepcopy(task)

    def record(self, task_id, body):
        if body['requestId'] in self.seen:
            return copy.deepcopy(self.seen[body['requestId']])
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('fixture interrupted write')
        task = self.tasks[task_id]
        if body['expectedRevision'] != task['revision']:
            raise ValueError('revision conflict')
        task.update({k: v for k, v in body.items() if k not in ('expectedRevision', 'actor', 'requestId', 'note')})
        task['revision'] += 1
        self.seen[body['requestId']] = copy.deepcopy(task)
        self.writes.append(('record', copy.deepcopy(body)))
        return copy.deepcopy(task)


class LocalSecretaryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(SecretaryService, 'SecretaryService implementation is required')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.notebook = NotebookFixture()
        self.message = self.notebook.append_record({'text': '模拟：下次见泽锐带平板。'})

    def service(self, reply):
        return SecretaryService(self.notebook, self.temp.name, model_runner=lambda context: reply)

    def finished(self, service, message_id=None, request_id=None):
        job = service.submit(message_id=message_id or self.message['id'], request_id=request_id)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = service.get_job(job['id'])
            if job['status'] in ('completed', 'failed'):
                return job
            time.sleep(0.01)
        self.fail('job did not finish')

    def test_reject_unsupported_external_action_preserves_input(self):
        job = self.finished(self.service({'summary': 'send', 'operations': [{'action': 'send_message', 'text': 'hi'}]}))
        self.assertEqual('failed', job['status'])
        self.assertEqual([], self.notebook.writes)
        self.assertEqual('模拟：下次见泽锐带平板。', self.notebook.record_detail('r1')['text'])

    def test_reject_malformed_model_json_without_task_writes(self):
        job = self.finished(self.service('{broken'))
        self.assertEqual('failed', job['status'])
        self.assertEqual([], self.notebook.writes)

    def test_reject_path_reference_and_excess_input(self):
        job = self.finished(self.service({'summary': 'unsafe', 'operations': [{'action': 'append', 'text': 'read', 'objectIds': ['/etc/passwd']}]}))
        self.assertEqual('failed', job['status'])
        large = self.notebook.append_record({'text': '大' * 40000})
        job = self.finished(self.service({'summary': 'none', 'operations': []}), message_id=large['id'], request_id='big')
        self.assertEqual('failed', job['status'])
        self.assertEqual([], self.notebook.writes)

    def test_conditional_memo_domain_and_original_link(self):
        reply = {'summary': '已记为下次见面时使用的备忘。', 'operations': [
            {'action': 'create', 'key': 'memo', 'task': {'title': '见泽锐时带平板', 'kind': 'memo',
                'domain': '他山', 'condition': '下次见泽锐', 'assignee': '我'}}]}
        service = self.service(reply)
        job = self.finished(service)
        self.assertEqual('completed', job['status'])
        task = self.notebook.get_task(job['result']['created'][0])
        self.assertEqual('memo', task['kind'])
        self.assertEqual('其他', task['state'])
        self.assertEqual('他山', task['domain'])
        self.assertEqual(self.message['at'], task['proposedAt'])
        self.assertEqual([], task['relatedRecordIds'])
        self.assertIn(task['id'], self.notebook.records['r1']['receipts'][-1]['objectIds'])
        self.assertEqual(job['id'], service.submit(message_id='r1')['id'])
        self.assertEqual(1, len(self.notebook.tasks))

    def test_wait_no_change_leaves_task_and_review_untouched(self):
        self.notebook.tasks['old'] = dict(id='old', revision=7, state='等对方', title='等待审批', needsReview=False)
        job = self.finished(self.service({'summary': '审批尚无变化，继续等待。', 'operations': []}))
        self.assertEqual('completed', job['status'])
        self.assertEqual(7, self.notebook.tasks['old']['revision'])
        self.assertFalse(self.notebook.tasks['old']['needsReview'])
        self.assertEqual([], self.notebook.writes)

    def test_reject_closed_reopen_from_later_read_old_message(self):
        self.notebook.tasks['old'] = dict(id='old', revision=2, state='已完成', title='本轮交件')
        job = self.finished(self.service({'summary': '催办', 'operations': [
            {'action': 'record', 'taskId': 'old', 'expectedRevision': 2, 'patch': {'state': '待办'}}]}))
        self.assertEqual('failed', job['status'])
        self.assertEqual('已完成', self.notebook.tasks['old']['state'])

    def test_preflight_rejects_entire_plan_before_any_write(self):
        job = self.finished(self.service({'summary': 'bad reference', 'operations': [
            {'action': 'create', 'key': 'one', 'task': {'title': 'allowed'}},
            {'action': 'record', 'taskId': 'missing', 'expectedRevision': 1, 'patch': {'note': 'x'}}]}))
        self.assertEqual('failed', job['status'])
        self.assertEqual([], self.notebook.writes)

    def test_new_independent_delivery_linked_and_resume_partial_once(self):
        self.notebook.tasks['old'] = dict(id='old', revision=2, state='待办', title='本轮交件')
        reply = {'summary': '本轮已交，下一轮单列。', 'operations': [
            {'action': 'create', 'key': 'next', 'task': {'title': '下一轮修改并回复', 'kind': 'action', 'completionCriterion': '修改稿发出'}},
            {'action': 'record', 'taskId': 'old', 'expectedRevision': 2, 'patch': {'state': '已完成', 'note': '原消息明确本轮已交'}},
            {'action': 'link', 'objectIds': ['old', '$next'], 'relation': 'follows', 'text': '下一轮交付承接原项'}]}
        self.notebook.fail_once = True
        service = self.service(reply)
        first = self.finished(service)
        self.assertEqual('failed', first['status'])
        self.assertEqual(1, len(first['result']['created']))
        restarted = self.service(reply)
        restarted.resume(first['id'])
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            job = restarted.get_job(first['id'])
            if job['status'] in ('completed', 'failed'):
                break
            time.sleep(.01)
        self.assertEqual('completed', job['status'], job)
        self.assertEqual(2, len(self.notebook.tasks))
        self.assertEqual(['old'], job['result']['closed'])
        self.assertEqual(1, len(job['result']['linked']))

    def test_real_source_reference_is_read_without_querying_and_preserved(self):
        class SavedSource:
            def __init__(self):
                self.reads = []
            def read(self, source_id, record_id):
                self.reads.append((source_id, record_id))
                return {'id': record_id, 'text': '虚构已保存资料，无变化', 'sourceId': source_id}
        source = SavedSource()
        service = SecretaryService(self.notebook, self.temp.name,
            model_runner=lambda context: {'summary': '已读这一条保存资料，无事项变化。', 'operations': []}, source_port=source)
        job = service.prepare({'sourceId': 'src-demo', 'recordId': 'saved-1'})
        result = service.run(job['id'])
        self.assertEqual('completed', result['status'])
        self.assertEqual([('src-demo', 'saved-1')], source.reads)
        self.assertEqual([], self.notebook.writes)
        self.assertTrue(any(record['text'] == '虚构已保存资料，无变化' for record in self.notebook.list_records()))

    def test_changed_saved_source_version_gets_a_new_processing_job(self):
        class Source:
            text = '虚构第一版'
            def read(self, source_id, record_id):
                return {'id': record_id, 'text': self.text}
        source = Source()
        service = SecretaryService(self.notebook, self.temp.name,
            model_runner=lambda _: {'summary': '已读保存版本。', 'operations': []}, source_port=source)
        ref = {'sourceId': 'src-demo', 'recordId': 'saved-1'}
        first = service.prepare(ref)
        self.assertEqual(first['id'], service.prepare(ref)['id'])
        source.text = '虚构第二版，补充新进展'
        second = service.prepare(ref)
        self.assertNotEqual(first['id'], second['id'])

    def test_reject_duplicate_json_keys(self):
        job = self.finished(self.service('{"summary":"one","summary":"two","operations":[]}'))
        self.assertEqual('failed', job['status'])
        self.assertEqual([], self.notebook.writes)

    def test_symlinked_private_directory_is_rejected(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (Path(self.temp.name) / 'secretary').symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SecretaryValidationError):
            self.service({'summary': 'none', 'operations': []})
        self.assertEqual([], list(outside.iterdir()))

    def test_actual_notebook_port_recovers_after_link_write_before_record(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        real = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        old = real.create_task({'title': '模拟本轮交件', 'state': '待办'})
        message = real.append_record({'text': '模拟：本轮已经发出，另有下一轮修改交付。'})
        class InterruptedPort:
            broken = False
            def __getattr__(self, name):
                return getattr(real, name)
            def append_record(self, body):
                if body['text'] == '下一轮承接本轮' and not self.broken:
                    self.broken = True
                    raise RuntimeError('simulated interruption after relation mutation')
                return real.append_record(body)
        port = InterruptedPort()
        reply = {'summary': '本轮关闭，下一轮新建关联。', 'operations': [
            {'action': 'create', 'key': 'next', 'task': {'title': '模拟下一轮修改交付'}},
            {'action': 'record', 'taskId': old['id'], 'expectedRevision': old['revision'],
             'patch': {'state': '已完成', 'note': '本输入明确本轮已发出'}},
            {'action': 'link', 'objectIds': [old['id'], '$next'], 'relation': 'follows', 'text': '下一轮承接本轮'}]}
        service = SecretaryService(port, root, model_runner=lambda context: reply)
        job = service.prepare(message['id'])
        failed = service.run(job['id'])
        self.assertEqual('failed', failed['status'])
        self.assertEqual(2, len(real.list_tasks()))
        completed = SecretaryService(port, root, model_runner=lambda _: self.fail('must reuse persisted plan')).run(job['id'])
        self.assertEqual('completed', completed['status'], completed)
        self.assertEqual(2, len(real.list_tasks()))
        self.assertEqual([old['id']], completed['result']['closed'])
        self.assertEqual(1, len([record for record in real.list_records() if record['text'] == '下一轮承接本轮']))
        self.assertEqual(message['text'], real.record_detail(message['id'])['text'])
        self.assertEqual(job['id'], service.submit(message['id'])['id'])

    def test_resume_job_left_running_by_terminated_process(self):
        import sqlite3
        service = self.service({'summary': '恢复后无变化。', 'operations': []})
        job = service.prepare(self.message['id'])
        ledger = Path(self.temp.name) / 'secretary' / 'jobs.sqlite3'
        with sqlite3.connect(ledger) as db:
            payload = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
            payload['status'] = 'running'
            db.execute('UPDATE jobs SET payload=? WHERE id=?', (json.dumps(payload), job['id']))
        restarted = self.service({'summary': '恢复后无变化。', 'operations': []})
        restarted.resume(job['id'])
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            status = restarted.get_job(job['id'])['status']
            if status == 'completed':
                break
            time.sleep(.01)
        self.assertEqual('completed', status)

    def test_submit_retries_failed_input_with_same_job_and_saved_plan(self):
        self.notebook.tasks['old'] = dict(id='old', revision=1, state='待办', title='模拟事项')
        self.notebook.fail_once = True
        reply = {'summary': '保存完成事实。', 'operations': [
            {'action': 'record', 'taskId': 'old', 'expectedRevision': 1,
             'patch': {'state': '已完成', 'note': '虚构输入明确已交付'}}]}
        service = self.service(reply)
        first = service.prepare(self.message['id'])
        self.assertEqual('failed', service.run(first['id'])['status'])
        retried = self.finished(service)
        self.assertEqual(first['id'], retried['id'])
        self.assertEqual('completed', retried['status'])
        self.assertEqual(1, len(self.notebook.writes))

    def test_image_and_text_attachments_reach_runner_as_actual_content(self):
        import base64
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a4N8AAAAASUVORK5CYII=')
        picture = nb.attach_asset('tiny.png', png, 'image/png')
        text = nb.attach_asset('context.txt', '虚构附件正文：下次见面带平板。'.encode(), 'text/plain')
        message = nb.append_record({'attachments': [picture['id'], text['id']]})
        seen = []
        def runner(context):
            seen.append(context)
            return {'summary': '已读取本条图片和文字附件，无新动作。', 'operations': []}
        service = SecretaryService(nb, root, model_runner=runner)
        final = service.run(service.prepare(message['id'])['id'])
        self.assertEqual('completed', final['status'], final)
        self.assertEqual(nb.asset(picture['id'])['path'], seen[0]['_imagePaths'][0])
        self.assertEqual('decoded_utf8', seen[0]['attachmentReading'][1]['nature'])
        self.assertIn('虚构附件正文', seen[0]['attachmentReading'][1]['text'])

    def test_unreadable_attachment_without_text_fails_without_inference(self):
        message = self.notebook.records['r1']
        message['text'] = ''
        message['attachments'] = [{'id': 'fake', 'name': 'payment-completed.pdf', 'mime': 'application/pdf'}]
        service = self.service({'summary': 'must not infer', 'operations': []})
        final = service.run(service.prepare('r1')['id'])
        self.assertEqual('failed', final['status'])
        self.assertEqual([], self.notebook.writes)

    def test_default_runner_transports_image_argument_without_prompt_path_dump(self):
        import sys
        from modules.secretary import CodexModelRunner
        root = Path(self.temp.name)
        capture = root / 'capture.json'
        image = root / 'fictional.png'
        image.write_bytes(b'fictional raw payload')
        executable = root / 'fake-codex'
        executable.write_text('#!' + sys.executable + '\n' +
            'import json,sys\n' +
            'from pathlib import Path\n' +
            'prompt=sys.stdin.read()\n' +
            'Path(' + repr(str(capture)) + ').write_text(json.dumps({"argv":sys.argv,"pathInPrompt":' + repr(str(image)) + ' in prompt}))\n' +
            'Path(sys.argv[sys.argv.index("-o")+1]).write_text(json.dumps({"summary":"fictional image transport","operations":[]}))\n')
        executable.chmod(0o700)
        result = CodexModelRunner(executable=str(executable), timeout=5)({'input': {'text': 'fictional'}, '_imagePaths': [str(image)]})
        self.assertEqual('fictional image transport', result['summary'])
        captured = json.loads(capture.read_text())
        self.assertEqual(str(image), captured['argv'][captured['argv'].index('--image') + 1])
        self.assertFalse(captured['pathInPrompt'])
        self.assertIn('--ignore-user-config', captured['argv'])

    def test_human_bound_progress_preserves_links_and_updates_existing_object(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '虚构本轮交件', 'state': '待办', 'summary': '交件后闭环'})
        message = nb.append_record({'text': '虚构：这一本轮材料已经发出。', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        seen = []
        def runner(context):
            seen.append(context)
            self.assertEqual([task['id']], nb.record_detail(message['id'])['objectIds'])
            return {'summary': '本轮交件已关闭。', 'operations': [
                {'action': 'record', 'taskId': task['id'], 'expectedRevision': task['revision'],
                 'patch': {'state': '已完成', 'note': '输入明确材料已发出'}}]}
        service = SecretaryService(nb, root, model_runner=runner)
        result = service.run(service.prepare(message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual([task['id']], seen[0]['focusedTaskIds'])
        self.assertEqual(task['id'], seen[0]['expandedTasks'][0]['id'])
        self.assertEqual('已完成', nb.get_task(task['id'])['state'])
        self.assertEqual([task['id']], nb.record_detail(message['id'])['objectIds'])
        self.assertEqual(message['text'], nb.record_detail(message['id'])['text'])

    def test_large_303_task_catalog_reaches_model_within_budget_without_quotes(self):
        original = self.message['text']
        for i in range(303):
            task_id = 'old-' + str(i)
            self.notebook.tasks[task_id] = dict(id=task_id, revision=9, title='虚构交付任务' + str(i),
                kind='action', domain='他山', state='等对方', assignee='我', proposedAt='2026-10-22T12:00:00Z',
                summary='虚构进展与独立交付边界。' * 80, completionCriterion='虚构材料发出并确认收到。' * 40,
                planDate=None, reviewDate='2026-10-30', relatedRecordIds=[],
                evidence=[{'quote': '仅应在重点展开中的模拟原文。' * 1000}])
        before = copy.deepcopy(self.notebook.tasks)
        seen = []
        def runner(context):
            seen.append(context)
            return {'summary': '本输入无新增，已检查有界目录。', 'operations': []}
        service = SecretaryService(self.notebook, self.temp.name, model_runner=runner)
        result = service.run(service.prepare(self.message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        context = seen[0]
        self.assertEqual(303, len(context['tasks']))
        self.assertTrue(context['coverage']['catalogComplete'])
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False, separators=(',', ':')).encode()), 240000)
        self.assertTrue(all('evidence' not in task for task in context['tasks']))
        self.assertEqual(before, self.notebook.tasks)
        self.assertEqual(original, self.notebook.record_detail('r1')['text'])

    def test_ai_receipt_is_not_consumed_as_new_input(self):
        receipt = self.notebook.append_record({'text': 'AI处理回执', 'actor': {'name': 'AI秘书', 'kind': 'ai'}})
        service = self.service({'summary': 'none', 'operations': []})
        with self.assertRaises(SecretaryValidationError):
            service.prepare(receipt['id'])

    def test_partial_catalog_reports_gap_and_rejects_new_object_creation(self):
        for i in range(1500):
            self.notebook.tasks['old-' + str(i)] = dict(id='old-' + str(i), revision=1,
                title='模拟历史条目' + str(i), state='已完成', kind='action', domain='他山',
                assignee='虚构负责人' * 20, summary='历史材料' * 100, completionCriterion='本轮交付' * 100)
        seen = []
        def runner(context):
            seen.append(context)
            return {'summary': '不应在目录不全时新增。', 'operations': [
                {'action': 'create', 'key': 'unsafe', 'task': {'title': '尚未完整查重的事项'}}]}
        service = SecretaryService(self.notebook, self.temp.name, model_runner=runner)
        result = service.run(service.prepare('r1')['id'])
        self.assertEqual('failed', result['status'])
        self.assertFalse(seen[0]['coverage']['catalogComplete'])
        self.assertGreater(seen[0]['coverage']['catalogOmittedCount'], 0)
        self.assertLessEqual(len(json.dumps(seen[0], ensure_ascii=False, separators=(',', ':')).encode()), 240000)
        self.assertEqual([], self.notebook.writes)
        self.assertEqual(1500, len(self.notebook.tasks))

    def test_new_substantive_recommendation_reenters_review_but_plain_note_stays_quiet(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '虚构等待对方确认', 'state': '等对方'})
        task = nb.record(task['id'], {'expectedRevision': task['revision'], 'confirm': True})
        self.assertFalse(task['needsReview'])
        plain = nb.append_record({'text': '虚构：仍在等对方，暂无变化。', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        quiet = SecretaryService(nb, root, model_runner=lambda _: {'summary': '无新决策，安静保留。', 'operations': [
            {'action': 'append', 'objectIds': [task['id']], 'text': '本轮仍等待，无需重新批阅。'}]})
        self.assertEqual('completed', quiet.run(quiet.prepare(plain['id'])['id'])['status'])
        self.assertFalse(nb.get_task(task['id'])['needsReview'])
        message = nb.append_record({'text': '虚构：对方明确需要我今天补交材料再批。', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        current = nb.get_task(task['id'])
        service = SecretaryService(nb, root, model_runner=lambda _: {'summary': '新事实需要用户决定，重新呈报。', 'operations': [
            {'action': 'record', 'taskId': task['id'], 'expectedRevision': current['revision'],
             'patch': {'needsReview': True, 'recommendation': {'state': '待办', 'reason': '对方新增补材料要求，需要本人安排。'},
                       'note': '新留言明确本轮新增材料要求，呈报这项新决策。'}}]})
        result = service.run(service.prepare(message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertTrue(nb.get_task(task['id'])['needsReview'])
        self.assertEqual('等对方', nb.get_task(task['id'])['state'])
        self.assertIn(task['id'], [item['id'] for item in nb.query('review', assignee='我')])

    def test_reject_ai_review_ack_and_closed_review_reopening(self):
        for state, fields in [('等对方', {'needsReview': False}),
                ('等对方', {'needsReview': True, 'note': '仅普通备注，无推荐决策'}),
                ('已完成', {'needsReview': True, 'recommendation': {'state': '待办', 'reason': '旧催办'}})]:
            with self.subTest(state=state, fields=fields):
                self.notebook.tasks['old'] = dict(id='old', revision=1, title='模拟原项', state=state, needsReview=False)
                message = self.notebook.append_record({'text': '虚构输入', 'objectIds': ['old']})
                service = self.service({'summary': 'invalid review', 'operations': [
                    {'action': 'record', 'taskId': 'old', 'expectedRevision': 1, 'patch': fields}]})
                result = service.run(service.prepare(message['id'])['id'])
                self.assertEqual('failed', result['status'])
                self.assertFalse(self.notebook.tasks['old']['needsReview'])
                self.assertEqual(state, self.notebook.tasks['old']['state'])
        self.assertEqual([], self.notebook.writes)

    def test_source_original_metadata_reaches_notebook_evidence_and_contacts(self):
        from modules.notebook import NotebookService
        from modules.sources import SourceRegistry
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        sources = SourceRegistry(root)
        original = {'nativeId': 'native-message-123', 'sender': '虚构原发言人', 'conversation': '虚构真实群名',
                    'at': '2026-10-21T10:11:12+08:00', 'type': 'text', 'text': '虚构来源原话：本轮还需补一份材料。'}
        receipt = sources.import_records('wechat', 'fictional', [original])
        saved = sources.query(receipt['sourceId'])['records'][0]
        reply = {'summary': '根据已保存原话新增候选。', 'operations': [
            {'action': 'create', 'key': 'new', 'task': {'title': '虚构补一份材料', 'completionCriterion': '本轮材料发出'}}]}
        service = SecretaryService(nb, root, model_runner=lambda _: reply, source_port=sources)
        result = service.run(service.prepare({'sourceId': receipt['sourceId'], 'recordId': saved['id']})['id'])
        self.assertEqual('completed', result['status'], result)
        task = nb.get_task(result['result']['created'][0])
        evidence = next(item for item in task['evidence'] if item.get('quote') == original['text'])
        self.assertEqual(original['sender'], evidence['sender'])
        self.assertEqual(original['conversation'], evidence['conversation'])
        self.assertEqual(original['at'], evidence['at'])
        self.assertTrue(any(item.get('nativeId') == original['nativeId'] and item.get('sourceId') == receipt['sourceId']
                            for item in task['sourceContacts']))
        imported = nb.record_detail(result['sourceMessageId'])
        self.assertEqual(original['text'], imported['text'])
        running_receipt = next(item['text'] for item in imported['receipts'] if item['status'] == 'running')
        self.assertIn(original['sender'], running_receipt)
        self.assertIn(original['conversation'], running_receipt)
        self.assertIn(original['at'], running_receipt)
        self.assertNotIn(saved['id'], running_receipt)
        self.assertNotIn(receipt['sourceId'], running_receipt)

    def test_trusted_review_intent_accepts_saved_ai_request_and_remains_idempotent(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '虚构等待到期复查', 'state': '等对方', 'reviewDate': '2026-10-22'})
        task = nb.record(task['id'], {'expectedRevision': task['revision'], 'confirm': True})
        request = nb.append_record({'text': '明确复查请求：请核查现有资料是否有新事实，缺少新来源时说明未核实。',
            'actor': {'name': '本地调度', 'kind': 'ai'}, 'objectIds': [task['id']]})
        seen = []
        def runner(context):
            seen.append(context)
            return {'summary': '仅复查已保存资料，无新增来源；不改变状态。', 'operations': []}
        service = SecretaryService(nb, root, model_runner=runner)
        with self.assertRaises(SecretaryValidationError):
            service.prepare(request['id'])
        job = service.prepare(request['id'], 'trusted-review', intent='review')
        final = service.run(job['id'])
        self.assertEqual('completed', final['status'], final)
        self.assertEqual('review', seen[0]['intent'])
        self.assertEqual('review', seen[0]['input']['intent'])
        self.assertFalse(seen[0]['reviewPolicy']['upstreamRefreshPerformed'])
        self.assertEqual([task['id']], seen[0]['focusedTaskIds'])
        self.assertEqual('等对方', nb.get_task(task['id'])['state'])
        self.assertFalse(nb.get_task(task['id'])['needsReview'])
        self.assertEqual(request['text'], nb.record_detail(request['id'])['text'])
        self.assertEqual(job['id'], service.submit(request['id'], 'trusted-review', intent='review')['id'])
        self.assertEqual(1, len(service.list_jobs()))
        with self.assertRaises(SecretaryValidationError):
            service.prepare(request['id'])

    def test_review_intent_requires_explicit_pending_bound_ai_input(self):
        service = self.service({'summary': 'should not run', 'operations': []})
        for message_id, intent in [(None, 'review'), (self.message['id'], 'review'), (self.message['id'], 'execute')]:
            with self.subTest(message_id=message_id, intent=intent):
                with self.assertRaises(SecretaryValidationError):
                    service.prepare(message_id, intent=intent)
        unbound = self.notebook.append_record({'text': 'AI普通回执', 'actor': {'name': 'AI', 'kind': 'ai'}})
        with self.assertRaises(SecretaryValidationError):
            service.prepare(unbound['id'], intent='review')
        self.assertEqual([], service.list_jobs())

    def test_plan_field_preflight_rejects_invalid_second_create_before_any_write(self):
        from modules.notebook import NotebookService
        invalids = [{'assignee': 'a' * 121}, {'condition': 'c' * 2001}, {'title': 't' * 1001},
                    {'timeRequirement': None}, {'note': 'bad\x00value'}, {'planDate': '2026-10-22T00:00:00Z'},
                    {'proposedAt': '2026-10-22T12:00:00'}, {'completionCriterion': 'x' * 2001}]
        for index, invalid in enumerate(invalids):
            with self.subTest(invalid=next(iter(invalid))):
                root = Path(self.temp.name) / str(index)
                nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
                message = nb.append_record({'text': '模拟批量候选，非法字段应整批拒绝。'})
                bad = {'title': 'invalid'}
                bad.update(invalid)
                service = SecretaryService(nb, root, model_runner=lambda _, bad=bad: {'summary': 'invalid', 'operations': [
                    {'action': 'create', 'key': 'first', 'task': {'title': '必须不被写入的第一个候选'}},
                    {'action': 'create', 'key': 'second', 'task': bad}]})
                result = service.run(service.prepare(message['id'])['id'])
                self.assertEqual('failed', result['status'])
                self.assertEqual([], nb.list_tasks())
                self.assertEqual(message['text'], nb.record_detail(message['id'])['text'])

    def test_conflict_retry_rereads_human_revision_and_can_choose_noop(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '虚构待核对结果', 'state': '等对方'})
        message = nb.append_record({'text': '模拟新增说明，先核对是否已经交付。', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                nb.record(task['id'], {'expectedRevision': task['revision'], 'summary': '人工最新说明：尚未确认交付',
                    'actor': {'name': '我', 'kind': 'human'}})
                return {'summary': '旧上下文中的关闭提议。', 'operations': [
                    {'action': 'record', 'taskId': task['id'], 'expectedRevision': task['revision'],
                     'patch': {'state': '已完成', 'note': '此提议应因人工并发修正而失败'}}]}
            current = next(item for item in context['tasks'] if item['id'] == task['id'])
            self.assertEqual(task['revision'] + 1, current['revision'])
            self.assertIn('人工最新说明', current['summary'])
            return {'summary': '重新读取人工修正后保留等待，不再关闭。', 'operations': []}
        service = SecretaryService(nb, root, model_runner=runner)
        job = service.prepare(message['id'])
        failed = service.run(job['id'])
        self.assertEqual('failed', failed['status'])
        completed = service.run(job['id'])
        self.assertEqual('completed', completed['status'], completed)
        self.assertEqual(2, len(contexts))
        self.assertEqual(1, completed['replanAttempts'])
        self.assertEqual('等对方', nb.get_task(task['id'])['state'])
        self.assertIn('人工最新说明', nb.get_task(task['id'])['summary'])
        self.assertEqual([], completed['steps'])

    def test_partial_create_conflict_replans_tail_without_duplicate_or_human_override(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '虚构本轮交件', 'state': '待办'})
        message = nb.append_record({'text': '模拟：本轮状态请核对，另记下一阶段候选。', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                nb.record(task['id'], {'expectedRevision': task['revision'], 'state': '暂缓', 'summary': '本人决定暂不关闭',
                    'actor': {'name': '我', 'kind': 'human'}})
                return {'summary': '新增阶段，尝试更新原项。', 'operations': [
                    {'action': 'create', 'key': 'next', 'task': {'title': '虚构下一阶段独立交付'}},
                    {'action': 'record', 'taskId': task['id'], 'expectedRevision': task['revision'],
                     'patch': {'state': '已完成', 'note': '旧修订提议'}}]}
            prefix = context['completedPrefix']
            self.assertEqual(1, len(prefix['created']))
            self.assertIn(prefix['created'][0], [item['id'] for item in context['tasks']])
            current = next(item for item in context['tasks'] if item['id'] == task['id'])
            return {'summary': '保留已新增候选和本人暂缓决定，仅补处理说明。', 'operations': [
                {'action': 'record', 'taskId': task['id'], 'expectedRevision': current['revision'],
                 'patch': {'note': '重新核对后保留本人的暂缓决定。'}}]}
        service = SecretaryService(nb, root, model_runner=runner)
        job = service.prepare(message['id'])
        first = service.run(job['id'])
        self.assertEqual('failed', first['status'])
        self.assertEqual(1, len(first['result']['created']))
        final = service.run(job['id'])
        self.assertEqual('completed', final['status'], final)
        self.assertEqual(first['result']['created'], final['result']['created'])
        self.assertEqual(2, len(nb.list_tasks()))
        self.assertEqual('暂缓', nb.get_task(task['id'])['state'])
        self.assertEqual('本人决定暂不关闭', nb.get_task(task['id'])['summary'])
        self.assertEqual(first['steps'][0], final['steps'][0])
        self.assertEqual(2, len(contexts))
        import sqlite3
        with sqlite3.connect(root / 'secretary' / 'jobs.sqlite3') as db:
            saved = json.loads(db.execute('SELECT payload FROM jobs WHERE id=?', (job['id'],)).fetchone()[0])
        self.assertEqual(1, len(saved['planArchives']))
        self.assertEqual(1, saved['planArchives'][0]['completedStepCount'])
        self.assertEqual(task['revision'], saved['planArchives'][0]['plan']['operations'][1]['expectedRevision'])
        self.assertNotIn('planArchives', final)

    def test_replanning_is_bounded_and_does_not_force_latest_human_state(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '模拟持续并发修改', 'state': '等对方'})
        message = nb.append_record({'text': '模拟并发复核请求', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        calls = []
        def runner(context):
            calls.append(context)
            current = nb.get_task(task['id'])
            nb.record(task['id'], {'expectedRevision': current['revision'], 'summary': '最新人工决定' + str(len(calls)),
                'actor': {'name': '我', 'kind': 'human'}})
            return {'summary': '必须因并发修改而拒绝的旧修订。', 'operations': [
                {'action': 'record', 'taskId': task['id'], 'expectedRevision': current['revision'],
                 'patch': {'state': '已完成', 'note': '禁止强制覆盖'}}]}
        service = SecretaryService(nb, root, model_runner=runner)
        job = service.prepare(message['id'])
        for _ in range(4):
            result = service.run(job['id'])
            self.assertEqual('failed', result['status'])
        self.assertEqual(3, len(calls))
        self.assertEqual(2, result['replanAttempts'])
        self.assertEqual('等对方', nb.get_task(task['id'])['state'])
        self.assertEqual('最新人工决定3', nb.get_task(task['id'])['summary'])
        self.assertNotIn('planArchives', result)

    def test_public_field_validator_runs_for_all_operations_before_first_task_write(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        message = nb.append_record({'text': '模拟两个均合法的候选。'})
        calls = []
        class Port:
            def __getattr__(self, name):
                return getattr(nb, name)
            def validate_fields(self, body, creating=False):
                self_assert = len(nb.list_tasks())
                if self_assert != 0:
                    raise AssertionError('pure field validation must finish before any writes')
                calls.append((body, creating))
                return nb.validate_fields(body, creating=creating)
        service = SecretaryService(Port(), root, model_runner=lambda _: {'summary': '两个候选均先校验。', 'operations': [
            {'action': 'create', 'key': 'first', 'task': {'title': '模拟候选一'}},
            {'action': 'create', 'key': 'second', 'task': {'title': '模拟候选二', 'relatedRecordIds': ['$first']}}]})
        result = service.run(service.prepare(message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        self.assertEqual(2, len(calls))
        self.assertTrue(all(creating for _, creating in calls))
        self.assertTrue(calls[1][0]['relatedRecordIds'][0].startswith('PREFLIGHT-'))
        self.assertEqual(2, len(nb.list_tasks()))

    def test_replanning_reads_latest_human_note_even_when_projection_fields_unchanged(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        task = nb.create_task({'title': '模拟只补备注的并发事项', 'state': '等对方'})
        message = nb.append_record({'text': '模拟：请核查这轮是否可以关闭', 'objectIds': [task['id']]})
        task = nb.get_task(task['id'])  # Linked input changes the notebook revision.
        contexts = []
        def runner(context):
            contexts.append(context)
            if len(contexts) == 1:
                nb.record(task['id'], {'expectedRevision': task['revision'],
                    'note': '人工最新更正：仍未发出，不要关闭。', 'actor': {'name': '我', 'kind': 'human'}})
                return {'summary': '旧判断将关闭，但必须因并发而拒绝。', 'operations': [
                    {'action': 'record', 'taskId': task['id'], 'expectedRevision': task['revision'],
                     'patch': {'state': '已完成', 'note': '旧上下文关闭提议'}}]}
            history = context['latestTaskHistory'][task['id']]
            self.assertTrue(any('人工最新更正' in item['note'] and item['actor']['kind'] == 'human' for item in history))
            return {'summary': '已读人工新备注，继续等待，不关闭。', 'operations': []}
        service = SecretaryService(nb, root, model_runner=runner)
        job = service.prepare(message['id'])
        self.assertEqual('failed', service.run(job['id'])['status'])
        final = service.run(job['id'])
        self.assertEqual('completed', final['status'], final)
        self.assertEqual('等对方', nb.get_task(task['id'])['state'])
        self.assertEqual(2, len(contexts))

    def test_sequential_links_use_simulated_refs_and_reject_entire_overflow_plan(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        existing = [nb.create_task({'title': '虚构关联对象' + str(i)})['id'] for i in range(101)]
        base = nb.create_task({'title': '虚构已关联99个对象的事项', 'relatedRecordIds': existing[:99]})
        message = nb.append_record({'text': '模拟两次关联，整体溢出应全部拒绝。', 'objectIds': [base['id']]})
        base = nb.get_task(base['id'])  # Linked input changes the notebook revision.
        service = SecretaryService(nb, root, model_runner=lambda _: {'summary': '两次关联必须先模拟聚合。', 'operations': [
            {'action': 'link', 'objectIds': [base['id'], existing[99]], 'relation': 'related_to', 'text': '模拟第一步关联'},
            {'action': 'link', 'objectIds': [base['id'], existing[100]], 'relation': 'related_to', 'text': '模拟第二步关联'}]})
        result = service.run(service.prepare(message['id'])['id'])
        self.assertEqual('failed', result['status'])
        self.assertEqual(base['revision'], nb.get_task(base['id'])['revision'])
        self.assertEqual(existing[:99], nb.get_task(base['id'])['relatedRecordIds'])
        self.assertEqual([], result['steps'])
        self.assertEqual([], result['result']['linked'])
        self.assertFalse(any(record['text'] in {'模拟第一步关联', '模拟第二步关联'} for record in nb.list_records()))

    def test_prior_record_and_local_alias_links_share_one_simulated_state(self):
        from modules.notebook import NotebookService
        root = Path(self.temp.name)
        nb = NotebookService(root / 'notebook' / 'notebook.sqlite3', root / 'source.json', root)
        old = nb.create_task({'title': '虚构原关联对象'})
        replacement = nb.create_task({'title': '虚构替换关联对象'})
        base = nb.create_task({'title': '虚构原事项', 'relatedRecordIds': [old['id']]})
        message = nb.append_record({'text': '模拟先替换关联，再关联两个新对象。', 'objectIds': [base['id']]})
        base = nb.get_task(base['id'])  # Linked input changes the notebook revision.
        reply = {'summary': '按同一模拟状态依次处理。', 'operations': [
            {'action': 'record', 'taskId': base['id'], 'expectedRevision': base['revision'],
             'patch': {'relatedRecordIds': [replacement['id']]}},
            {'action': 'create', 'key': 'one', 'task': {'title': '虚构新增对象一'}},
            {'action': 'create', 'key': 'two', 'task': {'title': '虚构新增对象二'}},
            {'action': 'link', 'objectIds': [base['id'], '$one'], 'relation': 'related_to', 'text': '关联新增一'},
            {'action': 'link', 'objectIds': [base['id'], '$two'], 'relation': 'related_to', 'text': '关联新增二'},
            {'action': 'link', 'objectIds': ['$one', '$two'], 'relation': 'follows', 'text': '新增对象之间关联'}]}
        service = SecretaryService(nb, root, model_runner=lambda _: reply)
        result = service.run(service.prepare(message['id'])['id'])
        self.assertEqual('completed', result['status'], result)
        created = result['result']['created']
        self.assertEqual([replacement['id']] + created, nb.get_task(base['id'])['relatedRecordIds'])
        self.assertEqual([created[1]], nb.get_task(created[0])['relatedRecordIds'])
        self.assertEqual(3, len(result['result']['linked']))

    def test_request_id_conflict_and_disk_status_survive_restart(self):
        service = self.service({'summary': 'kept', 'operations': []})
        first = self.finished(service, request_id='request-a')
        restarted = self.service({'summary': 'kept', 'operations': []})
        self.assertEqual(first['id'], restarted.get_job(first['id'])['id'])
        other = self.notebook.append_record({'text': '另一个输入'})
        with self.assertRaises(SecretaryValidationError):
            restarted.submit(message_id=other['id'], request_id='request-a')


if __name__ == '__main__':
    unittest.main()
