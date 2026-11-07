import tempfile
import unittest
from pathlib import Path
from modules.access import AccessService, AccessError


class AccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.clock=[1000]
        self.a=AccessService(Path(self.tmp.name),'https://notes.example.test',activation_token='a'*40,device_token='d'*40,clock=lambda:self.clock[0])
    def tearDown(self): self.tmp.cleanup()
    def test_bad_activation_and_oversize_password_rejected_without_initialization(self):
        for token,password in [('bad','password123'),('a'*40,'x'*257),('a'*40,'short')]:
            with self.assertRaises(AccessError): self.a.activate(token,password,'ip')
        self.assertFalse(self.a.initialized())
    def test_expired_or_replayed_activation_rejected(self):
        cookie=self.a.activate('a'*40,'password123','ip')
        with self.assertRaises(AccessError): self.a.activate('a'*40,'different123','ip')
        self.assertEqual(self.a.authenticate(cookie,None),'human')
    def test_device_cannot_become_browser_and_cookie_cannot_become_device(self):
        self.assertIsNone(self.a.authenticate('tashan_session='+'d'*40,None))
        self.assertEqual(self.a.authenticate('', 'Bearer '+'d'*40),'device')
        self.assertIsNone(self.a.authenticate('', 'Bearer invalid'))
        self.assertIsNone(self.a.authenticate('', 'Basic '+'d'*40))
    def test_two_sessions_logout_and_expiry(self):
        c1=self.a.activate('a'*40,'password123','ip')
        c2=self.a.login('password123','other')
        self.a.logout(c1)
        self.assertIsNone(self.a.authenticate(c1,None))
        self.assertEqual(self.a.authenticate(c2,None),'human')
        self.clock[0]+=15*86400
        self.assertIsNone(self.a.authenticate(c2,None))
    def test_password_hash_only_and_rate_limit(self):
        self.a.activate('a'*40,'password123','ip')
        for _ in range(10):
            with self.assertRaises(AccessError):self.a.login('wrongpass','blocked')
        with self.assertRaises(AccessError) as cm:self.a.login('password123','blocked')
        self.assertEqual(cm.exception.status,429)
        raw=self.a.db_file.read_bytes()
        self.assertNotIn(b'password123',raw)
        self.assertNotIn(('a'*40).encode(),raw)
        self.assertNotIn(('d'*40).encode(),raw)
    def test_restart_keeps_auth_and_expired_activation(self):
        self.clock[0]+=8*86400
        with self.assertRaises(AccessError):self.a.activate('a'*40,'password123','ip')
        b=AccessService(Path(self.tmp.name),'https://notes.example.test',clock=lambda:self.clock[0])
        self.assertFalse(b.initialized())
    def test_insecure_origin_rejected(self):
        with self.assertRaises(ValueError):AccessService(Path(self.tmp.name)/'bad','http://example.test')
    def test_access_folder_symlink_escape_rejected(self):
        base=Path(self.tmp.name)/'linked';base.mkdir()
        outside=Path(self.tmp.name)/'outside';outside.mkdir()
        (base/'access').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError):AccessService(base,'https://notes.example.test')
        self.assertFalse((outside/'access.sqlite3').exists())
    def test_named_owner_requires_correct_username_even_with_correct_password(self):
        self.a.activate('a'*40,'password123','ip',username='fixture_owner')
        for username in [None,'another_owner',"fixture_owner' OR '1'='1"]:
            with self.assertRaises(AccessError):self.a.login('password123','ip',username=username)
        cookie=self.a.login('password123','ip',username='fixture_owner')
        self.assertEqual(self.a.authenticate(cookie,None),'human')
    def test_invalid_username_cannot_consume_activation(self):
        for username in ['', 'x'*65, '<script>']:
            with self.assertRaises(AccessError):self.a.activate('a'*40,'password123','ip',username=username)
        self.assertFalse(self.a.initialized())

if __name__=='__main__':unittest.main()
