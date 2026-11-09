import os,tempfile,unittest
from pathlib import Path
from bridge.store import Store
from bridge.worker import Worker
from bridge.native_runner import NativePending

class LatencyTests(unittest.TestCase):
    def test_pending_native_job_and_send_precede_short_source_poll(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();os.chmod(root,0o700)
            s=Store(root/'state.sqlite','bot','peer',all_messages=True)
            self.addCleanup(s.close);events=[]
            s.ingest([{'message_id':'1','message_type':1,'message_state':2,'from_user_id':'peer','context_token':'ctx','item_list':[{'type':1,'text_item':{'text':'test'}}]}],'c')
            class API:
                def poll(self,cursor,timeout):events.append(('poll',timeout));return {'msgs':[],'get_updates_buf':'c'}
                def send_text(self,*a):events.append(('send',));return {}
            class Native:
                native=True
                def reply(self,j):events.append(('reply',));return 'done'
                def check(self):raise AssertionError('no idle check while processing job')
            result=Worker(s,API(),Native()).cycle()
            self.assertEqual([x[0] for x in events],['reply','send','poll'])
            self.assertEqual(events[-1][1],1)
            self.assertNotIn('model_started_at',result['timing']);self.assertIn('runner_attempt_started_at',result['timing'])
            self.assertIsInstance(s.message_received_at('1'),float)

    def test_native_wait_has_attempt_timing_not_fake_model_timing(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d).resolve();os.chmod(root,0o700);s=Store(root/'s.sqlite','bot','peer',all_messages=True);self.addCleanup(s.close)
            class API:
                def poll(self,*a,**k):return {'msgs':[{'message_id':'1','message_type':1,'message_state':2,'from_user_id':'peer','item_list':[{'type':1,'text_item':{'text':'hi'}}]}],'get_updates_buf':'c'}
            class Native:
                native=True
                def reply(self,j):raise NativePending('running')
            r=Worker(s,API(),Native()).cycle()
            self.assertNotIn('model_started_at',r['timing']);self.assertNotIn('model_finished_at',r['timing'])
