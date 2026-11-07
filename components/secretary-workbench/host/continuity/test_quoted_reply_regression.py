import contextlib,hashlib,sqlite3,time,types,unittest
from unittest.mock import patch
import native_source
from runtime import validate_event
from test_runtime import binding,event
ACCOUNT='wxid_fixture_operator'
PEER='21993263679@chatroom'
RAW_QUOTE=(57<<32)|49
class QuotedReplyRegression(unittest.TestCase):
 def test_runtime_accepts_actual_quoted_native_at(self):
  e={**event(),'serverId':'8000007471604428317','kind':49,'appType':57,'senderId':'wxid_fixture_2a84120860'}
  self.assertEqual(validate_event(binding(),e),e)
 def test_quote_without_current_native_at_is_rejected(self):
  e={**event(),'kind':49,'appType':57,'atUserIds':[]}
  with self.assertRaises(ValueError):validate_event(binding(),e)
 def test_non_quote_app_message_is_rejected(self):
  for app in [None,5,6,True]:
   e={**event(),'kind':49,'appType':app}
   with self.assertRaises(ValueError):validate_event(binding(),e)
 def test_group_quote_uses_current_source_not_quoted_text(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  c.execute('create table Name2Id(user_name text)');c.execute('insert into Name2Id values(?)',('wxid_fixture_2a84120860',))
  table='Msg_'+hashlib.md5(PEER.encode()).hexdigest()
  c.execute('create table '+table+'(server_id integer,create_time integer,local_type integer,real_sender_id integer,source text,local_id integer,sort_seq integer,message_content text)')
  at='<msgsource><atuserlist><![CDATA['+ACCOUNT+']]></atuserlist></msgsource>'
  now=int(time.time())
  rows=[(8000007471604428317,now,RAW_QUOTE,1,at,1,1,'quoted reply'),(8000260037665786189,now,RAW_QUOTE,1,'<msgsource/>',2,2,'old quote @target'),(8000048176174351767,now,1,1,at,3,3,'ordinary'),(8000077821281543749,now,(6<<32)|49,1,at,4,4,'file')]
  c.executemany('insert into '+table+' values(?,?,?,?,?,?,?,?)',rows)
  @contextlib.contextmanager
  def native(path):yield c,{'integrity':'ok','gap':None}
  lt=types.SimpleNamespace(native=native,decode=lambda x:x,ACCOUNT=ACCOUNT)
  recv=types.SimpleNamespace(sid=lambda x:str(x))
  route={'id':'forum','account':ACCOUNT,'peer':PEER,'since':now-1}
  with patch.dict('sys.modules',{'linux_tool':lt,'receive_source':recv}):result=native_source.read([route])
  ev=result[0]['events'];self.assertEqual([x['serverId']for x in ev],['8000007471604428317','8000048176174351767'])
  self.assertEqual(ev[0]['kind'],49);self.assertEqual(ev[0]['appType'],57);self.assertNotIn('appType',ev[1]);c.close()
if __name__=='__main__':unittest.main()
