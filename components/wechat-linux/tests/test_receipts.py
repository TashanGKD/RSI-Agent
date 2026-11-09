import sqlite3,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
import remote

class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.ledger=sqlite3.connect(':memory:');self.ledger.row_factory=sqlite3.Row
        self.ledger.execute('create table sends(id text primary key,hash text,text text,baseline integer,started real,state text,local_id integer,server_id text)')
        self.native=sqlite3.connect(':memory:');self.native.row_factory=sqlite3.Row
        self.native.execute('create table Name2Id(user_name text)');self.native.execute('insert into Name2Id(rowid,user_name) values(1,?)',(remote.ACCOUNT,))
        self.native.execute('create table '+remote.TABLE+'(local_id integer,server_id integer,status integer,message_content text,real_sender_id integer,local_type integer,create_time integer default 2)')
        self.native.execute('insert into '+remote.TABLE+'(local_id,server_id,status,message_content,real_sender_id,local_type) values(11,900,2,?,1,1)',('收到',));self.native.commit()
    def tearDown(self):self.ledger.close();self.native.close()
    def test_one_actual_message_cannot_satisfy_two_request_ids(self):
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('A','hash','收到',10,1.,'attempting',None,None))
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('B','hash','收到',10,2.,'accepted',11,'900'));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):result=remote.reconcile(self.ledger,'A')
        self.assertEqual(result['state'],'unknown')
    def test_later_attempt_bounds_older_unknown_receipt(self):
        for ident,t in [('A',1.),('B',2.)]:self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',(ident,'hash','收到',10,t,'attempting',None,None))
        self.ledger.commit()
        with patch('remote.connect',return_value=self.native):result=remote.reconcile(self.ledger,'A')
        self.assertEqual(result['state'],'unknown')
    def test_reused_local_id_with_different_server_id_is_not_same_receipt(self):
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('old','hash','earlier',10,1.,'accepted',11,'899'))
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('new','hash','收到',10,2.,'attempting',None,None));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):r=remote.reconcile(self.ledger,'new')
        self.assertEqual(r['state'],'accepted');self.assertEqual(r['server_id'],'900')
    def test_same_server_id_cannot_be_claimed_under_another_local_id(self):
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('old','hash','收到',10,1.,'accepted',99,'900'))
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('new','hash','收到',10,2.,'attempting',None,None));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):r=remote.reconcile(self.ledger,'new')
        self.assertEqual(r['state'],'unknown')
    def test_server_change_does_not_bypass_content_match(self):
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('new','hash','different content',10,2.,'attempting',None,None));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):r=remote.reconcile(self.ledger,'new')
        self.assertEqual(r['state'],'unknown')
    def test_receipt_index_migrates_local_uniqueness_to_server_uniqueness(self):
        with tempfile.TemporaryDirectory() as td:
            with patch('remote.ROOT',Path(td)):
                c=remote.sender_state()
                try:
                    cols='(id,hash,text,baseline,started,state,local_id,server_id)'
                    c.execute('insert into sends'+cols+' values(?,?,?,?,?,?,?,?)',('a','hash','a',10,1.,'accepted',11,'899'));c.commit()
                    c.execute('insert into sends'+cols+' values(?,?,?,?,?,?,?,?)',('b','hash','b',10,2.,'accepted',11,'900'));c.commit()
                    with self.assertRaises(sqlite3.IntegrityError):c.execute('insert into sends'+cols+' values(?,?,?,?,?,?,?,?)',('c','hash','c',10,3.,'accepted',12,'900'))
                finally:c.close()
    def test_lower_reused_local_id_can_match_new_server_snapshot(self):
        self.ledger.execute('alter table sends add column seen_servers text')
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?,?)',('new','hash','收到',99,1.,'attempting',None,None,'[]'));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):r=remote.reconcile(self.ledger,'new')
        self.assertEqual(r['state'],'accepted');self.assertEqual(r['server_id'],'900')
    def test_preexisting_same_text_is_not_a_new_receipt(self):
        self.ledger.execute('alter table sends add column seen_servers text')
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?,?)',('new','hash','收到',1,1.,'attempting',None,None,'["900"]'));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):r=remote.reconcile(self.ledger,'new')
        self.assertEqual(r['state'],'unknown')
    def test_signed_legacy_receipt_is_same_unsigned_identity(self):
        self.native.execute('update '+remote.TABLE+' set server_id=-5');self.native.commit()
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('old','hash','收到',10,1.,'accepted',99,'-5'))
        self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',('new','hash','收到',10,2.,'attempting',None,None));self.ledger.commit()
        with patch('remote.connect',return_value=self.native):r=remote.reconcile(self.ledger,'new')
        self.assertEqual(r['state'],'unknown')
    def test_normalization_collision_keeps_legacy_rows_unmodified(self):
        for ident,key in [('a','-5'),('b',str(2**64-5))]:
            self.ledger.execute('insert into sends values(?,?,?,?,?,?,?,?)',(ident,'hash','收到',10,1.,'accepted',11,key))
        self.ledger.commit();before=list(self.ledger.execute('select id,server_id from sends'))
        with self.assertRaises(ValueError):remote.normalize_legacy_receipts(self.ledger)
        self.assertEqual([tuple(x) for x in self.ledger.execute('select id,server_id from sends')],[tuple(x) for x in before])

if __name__=='__main__':unittest.main()
