import json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from bridge.private import write,read
from bridge.native_runner import NativeRunner,NativePending,THREAD

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();os.chmod(self.root,0o700)
        write(self.root/'native-context.json',{'thread_id':THREAD})
    def tearDown(self):self.tmp.cleanup()
    def test_submission_reconciles_and_does_not_repeat(self):
        calls=[];states=iter([{'state':'not_found'},{'state':'queued','queue_id':'q'},{'state':'running','turn_id':'t'},{'state':'completed','turn_id':'t','reply':'done'}])
        def execute(argv,**kw):calls.append(json.loads(kw['input']));return SimpleNamespace(stdout=json.dumps(next(states)),returncode=0)
        runner=NativeRunner(self.root,execute=execute);job={'id':'1','text':'update'}
        for _ in range(2):
            with self.assertRaises(NativePending):runner.reply(job)
        self.assertEqual(runner.reply(job),'done');self.assertEqual(runner.reply(job),'done')
        self.assertEqual(sum(c['action']=='submit' for c in calls),1)
    def test_unknown_submission_never_reexecutes_business(self):
        states=iter([{'state':'not_found'},{'state':'unavailable'},{'state':'not_found'}]);calls=[]
        def execute(argv,**kw):calls.append(json.loads(kw['input']));return SimpleNamespace(stdout=json.dumps(next(states)),returncode=2)
        runner=NativeRunner(self.root,execute=execute)
        for _ in range(2):
            with self.assertRaises(NativePending):runner.reply({'id':'1','text':'do work'})
        self.assertEqual(sum(c['action']=='submit' for c in calls),1)
    def test_unavailable_native_does_not_fallback_to_second_model(self):
        calls=[]
        def execute(argv,**kw):calls.append(argv);return SimpleNamespace(stdout='{"state":"unavailable"}',returncode=2)
        with self.assertRaises(NativePending):NativeRunner(self.root,execute=execute).reply({'id':'x','text':'query'})
        self.assertEqual(len(calls),1);self.assertTrue(calls[0][1].endswith('native_port.mjs'))

    def test_media_prepared_once_and_manifest_passed_to_same_submission(self):
        calls=[];prepares=[]
        class Media:
            def prepare(self,mid,items):
                prepares.append((mid,items));return {'prompt':'图片资料位置','inputs':[{'type':'localImage','path':'/private/p.png'}],'manifest_path':'/private/manifest.json','manifest_hash':'f'*64}
        states=iter([{'state':'not_found'},{'state':'queued','queue_id':'q'},{'state':'running','turn_id':'t'},{'state':'completed','turn_id':'t','reply':'已看图'}])
        def execute(argv,**kw):calls.append(json.loads(kw['input']));return SimpleNamespace(stdout=json.dumps(next(states)),returncode=0)
        runner=NativeRunner(self.root,execute=execute,media_preparer=Media());job={'id':'photo','text':'看图','items':[{'type':2}]}
        for _ in range(2):
            with self.assertRaises(NativePending):runner.reply(job)
        self.assertEqual(runner.reply(job),'已看图')
        self.assertEqual(len(prepares),1)
        submitted=[c for c in calls if c['action']=='submit'];self.assertEqual(len(submitted),1)
        self.assertEqual(submitted[0]['manifest_hash'],'f'*64)
        self.assertEqual(submitted[0]['prompt'],'看图')
        self.assertEqual(submitted[0]['manifest_path'],'/private/manifest.json')
        with self.assertRaises(ValueError):runner.reply(dict(job,items=[{'type':4}]))

    def test_full_media_budget_does_not_block_text_or_hide_media_gap(self):
        from bridge.media import MediaFailure
        calls=[];prepares=[]
        class Full:
            def prepare(self,*args):prepares.append(args);raise MediaFailure('media workspace size limit exceeded')
        states=iter([{'state':'not_found'},{'state':'queued','queue_id':'q'},{'state':'not_found'},{'state':'queued','queue_id':'q2'}])
        def execute(argv,**kw):calls.append(json.loads(kw['input']));return SimpleNamespace(stdout=json.dumps(next(states)),returncode=0)
        runner=NativeRunner(self.root,execute=execute,media_preparer=Full())
        with self.assertRaises(NativePending):runner.reply({'id':'text','text':'查询资料','items':[{'type':1,'text_item':{'text':'查询资料'}}]})
        self.assertEqual(prepares,[])
        with self.assertRaises(NativePending):runner.reply({'id':'image','text':'看图片','items':[{'type':2}]})
        self.assertEqual(len(prepares),1)
        submits=[c for c in calls if c['action']=='submit']
        self.assertEqual(submits[1]['prompt'],'看图片')
        self.assertEqual(read(Path(submits[1]['metadata_path']))['code'],'media workspace size limit exceeded')
        self.assertNotIn('manifest_path',submits[1])

    def test_pre_submit_media_rejection_can_report_gap_without_duplicate_business(self):
        calls=[]
        class Media:
            def prepare(self,*args):return {'prompt':'附件','inputs':[],'manifest_path':'/private/manifest.json','manifest_hash':'f'*64}
        states=iter([{'state':'not_found'},{'state':'media_rejected'}, {'state':'not_found'},{'state':'queued','queue_id':'q'}, {'state':'completed','turn_id':'t','reply':'附件校验失败，请重新发送'}])
        def execute(argv,**kw):calls.append(json.loads(kw['input']));return SimpleNamespace(stdout=json.dumps(next(states)),returncode=0)
        runner=NativeRunner(self.root,execute=execute,media_preparer=Media());job={'id':'bad','text':'看附件','items':[{'type':2}]}
        for _ in range(2):
            with self.assertRaises(NativePending):runner.reply(job)
        self.assertEqual(runner.reply(job),'附件校验失败，请重新发送')
        submits=[c for c in calls if c['action']=='submit'];self.assertEqual(len(submits),2)
        self.assertIn('manifest_path',submits[0]);self.assertNotIn('manifest_path',submits[1])
        self.assertEqual(submits[1]['prompt'],'看附件')
        self.assertEqual(read(Path(submits[1]['metadata_path']))['code'],'managed_attachment_validation_failed')
