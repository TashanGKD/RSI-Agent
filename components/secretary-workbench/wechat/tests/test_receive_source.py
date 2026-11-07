import tempfile,sqlite3,unittest,json
from pathlib import Path
from receive_source import SourceInbox

class SourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.native_path=Path(self.tmp.name)/'native.sqlite';self.native=sqlite3.connect(self.native_path);self.native.row_factory=sqlite3.Row
        self.native.executescript('create table Name2Id(user_name text);insert into Name2Id values("owner");insert into Name2Id values("small");create table Msg_pair(local_id integer,server_id integer,local_type integer,real_sender_id integer,create_time integer,sort_seq integer,message_content text);')
        self.n=SourceInbox(Path(self.tmp.name)/'source.sqlite',lambda:sqlite3.connect(self.native_path),'Msg_pair','small','owner',lambda v:v,'a'*32)
    def tearDown(self):self.n.close();self.native.close();self.tmp.cleanup()
    def row(self,local,sid,text='hi',at=100):
        self.native.execute('insert into Msg_pair values(?,?,1,1,?,?,?)',(local,sid,at,at*1000,text));self.native.commit()
    def ack(self,b):return self.n.ack(b['batch_id'],b['batch_hash'],b['ack_ids'])
    def test_before_ack_restart_replays_exact_batch(self):
        self.row(1,100);b=self.n.read();self.n.close()
        self.n=SourceInbox(Path(self.tmp.name)/'source.sqlite',lambda:sqlite3.connect(self.native_path),'Msg_pair','small','owner',lambda v:v,'a'*32)
        self.assertEqual(self.n.read(),b)
    def test_ack_is_bound_to_whole_batch_and_idempotent(self):
        self.row(1,100);b=self.n.read()
        with self.assertRaises(ValueError):self.n.ack(b['batch_id'],b['batch_hash'],['200'])
        self.assertEqual(self.n.read(),b)
        self.ack(b);self.ack(b);self.assertEqual(self.n.read()['events'],[])
    def test_reused_local_id_is_still_a_new_server_message(self):
        self.row(1,100);self.ack(self.n.read())
        self.native.execute('delete from Msg_pair');self.native.commit();self.row(1,200,'new')
        b=self.n.read();self.assertEqual([e['server_id'] for e in b['events']],[200])
    def test_capture_survives_native_row_removal_before_ack(self):
        self.row(1,100);b=self.n.read();self.native.execute('delete from Msg_pair');self.native.commit()
        self.assertEqual(self.n.read(),b)
    def test_zero_identity_is_not_exported_or_acknowledged(self):
        self.row(1,0);self.assertEqual(self.n.read()['events'],[])
        self.assertEqual(self.n.read()['provisional'][0]['local_id'],1)
        self.native.execute('update Msg_pair set server_id=100');self.native.commit()
        self.assertEqual(self.n.read()['ack_ids'],['100'])
    def test_pagination_preserves_all_ids(self):
        for i in range(1,261):self.row(i,1000+i,at=100+i)
        seen=[]
        while True:
            b=self.n.read()
            if not b['events']:break
            seen.extend(b['ack_ids']);self.ack(b)
        self.assertEqual(len(seen),260);self.assertEqual(len(set(seen)),260)
    def test_arbitrary_ack_is_rejected(self):
        with self.assertRaises(ValueError):self.n.ack('../../file','x'*64,['100'])
        with self.assertRaises(ValueError):self.n.ack('a'*32,'b'*64,['0'])
    def test_conflicting_bodies_under_one_server_id_are_not_guessed(self):
        self.row(1,100,'first');self.row(2,100,'different')
        with self.assertRaises(ValueError):self.n.read()
    def test_pending_pagination_flag_survives_replay(self):
        for i in range(1,131):self.row(i,i+1000,at=i)
        first=self.n.read();self.assertTrue(first['has_more']);self.assertEqual(first,self.n.read())
    def test_local_system_zero_is_not_a_provisional_user_command(self):
        self.row(1,0);self.native.execute('update Msg_pair set local_type=10000');self.native.commit()
        self.assertEqual(self.n.read()['provisional'],[])

if __name__=='__main__':unittest.main()
