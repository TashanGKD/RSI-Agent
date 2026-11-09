"""Invariant: only named explicit callables execute; scheduling only requests review.
Breaking inputs first: shell-like executor name; traversal request ID; oversized JSON;
symlink state directory. All reject before notebook or callable writes.
"""
import tempfile, unittest, json, sys, subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from modules.notebook import NotebookService
try:
    from modules.scheduler import Scheduler
    from modules.executors import ExecutorRegistry
except ImportError:
    Scheduler = ExecutorRegistry = None

class SecretaryPort:
    def __init__(self): self.calls=0; self.jobs={}; self.fail=False; self.intents=[]
    def submit(self,message_id=None,request_id=None,*,intent='input'):
        self.calls+=1; self.intents.append(intent)
        if self.fail: raise RuntimeError('worker stopped')
        self.jobs.setdefault(request_id,{'id':request_id,'status':'queued'})
        return self.jobs[request_id]
    def get_job(self,key): return self.jobs[key]

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Scheduler,'scheduler missing'); self.assertIsNotNone(ExecutorRegistry,'executor missing')
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.ws=Path(self.tmp.name)
        self.src=self.ws/'source.json'; self.src.write_text('{"records":[]}')
        self.n=NotebookService(self.ws/'notebook.sqlite3',self.src,self.ws); self.sec=SecretaryPort()
        self.now=datetime(2026,10,22,15,59,tzinfo=timezone.utc); self.clock=lambda:self.now
        self.s=Scheduler(self.ws,self.n,self.sec,clock=self.clock); self.e=ExecutorRegistry(self.ws,self.n,clock=self.clock)
    def task(self,**extra): return self.n.create_task(dict({'title':'复查资料','state':'待办','planDate':'2026-10-22'},**extra))
    def test_three_unsafe_inputs_reject_before_side_effects(self):
        t=self.task(); calls=[]
        with self.assertRaises(ValueError): self.e.register('shell;rm -rf',lambda _:calls.append(1))
        self.e.register('local',lambda _:calls.append(1))
        for args in [('local',t['id'],'../escape',{}),('local',t['id'],'r1',{'text':'x'*65536}),('missing',t['id'],'r2',{})]:
            with self.assertRaises(ValueError): self.e.dispatch(*args)
        self.assertEqual(calls,[]); self.assertEqual(self.n.list_records(),[])
    def test_symlink_state_directory_rejected(self):
        outside=self.ws/'outside'; outside.mkdir(); other=self.ws/'other'; other.mkdir()
        for name,cls,args in [('scheduler',Scheduler,(self.n,self.sec)),('executors',ExecutorRegistry,(self.n,))]:
            (other/name).symlink_to(outside,target_is_directory=True)
            with self.assertRaises(ValueError): cls(other,*args)
        self.assertEqual(list(outside.iterdir()),[])
    def test_unknown_stale_and_failed_condition_never_trigger(self):
        self.task(condition='下次见泽锐'); self.assertEqual(self.s.due_checks(),[])
        self.s.tick(apply=True); self.assertEqual(self.sec.calls,0)
        self.s.register_condition('下次见泽锐',lambda t:{'met':True,'fresh':False,'receipt':'old'})
        self.assertEqual(self.s.due_checks(),[])
        self.s.register_condition('下次见泽锐',lambda t:(_ for _ in ()).throw(RuntimeError('source stopped')))
        r=self.s.tick(apply=True); self.assertTrue(r['gaps']); self.assertEqual(self.sec.calls,0)
    def test_beijing_calendar_day_is_not_24_hours(self):
        self.task(planDate='2026-10-23'); self.assertEqual(self.s.due_checks(),[])
        self.now+=timedelta(minutes=2); self.assertEqual(len(self.s.due_checks()),1)
    def test_repeat_tick_restart_one_record_one_job_no_state_change(self):
        t=self.task(reviewDate='2026-10-21'); self.assertEqual(len(self.s.tick()['pending']),1)
        self.assertEqual(self.n.list_records(),[])
        r=self.s.tick(apply=True); Scheduler(self.ws,self.n,self.sec,clock=self.clock).tick(apply=True)
        self.assertEqual(len(self.n.list_records()),1); self.assertEqual(self.sec.calls,1)
        self.assertEqual(self.sec.intents,['review'])
        record=self.n.list_records()[0]; self.assertEqual(record['actor']['kind'],'ai'); self.assertEqual(record['objectIds'],[t['id']])
        self.assertEqual(self.n.get_task(t['id'])['state'],'待办'); self.assertEqual(r['runs'][0]['status'],'submitted')
        text=self.n.list_records()[0]['text']; self.assertIn('unknown',text); self.assertIn('review',text)
    def test_failed_worker_retry_is_durable_bounded_and_deduplicated(self):
        self.task(); self.sec.fail=True; self.s.tick(apply=True)
        self.assertEqual(self.s.status()[0]['status'],'failed'); self.s.tick(apply=True); self.assertEqual(self.sec.calls,1)
        for _ in range(3): self.now+=timedelta(minutes=2); self.s.tick(apply=True)
        self.assertEqual(self.sec.calls,3); self.assertEqual(len(self.n.list_records()),1)
        self.assertEqual(self.s.status()[0]['attempts'],3)
    def test_explicit_condition_needs_fresh_receipt(self):
        self.task(condition='meeting',planDate=None)
        self.s.register_condition('meeting',lambda t:{'met':True,'fresh':True,'receipt':'fixture-confirmed'})
        self.assertEqual(len(self.s.due_checks()),1); self.s.tick(apply=True); self.assertEqual(self.sec.calls,1)
    def test_dispatch_receipt_not_assignee_never_changes_business_state(self):
        t=self.task(assignee='AI'); calls=[]; self.assertEqual(self.e.list_requests(),[])
        self.e.register('check',lambda req:(calls.append(req) or {'status':'completed','summary':'fixture checked','result':{'count':2}}))
        r=self.e.dispatch('check',t['id'],'exec-one',{'scope':'fixture'})
        again=self.e.dispatch('check',t['id'],'exec-one',{'scope':'fixture'})
        self.assertEqual(r,again); self.assertEqual(len(calls),1); self.assertEqual(calls[0]['requestId'],'exec-one')
        self.assertEqual(self.n.get_task(t['id'])['state'],'待办'); records=self.n.list_records()
        self.assertEqual(len(records),1); self.assertEqual(records[0]['processing'],'completed')
        self.assertIn('fixture checked',records[0]['receipts'][-1]['text'])
        with self.assertRaises(ValueError): self.e.dispatch('check',t['id'],'exec-one',{'scope':'other'})
    def test_actual_failures_and_promise_only_rejected(self):
        t=self.task(); self.e.register('broken',lambda _:(_ for _ in ()).throw(RuntimeError('executor stopped')))
        r=self.e.dispatch('broken',t['id'],'fail'); self.assertEqual(r['status'],'failed'); self.assertIn('executor stopped',r['error'])
        self.e.register('promise',lambda _:{'status':'completed'})
        self.assertEqual(self.e.dispatch('promise',t['id'],'promise')['status'],'failed')
        self.assertEqual(self.n.get_task(t['id'])['state'],'待办')
    def test_restart_returns_receipt_without_rerun(self):
        t=self.task(); calls=[]; self.e.register('check',lambda req:(calls.append(req) or {'status':'completed','summary':'saved'}))
        self.e.dispatch('check',t['id'],'persist'); fresh=ExecutorRegistry(self.ws,self.n,clock=self.clock)
        fresh.register('check',lambda req:calls.append(req)); self.assertEqual(fresh.dispatch('check',t['id'],'persist')['status'],'completed')
        self.assertEqual(len(calls),1)
    def test_later_review_date_remains_separate_from_already_due_plan(self):
        self.task(reviewDate='2026-10-24'); self.s.tick(apply=True)
        self.now+=timedelta(days=2); self.s.tick(apply=True)
        self.assertEqual(self.sec.calls,2)
        self.assertEqual(len(self.n.list_records()),2)
    def test_stopped_submitted_worker_and_recovered_scheduler_lease(self):
        self.task(); self.s.tick(apply=True)
        self.now+=timedelta(minutes=10); self.s.tick(apply=True)
        self.assertEqual(self.s.status()[0]['status'],'failed')
        self.assertIn('stopped',self.s.status()[0]['error'])
        self.now+=timedelta(minutes=2); self.s.tick(apply=True)
        self.assertEqual(len(self.n.list_records()),1)
        self.assertEqual(self.sec.calls,2)
    def test_crashed_executor_lease_is_unconfirmed_and_never_reexecutes(self):
        t=self.task(); calls=[]
        def crash(req):
            calls.append(req); raise SystemExit('process interrupted')
        self.e.register('crash',crash)
        with self.assertRaises(SystemExit): self.e.dispatch('crash',t['id'],'interrupted')
        self.now+=timedelta(minutes=10)
        fresh=ExecutorRegistry(self.ws,self.n,clock=self.clock); fresh.register('crash',crash)
        result=fresh.dispatch('crash',t['id'],'interrupted')
        self.assertEqual(result['status'],'unconfirmed'); self.assertEqual(len(calls),1)
        self.assertEqual(self.n.get_task(t['id'])['state'],'待办')
    def test_actual_secretary_port_consumes_one_review_without_state_change(self):
        from modules.secretary import SecretaryService
        import time
        t=self.task()
        service=SecretaryService(self.n,self.ws,model_runner=lambda context:{'summary':'日期到期；现有信源未确认更新，保留原状态','operations':[]})
        scheduler=Scheduler(self.ws,self.n,service,clock=self.clock)
        result=scheduler.tick(apply=True); jobid=result['runs'][0]['jobId']
        deadline=time.monotonic()+3
        while service.get_job(jobid)['status'] in ('queued','running') and time.monotonic()<deadline: time.sleep(.02)
        self.assertEqual(service.get_job(jobid)['status'],'completed')
        with self.assertRaises(ValueError): service.submit(self.n.list_records()[0]['id'],request_id='ordinary-input-reject')
        scheduler.tick(apply=True); self.assertEqual(scheduler.status()[0]['status'],'reviewed')
        self.assertEqual(len(self.n.list_records()),1); self.assertEqual(self.n.get_task(t['id'])['state'],'待办')
    def test_interrupted_scheduler_lease_recovers_without_duplicate_raw_record(self):
        self.task()
        class CrashedSecretary(SecretaryPort):
            def submit(self,**kwargs): raise SystemExit('interrupted')
        crashed=Scheduler(self.ws,self.n,CrashedSecretary(),clock=self.clock)
        with self.assertRaises(SystemExit): crashed.tick(apply=True)
        self.s.tick(apply=True); self.assertEqual(self.sec.calls,0)
        self.now+=timedelta(minutes=10); self.s.tick(apply=True)
        self.assertEqual(self.sec.calls,1); self.assertEqual(len(self.n.list_records()),1)
    def test_concurrent_ticks_use_one_lease_and_one_review_input(self):
        import threading
        self.task(); entered=threading.Event(); release=threading.Event()
        class BlockedSecretary(SecretaryPort):
            def submit(port,**kwargs):
                entered.set(); release.wait(2); return super().submit(**kwargs)
        port=BlockedSecretary(); first=Scheduler(self.ws,self.n,port,clock=self.clock)
        worker=threading.Thread(target=lambda:first.tick(apply=True)); worker.start()
        self.assertTrue(entered.wait(2))
        result=self.s.tick(apply=True); self.assertIn({'status':'tick_busy'},result['gaps'])
        release.set(); worker.join(2); self.assertFalse(worker.is_alive())
        self.assertEqual(port.calls,1); self.assertEqual(len(self.n.list_records()),1)
    def test_source_failure_receipt_cannot_be_treated_as_fresh_true(self):
        self.task(condition='meeting')
        self.s.register_condition('meeting',lambda t:{'met':True,'fresh':True,'receipt':'cached','status':'failed'})
        result=self.s.tick(apply=True)
        self.assertEqual(self.sec.calls,0); self.assertTrue(result['gaps'])
    def test_notebook_receipt_outage_preserves_scheduler_failure(self):
        self.task(); self.sec.fail=True
        notebook=self.n
        class FailedReceiptPort:
            def __getattr__(self,name): return getattr(notebook,name)
            def set_record_processing(self,*args,**kwargs): raise RuntimeError('receipt storage unavailable')
        scheduler=Scheduler(self.ws,FailedReceiptPort(),self.sec,clock=self.clock)
        result=scheduler.tick(apply=True)
        self.assertEqual(result['runs'][0]['status'],'failed')
        self.assertIn('receipt storage',result['runs'][0]['receiptError'])
    def test_cli_noargs_only_usage(self):
        for module in ('scheduler','executors'):
            r=subprocess.run([sys.executable,'-m','modules.'+module],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
            self.assertIn('usage:',r.stdout+r.stderr); self.assertNotIn('Traceback',r.stderr)
if __name__=='__main__': unittest.main()
