"""Real local HTTP→notebook→secretary integration with isolated model fixture only."""
import base64,json,tempfile,threading,time,unittest,urllib.request,urllib.error
from pathlib import Path
try:
 from local_server import make_server
except ImportError:make_server=None

class LocalHTTPTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(make_server,'new local HTTP host must exist')
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.ws=Path(self.tmp.name)
  (self.ws/'source.json').write_text('{"records":[]}')
  def model(c):
   return {'summary':'验收样例已记为条件备忘','operations':[{'action':'create','key':'memo','task':{'title':'下次见面带资料','kind':'memo','domain':'他山','condition':'下次会面确认时','state':'其他','note':'隔离模型夹具'}}]}
  self.server=make_server(self.ws,port=0,model_runner=model)
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.addCleanup(self.close)
  self.base='http://127.0.0.1:'+str(self.server.server_port)
  self.boot=self.req('/api/bootstrap')[1]
 def close(self):
  if self.server:self.server.shutdown();self.server.server_close();self.server=None
 def req(self,path,body=None,headers=None):
  h={'Content-Type':'application/json'}
  if body is not None:h.update({'Origin':self.base,'X-CSRF-Token':getattr(self,'boot',{}).get('csrfToken','')})
  h.update(headers or {})
  request=urllib.request.Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=h)
  try:
   with urllib.request.urlopen(request,timeout=10) as r:return r.status,json.loads(r.read()) if r.headers.get_content_type()=='application/json' else r.read()
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
 def test_real_raw_message_secretary_record_readback(self):
  status,reply=self.req('/api/messages',{'text':'虚构验收：下次见面带资料','requestId':'H-MSG'})
  self.assertEqual(status,200);r=reply['record'];self.assertEqual(self.req('/api/bootstrap')[1]['tasks'],[])
  status,reply=self.req('/api/secretary/run',{'messageId':r['id'],'requestId':'H-JOB'})
  self.assertEqual(status,200);jid=reply['job']['id']
  for _ in range(100):
   job=self.req('/api/jobs/'+jid)[1]['job']
   if job['status'] in ('completed','failed'):break
   time.sleep(.02)
  self.assertEqual(job['status'],'completed',job)
  data=self.req('/api/bootstrap')[1];self.assertEqual(len(data['tasks']),1)
  self.assertEqual(data['tasks'][0]['kind'],'memo');self.assertEqual(data['records'][0]['text'],r['text'])
  self.assertEqual(data['records'][0]['processing'],'completed');self.assertTrue(data['records'][0]['receipts'])
 def test_review_confirmation_today_and_reload(self):
  status,r=self.req('/api/tasks',{'title':'本地动作','domain':'科研','state':'其他','recommendation':{'state':'待办','reason':'需要处理'}})
  self.assertEqual(status,200);t=r['task'];self.assertTrue(t['needsReview'])
  status,r=self.req('/api/tasks/'+t['id']+'/confirm',{'expectedRevision':t['revision'],'state':'待办','requestId':'H-CONFIRM'})
  self.assertEqual(status,200);t=r['task'];self.assertFalse(t['needsReview']);self.assertEqual(t['planDate'],self.boot['today'])
  status,r=self.req('/api/refresh',{});self.assertEqual(r['tasks'][0]['state'],'待办');self.assertFalse(r['tasks'][0]['needsReview'])
  self.assertEqual(self.req('/api/tasks/'+t['id']+'/record',{'expectedRevision':0,'note':'旧稿'})[0],409)
 def test_reject_security_inputs_before_mutating(self):
  for path in ['/../store.py','/%2e%2e/store.py','/api/assets/../secret','/notebook.sqlite3']:
   self.assertEqual(self.req(path)[0],404)
  self.assertEqual(self.req('/api/messages',{'text':'x'},{'Origin':'https://evil.invalid'})[0],403)
  self.assertEqual(self.req('/api/messages',{'text':'x'},{'X-CSRF-Token':'wrong'})[0],403)
  self.assertEqual(self.req('/api/messages',{'text':'x','unknown':True})[0],400)
  self.assertEqual(self.req('/api/uploads',{'name':'x.png','data':'***'})[0],400)
  self.assertEqual(self.req('/api/bootstrap')[1]['records'],[])
 def test_asset_binary_readback_and_reject_filename_escape(self):
  raw=b'\x89PNG\r\n\x1a\n'+bytes(25)
  status,r=self.req('/api/uploads',{'name':'附件.png','mime':'image/png','data':base64.b64encode(raw).decode()})
  self.assertEqual(status,200);asset=r['asset'];self.assertNotIn('path',asset)
  self.assertEqual(self.req(asset['url'])[1],raw)
  self.assertEqual(self.req('/api/uploads',{'name':'../x.png','data':base64.b64encode(raw).decode()})[0],400)
 def test_static_frontend_and_sources_are_independent(self):
  status,html=self.req('/');self.assertEqual(status,200);self.assertIn('主要导航'.encode(),html);self.assertIn(b'class="brand"',html)
  self.assertEqual(self.req('/app.js')[0],200);self.assertEqual(self.req('/style.css')[0],200)
  self.assertEqual(self.req('/api/sources')[0],200);self.assertEqual(self.req('/api/jobs')[1]['jobs'],[])

if __name__=='__main__':unittest.main()
