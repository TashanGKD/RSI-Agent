import json
from test_online_server import OnlineServerTests
from modules.notebook.http_port import HTTPNotebookPort

class WorkHTTPTests(OnlineServerTests):
 def test_device_work_end_to_end_and_authorization(self):
  boot=json.loads(self.call('/api/bootstrap',bearer='d'*40)[2]);csrf=boot['csrfToken']
  status,_,raw=self.call('/api/messages',{'text':'既有阶段结果','requestId':'OLD'},bearer='d'*40,csrf=csrf);self.assertEqual(status,200);m=json.loads(raw)['record']
  body={'expectedRecordHash':HTTPNotebookPort.work_record_hash(m),'requestId':'INTEGRATE','work':{'start':'2026-10-14','participants':['陈希鸿'],'organizations':['他山协会']},'task':{'title':'补交本轮评分','state':'已完成','assignee':'陈希鸿'}}
  path='/api/messages/'+m['id']+'/integrate-work'
  self.assertEqual(self.call(path,body)[0],401)
  self.assertEqual(self.call(path,body,bearer='d'*40,csrf='bad')[0],403)
  self.assertEqual(self.call(path,body,bearer='d'*40,csrf=csrf,origin='https://evil.invalid')[0],403)
  status,_,raw=self.call(path,body,bearer='d'*40,csrf=csrf);self.assertEqual(status,200,raw);t=json.loads(raw)['task'];self.assertEqual(t['state'],'已完成')
  status,_,raw=self.call('/api/notebook/work?start=2026-10-14&end=2026-10-14',bearer='d'*40);self.assertEqual(status,200,raw);q=json.loads(raw)
  self.assertEqual(q['objects'][0]['id'],t['id']);self.assertFalse(q['objects'][0]['needsReview']);self.assertEqual(q['objects'][0]['workEntries'][0]['id'],m['id'])
  self.assertEqual(self.call('/api/notebook/work?person=a&person=b',bearer='d'*40)[0],400)
  self.assertEqual(self.call('/api/notebook/work?unknown=yes',bearer='d'*40)[0],400)
  self.assertEqual(self.call('/api/notebook/work?cursor=-1',bearer='d'*40)[0],400)
  # HTTP adapter uses exactly the public route, reusing ordinary auth/CSRF.
  n=HTTPNotebookPort('http://127.0.0.1:'+str(self.server.server_port),'d'*40,self.tmp.name,allow_loopback_http=True)
  n.origin='https://notes.example.test'
  # The production Host guard is exercised above; loopback test cannot emulate its HTTPS host with this adapter.
