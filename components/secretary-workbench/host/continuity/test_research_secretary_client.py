import unittest
from unittest.mock import Mock
import runtime
import delivery_health as dh
import test_method_client_scope as ms

OWNER='00000000-0000-4000-8000-db73f74bf09a'

class ResearchSecretaryClient(unittest.TestCase):
    def setUp(self):
        ms.MethodClientScopeTests.setUp(self)
        self.allowed.add(OWNER)
    publish=ms.MethodClientScopeTests.publish
    read=ms.MethodClientScopeTests.read
    def item(self,**changes):
        value=ms.MethodClientScopeTests.item(self,client='research_secretary',
            employee='research-secretary',ownerThreadId=OWNER,
            requestIds=['isolated-research-materials-v1'],businessTitle='isolated metadata')
        value.update(changes)
        return value
    def test_exact_original_owner_and_stable_role_key(self):
        self.publish([self.item()])
        try:v=self.read()
        except ValueError as e:self.fail('authorized new role rejected: '+str(e))
        self.assertEqual(v['incidents'][0]['ownerThreadId'],OWNER)
    def test_parent_wrong_owner_or_wrong_employee_cannot_claim_new_role(self):
        for change in [{'ownerThreadId':'00000000-0000-4000-8000-af1651cef67a'},
                       {'ownerThreadId':ms.METHOD},{'employee':'science'},
                       {'employee':'research_secretary'},{'client':'research_unregistered'}]:
            self.publish([self.item(**change)])
            with self.assertRaises(ValueError):self.read()
    def test_resolution_still_requires_native_receipt(self):
        self.publish([self.item(nativeReceiptVerified=False)])
        with self.assertRaises(ValueError):self.read()
    def test_no_actual_business_does_not_manufacture_notice(self):
        self.publish([]);l=runtime.Ledger(':memory:');self.addCleanup(l.close);run=Mock()
        value=dh.Supervisor(self.root,{'id':'delivery-health-supervisor','threadId':ms.METHOD}).step(
            l,self.allowed,lambda _: {'status':'inProgress'},lambda _:[],lambda *_:None,run,'/inert',now=ms.NOW)
        self.assertTrue(value['sourceReady']);self.assertEqual(value['pending'],0)
        self.assertEqual(value['fixedClientOwners'].get('research_secretary'),OWNER)
        run.assert_not_called()
    def test_failure_retained_for_hr_without_interrupting_work(self):
        self.publish([self.item(status='blocked',nativeReceiptVerified=False,reasonCode='ISOLATED')])
        l=runtime.Ledger(':memory:');self.addCleanup(l.close);run=Mock()
        value=dh.Supervisor(self.root,{'id':'delivery-health-supervisor','threadId':ms.METHOD}).step(
            l,self.allowed,lambda _:{'status':'inProgress'},lambda _:[],lambda *_:None,run,'/inert',now=ms.NOW)
        self.assertTrue(value['sourceReady']);self.assertEqual(value['pending'],1)
        run.assert_not_called()

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
