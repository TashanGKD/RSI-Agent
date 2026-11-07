import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.proof import matches,friend
class ProofTests(unittest.TestCase):
 def test_text_whitespace_preserved(self):
  j={'action':'send_text','payload':{'text':'  中文\n尾巴  '}}
  self.assertTrue(matches(j,1,'  中文\n尾巴  ',''));self.assertFalse(matches(j,1,'中文\n尾巴',''))
 def test_quote_exact_original_server(self):
  j={'action':'reply','payload':{'text':'回复','source_id':'123'}}
  self.assertTrue(matches(j,49,'<msg><appmsg><type>57</type><title>回复</title><refermsg><svrid>123</svrid></refermsg></appmsg></msg>',''))
  self.assertFalse(matches(j,49,'<msg><appmsg><type>57</type><title>回复</title><refermsg><svrid>124</svrid></refermsg></appmsg></msg>',''))
 def test_plain_at_is_not_mention(self):
  j={'action':'mention','payload':{'text':'@我 测试','members':['wxid_fixture_1987fcaa9f']}}
  self.assertFalse(matches(j,1,'@我 测试',''))
  self.assertTrue(matches(j,1,'@我 测试','<msgsource><atuserlist>wxid_fixture_1987fcaa9f</atuserlist></msgsource>'))
 def test_forward_text_exact(self):
  j={'action':'forward','payload':{},'nativeSource':{'kind':1,'text':'原文'}}
  self.assertTrue(matches(j,1,'原文',''));self.assertFalse(matches(j,1,'另一个',''))
 def test_friend_is_not_just_contact_row(self):
  self.assertFalse(friend({'username':'x','flag':4,'local_type':3,'delete_flag':0}))
  self.assertTrue(friend({'username':'x','flag':3,'local_type':1,'delete_flag':0}))
 def test_unsafe_xml_refused(self):
  self.assertFalse(matches({'action':'reply','payload':{'text':'x','source_id':'1'}},49,'<!DOCTYPE x [<!ENTITY a "x">]><msg>&a;</msg>',''))
