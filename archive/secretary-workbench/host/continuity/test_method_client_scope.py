"""Existing v1 wire contract; synthetic files and in-memory state only."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import delivery_health as dh
import runtime

METHOD = '00000000-0000-4000-8000-4e07f8267a19'
OTHER = '00000000-0000-4000-8000-4344f0fd9daa'
NOW = 1793599000


class MethodClientScopeTests(unittest.TestCase):
 def setUp(self):
  tmp = tempfile.TemporaryDirectory()
  self.addCleanup(tmp.cleanup)
  self.root = Path(tmp.name).resolve()
  self.folder = self.root / 'versions' / 'v1234567890'
  self.folder.mkdir(parents=True)
  (self.root / 'live.json').write_text(json.dumps({
   'revision': 'v1234567890', 'snapshotUrl': '/versions/v1234567890/snapshot.json'}))
  self.allowed = {METHOD, OTHER}

 def item(self, **changes):
  row = {'id': 'delivery-method-one', 'businessId': 'task-method-one',
   'employee': 'system', 'businessTitle': '本岗原消息', 'ownerThreadId': METHOD,
   'status': 'resolved', 'updatedAt': NOW - 1,
   'requestIds': ['fixture-50bd85a69a89b5e1'],
   'client': 'employee_method', 'reasonCode': 'native_accepted',
   'recoveryOwnerThreadId': None, 'nativeReceiptVerified': True,
   'evidenceRefs': ['work-method-original']}
  row.update(changes)
  return row

 def publish(self, rows):
  (self.folder / 'snapshot.json').write_text(json.dumps({'workOverview': {
   'deliveryHealth': {'version': 1, 'observedAt': NOW, 'incidents': rows,
    'coverage': {'complete': True}}}}))

 def read(self):
  return dh.read_projection(self.root, self.allowed, now=NOW)

 def test_current_thirteen_field_method_message_is_accepted(self):
  row = self.item()
  self.assertEqual(len(row), 13)
  self.publish([row])
  try:
   value = self.read()
  except ValueError as exc:
   self.fail('authorized existing v1 method message rejected: ' + str(exc))
  self.assertEqual(value['incidents'][0]['client'], 'employee_method')
  self.assertEqual(value['incidents'][0]['ownerThreadId'], METHOD)

 def test_method_cannot_be_assigned_to_another_registered_owner(self):
  self.publish([self.item(ownerThreadId=OTHER)])
  with self.assertRaises(ValueError):
   self.read()

 def test_method_cannot_be_attributed_to_another_employee(self):
  self.publish([self.item(employee='secretary')])
  with self.assertRaises(ValueError):
   self.read()

 def test_unknown_client_is_not_dynamically_adopted(self):
  self.publish([self.item(client='unapproved_method')])
  with self.assertRaises(ValueError):
   self.read()

 def test_method_still_requires_registered_owner(self):
  self.publish([self.item()])
  with self.assertRaises(ValueError):
   dh.read_projection(self.root, {OTHER}, now=NOW)

 def test_method_resolved_still_requires_native_receipt(self):
  self.publish([self.item(nativeReceiptVerified=False)])
  with self.assertRaises(ValueError):
   self.read()

 def test_same_original_client_request_identity_is_not_duplicated(self):
  self.publish([self.item(), self.item()])
  with self.assertRaises(ValueError):
   self.read()

 def test_existing_five_client_normalization_is_unchanged(self):
  for client in ['secretary', 'science', 'organoid_bp', 'forum_employee', 'employee_pilot']:
   row = self.item(client=client, employee='legacy', ownerThreadId=OTHER)
   self.publish([row])
   actual = self.read()['incidents'][0]
   self.assertEqual(actual['client'], client)
   self.assertEqual(actual['ownerThreadId'], OTHER)
   self.assertEqual(actual['requestIds'], row['requestIds'])

 def test_delivered_method_history_does_not_create_a_notice(self):
  self.publish([self.item()])
  ledger = runtime.Ledger(':memory:')
  self.addCleanup(ledger.close)
  runner = Mock()
  live = Mock(return_value={'status': 'completed'})
  supervisor = dh.Supervisor(self.root, {
   'id': 'delivery-health-supervisor', 'threadId': METHOD})
  state = supervisor.step(ledger, self.allowed, live, lambda _: [],
   lambda *_: None, runner, '/synthetic/no-execution', now=NOW)
  self.assertTrue(state['sourceReady'])
  self.assertEqual(state['pending'], 0)
  self.assertEqual(ledger.c.execute('select count(*) from batches').fetchone()[0], 0)
  runner.assert_not_called()

 def test_busy_method_failure_is_saved_without_interrupting(self):
  self.publish([self.item(status='blocked', nativeReceiptVerified=False,
    reasonCode='NO_CURRENT_RECEIPT')])
  ledger = runtime.Ledger(':memory:')
  self.addCleanup(ledger.close)
  runner = Mock()
  supervisor = dh.Supervisor(self.root, {
   'id': 'delivery-health-supervisor', 'threadId': METHOD})
  state = supervisor.step(ledger, self.allowed,
   lambda _: {'status': 'inProgress'}, lambda _: [], lambda *_: None,
   runner, '/synthetic/no-execution', now=NOW)
  self.assertTrue(state['sourceReady'])
  self.assertEqual(state['pending'], 1)
  self.assertTrue(state['waitingForIdle'])
  runner.assert_not_called()

 def test_status_reports_source_loaded_at_import(self):
  self.publish([])
  ledger = runtime.Ledger(':memory:')
  self.addCleanup(ledger.close)
  supervisor = dh.Supervisor(self.root, {
   'id': 'delivery-health-supervisor', 'threadId': METHOD})
  state = supervisor.step(ledger, self.allowed,
   lambda _: {'status': 'inProgress'}, lambda _: [], lambda *_: None,
   Mock(), '/synthetic/no-execution', now=NOW)
  expected = hashlib.sha256(Path(dh.__file__).read_bytes()).hexdigest()
  self.assertEqual(state.get('consumerSourceSHA256'), expected)
  self.assertEqual(state.get('fixedClientOwners', {}).get('employee_method'), METHOD)


if __name__ == '__main__':
 unittest.main()

# Portable synthetic installation for this test module only.
def setUpModule():
 import delivery_health as health
 from unittest.mock import patch
 global _fixture_patch
 _fixture_patch = patch.multiple(health, CLIENTS=set(['secretary','science','organoid_bp','forum_employee','employee_pilot','employee_method','aup_support','research_secretary']), METHOD_OWNER='00000000-0000-4000-8000-4e07f8267a19', AUP_OWNER='00000000-0000-4000-8000-336afbb3b1e5', RESEARCH_SECRETARY_OWNER='00000000-0000-4000-8000-db73f74bf09a')
 _fixture_patch.start()
def tearDownModule():
 _fixture_patch.stop()
