import json,unittest,importlib.util,hashlib
from pathlib import Path
from test_app57_regression import parse,QUOTE

class ReviewedBoundaryTests(unittest.TestCase):
 def test_type1_claim_cannot_export_embedded_media_xml(self):
  raw=QUOTE.replace('先做隔离测试','&lt;msg&gt;&lt;img aeskey="INERT-CREDENTIAL"/&gt;&lt;/msg&gt;')
  r=parse(raw);self.assertNotIn('INERT-CREDENTIAL',json.dumps(r));self.assertFalse(r['appMessage']['quote']['textAvailable']);self.assertEqual(r['appMessage']['parseStatus'],'partial')
 def test_current_title_cannot_export_credential_like_fields(self):
  r=parse(QUOTE.replace('同意这个方案','aeskey=INERT-SECRET'))
  self.assertNotIn('INERT-SECRET',json.dumps(r));self.assertEqual(r['text'],'');self.assertEqual(r['appMessage']['parseStatus'],'failed')
 def test_claimed_identity_fields_cannot_carry_xml_or_credentials(self):
  raw=QUOTE.replace('original_sender','&lt;img aeskey="INERT-ID"/&gt;').replace('原发言者','access_token=INERT-NAME')
  r=parse(raw);self.assertNotIn('INERT-',json.dumps(r));self.assertIsNone(r['appMessage']['quote']['fromUser']);self.assertIsNone(r['appMessage']['quote']['displayName']);self.assertFalse(r['appMessage']['quote']['originalMessageVerified'])
 def test_literal_plaintext_keeps_newlines_punctuation_and_old_at(self):
  plain='@人事负责人 历史文字\nA < B，C > D [流泪]'
  r=parse(QUOTE.replace('先做隔离测试',plain.replace('<','&lt;').replace('>','&gt;')))
  self.assertEqual(r['text'],'同意这个方案\n引用：'+plain);self.assertTrue(r['appMessage']['quote']['textAvailable'])
 def test_current_reply_text_is_explicit_separate_from_quoted_text(self):
  r=parse(QUOTE.replace('先做隔离测试','@人事负责人 历史指令'))
  self.assertEqual(r['appMessage'].get('replyText'),'同意这个方案')
  self.assertEqual(r['appMessage']['quote']['text'],'@人事负责人 历史指令')
 def test_reply_only_consumer_contract_without_loading_listener(self):
  raw=QUOTE.replace('先做隔离测试','@人事负责人 历史指令')
  r=parse(raw)
  self.assertIn('@人事负责人',r['text'])
  self.assertNotIn('@人事负责人',r['appMessage']['replyText'])
  raw=raw.replace('同意这个方案','@人事负责人 当前请求')
  self.assertIn('@人事负责人',parse(raw)['appMessage']['replyText'])
