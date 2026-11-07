import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.driver import Policy,preview_context
from operations.contract import validate_job
class DriverValidation(unittest.TestCase):
 def setUp(self):self.p=Policy({'account':'wxid_fixture_operator','version':2,'clients':{'a':{'peers':['wxid_fixture_a'],'actions':['send_text']}}})
 def test_client_labels_are_attribution_not_target_tenants(self):self.p.check({'client':'a','peer':'wxid_fixture_other','action':'send_text'})
 def test_new_attribution_client(self):self.p.check({'client':'b','peer':'wxid_fixture_a','action':'send_text'})
 def test_action_syntax_still_validated(self):
  with self.assertRaises(ValueError):validate_job({'client':'a','request_id':'one','peer':'wxid_fixture_a','action':'shell','payload':{}})
 def test_confirmation_context_changes_with_target_or_text(self):
  a=preview_context('wxid_fixture_a','header','hello',None)
  self.assertNotEqual(a,preview_context('wxid_fixture_b','header','hello',None));self.assertNotEqual(a,preview_context('wxid_fixture_a','header','different',None))
 def test_forward_source_still_requires_valid_native_identity_syntax(self):
  with self.assertRaises(ValueError):validate_job({'client':'a','request_id':'one','peer':'wxid_fixture_a','action':'forward','payload':{'source_peer':'../../private','source_id':'1'}})
