"""Isolated cloud queue and outbound worker contracts; never use real model/auth."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from contracts.errors import ConflictError, ValidationError
from modules.notebook import NotebookService
from modules.secretary.cloud_queue import CloudSecretaryQueue
from modules.secretary.cloud_worker import CloudWorker, load_config, _CloudRunJournal
from modules.notebook.http_port import HTTPNotebookPort, RemoteNotebookError


class CloudWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.nb = NotebookService(self.root/'cloud.sqlite3', self.root/'missing.json', self.root/'cloud')
        self.message = self.nb.append_record({'text':'准备平板参加讨论', 'actor':{'name':'我','kind':'human'}})
        self.other = self.nb.append_record({'text':'核对下周安排', 'actor':{'name':'我','kind':'human'}})
        self.queue = CloudSecretaryQueue(self.nb, self.root/'cloud', lease_seconds=900)

    def test_reject_request_id_reuse_for_another_input(self):
        first = self.queue.submit(self.message['id'], 'req-1')
        with self.assertRaises(ValidationError):
            self.queue.submit(self.other['id'], 'req-1')
        self.assertEqual(self.queue.submit(self.message['id'], 'req-1')['id'], first['id'])

    def test_reject_wrong_lease_owner_and_stale_lease(self):
        job = self.queue.submit(self.message['id'])
        lease = self.queue.claim('mac-one')
        for owner, token in [('mac-two', lease['leaseToken']), ('mac-one', 'wrong-token')]:
            with self.subTest(owner=owner), self.assertRaises(ValidationError):
                self.queue.report(job['id'], owner, token, 'completed', result={'summary':'完成'})
        self.queue._clock = lambda: 10**12
        with self.assertRaises(ValidationError):
            self.queue.report(job['id'], 'mac-one', lease['leaseToken'], 'completed', result={'summary':'完成'})
        self.assertEqual(self.queue.get_job(job['id'])['status'], 'running')

    def test_reject_bad_url_without_exposing_credential(self):
        for url in ['http://cloud.example', 'https://fixture:invalid@cloud.example', 'https://cloud.example/?token=SECRET', 'file:///etc/passwd']:
            with self.subTest(url=url), self.assertRaises(ValidationError) as caught:
                HTTPNotebookPort(url, 'TOP_SECRET_TOKEN', self.root/'mac')
            self.assertNotIn('TOP_SECRET_TOKEN', str(caught.exception))
            self.assertNotIn('password', str(caught.exception))
        with self.assertRaises(ValidationError):
            HTTPNotebookPort('http://127.0.0.1:1', 'token', self.root/'mac')

    def test_reject_overlong_result_and_raw_context(self):
        job = self.queue.submit(self.message['id'])
        lease = self.queue.claim('mac-one')
        for result in [{'summary':'x'*65537}, {'summary':'ok','plan':{'secret':'data'}}]:
            with self.subTest(result=list(result)), self.assertRaises(ValidationError):
                self.queue.report(job['id'], 'mac-one', lease['leaseToken'], 'completed', result=result)
        self.assertEqual(self.queue.get_job(job['id'])['status'], 'running')

    def test_single_global_lease_persistence_and_completed_idempotency(self):
        job = self.queue.submit(self.message['id'], 'req-a')
        self.queue.submit(self.other['id'])
        lease = self.queue.claim('mac-one')
        again = CloudSecretaryQueue(self.nb, self.root/'cloud')
        self.assertIsNone(again.claim('mac-two'))
        saved = again.report(job['id'], 'mac-one', lease['leaseToken'], 'completed', result={'summary':'已整理','created':[]})
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(again.submit(self.message['id'], 'req-b')['id'], job['id'])
        with self.assertRaises(ValidationError):
            again.submit(self.other['id'], 'req-b')
        self.assertNotIn('leaseToken', again.get_job(job['id']))
        self.assertNotIn('input', again.get_job(job['id']))
        self.assertEqual(again.claim('mac-two')['job']['messageId'], self.other['id'])

    def test_expiry_recovery_is_bounded_and_rejects_old_report(self):
        job = self.queue.submit(self.message['id'])
        now = [1000.0]
        self.queue._clock = lambda: now[0]
        first = self.queue.claim('mac-one')
        for index in range(2):
            now[0] += 901
            self.assertIsNotNone(self.queue.claim('mac-one'))
        now[0] += 901
        self.assertIsNone(self.queue.claim('mac-one'))
        self.assertEqual(self.queue.get_job(job['id'])['status'], 'failed')
        with self.assertRaises(ValidationError):
            self.queue.report(job['id'], 'mac-one', first['leaseToken'], 'completed', result={'summary':'晚到'})
        self.assertEqual(self.queue.submit(self.message['id'])['status'], 'failed')

    def test_failed_report_requires_explicit_bounded_resubmit(self):
        job = self.queue.submit(self.message['id'])
        for attempt in range(3):
            claim = self.queue.claim('mac-one')
            self.queue.report(job['id'], 'mac-one', claim['leaseToken'], 'failed', error='SECRET input /Users/private')
            self.assertIsNone(self.queue.claim('mac-one'))
            job = self.queue.submit(self.message['id'])
            self.assertNotIn('SECRET', json.dumps(job))
            self.assertEqual(job['status'], 'queued' if attempt < 2 else 'failed')

    def serve(self):
        outer = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def send_json(self, body, status=200):
                data=json.dumps(body, ensure_ascii=False).encode()
                self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.headers.get('Authorization') != 'Bearer fixture-token':
                    return self.send_json({'error':'secret server detail'},401)
                try:
                    path=urlsplit(self.path).path
                    if path=='/api/bootstrap' and getattr(outer,'redirect_to',None):
                        self.send_response(302);self.send_header('Location',outer.redirect_to);self.end_headers();return
                    if path=='/api/bootstrap': return self.send_json({'csrfToken':'fixture-csrf','tasks':outer.nb.list_tasks(),'records':outer.nb.list_records()})
                    if path.startswith('/api/tasks/'): return self.send_json(outer.nb.detail(path.rsplit('/',1)[1]))
                    if path.startswith('/api/messages/'): return self.send_json({'record':outer.nb.record_detail(path.rsplit('/',1)[1])})
                    if path=='/api/messages': return self.send_json({'records':outer.nb.list_records()})
                    if path.startswith('/api/assets/'):
                        asset=outer.nb.asset(path.rsplit('/',1)[1]);data=Path(asset['path']).read_bytes()
                        self.send_response(200);self.send_header('Content-Type',asset['mime']);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
                    return self.send_json({},404)
                except KeyError:return self.send_json({},404)
            def do_POST(self):
                if self.headers.get('Authorization') != 'Bearer fixture-token': return self.send_json({},401)
                if getattr(outer,'csrf_fail_once',False):
                    outer.csrf_fail_once=False;return self.send_json({'error':'SECRET response'},403)
                if self.headers.get('Origin') != outer.url or self.headers.get('X-CSRF-Token') != 'fixture-csrf': return self.send_json({},403)
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                path=urlsplit(self.path).path
                try:
                    if path=='/api/tasks': return self.send_json({'task':outer.nb.create_task(body)})
                    if path.endswith('/record'): return self.send_json({'task':outer.nb.record(path.split('/')[3],body)})
                    if path=='/api/messages': return self.send_json({'record':outer.nb.append_record(body)})
                    if path.endswith('/processing'): return self.send_json({'record':outer.nb.set_record_processing(path.split('/')[3],body['status'],body.get('receipt',''),body.get('objectIds'))})
                    if path=='/api/validate': outer.nb.validate_fields(body['body'],body['creating']);return self.send_json({'valid':True})
                    if path=='/api/worker/claim': return self.send_json({'claim':outer.queue.claim(body['workerId'])})
                    if path.endswith('/report'): return self.send_json({'job':outer.queue.report(path.split('/')[4], body['workerId'],body['leaseToken'],body['status'],body.get('result'),body.get('error'))})
                    return self.send_json({},404)
                except ConflictError:return self.send_json({'error':'revision includes SECRET'},409)
                except ValueError:return self.send_json({'error':'private body'},400)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.url='http://127.0.0.1:'+str(server.server_port)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        return HTTPNotebookPort(self.url,'fixture-token',self.root/'mac',allow_loopback_http=True)

    def test_actual_http_notebook_roundtrip_and_conflict(self):
        port=self.serve()
        task=port.create_task({'title':'真实HTTP夹具','actor':{'name':'AI秘书','kind':'ai'},'requestId':'create-1'})
        changed=port.record(task['id'],{'expectedRevision':task['revision'],'note':'进展','actor':{'name':'AI秘书','kind':'ai'},'requestId':'record-1'})
        self.assertEqual(port.get_task(task['id'])['revision'],changed['revision'])
        with self.assertRaises(ConflictError): port.record(task['id'],{'expectedRevision':0,'note':'旧版本','requestId':'stale'})
        self.assertEqual(len(port.list_tasks()),1)
        self.assertEqual(port.record_detail(self.message['id'])['text'],self.message['text'])
        self.assertTrue(port.validate_fields({'title':'预校验','actor':{'name':'AI秘书','kind':'ai'}},creating=True))

    def test_actual_http_claim_injected_model_cloud_save_and_report(self):
        port=self.serve()
        job=self.queue.submit(self.message['id'],'request-worker')
        calls=[]
        def runner(context):
            calls.append(context)
            return {'summary':'已记下讨论准备。','operations':[{'action':'create','key':'a','task':{'title':'讨论时带平板','kind':'action','domain':'他山','state':'其他'}}]}
        worker=CloudWorker(port,self.root/'mac','mac-one',model_runner=runner)
        result=worker.run_once()
        self.assertEqual(result['status'],'completed')
        self.assertEqual(self.queue.get_job(job['id'])['status'],'completed')
        self.assertEqual(self.nb.list_tasks()[0]['title'],'讨论时带平板')
        self.assertEqual(self.nb.list_tasks()[0]['state'],'其他')
        self.assertEqual(self.nb.record_detail(self.message['id'])['processing'],'completed')
        self.assertEqual(len(calls),1)
        self.assertIsNone(worker.run_once())
        local_journal=(self.root/'mac'/'secretary'/'jobs.sqlite3').read_bytes()
        self.assertNotIn(self.message['text'].encode(),local_journal)
        self.assertNotIn('讨论时带平板'.encode(),local_journal)

    def test_overlong_model_reply_never_writes_notebook(self):
        port=self.serve();job=self.queue.submit(self.message['id'])
        worker=CloudWorker(port,self.root/'mac','mac-one',model_runner=lambda _: {'summary':'x'*65537,'operations':[]})
        self.assertEqual(worker.run_once()['status'],'failed')
        self.assertEqual(self.nb.list_tasks(),[])
        self.assertEqual(self.queue.get_job(job['id'])['status'],'failed')


    def test_http_redirect_never_forwards_bearer_and_errors_are_redacted(self):
        port=self.serve()
        hits=[]
        class Other(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                hits.append(self.headers.get('Authorization'))
                self.send_response(200);self.end_headers();self.wfile.write(b'{}')
        other=ThreadingHTTPServer(('127.0.0.1',0),Other)
        threading.Thread(target=other.serve_forever,daemon=True).start()
        self.addCleanup(other.server_close);self.addCleanup(other.shutdown)
        self.redirect_to='http://127.0.0.1:'+str(other.server_port)+'/steal'
        with self.assertRaises(RemoteNotebookError) as caught: port.list_tasks()
        self.assertEqual(hits,[])
        self.assertNotIn('fixture-token',str(caught.exception))
        self.redirect_to=None
        unauthorized=HTTPNotebookPort(self.url,'bad-secret-token',self.root/'bad',allow_loopback_http=True)
        with self.assertRaises(RemoteNotebookError) as caught:unauthorized.list_tasks()
        self.assertNotIn('secret server detail',str(caught.exception))
        self.assertNotIn('bad-secret-token',str(caught.exception))

    def test_csrf_retry_same_request_and_bounded_attachment_cache(self):
        port=self.serve()
        self.csrf_fail_once=True
        task=port.create_task({'title':'写入仅一次','requestId':'csrf-retry'})
        self.assertEqual(len(self.nb.list_tasks()),1)
        self.assertEqual(self.nb.list_tasks()[0]['id'],task['id'])
        asset=self.nb.attach_asset('notes.txt',b'fixture attachment')
        message=self.nb.append_record({'text':'附件','attachments':[asset['id']]})
        port.record_detail(message['id'])
        cached=port.asset(asset['id'])
        self.assertEqual(Path(cached['path']).read_bytes(),b'fixture attachment')
        self.assertTrue(Path(cached['path']).is_relative_to((self.root/'mac'/'notebook'/'attachments').resolve()))
        with self.assertRaises(ValidationError):port.asset('../../private')

    def test_restart_recovers_completed_prefix_without_reapplying_it(self):
        port=self.serve()
        model_calls=[]
        def first_model(context):
            return {'summary':'先后记下两项','operations':[
                {'action':'create','key':'a','task':{'title':'已保存前缀','state':'其他'}},
                {'action':'create','key':'b','task':{'title':'第二项','state':'其他'}}]}
        journal=_CloudRunJournal(port,self.root/'mac',model_runner=first_model)
        job=journal.prepare(self.message['id'],'cloud-recovery')
        original=port.create_task
        attempts=[0]
        def fail_second(body):
            attempts[0]+=1
            if attempts[0]==2:raise RuntimeError('fixture crash before second write')
            return original(body)
        port.create_task=fail_second
        self.assertEqual(journal.run(job['id'])['status'],'failed')
        self.assertEqual(len(self.nb.list_tasks()),1)
        port.create_task=original
        def tail_model(context):
            model_calls.append(context)
            return {'summary':'已恢复剩余一项','operations':[{'action':'create','key':'b','task':{'title':'第二项','state':'其他'}}]}
        restarted=_CloudRunJournal(port,self.root/'mac',model_runner=tail_model)
        prepared=restarted.prepare(self.message['id'],'cloud-recovery')
        self.assertEqual(restarted.run(prepared['id'])['status'],'completed')
        self.assertEqual(sorted(t['title'] for t in self.nb.list_tasks()),['已保存前缀','第二项'])
        self.assertEqual(len(model_calls[0]['completedPrefix']['created']),1)
        data=(self.root/'mac'/'secretary'/'jobs.sqlite3').read_bytes()
        for secret in ('已保存前缀','第二项',self.message['text']):self.assertNotIn(secret.encode(),data)

    def test_config_requires_private_regular_file_and_explicit_fields(self):
        path=self.root/'config.json'
        path.write_text(json.dumps({'baseUrl':'https://private.example','deviceToken':'token','workspace':str(self.root/'mac'),'workerId':'mac-one'}))
        path.chmod(0o644)
        with self.assertRaises(ValidationError):load_config(path)
        path.chmod(0o600)
        self.assertEqual(load_config(path)['workerId'],'mac-one')
        link=self.root/'config-link';link.symlink_to(path)
        with self.assertRaises(ValidationError):load_config(link)

if __name__=='__main__':unittest.main()
