import unittest,sqlite3,hashlib,types,sys
from contextlib import contextmanager
from unittest.mock import patch
from operations.proof import matches,native_message


class TerminalLFTests(unittest.TestCase):
 def test_exactly_one_terminal_lf_only(self):
  j=lambda text:{'action':'send_text','payload':{'text':text}}
  for expected,actual in [('正文\n','正文'),('  首行\n内部行 \n','  首行\n内部行 ')]:
   self.assertTrue(matches(j(expected),1,actual,''))
  for expected,actual in [('正文\n\n','正文'),('正文\n\n','正文\n'),('正文\r\n','正文\r'),(' 前导\n','前导'),('内\n部\n','内部'),('末尾 \n','末尾'),('正文\n','正文 '),('\n','')]:
   self.assertFalse(matches(j(expected),1,actual,''),(repr(expected),repr(actual)))
  self.assertFalse(matches(j('正文\n'),49,'正文',''))
  self.assertFalse(matches({'action':'forward','payload':{},'nativeSource':{'kind':1,'text':'正文\n'}},1,'正文',''))
 def check(self,rows,expected='正文\n',before=(),alter=None):
  c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;peer='123@chatroom';name='Msg_'+hashlib.md5(peer.encode()).hexdigest()
  c.execute('create table Name2Id(user_name text)');c.executemany('insert into Name2Id values(?)',[('wxid_fixture_b68b0ccde5',),('wxid_fixture_4c90539d6a',)])
  c.execute('create table '+name+'(server_id integer,status integer,local_type integer,message_content text,source text,real_sender_id integer,create_time integer)')
  c.executemany('insert into '+name+' values(?,?,?,?,?,?,?)',[(sid,status,kind,text,'',sender,when) for sid,status,kind,text,sender,when in rows])
  @contextmanager
  def native(path):yield c,{'consistency':'committed'}
  module=types.SimpleNamespace(native=native,ACCOUNT='wxid_fixture_b68b0ccde5',decode=lambda s:s)
  j={'peer':peer,'action':'send_text','payload':{'text':expected},'result':{'sendClicks':1}}
  a={'peer':peer,'action':'send_text','text':expected,'beforeIds':list(before),'startedAt':1000.2,'clickScheduled':True}
  if alter:a.update(alter)
  try:
   with patch.dict(sys.modules,{'linux_tool':module}):return native_message(j,a)
  finally:c.close()
 def test_unique_receipt_retains_both_bodies_hashes_and_one_click(self):
  p=self.check([(123,2,1,'正文',1,1000)])
  self.assertEqual(p['state'],'accepted');self.assertEqual(p['serverId'],'123');self.assertEqual(p['sendClicks'],1)
  x=p['textComparison'];self.assertEqual(x['mode'],'single_terminal_lf_removed');self.assertEqual(x['expectedText'],'正文\n');self.assertEqual(x['actualText'],'正文');self.assertEqual(x['expectedSHA256'],hashlib.sha256('正文\n'.encode()).hexdigest());self.assertEqual(x['actualSHA256'],hashlib.sha256('正文'.encode()).hexdigest())
 def test_duplicate_or_mixed_exact_and_lf_candidates_do_not_pass(self):
  for second in ['正文','正文\n']:
   self.assertEqual(self.check([(123,2,1,'正文',1,1000),(124,2,1,second,1,1000)])['state'],'unknown')
 def test_status_sender_baseline_time_type_and_attempt_identity_remain_required(self):
  for row in [(123,1,1,'正文',1,1000),(123,2,49,'正文',1,1000),(123,2,1,'正文',2,1000),(123,2,1,'正文',1,998)]:
   self.assertEqual(self.check([row])['state'],'unknown')
  self.assertEqual(self.check([(123,2,1,'正文',1,1000)],before=['123'])['state'],'unknown')
  for alter in [{'peer':'other@chatroom'},{'action':'send_image'},{'text':'different'},{'clickScheduled':False}]:
   self.assertEqual(self.check([(123,2,1,'正文',1,1000)],alter=alter)['state'],'unknown')


if __name__=='__main__':unittest.main()
