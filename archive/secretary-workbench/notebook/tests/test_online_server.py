import json
import tempfile
import threading
import unittest
import http.client
from pathlib import Path
from local_server import make_server
from modules.access import AccessService

class OnlineServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();p=Path(self.tmp.name)
        self.access=AccessService(p,'https://notes.example.test',activation_token='a'*40,device_token='d'*40)
        self.server=make_server(p,port=0,access=self.access)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
    def tearDown(self):self.server.shutdown();self.server.server_close();self.tmp.cleanup()
    def call(self,path,body=None,cookie=None,bearer=None,csrf=None,origin='https://notes.example.test',host='notes.example.test'):
        c=http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        h={'Host':host,'Origin':origin,'Content-Type':'application/json'}
        if cookie:h['Cookie']=cookie
        if bearer:h['Authorization']='Bearer '+bearer
        if csrf:h['X-CSRF-Token']=csrf
        c.request('GET' if body is None else 'POST',path,None if body is None else json.dumps(body),h)
        r=c.getresponse();raw=r.read();out=(r.status,dict(r.getheaders()),raw);c.close();return out
    def test_every_private_route_requires_auth(self):
        for path in ['/api/bootstrap','/api/tasks/guessed','/api/assets/guessed','/api/jobs','/api/messages','/api/sources','/api/schedule?start=2026-10-23&end=2026-10-23','/api/schedule/guessed','/schedule.js','/schedule.css','/app.js']:
            self.assertEqual(self.call(path)[0],401,path)
        self.assertEqual(self.call('/')[0],303)
        self.assertEqual(self.call('/api/tasks',{'title':'hostile'})[0],401)
    def test_wrong_host_cross_origin_and_cookie_cannot_claim_worker(self):
        self.assertEqual(self.call('/api/auth/status',host='evil.test')[0],403)
        self.assertEqual(self.call('/api/auth/activate',{'token':'a'*40,'password':'password123'},origin='https://evil.test')[0],403)
        _,headers,_=self.call('/api/auth/activate',{'token':'a'*40,'password':'password123'})
        cookie=headers['Set-Cookie'];_,_,raw=self.call('/api/bootstrap',cookie=cookie);csrf=json.loads(raw)['csrfToken']
        self.assertEqual(self.call('/api/worker/claim',{'workerId':'x'},cookie=cookie,csrf=csrf)[0],403)
        self.assertEqual(self.call('/api/messages',{'text':'no csrf'},cookie=cookie)[0],403)
    def test_identity_is_server_assigned_and_logout_revokes(self):
        _,headers,_=self.call('/api/auth/activate',{'token':'a'*40,'password':'password123'})
        cookie=headers['Set-Cookie'];_,_,raw=self.call('/api/bootstrap',cookie=cookie);csrf=json.loads(raw)['csrfToken']
        status,_,raw=self.call('/api/messages',{'text':'hello','actor':{'name':'forged AI','kind':'ai'}},cookie=cookie,csrf=csrf)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['record']['actor'],{'name':'我','kind':'human'})
        self.assertEqual(self.call('/api/auth/logout',{},cookie=cookie,csrf=csrf)[0],200)
        self.assertEqual(self.call('/api/bootstrap',cookie=cookie)[0],401)
    def test_device_cannot_inject_raw_sources_or_confirm_human_review(self):
        _,_,raw=self.call('/api/bootstrap',bearer='d'*40);csrf=json.loads(raw)['csrfToken']
        for body in [{'title':'x','sources':[{'quote':'raw original','label':'wechat'}]}, {'title':'x','confirm':True}, {'title':'x','needsReview':False}]:
            self.assertEqual(self.call('/api/tasks',body,bearer='d'*40,csrf=csrf)[0],400)
        status,_,raw=self.call('/api/tasks',{'title':'safe summary'},bearer='d'*40,csrf=csrf)
        self.assertEqual(status,200);task=json.loads(raw)['task']
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/confirm',{'expectedRevision':task['revision']},bearer='d'*40,csrf=csrf)[0],403)

    def test_schedule_uses_server_identity_and_existing_security(self):
        _,_,raw=self.call('/api/bootstrap',bearer='d'*40);csrf=json.loads(raw)['csrfToken']
        status,_,raw=self.call('/api/tasks',{'title':'safe schedule','state':'待办','planDate':'2026-10-25'},bearer='d'*40,csrf=csrf)
        self.assertEqual(status,200);task=json.loads(raw)['task']
        status,_,raw=self.call('/api/schedule?start=2026-10-25&end=2026-10-25',bearer='d'*40)
        self.assertEqual(status,200);e=json.loads(raw)['entries'][0]
        body={'expectedRevision':e['revision'],'expectedObjectRevision':task['revision'],'note':'设备备注','actor':{'name':'伪装本人','kind':'human'}}
        path='/api/schedule/'+e['id']+'/record'
        self.assertEqual(self.call(path,body,bearer='d'*40,csrf=csrf,origin='null')[0],403)
        self.assertEqual(self.call(path,body,bearer='d'*40)[0],403)
        self.assertEqual(self.call(path,body,bearer='d'*40,csrf=csrf)[0],200)
        status,_,raw=self.call('/api/schedule/'+e['id'],bearer='d'*40)
        self.assertEqual(json.loads(raw)['history'][0]['actor'],{'name':'秘书','kind':'ai'})

    def test_online_retains_community_font_faces(self):
        status,_,raw=self.call('/style.css',bearer='d'*40)
        self.assertEqual(status,200)
        self.assertTrue(b'@font-face' in raw,'community font faces must be retained')
        self.assertTrue(b'GoogleSans,Harmony' in raw,'community font family must be retained')

    def test_only_authenticated_static_fonts_may_cache(self):
        from unittest.mock import patch
        fonts=Path(self.tmp.name)/'font-fixture'/'web'/'fonts';fonts.mkdir(parents=True)
        (fonts/'google-sans-flex-latin.woff2').write_bytes(b'synthetic-font-header-fixture')
        with patch('local_server.APP',Path(self.tmp.name)/'font-fixture'):
            status,headers,_=self.call('/fonts/google-sans-flex-latin.woff2',bearer='d'*40)
            self.assertEqual(status,200);self.assertEqual(headers.get('Cache-Control'),'private, max-age=86400')
            for path in ['/api/bootstrap','/api/schedule?start=2026-10-24&end=2026-10-24','/fonts/not-an-allowed-font.woff2']:
                _,headers,_=self.call(path,bearer='d'*40)
                self.assertEqual(headers.get('Cache-Control'),'no-store',path)
            status,headers,_=self.call('/fonts/google-sans-flex-latin.woff2')
            self.assertEqual(status,401);self.assertEqual(headers.get('Cache-Control'),'no-store')


    def test_tool_metadata_locator_and_local_raw_boundary(self):
        _,_,raw=self.call('/api/bootstrap',bearer='d'*40);csrf=json.loads(raw)['csrfToken']
        ref={'sourceId':'wechat:fixture','nativeId':'real-100','conversation':'原群名','sender':'原昵称','version':'v2'}
        status,_,raw=self.call('/api/tasks',{'title':'仅元数据','sourceContacts':[ref]},bearer='d'*40,csrf=csrf)
        self.assertEqual(status,200,raw);task=json.loads(raw)['task'];self.assertEqual(task['sourceContacts'],[ref])
        self.assertEqual(self.call('/api/sources/wechat:fixture/receipts',bearer='d'*40)[0],404)
        self.assertEqual(self.call('/api/sources/wechat:fixture/imports',{'records':[]},bearer='d'*40,csrf=csrf)[0],404)
        self.assertEqual(self.call('/api/tasks/'+task['id']+'/record',{'expectedRevision':task['revision'],'sourceContacts':[dict(ref,key='secret')]},bearer='d'*40,csrf=csrf)[0],400)
        status,_,raw=self.call('/api/source-catalog',{'sourceId':'wechat:fixture','displayName':'微信目录','status':'cached_only','recordCount':3,'expectedRevision':0},bearer='d'*40,csrf=csrf)
        self.assertEqual(status,200,raw)
        self.assertEqual(self.call('/api/notebook/capabilities',bearer='d'*40)[0],200)

if __name__=='__main__':unittest.main()
