import contextlib,hashlib,sqlite3,sys,time,unittest
from types import SimpleNamespace
from unittest.mock import patch
from xml.sax.saxutils import escape
import native_source as s
import runtime as r
from test_runtime import binding,event

OWNER=s.OWNER
RAW=(57<<32)|49

def quote(title,old='@人事负责人 旧话',typ='57'):
 return '<msg><appmsg><title>'+escape(title)+'</title><type>'+typ+'</type><refermsg><content>'+escape(old)+'</content></refermsg></appmsg></msg>'

class PrivateQuotedName(unittest.TestCase):
 def read(self,body,raw_type=RAW,sender=OWNER,peer=OWNER):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row
  table='Msg_'+hashlib.md5(peer.encode()).hexdigest()
  c.execute('create table '+table+'(server_id integer,create_time integer,local_type integer,real_sender_id integer,source text,sort_seq integer,local_id integer,message_content text)')
  c.execute('create table Name2Id(user_name text)');c.execute('insert into Name2Id values(?)',(sender,))
  c.execute('insert into '+table+' values(?,?,?,?,?,?,?,?)',(8000013263125808652,int(time.time()),raw_type,1,'<msgsource/>',1,419,body))
  @contextlib.contextmanager
  def native(_):yield c,{'integrity':'ok','gap':None}
  route=dict(id='owner-hr',account=s.ACCOUNT,peer=peer,since=1,triggerMode='owner_name',ownerId=OWNER,aliases=['人事负责人'])
  try:
   with patch.dict(sys.modules,{'linux_tool':SimpleNamespace(native=native,decode=lambda x:x,ACCOUNT=s.ACCOUNT),'receive_source':SimpleNamespace(sid=lambda x:str(x))}):return s.read([route])[0]
  finally:c.close()

 def test_current_title_triggers_without_exporting_quote(self):
  title='@人事负责人 正常使用读取工具'
  x=self.read(quote(title,'@论坛会务 旧引用'))['events']
  self.assertEqual(len(x),1)
  self.assertEqual(x[0]['kind'],49);self.assertEqual(x[0]['appType'],57)
  self.assertEqual(x[0]['triggerType'],'owner_name')
  self.assertEqual(x[0]['sourceTextSHA256'],hashlib.sha256(title.encode()).hexdigest())
  self.assertNotIn('text',x[0]);self.assertNotIn('title',x[0])

 def test_old_quote_name_alone_never_triggers(self):
  self.assertEqual(self.read(quote('谢谢，已看','@人事负责人 请做'))['events'],[])

 def test_third_party_title_never_triggers(self):
  self.assertEqual(self.read(quote('@人事负责人 做事'),sender='wxid_fixture_4c90539d6a')['events'],[])

 def test_non_reply_app_cannot_claim_name(self):
  for typ in [5,6,19]:
   self.assertEqual(self.read(quote('@人事负责人 做事',typ=str(typ)),raw_type=(typ<<32)|49)['events'],[])

 def test_raw_type_and_xml_type_must_agree(self):
  self.assertEqual(self.read(quote('@人事负责人 做事',typ='5'))['events'],[])

 def test_ambiguous_title_type_or_nested_title_rejected(self):
  bodies=[quote('@人事负责人 做事').replace('</title>','</title><title>@人事负责人 第二个</title>'),quote('@人事负责人 做事').replace('</type>','</type><type>57</type>'),'<msg><appmsg><title><b>@人事负责人 做事</b></title><type>57</type></appmsg></msg>','<msg><wrapper>'+quote('@人事负责人 做事')+'</wrapper></msg>']
  for body in bodies:self.assertEqual(self.read(body)['events'],[])

 def test_entity_malformed_and_oversize_rejected(self):
  bodies=['<!DOCTYPE msg [<!ENTITY n "@人事负责人 做事">]><msg><appmsg><title>&n;</title><type>57</type></appmsg></msg>',quote('@人事负责人 做事')[:-3],quote('@人事负责人 '+'x'*65536)]
  for body in bodies:self.assertEqual(self.read(body)['events'],[])

 def test_plain_name_behavior_and_hash_kept(self):
  title='@人事负责人 继续原工作'
  x=self.read(title,raw_type=1)['events'][0]
  self.assertEqual(x['sourceTextSHA256'],hashlib.sha256(title.encode()).hexdigest())
  self.assertNotIn('appType',x)

 def test_runtime_accepts_exact_private_quoted_name(self):
  b={**binding(),'id':'owner-hr','peer':OWNER,'triggerMode':'owner_name','ownerId':OWNER,'aliases':['人事负责人']}
  e={**event(),'peer':OWNER,'kind':49,'appType':57,'atUserIds':[],'triggerType':'owner_name','namedRecipient':'人事负责人','sourceTextSHA256':'a'*64}
  try:actual=r.validate_event(b,e)
  except ValueError as ex:self.fail('current private quoted name rejected: '+str(ex))
  self.assertEqual(actual,e)

 def test_runtime_still_rejects_cross_scope_and_other_app(self):
  b={**binding(),'id':'owner-hr','peer':OWNER,'triggerMode':'owner_name','ownerId':OWNER,'aliases':['人事负责人']}
  e={**event(),'peer':OWNER,'kind':49,'appType':57,'atUserIds':[],'triggerType':'owner_name','namedRecipient':'人事负责人','sourceTextSHA256':'a'*64}
  for bad in [{**e,'senderId':'wxid_fixture_4c90539d6a'},{**e,'peer':'wxid_fixture_4c90539d6a'},{**e,'appType':5},{**e,'appType':True},{**e,'namedRecipient':'其他员工'},{**e,'sourceTextSHA256':'x'}]:
   with self.assertRaises(ValueError):r.validate_event(b,bad)

if __name__=='__main__':unittest.main()
