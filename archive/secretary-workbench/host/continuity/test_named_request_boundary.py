import unittest
import native_source as s

class NamedRequestBoundaryTests(unittest.TestCase):
 def setUp(self):
  self.aliases=['\u4ed6\u5c71\u79d8\u4e66','\u7c7b\u5668\u5b98BP','\u4eba\u4e8b\u8d1f\u8d23\u4eba']
 def test_direct_polite_address_after_exact_alias_is_recognized(self):
  for phrase in ['\u8bf7\u4f60','\u8bf7\u60a8','\u9ebb\u70e6\u4f60','\u9ebb\u70e6\u60a8']:
   for name in self.aliases:
    self.assertEqual(s.addressed_names('@'+name+phrase+'\u770b\u770b',self.aliases),[name])
 def test_unknown_extended_names_and_quoted_old_tags_rejected(self):
  for body in [
   '@'+self.aliases[0]+'\u52a9\u7406\u8bf7\u4f60\u770b',
   '@'+self.aliases[1]+'\u7814\u7a76\u5458\u8bf7\u4f60\u770b',
   '\u8f6c\u53d1\uff1a@'+self.aliases[0]+'\u8bf7\u4f60\u770b',
   '\u201c@'+self.aliases[0]+'\u8bf7\u4f60\u770b\u201d',
   '@unknown\u8bf7\u4f60\u770b',
   '@'+self.aliases[1]+'extra please look',
  ]:
   self.assertEqual(s.addressed_names(body,self.aliases),[])
 def test_multiple_leading_known_names_stay_ambiguous(self):
  body='@'+self.aliases[0]+' @'+self.aliases[1]+'\u8bf7\u4f60\u770b'
  self.assertEqual(s.addressed_names(body,self.aliases),self.aliases[:2])
 def test_quoted_current_text_only_not_embedded_old_name(self):
  body='<msg><appmsg><type>57</type><title>ok</title><refermsg><content>@'+self.aliases[0]+'\u8bf7\u4f60\u770b</content></refermsg></appmsg></msg>'
  self.assertEqual(s.addressed_names(s.current_quote_text(body),self.aliases),[])

if __name__=='__main__':
 unittest.main()
