import unittest
import delivery_health as dh
import runtime
from unittest.mock import Mock
import test_method_client_scope as ms
METHOD,OTHER,NOW=ms.METHOD,ms.OTHER,ms.NOW

AUP='00000000-0000-4000-8000-336afbb3b1e5'

class AupClientScopeTests(unittest.TestCase):
 def setUp(self):
  ms.MethodClientScopeTests.setUp(self)
  self.allowed.add(AUP)
 publish=ms.MethodClientScopeTests.publish
 read=ms.MethodClientScopeTests.read
 def item(self,**changes):
  row=ms.MethodClientScopeTests.item(self,client='aup_support',employee='aup_support',ownerThreadId=AUP,requestIds=['synthetic-aup-existing-v1'],businessTitle='isolated fixture only')
  row.update(changes);return row
 def test_authorized_exact_v1_identity_accepted(self):
  row=self.item();self.assertEqual(len(row),13);self.publish([row])
  try:value=self.read()
  except ValueError as e:self.fail('new explicitly registered client rejected: '+str(e))
  self.assertEqual(value['incidents'][0]['ownerThreadId'],AUP)
 def test_cross_owner_or_employee_rejected(self):
  for changes in [{'ownerThreadId':OTHER},{'ownerThreadId':METHOD},{'employee':'secretary'},{'client':'aup_unregistered'}]:
   self.publish([self.item(**changes)])
   with self.assertRaises(ValueError):self.read()
 def test_resolved_still_needs_native_receipt(self):
  self.publish([self.item(nativeReceiptVerified=False)])
  with self.assertRaises(ValueError):self.read()
 def test_registration_alone_does_not_manufacture_delivery(self):
  self.publish([]);ledger=runtime.Ledger(':memory:');self.addCleanup(ledger.close);runner=Mock()
  status=dh.Supervisor(self.root,{'id':'delivery-health-supervisor','threadId':METHOD}).step(ledger,self.allowed,lambda _:{'status':'inProgress'},lambda _:[],lambda *_:None,runner,'/inert',now=NOW)
  self.assertTrue(status['sourceReady']);self.assertEqual(status['pending'],0);self.assertEqual(ledger.c.execute('select count(*) from batches').fetchone()[0],0);runner.assert_not_called()
 def test_failure_is_retained_while_hr_busy(self):
  self.publish([self.item(status='blocked',nativeReceiptVerified=False,reasonCode='INERT_FIXTURE')]);ledger=runtime.Ledger(':memory:');self.addCleanup(ledger.close);runner=Mock()
  status=dh.Supervisor(self.root,{'id':'delivery-health-supervisor','threadId':METHOD}).step(ledger,self.allowed,lambda _:{'status':'inProgress'},lambda _:[],lambda *_:None,runner,'/inert',now=NOW)
  self.assertTrue(status['sourceReady']);self.assertEqual(status['pending'],1);self.assertTrue(status['waitingForIdle']);runner.assert_not_called()
  self.assertEqual(status['fixedClientOwners'].get('aup_support'),AUP)

if __name__=='__main__':unittest.main()

# Portable synthetic installation for this test module only.
def setUpModule():
 import delivery_health as health
 from unittest.mock import patch
 global _fixture_patch
 _fixture_patch = patch.multiple(health, CLIENTS=set(['secretary','science','organoid_bp','forum_employee','employee_pilot','employee_method','aup_support','research_secretary']), METHOD_OWNER='00000000-0000-4000-8000-4e07f8267a19', AUP_OWNER='00000000-0000-4000-8000-336afbb3b1e5', RESEARCH_SECRETARY_OWNER='00000000-0000-4000-8000-db73f74bf09a')
 _fixture_patch.start()
def tearDownModule():
 _fixture_patch.stop()
