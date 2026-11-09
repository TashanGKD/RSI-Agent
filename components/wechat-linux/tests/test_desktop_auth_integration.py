"""Real websockify authentication against local inert files; no X/WeChat or SSH."""
import unittest, importlib.util, tempfile, pathlib, subprocess, sys, os, socket, time, http.client, base64, hashlib

@unittest.skipUnless(importlib.util.find_spec('websockify'),'vendor runtime is present on AUP only')
class AuthenticationIntegration(unittest.TestCase):
    def test_actual_http_and_websocket_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp).resolve();web=root/'web';web.mkdir();(web/'index.html').write_text('inert fixture')
            auth=root/'auth.json';auth.write_text('{"credential":"fixture:random-password"}');auth.chmod(0o600)
            s=socket.socket();s.bind(('127.0.0.1',0));port=s.getsockname()[1];s.close()
            p=subprocess.Popen([sys.executable,'-m','websockify','--web',str(web),'--web-auth','--auth-plugin','desktop_control.FileAuth','--auth-source',str(auth),'127.0.0.1:'+str(port),'127.0.0.1:1'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            try:
                deadline=time.monotonic()+5
                while True:
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.2):break
                    except OSError:
                        if time.monotonic()>deadline:raise AssertionError('fixture server unavailable')
                        time.sleep(.05)
                def request(headers):
                    c=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
                    try:c.request('GET','/index.html',headers=headers);r=c.getresponse();body=r.read();return r.status,body
                    finally:c.close()
                self.assertEqual(request({})[0],401)
                self.assertEqual(request({'Authorization':'Basic '+base64.b64encode(b'fixture:wrong').decode()})[0],401)
                self.assertEqual(request({'Authorization':'Basic '+base64.b64encode(b'fixture:random-password').decode()}),(200,b'inert fixture'))
                import desktop_control
                desktop_control.verify_web_auth('127.0.0.1',port,'fixture:random-password',hashlib.sha256(b'inert fixture').hexdigest())
                with self.assertRaises(ValueError):desktop_control.verify_web_auth('127.0.0.1',port,'fixture:wrong',hashlib.sha256(b'inert fixture').hexdigest())
                with self.assertRaises(ValueError):desktop_control.verify_web_auth('127.0.0.1',port,'fixture:random-password','0'*64)
                upgrade={'Connection':'Upgrade','Upgrade':'websocket','Sec-WebSocket-Version':'13','Sec-WebSocket-Key':base64.b64encode(b'0123456789abcdef').decode()}
                self.assertEqual(request(upgrade)[0],401)
            finally:p.terminate();p.wait(timeout=4)

if __name__=='__main__':unittest.main()
