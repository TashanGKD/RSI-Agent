"""Synthetic-only cloud boundary tests. Never open a user's formal notebook.

Invariant: export only allowlisted task meaning/history; never raw evidence or
credentials. Reject XML/credential/path injected bundles, existing destinations,
and symlink ancestors before creating a database or partial export.
"""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modules.notebook import NotebookService, ValidationError


class CloudProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.src = self.root / 'source.json'
        self.src.write_text(json.dumps({'records': [
            {'recordId': 'OLD-1', 'action': '核对申请材料', 'status': '待处理'},
            {'recordId': 'OLD-2', 'action': '材料已交', 'status': '已完成'}]}))
        self.n = NotebookService(self.root / 'local.db', self.src, self.root / 'local')
        spec = importlib.util.find_spec('modules.notebook.cloud_projection')
        self.assertIsNotNone(spec, 'cloud projection component is required')
        from modules.notebook.cloud_projection import export_projection, import_projection
        self.export = export_projection
        self.load = import_projection

    def bundle(self):
        output = self.root / 'bundle'
        result = self.export(self.n, output)
        self.assertEqual(Path(result['bundle']), output / 'projection.json')
        self.assertEqual(Path(result['audit']), output / 'audit.json')
        return output

    def tamper(self, output, mutate):
        path = output / 'projection.json'
        obj = json.loads(path.read_text())
        mutate(obj)
        path.write_text(json.dumps(obj, ensure_ascii=False))
        audit = json.loads((output / 'audit.json').read_text())
        audit['bundleSha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / 'audit.json').write_text(json.dumps(audit))

    def test_reject_xml_credential_and_absolute_path_even_with_updated_checksum(self):
        for index, hostile in enumerate([
                '<msg><img aeskey="abc123" cdnthumburl="private"/></msg>',
                'Authorization: Bearer private-token-value-12345',
                '附件在 /Users/example/WeChat/secret.txt',
                'sk-proj-synthetickeyvalue1234567890',
                'token=synthetic-private-key',
                '%2FUsers%2Fexample%2Fcredential.txt']):
            output = self.root / ('bundle-' + str(index))
            self.export(self.n, output)
            self.tamper(output, lambda b: b['objects'][0].update(summary=hostile))
            ws = self.root / ('cloud-' + str(index))
            with self.assertRaises(ValidationError):
                self.load(output, ws / 'cloud.db', ws)
            self.assertFalse(ws.exists(), 'validation must precede allocations')

    def test_no_overwrite_or_symlink_escape(self):
        output = self.bundle()
        before = (output / 'projection.json').read_bytes()
        with self.assertRaises(ValidationError):
            self.export(self.n, output)
        self.assertEqual((output / 'projection.json').read_bytes(), before)
        ws = self.root / 'cloud'
        ws.mkdir()
        db = ws / 'cloud.db'
        db.write_bytes(b'existing database')
        with self.assertRaises(ValidationError):
            self.load(output, db, ws)
        self.assertEqual(db.read_bytes(), b'existing database')
        link = self.root / 'link'
        link.symlink_to(ws, target_is_directory=True)
        with self.assertRaises(ValidationError):
            self.export(self.n, link / 'export')
        with self.assertRaises(ValidationError):
            self.load(output, link / 'other.db', link)
        self.assertFalse((ws / 'export').exists())
        self.assertFalse((ws / 'other.db').exists())

    def test_source_echo_is_removed_from_notes_previous_summary_and_hidden_versions(self):
        secret = '这是只留在本机的完整微信语音转写内容切勿上传外部服务器'
        short = '另外一段历史私密来源原话不能出现在摘要里'
        with self.n._connect() as db:
            raw = json.loads(db.execute("SELECT payload FROM tasks WHERE id='OLD-1'").fetchone()[0])
            raw['evidence'] = [{'sender': '合成人物', 'text': secret}]
            raw['lastKnownState'] = '进展：' + secret
            db.execute("UPDATE tasks SET payload=? WHERE id='OLD-1'", (json.dumps(raw),))
            db.execute('INSERT INTO source_versions VALUES(?,?,?,?)', (
                'OLD-1', 'synthetic-hash', json.dumps({'evidence': [{'quote': short}]}), '2026-10-22T00:00:00Z'))
        t = self.n.get_task('OLD-1')
        self.n.record(t['id'], {'expectedRevision': t['revision'], 'summary': '已复核', 'note': '引用：' + short})
        t = self.n.get_task('OLD-1')
        self.n.record(t['id'], {'expectedRevision': t['revision'], 'note': '本人决定下周再核对'})
        t = self.n.get_task('OLD-1')
        self.n.record(t['id'], {'expectedRevision': t['revision'], 'note': 'AI照抄：' + secret,
            'actor': {'name': 'AI秘书', 'kind': 'ai'}})
        self.n.append_record({'text': secret, 'objectIds': ['OLD-1'], 'sourceRefs': [
            {'sourceId': 'wechat:personal', 'recordId': 'native-123', 'nativeId': '123', 'conversation': '合成会话'}]})
        output = self.bundle()
        exported = ''.join(p.read_text() for p in output.iterdir())
        for forbidden in (secret, short, 'aeskey', str(self.root), 'AI照抄'):
            self.assertNotIn(forbidden, exported)
        self.assertIn('本人决定下周再核对', exported)
        audit = json.loads((output / 'audit.json').read_text())
        self.assertGreaterEqual(audit['sourceFingerprintCount'], 2)
        self.assertTrue(audit['sourceEchoAuditPassed'])
        cloud = self.root / 'cloud'
        result = self.load(output, cloud / 'cloud.db', cloud)
        self.assertEqual(result['objectCount'], 2)
        n = NotebookService(cloud / 'cloud.db', cloud / 'missing-source.json', cloud)
        self.assertEqual(n.get_task('OLD-1')['revision'], self.n.get_task('OLD-1')['revision'])
        task = n.get_task('OLD-1')
        self.assertEqual(task['evidence'][0]['localOnly'], True)
        self.assertEqual(task['evidence'][0]['label'], '原文保留Mac')
        self.assertNotIn(secret, json.dumps(n.detail('OLD-1'), ensure_ascii=False))

    def test_303_stable_ids_current_fields_and_history_survive_actual_service_readback(self):
        for i in range(301):
            self.n.create_task({'title': '合成事项' + str(i), 'domain': '他山', 'assignee': 'AI',
                'state': '等对方', 'reviewDate': '2099-01-01', 'condition': '收到回复时复查'})
        t = self.n.get_task('OLD-1')
        self.n.record(t['id'], {'expectedRevision': t['revision'], 'state': '暂缓', 'domain': '科研',
            'reviewDate': '2099-02-01', 'relatedRecordIds': ['OLD-2'], 'note': '本人决定等结果'})
        before = {t['id']: t for t in self.n.list_tasks()}
        event_ids = [e['id'] for e in self.n.detail('OLD-1')['timeline']]
        output = self.bundle()
        cloud = self.root / 'cloud'
        self.load(output, cloud / 'cloud.db', cloud)
        n = NotebookService(cloud / 'cloud.db', cloud / 'missing-source.json', cloud)
        after = {t['id']: t for t in n.list_tasks()}
        self.assertEqual(set(before), set(after))
        self.assertEqual(len(after), 303)
        for rid in before:
            for field in ('state', 'kind', 'domain', 'assignee', 'planDate', 'reviewDate', 'condition',
                          'revision', 'needsReview', 'recommendation', 'relatedRecordIds'):
                self.assertEqual(before[rid].get(field), after[rid].get(field), (rid, field))
        projected = after['OLD-1']['cloudProjectionTimeline']
        self.assertEqual({e['id'] for e in projected}, set(event_ids))
        self.assertEqual(projected[0]['actor']['kind'], 'human')
        self.assertEqual(projected[0]['changes']['state'], '暂缓')
        self.assertIn('OLD-2', [t['id'] for t in n.detail('OLD-1')['relatedTasks']])
        current = n.get_task('OLD-1')
        changed = n.record('OLD-1', {'expectedRevision': current['revision'], 'note': '云上新增批注'})
        self.assertEqual(changed['revision'], current['revision'] + 1)

    def test_tampered_unknown_fields_and_checksum_are_rejected(self):
        output = self.bundle()
        self.tamper(output, lambda b: b['objects'][0].update(hiddenRawSource='private'))
        with self.assertRaises(ValidationError):
            self.load(output, self.root / 'cloud' / 'cloud.db', self.root / 'cloud')
        self.assertFalse((self.root / 'cloud').exists())

    def test_human_note_used_as_fallback_evidence_is_still_necessary_human_meaning(self):
        self.n.create_task({'title': '独立判断事项', 'note': '本人决定先完成方案再联系对方'})
        output = self.bundle()
        data = json.loads((output / 'projection.json').read_text())
        task = next(t for t in data['objects'] if t['title'] == '独立判断事项')
        self.assertEqual(task['cloudProjectionTimeline'][0]['note'], '本人决定先完成方案再联系对方')

    def test_audit_cannot_hide_raw_content_and_failed_import_cleans_new_workspace(self):
        output = self.bundle()
        path = output / 'audit.json'
        original = path.read_text()
        audit = json.loads(original)
        audit['debugOriginal'] = '不得夹带原始文本'
        path.write_text(json.dumps(audit))
        ws = self.root / 'cloud'
        with self.assertRaises(ValidationError):
            self.load(output, ws / 'cloud.db', ws)
        self.assertFalse(ws.exists())
        path.write_text(original)
        with patch('modules.notebook.cloud_projection.NotebookService', side_effect=RuntimeError('synthetic database failure')):
            with self.assertRaises(RuntimeError):
                self.load(output, ws / 'cloud.db', ws)
        self.assertFalse(ws.exists())

    def test_linked_record_does_not_become_duplicate_projected_event(self):
        message = self.n.append_record({'text': '本人决定等待回信', 'objectIds': ['OLD-1']})
        output = self.bundle()
        data = json.loads((output / 'projection.json').read_text())
        task = next(t for t in data['objects'] if t['id'] == 'OLD-1')
        self.assertNotIn(message['id'], [e['id'] for e in task['cloudProjectionTimeline']])
        self.assertEqual(data['records'][0]['id'], message['id'])

    def test_source_echo_cannot_hide_in_time_or_previous_nested_metadata(self):
        secret = '只留本机的一段来源原话不可作为时间传出'
        with self.n._connect() as db:
            raw = json.loads(db.execute("SELECT payload FROM tasks WHERE id='OLD-1'").fetchone()[0])
            raw.update(evidence=[{'quote': secret}], proposedAt=secret)
            db.execute("UPDATE tasks SET payload=? WHERE id='OLD-1'", (json.dumps(raw),))
        task = self.n.get_task('OLD-1')
        self.n.record('OLD-1', {'expectedRevision': task['revision'], 'note': '继续核对', 'sourceTime': secret})
        # Simulate old event metadata, whose sourceTime was not date validated.
        with self.n._connect() as db:
            event = db.execute("SELECT seq,payload FROM local_changes WHERE id='OLD-1'").fetchone()
            payload = json.loads(event['payload'])
            payload['sourceTime'] = secret
            db.execute('UPDATE local_changes SET payload=? WHERE seq=?', (json.dumps(payload), event['seq']))
        output = self.bundle()
        self.assertNotIn(secret, (output / 'projection.json').read_text())

    def test_nested_unknown_history_and_locator_payloads_are_rejected(self):
        task = self.n.get_task('OLD-1')
        self.n.record('OLD-1', {'expectedRevision': task['revision'], 'note': '本轮判断已保存'})
        for index, mutate in enumerate((
                lambda b: b['objects'][0]['sourceContacts'].append({'senderName': {'raw': 'hidden body'}}),
                lambda b: b['objects'][0]['cloudProjectionTimeline'][0]['previous'].update(summary={'raw': 'hidden body'}),
                lambda b: b['objects'][0].update(recommendation={'state': '待办', 'reason': 'safe', 'raw': 'hidden body'}))):
            output = self.root / ('nested-' + str(index))
            self.export(self.n, output)
            self.tamper(output, mutate)
            ws = self.root / ('nested-cloud-' + str(index))
            with self.assertRaises(ValidationError):
                self.load(output, ws / 'cloud.db', ws)
            self.assertFalse(ws.exists())

    def test_opaque_business_ids_can_name_credential_review_without_exporting_credentials(self):
        # An identifier can name the topic of an action; it is not prose evidence.
        task_id = 'TASK-AUTHORIZATION-REVIEW'
        with self.n._connect() as db:
            db.execute("UPDATE tasks SET id=? WHERE id='OLD-1'", (task_id,))
            row = db.execute('SELECT payload FROM tasks WHERE id=?', (task_id,)).fetchone()
            payload = json.loads(row[0]);payload['id'] = task_id
            db.execute('UPDATE tasks SET payload=? WHERE id=?', (json.dumps(payload), task_id))
        task = self.n.get_task(task_id)
        self.n.record(task_id, {'expectedRevision': task['revision'], 'relatedRecordIds': ['OLD-2']})
        output = self.bundle()
        ws = self.root / 'cloud'
        self.load(output, ws / 'cloud.db', ws)
        n = NotebookService(ws / 'cloud.db', ws / 'missing-source.json', ws)
        self.assertEqual(n.get_task(task_id)['id'], task_id)
        self.assertEqual(n.get_task(task_id)['revision'], self.n.get_task(task_id)['revision'])

    def test_recognizable_credential_value_cannot_use_the_identifier_exception(self):
        output = self.bundle()
        self.tamper(output, lambda b: b['objects'][0].update(id='sk-proj-synthetickeyvalue1234567890'))
        ws = self.root / 'cloud'
        with self.assertRaisesRegex(ValidationError, '编号不能包含认证凭证'):
            self.load(output, ws / 'cloud.db', ws)
        self.assertFalse(ws.exists())


if __name__ == '__main__':
    unittest.main()
