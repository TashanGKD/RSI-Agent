import importlib.util, pathlib, unittest, tempfile, os, json, socket, threading, base64, time, socketserver, contextlib, io
from unittest.mock import patch

FILE = pathlib.Path(__file__).resolve().parents[1] / 'desktop_control.py'

def load():
    if not FILE.exists(): raise AssertionError('desktop control implementation is missing')
    spec=importlib.util.spec_from_file_location('desktop_control', FILE)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class DesktopControlTests(unittest.TestCase):
    def setUp(self): self.m=load()
    def test_default_does_not_contact_remote(self):
        calls=[]
        with contextlib.redirect_stdout(io.StringIO()):
            self.m.main([], rpc=lambda *a: calls.append(a))
            self.m.main(['start'], rpc=lambda *a: calls.append(a))
        self.assertEqual(calls,[])
    def test_reject_unsafe_mode_ttl_duplicate_and_unknown_fields(self):
        for r in [{'action':'start','mode':'everything','ttl':60}, {'action':'start','mode':'view','ttl':999999}, {'action':'start','mode':'view','ttl':True}, {'action':'start','mode':'view','ttl':60,'host':'0.0.0.0'}]:
            with self.subTest(r=r), self.assertRaises(ValueError):self.m.parse_request(json.dumps(r))
        with self.assertRaises(ValueError):self.m.parse_request('{"action":"status","action":"start"}')
    def test_navigate_has_no_keyboard_or_clipboard_and_compose_blocks_enter(self):
        a=self.m.input_flags('navigate');self.assertEqual(a[a.index('-input')+1],'MB');self.assertIn('-nosel',a)
        a=self.m.input_flags('compose');self.assertEqual(a[a.index('-remap')+1],'Return-None,KP_Enter-None')
        self.assertIn('-viewonly',self.m.input_flags('view'))
    def test_private_file_refuses_symlink_and_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d).resolve();p=root/'state.json';p.write_text('{}');p.chmod(0o644)
            with self.assertRaises(ValueError):self.m.read_private(p)
            p.chmod(0o600);q=root/'alias';q.symlink_to(p)
            with self.assertRaises(ValueError):self.m.read_private(q)
            self.assertEqual(self.m.read_private(p),{})
    def test_stop_token_must_match_and_pid_reuse_refused(self):
        s={'session':'a'*32,'processes':[{'pid':12,'birth':'100'}]}
        with self.assertRaises(ValueError):self.m.stop_processes(s,'b'*32, birth=lambda _: '100', kill=lambda _: self.fail('must not kill'))
        killed=[];self.m.stop_processes(s,'a'*32,birth=lambda _: '101',kill=killed.append);self.assertEqual(killed,[])
    def test_http_request_guard_rejects_cross_site_host_body_and_huge_header(self):
        base=b'GET /index.html HTTP/1.1\r\nHost: 127.0.0.1:1234\r\n'
        for raw in [base+b'Origin: https://evil.test\r\n\r\n',base.replace(b'127.0.0.1:1234',b'evil.test')+b'\r\n',base+b'Content-Length: 8\r\n\r\n',base+b'Transfer-Encoding: chunked\r\n\r\n',base+b'X: '+b'x'*40000+b'\r\n\r\n']:
            with self.subTest(raw=raw[:120]),self.assertRaises(ValueError):self.m.inject_auth(raw,'127.0.0.1:1234','secret')
    def test_auth_is_injected_for_upgrade_and_never_reflects_client_auth(self):
        raw=b'GET /websockify HTTP/1.1\r\nHost: 127.0.0.1:1234\r\nOrigin: http://127.0.0.1:1234\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nAuthorization: attacker\r\n\r\n'
        result=self.m.inject_auth(raw,'127.0.0.1:1234','dXNlcjpwYXNz')
        self.assertIn(b'Authorization: Basic dXNlcjpwYXNz',result);self.assertNotIn(b'attacker',result);self.assertIn(b'Connection: Upgrade',result)
    def test_file_auth_missing_or_wrong_credentials_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d).resolve()/'auth.json';p.write_text(json.dumps({'credential':'user:random'}));p.chmod(0o600)
            auth=self.m.FileAuth(str(p))
            for h in [{},{'Authorization':'Basic '+base64.b64encode(b'user:wrong').decode()}]:
                with self.assertRaises(Exception):auth.authenticate(h,None,None)
            auth.authenticate({'Authorization':'Basic '+base64.b64encode(b'user:random').decode()},None,None)

    def test_failed_start_cleans_generated_credentials_and_never_spawns(self):
        with tempfile.TemporaryDirectory() as d, patch.object(self.m,'ROOT',pathlib.Path(d).resolve()), patch.object(self.m.subprocess,'run',side_effect=FileNotFoundError()), patch.object(self.m.subprocess,'Popen') as spawn:
            with self.assertRaises(FileNotFoundError):self.m.remote({'action':'start','mode':'view','ttl':60})
            spawn.assert_not_called()
            self.assertFalse(list(pathlib.Path(d).glob('session-*/auth.json')))
            self.assertFalse(list(pathlib.Path(d).glob('session-*/web/index.html')))
            self.assertEqual(self.m.remote({'action':'status'})['state'],'stopped')

    def roundtrip(self, websocket=False):
        observed=[]
        class Fixture(socketserver.BaseRequestHandler):
            def handle(s):
                h=b''
                while not h.endswith(b'\r\n\r\n'):h+=s.request.recv(1)
                observed.append(h)
                if websocket:
                    s.request.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n')
                    packet=s.request.recv(1024);s.request.sendall(packet)
                else:s.request.sendall(b'HTTP/1.1 200 OK\r\nContent-Length: 7\r\nConnection: close\r\n\r\nfixture')
        dest=socketserver.ThreadingTCPServer(('127.0.0.1',0),Fixture);threading.Thread(target=dest.serve_forever,daemon=True).start()
        original=socket.create_connection
        state={'credential':'fixture-secret','expiresAt':time.time()+30}
        relay=self.m.Relay(state);threading.Thread(target=relay.serve_forever,daemon=True).start();host='127.0.0.1:'+str(relay.server_address[1])
        def dial(addr,**kwargs):return original(dest.server_address if addr==(self.m.HOST,16997) else addr,**kwargs)
        try:
            with patch.object(self.m.socket,'create_connection',side_effect=dial),original(relay.server_address,timeout=3) as client:
                header='GET /websockify HTTP/1.1\r\nHost: '+host+'\r\nOrigin: http://'+host+'\r\n'
                if websocket:header+='Connection: Upgrade\r\nUpgrade: websocket\r\n'
                client.sendall((header+'\r\n').encode());reply=b''
                while b'\r\n\r\n' not in reply:reply+=client.recv(1)
                if websocket:
                    packet=b'\x82\x83\x12\x34\x56\x78abc';client.sendall(packet);self.assertEqual(client.recv(100),packet)
                else:self.assertEqual(client.recv(7),b'fixture')
            self.assertIn(b'Authorization: Basic fixture-secret',observed[0])
        finally:relay.release();relay.shutdown();relay.server_close();dest.shutdown();dest.server_close()
    def test_real_local_http_fixture_relay(self):self.roundtrip()
    def test_real_local_websocket_upgrade_and_binary_fixture_relay(self):self.roundtrip(True)

if __name__=='__main__':unittest.main()
