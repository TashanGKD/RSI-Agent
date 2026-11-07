import copy
import hashlib
import unittest

from delivery_obligations import build, validate

OWNER = '00000000-0000-4000-8000-4344f0fd9daa'
RID = 'secretary-fixture-1772498e-20260101'
HASH = hashlib.sha256(b'approved draft').hexdigest()

def claim(**changes):
    return dict(dict(employee='secretary', client='secretary', ownerThreadId=OWNER,
                     businessKey='business-a', requestId=RID, componentCount=1,
                     kind='prepared', positive=True, peer='private-target',
                     action='send_text', contentHash=HASH, sourceRef=None), **changes)

def job(**changes):
    return dict(dict(client='secretary', request_id=RID, peer='private-target',
                     action='send_text', state='failed', noSend=True, contentHash=HASH), **changes)

def accepted(**changes):
    return job(state='succeeded', noSend=False, serverId='123', nativeReceiptVerified=True,
               nativeProof={'kind':'text_exact_sha256','peer':'private-target','serverId':'123',
                            'senderId':'sender','nativeStatus':2,'uniqueCandidateCount':1,
                            'nativeCreateTime':100,'evidence':'native-sender-status-and-operation-semantics',
                            'expectedSHA256':HASH,'actualSHA256':HASH}, **changes)

class ObligationsTests(unittest.TestCase):
    def project(self, claims, exact=None, jobs=()):
        return build(claims, exact or {}, jobs, [{'id':'secretary','threadId':OWNER}], 200)

    def test_frozen_positive_and_not_found_both_required(self):
        missing = {('secretary', RID): {'state':'not_found'}}
        self.assertEqual(self.project([claim()], missing)['rows'][0]['stage'], 'committed_not_admitted')
        for facts, results in [([claim(positive=False)], missing), ([claim()], {}), ([], missing)]:
            self.assertEqual(self.project(facts, results)['rows'], [])

    def test_terminal_no_send_and_scope_deduplication(self):
        original = job(action='send_image')
        claims = [claim(kind='failed', action='send_image')]*2
        exact = {('secretary', RID): original}
        result = self.project(claims, exact, [accepted(request_id=RID+'-text')])
        self.assertEqual(len(result['rows']), 1)
        self.assertEqual(result['rows'][0]['stage'], 'terminal_no_send')
        original['noSend'] = False
        self.assertEqual(self.project(claims, exact)['rows'], [])

    def test_late_receipt_or_same_component_successor_removes_only_matching_row(self):
        exact = {('secretary', RID):job()}
        facts = [claim(kind='failed')]
        for retry in [accepted(), accepted(request_id=RID+'-r1')]:
            self.assertFalse(self.project(facts, exact, [retry])['rows'])
        other = accepted(request_id=RID+'-other')
        self.assertTrue(self.project(facts, exact, [other])['rows'])
        conflicting = accepted(request_id=RID+'-r1', scopeOwnerThreadId='wrong')
        self.assertTrue(self.project(facts, exact, [conflicting])['rows'])

    def test_idless_current_preparation_and_separate_authority_wait(self):
        rows = self.project([claim(requestId=None, componentCount=3), claim(
            businessKey='authority-a', requestId=None, kind='authority', componentCount=4)])['rows']
        self.assertEqual(sorted(r['componentCount'] for r in rows),[3,4]);self.assertTrue(all(r['stage']=='committed_not_admitted' for r in rows))

    def test_invalid_identity_shape_and_private_fields_refused(self):
        self.assertFalse(self.project([claim(requestId=None, ownerThreadId='wrong')])['rows'])
        self.assertFalse(self.project([claim(requestId=None, employee='other')])['rows'])
        out = self.project([claim(requestId=None)])
        for delta in [{'body':'private'}, {'sourceRef':'/Users/private'},
                      {'componentCount':True}, {'businessKey':'target@chatroom'}]:
            tampered=copy.deepcopy(out)
            tampered['rows'][0].update(delta)
            with self.assertRaises(ValueError):
                validate(tampered, {'secretary':OWNER}, {})

    def test_cloud_keeps_existing_work_fields_and_strips_local_obligations(self):
        from online_sync import make_projection
        source={'mode':{'id':'mode','path':'mode','text':'mode'}}
        old={'version':1,'readOnly':True,'modes':{'sourceId':'mode'},'employees':[{'id':'secretary','threadId':OWNER}]}
        snap={'tasks':[],'warnings':[],'workOverview':dict(old,deliveryObligations=self.project([claim(requestId=None)]))}
        published,_=make_projection(snap,source)
        self.assertEqual(published['workOverview'],old)
        self.assertIn('deliveryObligations',snap['workOverview'])

def setUpModule():
 from unittest.mock import patch
 import contextlib,collect,send_tool_observer,delivery_obligations,employee_profiles,account_contract,model_accounts
 global _portable_patches
 _portable_patches=contextlib.ExitStack()
 clients={'secretary':'secretary','science':'science','organoid_bp':'organoid','forum_employee':'forum','employee_pilot':'employee-pilot','employee_method':'system','aup_support':'aup-support','research_secretary':'research-secretary'}
 ids={'secretary':'00000000-0000-4000-8000-4344f0fd9daa','science':'00000000-0000-4000-8000-37b7cd446cba','organoid':'00000000-0000-4000-8000-f709f264f942'}
 emails=tuple('fixture'+str(i)+'@example.invalid' for i in range(3))
 for mod,key,value in [(send_tool_observer,'CLIENTS',clients),(collect,'IDS',ids),(delivery_obligations,'CLIENTS',clients),(delivery_obligations,'OWNERS',ids),(employee_profiles,'IDS',ids),(account_contract,'EMAILS',emails),(model_accounts,'EMAILS',emails)]:
  _portable_patches.enter_context(patch.object(mod,key,value))
def tearDownModule():
 _portable_patches.close()
