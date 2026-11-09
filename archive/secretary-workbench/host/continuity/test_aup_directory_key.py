import unittest
import test_aup_client_scope as ac
from test_method_client_scope import OTHER, METHOD


class StableAupDirectoryKeyTests(unittest.TestCase):
 def setUp(self):
  ac.AupClientScopeTests.setUp(self)
 publish = ac.AupClientScopeTests.publish
 read = ac.AupClientScopeTests.read
 item = ac.AupClientScopeTests.item

 def test_stable_directory_key_and_previous_candidate_are_supported(self):
  for employee in ['aup-support', 'aup_support']:
   self.publish([self.item(employee=employee)])
   try:
    result = self.read()
   except ValueError as error:
    self.fail('fixed authorized directory key rejected: ' + str(error))
   self.assertEqual(result['incidents'][0]['employee'], employee)
   self.assertEqual(result['incidents'][0]['client'], 'aup_support')

 def test_three_wrong_identity_inputs_stay_rejected(self):
  for changes in [
   {'employee': 'aup-support', 'ownerThreadId': OTHER},
   {'employee': 'aup_support_other'},
   {'client': 'aup-support', 'employee': 'aup-support'},
   {'employee': 'aup-support', 'ownerThreadId': METHOD},
   {'employee': 'aup-support '},
   {'employee': 'AUP-support'},
  ]:
   self.publish([self.item(**changes)])
   with self.assertRaises(ValueError):
    self.read()

 def test_alias_does_not_bypass_native_receipt_or_duplicate_identity(self):
  self.publish([self.item(employee='aup-support', nativeReceiptVerified=False)])
  with self.assertRaises(ValueError):
   self.read()
  self.publish([self.item(employee='aup-support'), self.item(employee='aup_support')])
  with self.assertRaises(ValueError):
   self.read()

if __name__ == '__main__':
 unittest.main()

setUpModule=ac.setUpModule
tearDownModule=ac.tearDownModule
