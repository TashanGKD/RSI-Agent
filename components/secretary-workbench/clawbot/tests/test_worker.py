import os
import tempfile
import unittest
from pathlib import Path

from bridge.store import Store
from bridge.api import APIError, TransportError
from bridge.worker import Worker, process_lock


class FakeAPI:
    def __init__(self):self.sent=[];self.fail=None;self.messages=[]
    def poll(self,cursor,timeout=35):return {'msgs':self.messages,'get_updates_buf':'cursor'}
    def send_text(self,*args):
        self.sent.append(args)
        if self.fail:raise self.fail
        return {'ret':0}
    def send_image(self,*args,**kwargs):return self.send_text(*args)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve();os.chmod(self.root,0o700)
        self.store=Store(self.root/'state.sqlite','bot','peer');self.api=FakeAPI();self.calls=[]
        def reply(prompt,history):self.calls.append(prompt);return '收到：'+prompt
        self.worker=Worker(self.store,self.api,reply)
    def tearDown(self):self.store.close();self.tmp.cleanup()
    def message(self):return {'message_id':123,'message_type':1,'message_state':2,'from_user_id':'peer','to_user_id':'bot','context_token':'ctx','item_list':[{'type':1,'text_item':{'text':'秘书：你好'}}]}
    def test_keyword_runs_once_and_sends_once(self):
        self.api.messages=[self.message()]
        self.worker.cycle();self.worker.cycle()
        self.assertEqual(self.calls,['你好']);self.assertEqual(len(self.api.sent),1)
        self.assertEqual(self.store.snapshot()['outbox'],{'accepted':1})
    def test_keyword_free_input_does_not_wake_model(self):
        m=self.message();m['item_list'][0]['text_item']['text']='随手记'
        self.api.messages=[m];self.worker.cycle()
        self.assertEqual(self.calls,[]);self.assertEqual(self.api.sent,[])
    def test_unknown_send_is_not_retried(self):
        self.api.messages=[self.message()];self.api.fail=TransportError('unknown')
        self.worker.cycle();self.worker.cycle()
        self.assertEqual(len(self.api.sent),1);self.assertEqual(self.store.snapshot()['outbox'],{'unknown':1})
    def test_refusal_is_not_delivery(self):
        self.api.messages=[self.message()];self.api.fail=APIError(-2)
        self.worker.cycle()
        self.assertEqual(self.store.snapshot()['outbox'],{'failed':1})
    def test_malformed_result_is_unknown(self):
        self.api.messages=[self.message()];self.api.fail=APIError('invalid-code')
        result=self.worker.cycle()
        self.assertEqual(self.store.snapshot()['outbox'],{'unknown':1})
        self.assertEqual(result['state'],'delivery_attention')
    def test_oversized_optional_receipt_cannot_undo_accepted_send(self):
        self.api.messages=[self.message()]
        self.api.send_text=lambda *a:{'ret':0,'message_id':'x'*66000}
        self.worker.cycle()
        self.assertEqual(self.store.snapshot()['outbox'],{'accepted':1})

    def test_non_unicode_receipt_id_is_omitted_not_delivery_failure(self):
        self.api.messages=[self.message()]
        self.api.send_text=lambda *a:{'ret':0,'message_id':'\ud800'}
        self.worker.cycle()
        self.assertEqual(self.store.snapshot()['outbox'],{'accepted':1})

    def test_failure_notice_handles_maximum_message_id(self):
        m=self.message();m['message_id']='x'*512;self.api.messages=[m]
        self.worker.runner=lambda *a:(_ for _ in ()).throw(RuntimeError('failed'))
        result=self.worker.cycle()
        self.assertEqual(result['state'],'reply_failed');self.assertEqual(len(self.api.sent),1)
    def test_no_context_leaves_send_pending(self):
        self.store.enqueue_text('test','one');self.worker.flush_one()
        self.assertEqual(self.store.snapshot()['outbox'],{'pending':1});self.assertEqual(self.api.sent,[])
    def test_single_worker_lock(self):
        with process_lock(self.root):
            with self.assertRaises(RuntimeError):
                with process_lock(self.root):pass
    def test_model_failure_does_not_make_success_message(self):
        def bad(*args):raise RuntimeError('failed')
        self.worker.runner=bad;self.api.messages=[self.message()]
        result=self.worker.cycle();self.assertEqual(self.store.snapshot()['jobs'],{'failed':1})
        self.assertEqual(result['state'],'reply_failed')
        self.assertEqual(len(self.api.sent),1)
        self.assertIn('未完成',self.api.sent[0][1])

    def test_backlog_is_processed_even_if_poll_unavailable(self):
        self.store.ingest([self.message()],'cursor')
        def broken(*a,**k):raise TransportError('unavailable')
        self.api.poll=broken
        self.worker.cycle()
        self.assertEqual(len(self.api.sent),1)

    def test_queued_send_not_blocked_by_poll(self):
        self.store.ingest([self.message()],'cursor')
        job=self.store.claim_job();self.store.fail_job(job['id'],'fixture')
        self.store.enqueue_text('outbound','one')
        self.api.poll=lambda *a,**k:(_ for _ in ()).throw(TransportError('unavailable'))
        self.worker.cycle();self.assertEqual(len(self.api.sent),1)

    def test_native_runner_receives_persisted_attachment_items(self):
        self.store.close();self.store=Store(self.root/'state.sqlite','bot','peer',all_messages=True)
        self.worker.store=self.store
        seen=[]
        class Native:
            native=True
            def reply(self,job):seen.append(job);return '已看附件'
            def check(self):return True
        self.worker.runner=Native()
        m=self.message();m['item_list']=[{'type':2,'image_item':{'media':{'encrypt_query_param':'fixture'}}}]
        self.api.messages=[m]
        self.worker.cycle();self.worker.cycle()
        self.assertEqual(len(seen),1);self.assertEqual(seen[0]['items'],m['item_list'])
        self.assertEqual(len(self.api.sent),1)

    def test_native_validation_failure_preserves_pending_without_resend_advice(self):
        class Native:
            native=True
            def reply(self,job):raise ValueError('private journal mismatch')
            def check(self):return True
        self.worker.runner=Native();self.api.messages=[self.message()]
        result=self.worker.cycle()
        self.assertEqual(self.store.snapshot()['jobs'],{'pending':1})
        self.assertEqual(self.api.sent,[])
        self.assertEqual(result['native_wait_reason'],'native_request_validation_failed')

if __name__=='__main__':unittest.main()
