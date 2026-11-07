import unittest
from native_source import mentions,validated_routes
class SourceTests(unittest.TestCase):
 def test_no_invented_native_mention(self):self.assertEqual(mentions('plain @吾愿'),[])
 def test_entities_rejected(self):
  with self.assertRaises(ValueError):mentions('<!DOCTYPE a><atuserlist>xxx</atuserlist>')
 def test_repeated_or_unsafe_identity_rejected(self):
  for s in ['<atuserlist>a</atuserlist><atuserlist>b</atuserlist>','<atuserlist>$(touch /tmp/x)</atuserlist>']:
   with self.assertRaises(ValueError):mentions(s)
 def test_native_cdata(self):self.assertEqual(mentions('<atuserlist><![CDATA[wxid_fixture_operator, wxid_fixture_4c90539d6a]]></atuserlist>'),['wxid_fixture_operator','wxid_fixture_4c90539d6a'])
 def test_binding_scope_and_duplicate_rejected(self):
  good={'id':'forum','account':'wxid_fixture_operator','peer':'21993263679@chatroom','since':1}
  for rows in [[{**good,'peer':'1@chatroom;DROP TABLE x'}],[good,good],[{**good,'account':'wxid_fixture_4c90539d6a'}]]:
   with self.assertRaises(ValueError):validated_routes(rows)
if __name__=='__main__':unittest.main()
