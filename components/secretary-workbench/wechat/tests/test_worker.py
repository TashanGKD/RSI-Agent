import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from queue_store import Queue
from worker import cycle,remote,validate_workspace
from worker import main
from test_queue import event

class Runner:
    def __init__(self):self.calls=0
    def reply(self,j):self.calls+=1;return '收到'

class WorkerTests(unittest.TestCase):
    def test_old_resident_model_loop_is_disabled_even_if_explicitly_launched(self):
        with patch('sys.argv',['worker.py','--execute','--workspace','/home/operator/Library/Application Support/TashanNativeWeixinBridge']),patch('worker.validate_workspace',side_effect=AssertionError('retirement guard must stop before live workspace')):
            with self.assertRaises(SystemExit) as e:main()
        self.assertIn('retired',str(e.exception))
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.q=Queue(Path(self.t.name)/'q.sqlite','wxid_fixture_8e822a662c','wxid_fixture_1987fcaa9f',0);self.r=Runner();self.sends=0
    def tearDown(self):self.q.close();self.t.cleanup()
    def call(self,r):
        if r['action']=='read':return {'events':[event()], 'cursor':1}
        self.sends+=1;return {'state':'accepted','server_id':'456'}
    def test_duplicate_poll_has_one_generation_and_send(self):
        cycle(self.q,self.r,self.call);cycle(self.q,self.r,self.call)
        self.assertEqual((self.r.calls,self.sends),(1,1))
    def test_disconnect_keeps_reply_and_request_id(self):
        self.q.ingest([event()],1);j=self.q.next_job();self.q.finish(j['id'],'收到')
        ids=[]
        def call(r):
            if r['action']=='read':return {'events':[],'cursor':1}
            ids.append(r['request_id']);raise ConnectionError()
        with self.assertRaises(ConnectionError):cycle(self.q,self.r,call)
        self.assertEqual(len(self.q.outbox()),1)
        def restored(r):
            if r['action']=='read':return {'events':[],'cursor':1}
            ids.append(r['request_id']);return {'state':'accepted'}
        cycle(self.q,self.r,restored)
        self.assertEqual(ids[0],ids[1]);self.assertEqual(self.r.calls,0)
    def test_unknown_result_never_blind_resends(self):
        def call(r):
            if r['action']=='read':return {'events':[event()],'cursor':1}
            if r['action']=='delivery':return {'state':'unknown'}
            self.sends+=1;return {'state':'unknown'}
        cycle(self.q,self.r,call);cycle(self.q,self.r,call)
        self.assertEqual(self.sends,1);self.assertEqual(self.q.counts()['outbox'],{'unknown':1})
    def test_late_native_receipt_resolves_without_resend(self):
        phase=[False]
        def call(r):
            if r['action']=='read':return {'events':[event()],'cursor':1}
            if r['action']=='delivery':return {'state':'accepted','server_id':'789'}
            self.sends+=1;return {'state':'unknown'}
        cycle(self.q,self.r,call);cycle(self.q,self.r,call)
        self.assertEqual(self.sends,1);self.assertEqual(self.q.counts()['outbox'],{'accepted':1})
    def test_source_failure_does_not_advance_checkpoint(self):
        def fail(r):raise ConnectionError()
        with self.assertRaises(ConnectionError):cycle(self.q,self.r,fail)
        self.assertEqual(self.q.cursor(),0)
    def test_ssh_receives_data_on_stdin_never_in_command(self):
        captured={}
        class Result:returncode=0;stdout='{"state":"accepted"}'
        def run(args,**kw):captured.update(args=args,**kw);return Result()
        text='$(touch /tmp/not-run)'
        remote({'action':'send','text':text},run)
        self.assertNotIn(text,' '.join(captured['args']))
        self.assertIn(text,captured['input'])
    def test_workspace_cannot_repurpose_root_home_or_relative_path(self):
        for path in ['/','/home/operator','../../somewhere']:
            with self.assertRaises(ValueError):validate_workspace(path)
    def test_failed_or_cooling_voice_cannot_be_overtaken(self):
        first=event('');first['kind']=34
        later=event('上一条语音照办');later['local_id']=2;later['server_id']=456
        self.q.ingest([first,later],2)
        def call(r):
            if r['action']=='read':return {'events':[],'cursor':2}
            return {'state':'accepted'}
        with patch('voice.ready_to_attempt',return_value=False):
            result=cycle(self.q,self.r,call,voice_root=Path(self.t.name))
        self.assertEqual(self.r.calls,0)
        self.assertEqual(result['state'],'voice_reading_attention')
    def test_lost_source_ack_replays_one_committed_job(self):
        state={'acks':0,'sent':0,'acked':False}
        def call(r):
            if r['action']=='read':
                if state['acked']:return {'api_version':2,'events':[],'cursor':1}
                return {'api_version':2,'events':[event()],'cursor':1,'batch_id':'a'*32,'batch_hash':'b'*64,'ack_ids':['123']}
            if r['action']=='ack':
                state['acks']+=1
                if state['acks']==1:raise ConnectionError()
                state['acked']=True;return {'state':'acked'}
            state['sent']+=1;return {'state':'accepted'}
        with self.assertRaises(ConnectionError):cycle(self.q,self.r,call)
        self.assertEqual(self.r.calls,0);self.assertEqual(self.q.counts()['events'],1)
        cycle(self.q,self.r,call);cycle(self.q,self.r,call)
        self.assertEqual(self.r.calls,1);self.assertEqual(state['sent'],1);self.assertEqual(state['acks'],2)
    def test_provisional_earlier_input_is_an_ordering_barrier(self):
        later=event('上一条语音照办');later['local_id']=2
        self.q.ingest([later],2)
        def call(r):
            if r['action']=='read':return {'api_version':2,'events':[],'cursor':2,'provisional':[{'sender':'wxid_fixture_1987fcaa9f','kind':34,'local_id':1,'created':later['created'],'sort_seq':int(later['created']*1000)}]}
            return {'state':'accepted'}
        result=cycle(self.q,self.r,call)
        self.assertEqual(self.r.calls,0);self.assertEqual(result['state'],'source_identity_attention')

if __name__=='__main__':unittest.main()
