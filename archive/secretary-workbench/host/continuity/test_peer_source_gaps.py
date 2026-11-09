"""Isolated SQLite peers and memory ledger; no native source or live queue."""
import contextlib,hashlib,sqlite3,time,types,unittest
from unittest.mock import patch
import native_source as source
import runtime
from test_runtime import binding

class PeerGaps(unittest.TestCase):
    def fixture(self, many=False):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
        c.execute('create table Name2Id(user_name text)')
        c.execute('insert into Name2Id values(?)',('wxid_fixture_0fd4310213',))
        good=dict(binding(),id='good',peer='22489222004@chatroom',since=int(time.time())-10)
        missing=dict(good,id='missing',peer='21339478653@chatroom')
        table='Msg_'+hashlib.md5(good['peer'].encode()).hexdigest()
        c.execute('create table '+table+'(server_id integer,create_time integer,local_type integer,real_sender_id integer,source text,local_id integer,sort_seq integer,message_content text)')
        at='<atuserlist>'+source.ACCOUNT+'</atuserlist>'
        for i in range(1001 if many else 1):
            c.execute('insert into '+table+' values(?,?,?,?,?,?,?,?)',(10000+i,int(time.time()),1,1,at,i,i,'ordinary'))
        @contextlib.contextmanager
        def native(path):
            yield c,{'integrity':'ok','gap':None}
        modules={'linux_tool':types.SimpleNamespace(native=native,decode=lambda x:x,ACCOUNT=source.ACCOUNT),
                 'receive_source':types.SimpleNamespace(sid=lambda x:str(x))}
        return c,good,missing,modules

    def test_missing_peer_does_not_hide_neighbor_native_event(self):
        c,good,missing,modules=self.fixture()
        try:
            with patch.dict('sys.modules',modules):
                try:frames=source.read([missing,good])
                except sqlite3.OperationalError:self.fail('missing peer table must not abort healthy peer')
            self.assertEqual(frames[0]['kind'],'source_gap')
            self.assertEqual(frames[0]['reason'],'message_table_missing')
            self.assertFalse(frames[0]['coverage']['complete'])
            self.assertEqual(frames[1]['events'][0]['serverId'],'10000')
        finally:c.close()

    def test_large_peer_window_is_a_gap_not_silent_loss(self):
        c,good,missing,modules=self.fixture(many=True)
        try:
            with patch.dict('sys.modules',modules):
                try:frames=source.read([good,missing])
                except ValueError:self.fail('bounded peer overflow must be isolated as a gap')
            self.assertEqual(frames[0]['kind'],'source_gap')
            self.assertEqual(frames[0]['reason'],'peer_window_exceeded')
        finally:c.close()

    def handler(self):
        f=getattr(runtime,'apply_source_frame',None)
        self.assertIsNotNone(f,'runtime must retain per-peer gap without aborting other routes')
        return f

    def gap(self,b):
        return dict(kind='source_gap',binding=b['id'],observedAt=time.time(),reason='message_table_missing',
                    coverage={'complete':False,'scope':'registered peer native mention or explicit owner employee name','rawTextReturned':False})

    def test_runtime_gap_is_local_and_success_clears_old_gap(self):
        f=self.handler();a=binding();b=dict(a,id='other',peer='22489222004@chatroom')
        l=runtime.Ledger(':memory:');s={'bindings':{a['id']:{'sourceReady':True}},'sourceReady':True}
        try:
            f([a,b],l,s,self.gap(b))
            self.assertTrue(s['bindings'][a['id']]['sourceReady'])
            self.assertFalse(s['bindings'][b['id']]['sourceReady'])
            self.assertEqual(s['bindings'][b['id']]['sourceGapReason'],'message_table_missing')
            self.assertTrue(s['sourceReady']);self.assertFalse(s['sourceCoverageComplete'])
            f([a,b],l,s,dict(kind='source',binding=b['id'],observedAt=time.time(),events=[],coverage={'complete':True}))
            self.assertTrue(s['bindings'][b['id']]['sourceReady'])
            self.assertIsNone(s['bindings'][b['id']].get('sourceGapReason'))
            self.assertTrue(s['sourceCoverageComplete'])
        finally:l.close()

    def test_unknown_binding_reason_or_invented_gap_events_are_rejected(self):
        f=self.handler();b=binding();l=runtime.Ledger(':memory:')
        try:
            for delta in ({'binding':'not-registered'},{'reason':'unknown_reason'},{'events':[{'id':'fake'}]}):
                with self.assertRaises(ValueError):f([b],l,{'bindings':{}},dict(self.gap(b),**delta))
        finally:l.close()

if __name__=='__main__':unittest.main()
