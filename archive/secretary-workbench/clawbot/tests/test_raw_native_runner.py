import hashlib,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from bridge.private import write,read
from bridge.native_runner import NativeRunner,NativePending,THREAD
from bridge.media import MediaFailure

class RawRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();os.chmod(self.root,0o700)
        write(self.root/'native-context.json',{'thread_id':THREAD})

    def runner(self,states,media=None):
        self.calls=[];responses=iter(states)
        def execute(argv,**kwargs):
            self.calls.append(json.loads(kwargs['input']))
            result=next(responses)
            if isinstance(result,Exception):raise result
            return SimpleNamespace(stdout=json.dumps(result),returncode=0)
        return NativeRunner(self.root,execute=execute,media_preparer=media)

    def test_raw_submission_and_private_metadata_not_added_to_body(self):
        class Media:
            def prepare(self,*args):return{'prompt':'LONG INSTRUCTION MUST STAY OUT','manifest_path':'/private/m.json','manifest_hash':'f'*64,'inputs':[]}
        runner=self.runner([{'state':'not_found'},{'state':'queued','queue_id':'q'}],Media())
        raw='  秘书： abc\nhttps://example.com/  '
        with self.assertRaises(NativePending):runner.reply({'id':'one','text':raw,'raw_text':raw,'items':[{'type':4}]})
        request=self.calls[-1];self.assertEqual(request['prompt'],raw);self.assertEqual(request['input_format'],'raw-v2')
        self.assertEqual(request['wx_message_id'],'one');self.assertEqual(request['manifest_path'],'/private/m.json')

    def test_media_failure_is_managed_metadata_not_a_changed_prompt(self):
        class Media:
            def prepare(self,*args):raise MediaFailure('media workspace size limit exceeded')
        runner=self.runner([{'state':'not_found'},{'state':'queued','queue_id':'q'}],Media())
        with self.assertRaises(NativePending):runner.reply({'id':'two','text':'原文  ','items':[{'type':2}]})
        request=self.calls[-1];self.assertEqual(request['prompt'],'原文  ')
        receipt=read(Path(request['metadata_path']));self.assertEqual(receipt['status'],'failed')
        self.assertEqual(receipt['code'],'media workspace size limit exceeded');self.assertEqual(receipt['read_status'],'unread')
        self.assertEqual(hashlib.sha256(Path(request['metadata_path']).read_bytes()).hexdigest(),request['metadata_hash'])

    def test_original_incoming_recovered_for_preupgrade_unsubmitted_job(self):
        runner=self.runner([{'state':'not_found'},{'state':'queued','queue_id':'q'}])
        with self.assertRaises(NativePending):runner.reply({'id':'old-unsubmitted','text':'trimmed','raw_text':'  秘书：trimmed  '})
        self.assertEqual(self.calls[-1]['prompt'],'  秘书：trimmed  ')

    def test_old_completed_journal_and_unknown_legacy_are_not_replayed(self):
        key=hashlib.sha256(b'old').hexdigest();path=self.root/'native-requests'/ (key+'.json')
        path.parent.mkdir(mode=0o700)
        saved={'state':'completed','client_id':'weixin-'+key,'message_id':'old','prompt_hash':hashlib.sha256(b'trimmed').hexdigest(),'reply':'old reply'}
        write(path,saved);runner=self.runner([])
        self.assertEqual(runner.reply({'id':'old','text':'trimmed','raw_text':'秘书：trimmed'}),'old reply');self.assertEqual(self.calls,[])
        saved['state']='uncertain';write(path,saved);runner=self.runner([{'state':'not_found'}])
        with self.assertRaises(NativePending):runner.reply({'id':'old','text':'trimmed','raw_text':'秘书：trimmed'})
        self.assertEqual(self.calls[0]['input_format'],'legacy-v1');self.assertEqual([c['action'] for c in self.calls],['poll'])

    def test_acceptance_without_stdout_recovers_without_second_submit(self):
        runner=self.runner([{'state':'not_found'},OSError('receipt lost'),{'state':'completed','turn_id':'t','native_message_id':'native','reply':'done'}])
        with self.assertRaises(NativePending):runner.reply({'id':'lost','text':'same'})
        runner=NativeRunner(self.root,execute=runner.execute)
        self.assertEqual(runner.reply({'id':'lost','text':'same'}),'done')
        self.assertEqual(sum(x['action']=='submit' for x in self.calls),1)
        saved=read(self.root/'native-requests'/(hashlib.sha256(b'lost').hexdigest()+'.json'))
        self.assertEqual(saved['native_message_id'],'native')

    def test_native_port_lock_prevents_concurrent_submission_and_releases(self):
        import fcntl
        path=self.root/'native-port.lock'
        fd=os.open(path,os.O_CREAT|os.O_RDWR,0o600)
        runner=self.runner([{'state':'connected'}])
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(NativePending,'native_port_busy'):runner.invoke({'action':'inspect'})
            self.assertEqual(self.calls,[])
        finally:os.close(fd)
        self.assertEqual(runner.invoke({'action':'inspect'})['state'],'connected')
