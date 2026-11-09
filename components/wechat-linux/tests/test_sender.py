import unittest,tempfile,hashlib,base64
from pathlib import Path
from unittest.mock import patch
import sender

class SenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.n=0
        self.s=sender.Sender(Path(self.tmp.name)/'ledger.sqlite',self.ui,self.lookup)
        self.target={'username':'peer','displayName':'Unique'}
        self.r={'action':'send_text','execute':True,'peer':'peer','request_id':'a'*64,'text':'hello'}
    def tearDown(self):self.s.c.close();self.tmp.cleanup()
    def ui(self,r,t):self.n+=1
    def lookup(self,row):return {'state':'accepted','serverId':'123','evidence':'fixture-native'}
    def test_replay_after_restart_does_not_send_twice(self):
        self.s.send(self.r,self.target);self.s.c.close()
        self.s=sender.Sender(Path(self.tmp.name)/'ledger.sqlite',self.ui,self.lookup)
        self.assertEqual(self.s.send(self.r,self.target)['serverId'],'123');self.assertEqual(self.n,1)
    def test_changed_body_or_target_under_same_id_rejected(self):
        self.s.send(self.r,self.target)
        for r,t in [({**self.r,'text':'different'},self.target),(self.r,{'username':'other','displayName':'Other'})]:
            with self.assertRaises(ValueError):self.s.send(r,t)
        self.assertEqual(self.n,1)
    def test_interruption_never_blind_resends(self):
        def broke(*_):self.n+=1;raise ConnectionError()
        self.s.ui=broke;self.s.lookup=lambda row:{'state':'unknown'}
        self.assertEqual(self.s.send(self.r,self.target)['state'],'unknown')
        self.assertEqual(self.s.send(self.r,self.target)['state'],'unknown');self.assertEqual(self.n,1)
    def test_bad_image_and_oversize_no_side_effect(self):
        for value in ['../etc/passwd',base64.b64encode(b'x'*1100000).decode()]:
            with self.assertRaises(ValueError):self.s.send({**self.r,'action':'send_image','image_base64':value},self.target)
        self.assertEqual(self.n,0)
    def test_shell_text_is_data(self):
        r={**self.r,'text':'$(touch /tmp/evil); `id`'}
        self.s.send(r,self.target)
        self.assertEqual(self.s.c.execute('select payload from sends').fetchone()[0],r['text'])
    def test_mismatched_binding_or_duplicate_name_rejected(self):
        cfg={'peer':'someone','header_sha256':'a'*64}
        with self.assertRaises(ValueError):sender.validate_binding(cfg,self.target,b'pixels')
    def test_corrupt_local_ledger_symlink_rejected(self):
        p=Path(self.tmp.name)/'link';p.symlink_to(Path(self.tmp.name)/'ledger.sqlite')
        with self.assertRaises(ValueError):sender.Sender(p,self.ui,self.lookup)
    def test_two_requests_cannot_claim_the_same_native_server_receipt(self):
        self.s.send(self.r,self.target)
        result=self.s.send({**self.r,'request_id':'b'*64},self.target)
        self.assertEqual(result['state'],'unknown');self.assertEqual(result['reason'],'native_receipt_already_claimed')
    def test_legacy_accepted_request_returns_existing_receipt_without_new_send(self):
        import sqlite3
        root=Path(self.tmp.name);c=sqlite3.connect(root/'native-outbox.sqlite')
        c.execute('create table sends(id text,text text,state text,server_id text,local_id int)')
        c.execute('insert into sends values(?,?,?,?,?)',('c'*64,'hello','accepted','999',None));c.commit();c.close()
        (root/'native-outbox.sqlite').chmod(0o600)
        result=sender.legacy_receipt(root,'c'*64)
        self.assertEqual(result['serverId'],'999');self.assertTrue(result['legacyReceipt'])
        with self.assertRaises(ValueError):sender.legacy_receipt(root,'c'*64,{**self.r,'text':'changed'},{'username':'wxid_fixture_c2253ec460'})

