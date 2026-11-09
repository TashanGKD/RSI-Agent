import unittest,time,sqlite3,hashlib,contextlib,sys
from types import SimpleNamespace
from unittest.mock import patch
import native_source as s
import runtime as r
from test_runtime import binding,event

OWNER='wxid_fixture_owner'
class NamedInboxTests(unittest.TestCase):
 def test_actual_read_query_for_private_row(self):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  table='Msg_'+hashlib.md5(OWNER.encode()).hexdigest()
  c.execute('create table '+table+'(server_id integer,create_time integer,local_type integer,real_sender_id integer,source text,sort_seq integer,local_id integer,message_content text)')
  c.execute('create table Name2Id(user_name text)');c.execute('insert into Name2Id values(?)',(OWNER,))
  c.execute('insert into '+table+' values(?,?,?,?,?,?,?,?)',(123456789,int(time.time()),1,1,'',1,5,'@他山秘书 请看前面两条语音'))
  @contextlib.contextmanager
  def native(_):yield c,{'integrity':'ok'}
  route=dict(id='owner-secretary',account=s.ACCOUNT,peer=OWNER,since=1,triggerMode='owner_name',ownerId=OWNER,aliases=['他山秘书'])
  with patch.dict(sys.modules,{'linux_tool':SimpleNamespace(native=native,decode=lambda x:x,ACCOUNT=s.ACCOUNT),'receive_source':SimpleNamespace(sid=lambda x:str(x))}):
   rows=s.read([route]);self.assertEqual(rows[0]['events'][0]['namedRecipient'],'他山秘书');self.assertNotIn('text',rows[0]['events'][0])
  c.close()
 def test_explicit_name_boundary_and_quotes(self):
  aliases=['他山秘书','类器官BP','论坛会务','细胞科研']
  self.assertEqual(s.addressed_names('@他山秘书 请接上前面两条语音',aliases),['他山秘书'])
  self.assertEqual(s.addressed_names('＠细胞科研：看看这个结果',aliases),['细胞科研'])
  for text in ['转发：@他山秘书 请做','“@他山秘书 请做”','@他山秘书助理 请做','某人说@他山秘书','@未知员工 请做']:
   self.assertEqual(s.addressed_names(text,aliases),[])
 def test_bp_case_variants_use_same_canonical_role(self):
  for name in ['类器官bp','类器官BP','类器官Bp','类器官bP']:
   self.assertEqual(s.addressed_names('@'+name+' 请确认收到',['类器官BP','类器官']),['类器官BP'])
 def test_multiple_names_not_arbitrarily_claimed(self):
  self.assertEqual(s.addressed_names('@他山秘书 @论坛会务 一起看看',['他山秘书','论坛会务']),['他山秘书','论坛会务'])
 def test_private_routes_same_peer_only_disjoint_names(self):
  a=dict(id='owner-secretary',account=s.ACCOUNT,peer=OWNER,since=1,triggerMode='owner_name',ownerId=OWNER,aliases=['他山秘书'])
  b={**a,'id':'owner-forum','aliases':['论坛会务']}
  self.assertEqual(s.validated_routes([a,b]),[a,b])
  for bad in [{**b,'aliases':['他山秘书']},{**b,'peer':'wxid_fixture_4c90539d6a'},{**b,'ownerId':'wxid_fixture_4c90539d6a'},{**b,'aliases':['../bad']}]:
   with self.assertRaises(ValueError):s.validated_routes([a,bad])
 def test_owner_event_requires_real_owner_and_exact_name(self):
  b={**binding(),'id':'owner-secretary','peer':OWNER,'triggerMode':'owner_name','ownerId':OWNER,'aliases':['他山秘书']}
  e={**event(),'peer':OWNER,'atUserIds':[],'triggerType':'owner_name','namedRecipient':'他山秘书','sourceTextSHA256':'a'*64}
  r.validate_binding(b);self.assertEqual(r.validate_event(b,e)['triggerType'],'owner_name')
  for bad in [{**e,'senderId':'wxid_fixture_4c90539d6a'},{**e,'namedRecipient':'其他员工'},{**e,'kind':49},{**e,'sourceTextSHA256':'bad'},{**e,'peer':binding()['peer']}]:
   with self.assertRaises(ValueError):r.validate_event(b,bad)
 def test_group_typed_tag_limited_to_owner_opt_in(self):
  b={**binding(),'ownerId':OWNER,'ownerTextAliases':['吾愿','他山秘书']}
  e={**event(),'atUserIds':[],'triggerType':'owner_group_name','namedRecipient':'吾愿','sourceTextSHA256':'a'*64}
  self.assertEqual(r.validate_event(b,e)['triggerType'],'owner_group_name')
  for bad in [{**e,'senderId':'wxid_fixture_4c90539d6a'},{**e,'namedRecipient':'陌生员工'}]:
   with self.assertRaises(ValueError):r.validate_event(b,bad)
  with self.assertRaises(ValueError):r.validate_event(binding(),e)

if __name__=='__main__':unittest.main()
