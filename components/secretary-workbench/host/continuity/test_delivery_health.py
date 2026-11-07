"""Synthetic projection + original in-memory ledger; never sends WeChat or uses live state."""
import datetime, json, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import runtime
try:
 import delivery_health as dh
except ModuleNotFoundError:
 dh = None

OWNER='00000000-0000-4000-8000-4344f0fd9daa'
ROOT='00000000-0000-4000-8000-4e07f8267a19'
NOW=1793522000

class DeliveryHealthTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.base=Path(self.tmp.name).resolve();(self.base/'versions/v1234567890').mkdir(parents=True)
  self.snapshot=self.base/'versions/v1234567890/snapshot.json'
  self.allowed={OWNER};self.binding={'id':'delivery-health-supervisor','threadId':ROOT,'historyThreadId':ROOT,'cwd':'/home/operator/softmatter'}
  self.ledger=runtime.Ledger(':memory:');self.addCleanup(self.ledger.close)
  self.live=Mock(return_value={'status':'completed'})
  self.queue=Mock(return_value=[]);self.find=Mock(return_value=None)
  self.runner=Mock(return_value=SimpleNamespace(returncode=0,stdout='Queued message 00000000-0000-4000-8000-479c4f1eb72a for thread '+ROOT+'.\n'))
 def require(self):
  self.assertIsNotNone(dh,'Existing service has no delivery-health supervision consumer')
 def incident(self,**kw):
  v={'id':'delivery-task-one','businessId':'task-one','employee':'secretary','businessTitle':'一份待交结果','ownerThreadId':OWNER,'status':'blocked','updatedAt':NOW-1,'requestIds':['job-one'],'client':'secretary','reasonCode':'CHAT_POPOUT_NOT_OPENED','recoveryOwnerThreadId':None,'nativeReceiptVerified':False,'evidenceRefs':['work-one']};v.update(kw);return v
 def publish(self,incidents=None,**kw):
  p={'version':1,'observedAt':NOW,'incidents':incidents if incidents is not None else [self.incident()],'coverage':{'complete':True}};p.update(kw)
  self.snapshot.write_text(json.dumps({'workOverview':{'deliveryHealth':p}}))
  (self.base/'live.json').write_text(json.dumps({'revision':'v1234567890','snapshotUrl':'/versions/v1234567890/snapshot.json'}))
 def step(self,supervisor=None,now=NOW):
  self.require();s=supervisor or dh.Supervisor(self.base,self.binding)
  return s.step(self.ledger,self.allowed,self.live,self.queue,self.find,self.runner,'/synthetic/official-cli',now=now)
 def test_reject_traversal_snapshot_path(self):
  self.require();(self.base/'live.json').write_text(json.dumps({'snapshotUrl':'/versions/../../secret/snapshot.json'}))
  with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_reject_symlink_snapshot(self):
  self.require();self.publish();p=self.base/'outside.json';p.write_bytes(self.snapshot.read_bytes());self.snapshot.unlink();self.snapshot.symlink_to(p)
  with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_larger_valid_snapshot_can_be_read_and_still_has_a_finite_budget(self):
  self.publish()
  with self.snapshot.open('ab') as f:f.write(b' ' * (17 * 1024 * 1024))
  projection=dh.read_projection(self.base,self.allowed,now=NOW)
  self.assertEqual(projection['incidents'][0]['requestIds'],['job-one'])
  with self.snapshot.open('r+b') as f:f.truncate(24 * 1024 * 1024 + 1)
  with self.assertRaisesRegex(ValueError,'projection size/type'):
   dh.read_projection(self.base,self.allowed,now=NOW)
 def test_reject_unregistered_owner(self):
  self.require();self.publish([self.incident(ownerThreadId='00000000-0000-4000-8000-2f402daec245')])
  with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_reject_resolved_without_native_receipt(self):
  self.require();self.publish([self.incident(status='resolved',nativeReceiptVerified=False)])
  with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_reject_stale_and_future_projection(self):
  self.require()
  for at in [NOW-1201,NOW+61]:
   self.publish(observedAt=at)
   with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_reject_invalid_original_request_id(self):
  self.require();self.publish([self.incident(requestIds=['$(touch /tmp/never)'])])
  with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_reject_nonfinite_evidence_time(self):
  self.require();self.publish([self.incident(updatedAt=float('nan'))])
  with self.assertRaises(ValueError):dh.read_projection(self.base,self.allowed,now=NOW)
 def test_busy_retains_failure_without_queue_or_fake_wechat_event(self):
  self.publish();self.live.return_value={'status':'inProgress'}
  r=self.step();self.assertEqual(r['pending'],1);self.runner.assert_not_called()
  self.assertEqual(self.ledger.c.execute('select count(*) from events').fetchone()[0],0)
  self.assertEqual(self.ledger.c.execute('select count(*) from batches').fetchone()[0],0)
 def test_existing_input_queue_is_not_overtaken(self):
  self.publish();self.queue.return_value=[{'id':'earlier-real-request'}]
  r=self.step();self.assertTrue(r['waitingForExistingQueue']);self.runner.assert_not_called()
 def test_idle_queues_once_using_original_cli_and_original_batch_store(self):
  self.publish();self.step();self.runner.assert_called_once()
  args=self.runner.call_args.args[0];self.assertEqual(args[:4],['/synthetic/official-cli','queue','--thread',ROOT]);self.assertNotIn('--resume',args)
  row=self.ledger.c.execute('select * from batches').fetchone();self.assertIsNotNone(row);self.assertEqual(row['binding'],'delivery-health-supervisor')
  self.assertIn('监控资料',row['body']);self.assertNotIn('原生@事件',row['body'])
  self.find.return_value={'where':'queue','id':'original-queue'};self.step();self.runner.assert_called_once()
 def test_same_failure_new_sample_time_does_not_repeat_after_delivery(self):
  self.publish();self.step();self.find.return_value={'where':'history','id':'original-native-item','turnId':'original-turn'};self.step()
  self.publish(observedAt=NOW+2);self.step(now=NOW+2);self.runner.assert_called_once()
 def test_repair_assignment_does_not_resolve_delivery(self):
  self.publish([self.incident(recoveryOwnerThreadId='00000000-0000-4000-8000-7cd0d4e0445a')]);self.live.return_value={'status':'inProgress'}
  r=self.step();self.assertEqual(r['pending'],1)
 def test_native_delivery_before_idle_suppresses_stale_unsent_alert(self):
  self.publish();self.live.return_value={'status':'inProgress'};self.step()
  self.publish([self.incident(status='resolved',nativeReceiptVerified=True,requestIds=['job-one','job-recovery'])]);self.live.return_value={'status':'completed'}
  r=self.step();self.assertEqual(r['pending'],0);self.runner.assert_not_called()
 def test_partial_delivery_keeps_other_component(self):
  self.publish([self.incident(status='resolved',nativeReceiptVerified=True),self.incident(id='delivery-image',requestIds=['image-one'],status='blocked')]);self.live.return_value={'status':'inProgress'}
  self.assertEqual(self.step()['pending'],1)
 def test_unknown_is_not_sent_or_automatically_retried(self):
  self.publish([self.incident(status='unknown',reasonCode='UNKNOWN')]);self.live.return_value={'status':'inProgress'}
  self.assertEqual(self.step()['pending'],1);self.runner.assert_not_called()
 def test_cancelled_business_is_not_claimed_delivered_and_not_alerted(self):
  self.publish([self.incident(status='not_required')]);self.assertEqual(self.step()['pending'],0);self.runner.assert_not_called()
 def test_missing_incident_never_erases_known_unresolved_failure(self):
  self.publish();self.live.return_value={'status':'inProgress'};s=None;self.step()
  self.publish([]);self.assertEqual(self.step()['pending'],1)
 def test_transport_unknown_never_resubmits_after_restart(self):
  self.publish();self.runner.side_effect=TimeoutError('synthetic timeout')
  self.step();self.runner.side_effect=None
  self.step();self.runner.assert_called_once()
  self.assertEqual(self.ledger.c.execute('select state from batches').fetchone()[0],'unknown')
 def test_pending_survives_consumer_recreation(self):
  self.publish();self.live.return_value={'status':'inProgress'};self.step()
  self.live.return_value={'status':'completed'};self.step();self.runner.assert_called_once()
 def test_never_submitted_notice_is_superseded_if_delivery_completes_after_crash(self):
  self.require();self.publish()
  original=self.ledger.patch
  def crash(ident,**kw):
   if kw.get('state')=='submitting':raise RuntimeError('synthetic pre-submit crash')
   return original(ident,**kw)
  with patch.object(self.ledger,'patch',side_effect=crash):
   with self.assertRaisesRegex(RuntimeError,'synthetic pre-submit crash'):self.step()
  self.runner.assert_not_called()
  self.publish([self.incident(status='resolved',nativeReceiptVerified=True)])
  self.step();self.runner.assert_not_called()
  self.assertEqual(self.ledger.c.execute('select state from batches').fetchone()[0],'superseded')
 def test_credentials_are_not_forwarded_with_title(self):
  self.publish([self.incident(businessTitle='password: never-forward-this-secret')]);self.step()
  body=self.runner.call_args.args[0][-1];self.assertNotIn('never-forward-this-secret',body)
 def test_schema_missing_is_not_reported_healthy(self):
  self.require();self.snapshot.write_text('{}');(self.base/'live.json').write_text(json.dumps({'snapshotUrl':'/versions/v1234567890/snapshot.json'}))
  r=self.step();self.assertFalse(r['sourceReady']);self.runner.assert_not_called()
 def test_bounded_source_gaps_are_not_claimed_complete(self):
  self.require();self.publish(coverage={'bounded':True,'gaps':['list capped at 100']})
  self.assertTrue(dh.read_projection(self.base,self.allowed,now=NOW)['coveragePartial'])
 def test_original_service_cycle_invokes_health_without_another_loop(self):
  self.require()
  from test_runtime import binding
  root=self.base/'isolated-runtime';root.mkdir();config=root/'registry.json';config.write_text(json.dumps({'ownerThread':ROOT}))
  fake=Mock();fake.step.return_value={'sourceReady':True,'pending':1}
  with patch.object(runtime,'ROOT',root),patch('delivery_health.Supervisor',return_value=fake),patch('runtime.start_source',return_value=SimpleNamespace(stdout=None)),patch('runtime.stop_source'),patch('runtime.select.select',return_value=([],[],[])),patch('runtime.registry',return_value=[binding()]),patch('runtime.dispatch_role',return_value={}),patch('runtime.atomic',side_effect=RuntimeError('synthetic cycle complete')):
   with self.assertRaisesRegex(RuntimeError,'synthetic cycle complete'):runtime.run([binding()],config)
  fake.step.assert_called_once()

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
