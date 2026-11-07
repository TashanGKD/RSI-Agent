"""Local notebook contract; isolated fixtures only, no user DB or source services.
Invariant: reject invalid IDs, unknown mutations, hostile assets before any durable write.
Breaking inputs: ../ paths, unknown state/field, foreign object reference, fake image bytes.
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
try:
    from modules.notebook import NotebookService
except ImportError:
    NotebookService = None
from store import ValidationError, ConflictError

class LocalNotebookTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(NotebookService, 'independent NotebookService must be implemented')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ws=Path(self.tmp.name); self.src=self.ws/'source.json';self.db=self.ws/'notebook.sqlite3'
        self.src.write_text(json.dumps({'records':[
            {'recordId':'OLD-1','action':'复核本轮方案','status':'待处理','counterparty':'协作者丙'},
            {'recordId':'OLD-2','action':'已交材料','status':'已完成'}]},ensure_ascii=False))
        self.n=NotebookService(self.db,self.src,self.ws)

    def test_reject_three_hostile_mutations_without_partial_write(self):
        task=self.n.get_task('OLD-1'); before=self.n.detail('OLD-1')
        bad=[{'state':'DROP TABLE tasks'}, {'unrecognized':'x'}, {'relatedRecordIds':['../secret']}]
        for p in bad:
            with self.assertRaises(ValidationError):self.n.record('OLD-1',dict(p,expectedRevision=task['revision'],note='必须回滚'))
            self.assertEqual(self.n.get_task('OLD-1')['revision'],task['revision'])
        self.assertEqual(self.n.detail('OLD-1')['timeline'],before['timeline'])

    def test_unbound_message_and_receipt_preserve_raw_input(self):
        r=self.n.append_record({'text':'下次见泽锐带平板','requestId':'MSG-1'})
        self.assertEqual(r['objectIds'],[]);self.assertEqual(r['processing'],'pending')
        self.assertEqual(self.n.append_record({'text':'下次见泽锐带平板','requestId':'MSG-1'})['id'],r['id'])
        self.assertEqual(len(self.n.list_tasks()),2,'no fake task for raw message')
        done=self.n.set_record_processing(r['id'],'completed','已记成条件备忘',object_ids=['OLD-1'])
        self.assertEqual(done['text'],'下次见泽锐带平板');self.assertEqual(done['receipts'][-1]['text'],'已记成条件备忘')
        self.assertEqual(self.n.record_detail(r['id'])['objectIds'],['OLD-1'])

    def test_state_and_review_are_independent(self):
        t=self.n.create_task({'title':'补技术表述','state':'其他','recommendation':{'state':'待办','reason':'需要一轮补充'},'domain':'示例项目项目'})
        self.assertTrue(t['needsReview'])
        t=self.n.record(t['id'],{'expectedRevision':t['revision'],'state':'待办','actor':{'name':'AI秘书','kind':'ai'}})
        self.assertTrue(t['needsReview'],'AI state does not pretend human acknowledged')
        t=self.n.record(t['id'],{'expectedRevision':t['revision'],'confirm':True,'state':'待办'})
        self.assertFalse(t['needsReview']); self.assertTrue(t['planDate'])
        self.assertIn(t['id'],[x['id'] for x in self.n.query('today',assignee='我')])
        self.assertNotIn(t['id'],[x['id'] for x in self.n.query('review')])

    def test_note_only_does_not_change_selected_options(self):
        t=self.n.get_task('OLD-1')
        after=self.n.record(t['id'],{'expectedRevision':t['revision'],'note':'看了前半部分'})
        for key in ['state','assignee','planDate','reviewDate','needsReview']:
            self.assertEqual(after[key],t[key],key)
        self.assertIn('看了前半部分',json.dumps(self.n.detail(t['id']),ensure_ascii=False))

    def test_future_plan_and_domain_and_owner_are_separate(self):
        t=self.n.create_task({'title':'核对资料','state':'待办','domain':'他山','assignee':'AI','planDate':'2099-01-01','confirm':True})
        self.assertEqual(self.n.query('today',domain='他山',assignee='AI'),[])
        self.assertIn(t['id'],[x['id'] for x in self.n.query('all',domain='他山',assignee='AI')])
        p=self.n.record(t['id'],{'expectedRevision':t['revision'],'planDate':'2020-01-01'})
        self.assertIn(t['id'],[x['id'] for x in self.n.query('today',domain='他山',assignee='AI')])

    def test_closed_state_suppresses_review_but_preserves_history(self):
        t=self.n.create_task({'title':'交本轮材料','reviewDate':'2099-01-01','state':'待办'})
        t=self.n.record(t['id'],{'expectedRevision':t['revision'],'state':'已完成','note':'本人确认已交','confirm':True})
        self.assertFalse(t['needsReview']);self.assertIsNone(t['reviewDate'])
        reopened=self.n.record(t['id'],{'expectedRevision':t['revision'],'state':'其他'})
        self.assertIsNone(reopened['reviewDate'],'reopening never revives old reminder')
        self.assertIn('本人确认已交',json.dumps(self.n.detail(t['id']),ensure_ascii=False))
        self.assertEqual(self.n.get_task('OLD-2')['state'],'已完成')

    def test_retry_collision_and_conflict(self):
        t=self.n.get_task('OLD-1');body={'expectedRevision':t['revision'],'note':'一次备注','requestId':'REQ-ONE'}
        after=self.n.record(t['id'],body)
        self.assertEqual(self.n.record(t['id'],body)['revision'],after['revision'])
        with self.assertRaises(ValidationError):self.n.record(t['id'],dict(body,note='另一个请求'))
        with self.assertRaises(ConflictError):self.n.record(t['id'],{'expectedRevision':t['revision'],'state':'暂缓'})
        self.assertEqual(self.n.get_task(t['id'])['revision'],after['revision'])

    def test_links_and_restart_keep_ids_records_and_old_data(self):
        t=self.n.create_task({'title':'下一轮修改','relatedRecordIds':['OLD-1'],'domain':'示例项目项目'})
        r=self.n.append_record({'text':'原始输入','objectIds':[t['id']]})
        n=NotebookService(self.db,self.src,self.ws)
        self.assertEqual(n.get_task(t['id'])['relatedRecordIds'],['OLD-1'])
        self.assertEqual(n.record_detail(r['id'])['text'],'原始输入')
        self.assertEqual(n.get_task('OLD-1')['title'],'复核本轮方案')
        self.assertIn(t['id'],[x['id'] for x in n.detail('OLD-1')['relatedTasks']])

    def test_foreign_ref_and_false_confirm_are_not_silent_writes(self):
        t=self.n.get_task('OLD-1')
        with self.assertRaises((KeyError,ValidationError)):self.n.append_record({'text':'x','objectIds':['MISSING']})
        with self.assertRaises(ValidationError):self.n.record(t['id'],{'expectedRevision':t['revision'],'confirm':'yes'})
        self.assertEqual(len(self.n.list_records()),0)

    def test_reject_hostile_assets_and_cleanup(self):
        for name,body in [('../p.png',b'fake'),('x.html',b'<script>'),('x.png',b'not a png')]:
            with self.assertRaises(ValidationError):self.n.attach_asset(name,body)
        asset_root=self.ws/'notebook'/'attachments'
        self.assertEqual([p for p in asset_root.glob('*') if p.is_file()],[])

    def test_asset_readback_is_bounded_and_content_addressed(self):
        raw=b'\x89PNG\r\n\x1a\n'+b'\x00'*25
        a=self.n.attach_asset('说明.png',raw,'image/png')
        self.assertEqual(Path(self.n.asset(a['id'])['path']).read_bytes(),raw)
        r=self.n.append_record({'text':'看这张图','attachments':[a['id']]})
        self.assertEqual(r['attachments'][0]['id'],a['id'])
        with self.assertRaises((KeyError,ValidationError)):self.n.asset('../x')

    def test_local_notes_and_contextual_message_are_inline_evidence(self):
        t=self.n.create_task({'title':'没有外部来源的事项','note':'本人亲自补充的原话'})
        self.assertEqual(self.n.get_task(t['id'])['evidence'][0]['quote'],'本人亲自补充的原话')
        t2=self.n.create_task({'title':'来自留言'})
        self.n.append_record({'text':'这是原始留言','objectIds':[t2['id']]})
        self.assertEqual(self.n.get_task(t2['id'])['evidence'][0]['quote'],'这是原始留言')

    def test_asset_transaction_failure_does_not_leave_orphan_file(self):
        from contextlib import contextmanager
        import sqlite3
        original=self.n._connect
        @contextmanager
        def fail_transaction():
            with original() as db:
                yield db
                raise sqlite3.OperationalError('injected commit failure')
        self.n._connect=fail_transaction
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.n.attach_asset('failure.png',b'\x89PNG\r\n\x1a\n'+bytes(25))
        finally:self.n._connect=original
        self.assertEqual(list(self.n.assets_dir.glob('*')),[])

    def test_unhashable_reference_input_rejected_as_validation(self):
        with self.assertRaises(ValidationError):self.n.append_record({'text':'x','objectIds':[{}]})
        self.assertEqual(self.n.list_records(),[])

    def test_shared_information_links_both_objects_without_renaming(self):
        t=self.n.create_task({'title':'下一步独立事项'})
        self.n.append_record({'text':'两件事关联','objectIds':['OLD-1',t['id']],'actor':{'name':'AI秘书','kind':'ai'}})
        self.assertIn(t['id'],[x['id'] for x in self.n.detail('OLD-1')['relatedTasks']])
        self.assertIn('OLD-1',[x['id'] for x in self.n.detail(t['id'])['relatedTasks']])
        self.assertEqual(self.n.get_task('OLD-1')['title'],'复核本轮方案')

    def test_independent_notebook_cli_no_args_is_safe_usage(self):
        import subprocess,sys
        p=subprocess.run([sys.executable,'-S','-m','modules.notebook'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertIn('usage',p.stdout.lower())

    def test_source_provenance_is_distinct_from_recording_author(self):
        t=self.n.create_task({'title':'原始请求'})
        r=self.n.append_record({'text':'请确认这次课程','objectIds':[t['id']],
            'actor':{'name':'AI秘书','kind':'ai'},'sourceRefs':[{'sourceId':'feishu:personal','recordId':'rec_abc',
            'nativeId':'msg-1','sender':'原发言人','conversation':'真实群聊','at':'2026-10-20T09:10:00+08:00','type':'text'}]})
        self.assertEqual(r['actor']['name'],'AI秘书')
        self.assertEqual(r['sourceRefs'][0]['sender'],'原发言人')
        after=self.n.get_task(t['id']);e=after['evidence'][0]
        self.assertEqual(e['quote'],'请确认这次课程');self.assertEqual(e['sender'],'原发言人')
        self.assertEqual(e['conversation'],'真实群聊');self.assertEqual(e['at'],'2026-10-20T09:10:00+08:00')
        self.assertEqual(after['sourceContacts'][0]['nativeId'],'msg-1')
        with self.assertRaises(ValidationError):self.n.append_record({'text':'x','sourceRefs':[{'path':'/etc/passwd'}]})

    def test_workspace_symlink_rejected_before_any_outside_write(self):
        with tempfile.TemporaryDirectory() as outside:
            fresh=self.ws/'symlink-workspace';fresh.mkdir()
            (fresh/'notebook').symlink_to(outside,target_is_directory=True)
            source=fresh/'source.json';source.write_text('{"records":[]}')
            with self.assertRaises(ValidationError):
                NotebookService(fresh/'notebook/notebook.sqlite3',source,fresh)
            self.assertEqual(list(Path(outside).iterdir()),[],'reject before creating DB/WAL/attachments')

    def test_pure_public_validation_checks_whole_mutation_without_write(self):
        validator=getattr(self.n,'validate_fields',None)
        self.assertIsNotNone(validator,'public validation port must exist')
        before=self.n.list_tasks()
        for p in [{'title':'x','assignee':'a'*121},{'title':'x','condition':None,'timeRequirement':None},{'title':'x','planDate':'20261022'},{'title':'x','deadlineDate':'2026-02-30'}]:
            with self.assertRaises(ValidationError):validator(p,creating=True)
        self.assertEqual(self.n.list_tasks(),before)

    def test_shared_contract_has_no_storage_dependency(self):
        import subprocess,sys
        p=subprocess.run([sys.executable,'-S','-c',"import contracts,sys;assert 'store' not in sys.modules;from contracts.errors import ConflictError,ValidationError"],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_notebook_runs_with_only_own_module_and_shared_contracts(self):
        import subprocess,sys,shutil,os
        app=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'modules').mkdir()
            shutil.copytree(app/'modules/notebook',root/'modules/notebook',ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(app/'contracts',root/'contracts',ignore=shutil.ignore_patterns('__pycache__'))
            env=dict(os.environ);env.pop('PYTHONPATH',None)
            code="from pathlib import Path;from modules.notebook import NotebookService;p=Path('work');p.mkdir();(p/'source.json').write_text('{\"records\":[]}');n=NotebookService(p/'book.db',p/'source.json',p);r=n.append_record({'text':'独立模块'});assert n.record_detail(r['id'])['text']=='独立模块';print('isolated module passed')"
            result=subprocess.run([sys.executable,'-S','-c',code],cwd=root,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('isolated module passed',result.stdout)

    def test_future_review_quiet_except_explicit_current_plan(self):
        t=self.n.create_task({'title':'以后再看','state':'其他','reviewDate':'2099-01-01'})
        self.assertNotIn(t['id'],[x['id'] for x in self.n.query('review')])
        t=self.n.record(t['id'],{'expectedRevision':t['revision'],'state':'待办','planDate':'2020-01-01'})
        self.assertIn(t['id'],[x['id'] for x in self.n.query('review')])
        t=self.n.record(t['id'],{'expectedRevision':t['revision'],'state':'暂缓'})
        self.assertNotIn(t['id'],[x['id'] for x in self.n.query('review')])

    def test_legacy_confirmed_unplanned_pending_remains_actionable_without_new_date(self):
        # Build an actually pre-migration confirmed ledger; the private legacy
        # writer must not bypass the 4.3 operation journal after migration.
        from modules.notebook.legacy_notebook import Notebook
        old_db=self.ws/'preconfirmed.sqlite3';old=Notebook(old_db,self.src);old.refresh()
        legacy=old.task('OLD-1')
        old.record('OLD-1',{'expectedRevision':legacy['revision'],'state':'待办'})
        self.n=NotebookService(old_db,self.src,self.ws)
        t=self.n.get_task('OLD-1')
        self.assertFalse(t['needsReview']);self.assertIsNone(t['planDate'])
        self.assertIn('OLD-1',[x['id'] for x in self.n.query('today')])
        t=self.n.record('OLD-1',{'expectedRevision':t['revision'],'planDate':None})
        self.assertTrue(t['planDateExplicit'])
        self.assertNotIn('OLD-1',[x['id'] for x in self.n.query('today')])

    def test_legacy_structured_proposal_time_projects_as_explicit_original_time(self):
        original=json.loads(self.src.read_text());original['records'][0]['proposedAt']={'earliestExplicitMessage':'2026-10-15T09:10:00+08:00'}
        self.src.write_text(json.dumps(original,ensure_ascii=False));self.n.legacy.refresh()
        self.assertEqual(self.n.get_task('OLD-1')['proposedAt'],'2026-10-15T09:10:00+08:00')

    def test_shared_contract_rejects_invalid_dates_and_domain(self):
        for patch in [{'domain':'新发明的类型'},{'planDate':'2026-02-30'},{'reviewDate':'tomorrow'},{'assignee':{'name':'x'}}]:
            with self.assertRaises(ValidationError):self.n.create_task(dict(title='x',**patch))
        self.assertEqual(len(self.n.list_tasks()),2)

if __name__=='__main__':unittest.main()
