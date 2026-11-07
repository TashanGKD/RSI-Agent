"""Explicit main-secretary attestation, never inference or native replay.

Reject wrong binding/source hashes, active worker, unaccepted notice and live
queued inputs; all accounts, sources, feedback and audit are isolated fixtures.
"""
import hashlib,json,os,tempfile,time,unittest
from pathlib import Path
from bridge.store import Store,_json,_hash
from bridge.private import write,read
from bridge.native_runner import THREAD
from bridge.worker import process_lock
try:
    from bridge.maintenance import cover_in_main
except ImportError:cover_in_main=None

class MainCoverageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cover_in_main,'explicit locked maintenance missing')
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name).resolve();self.root.chmod(0o700)
        write(self.root/'account.json',{'account_id':'bot','peer_id':'owner'})
        write(self.root/'native-context.json',{'thread_id':THREAD})
        self.s=Store(self.root/'state.sqlite','bot','owner',all_messages=True);self.addCleanup(self.s.close)
        for mid,text in [('one','progress?'),('two','voice progress?'),('business','pay invoice')]:
            kind=3 if mid=='two' else 1;obj={'text':text}
            self.s.ingest([{'message_id':mid,'from_user_id':'owner','message_type':1,'message_state':2,'item_list':[{'type':kind,{1:'text_item',3:'voice_item'}[kind]:obj}]}],'c')
        self.s.enqueue_text('combined progress notice','notice');o=self.s.claim_outbox();self.s.finish_outbox(o['id'],'accepted',{'api_accepted':True,'phone_delivery_verified':False,'client_id':o['client_id']})
        out=self.s.db.execute("select * from outbox where request_id='notice'").fetchone()
        self.audit=self.root/'audit.json';write(self.audit,{'main_thread_id':THREAD,'checked_at':time.time(),'queue_complete':True,'queue':[]})
        self.plan={'version':1,'operation_id':'fixture-cover','kind':'progress_inquiries_handled_in_main','binding_sha256':_hash(_json(['bot','owner'])),'main_thread_id':THREAD,'main_turn_id':'00000000-0000-4000-8000-0055502b98eb','actor':'main-secretary','attestation':'read_exact_inputs_in_existing_turn','audit_path':str(self.audit),'audit_sha256':hashlib.sha256(self.audit.read_bytes()).hexdigest(),'notice':{'request_id':'notice','payload_sha256':_hash(out['payload']),'receipt_sha256':_hash(out['receipt'])},'sources':[]}
        for mid in ['one','two']:
            row=self.s.db.execute('select body,body_hash from incoming where id=?',(mid,)).fetchone()
            text='progress?' if mid=='one' else 'voice progress?'
            self.plan['sources'].append({'message_id':mid,'body_sha256':row['body_hash'],'text_sha256':_hash(text),'classification':'explicit_status_inquiry'})
        d=self.root/'native-requests';d.mkdir(mode=0o700)
        self.journal=d/(_hash('one')+'.json');write(self.journal,{'version':3,'message_id':'one','client_id':'weixin-'+_hash('one'),'state':'queued','last_native_state':'submission_unknown','queue_id':'missing-q','prompt_hash':_hash('progress?')});self.before=self.journal.read_bytes()
    def apply(self):return cover_in_main(self.root,self.plan,execute=True)
    def test_marks_exact_sources_handled_without_native_completion_or_new_outbound(self):
        result=self.apply();self.assertEqual(result['state'],'handled_in_main');self.assertEqual(len(result['records']),2)
        self.assertFalse(result['records'][0]['native_execution_claimed']);self.assertEqual(result['records'][0]['native_submission']['last_native_state'],'submission_unknown')
        self.assertFalse(result['records'][0]['notice']['phone_delivery_verified'])
        self.assertEqual(self.journal.read_bytes(),self.before);self.assertEqual(self.s.snapshot()['outbox'],{'accepted':1})
        job=self.s.claim_job();self.assertEqual(job['id'],'business')
        self.assertTrue(self.apply()['already_applied']);self.assertEqual(self.journal.read_bytes(),self.before)
    def test_active_worker_lock_rejects_maintenance(self):
        with process_lock(self.root):
            with self.assertRaises(RuntimeError):self.apply()
        self.assertEqual(self.s.snapshot()['jobs'],{'pending':3})
    def test_binding_hash_source_hash_and_nonattested_input_reject_atomically(self):
        for mutate in [lambda p:p.update(binding_sha256='f'*64),lambda p:p['sources'][1].update(body_sha256='f'*64),lambda p:p.update(attestation='automatic_guess')]:
            original=json.loads(json.dumps(self.plan));mutate(self.plan)
            with self.assertRaises(ValueError):self.apply()
            self.assertEqual(self.s.snapshot()['jobs'],{'pending':3});self.plan=original
    def test_pending_unknown_or_changed_notice_does_not_create_another_send(self):
        for state in ['pending','unknown','failed']:
            self.s.db.execute('update outbox set status=?',(state,))
            with self.assertRaises(ValueError):self.apply()
        self.s.db.execute("update outbox set status='accepted',payload='{}'")
        with self.assertRaises(ValueError):self.apply()
        self.assertEqual(self.s.db.execute('select count(*) from outbox').fetchone()[0],1)
    def test_live_queue_or_existing_reply_prevents_coverage(self):
        write(self.audit,{'main_thread_id':THREAD,'checked_at':time.time(),'queue_complete':True,'queue':[{'id':'live','clientUserMessageId':'weixin-'+_hash('one')}]});self.plan['audit_sha256']=hashlib.sha256(self.audit.read_bytes()).hexdigest()
        with self.assertRaises(ValueError):self.apply()
        write(self.audit,{'main_thread_id':THREAD,'checked_at':time.time(),'queue_complete':True,'queue':[]});self.plan['audit_sha256']=hashlib.sha256(self.audit.read_bytes()).hexdigest()
        j=self.s.claim_job();self.s.complete_job(j['id'],'an independent reply')
        with self.assertRaises(ValueError):self.apply()
    def test_dry_run_does_not_touch_database_or_journal(self):
        before=(self.root/'state.sqlite').read_bytes()
        self.assertEqual(cover_in_main(self.root,self.plan)['state'],'dry_run')
        self.assertEqual((self.root/'state.sqlite').read_bytes(),before);self.assertEqual(self.journal.read_bytes(),self.before)
    def test_cli_defaults_only_help_or_dry_run(self):
        import subprocess,sys
        before=(self.root/'state.sqlite').read_bytes()
        r=subprocess.run([sys.executable,'-m','bridge.cli'],capture_output=True,text=True,timeout=3)
        self.assertEqual(r.returncode,0);self.assertIn('usage:',r.stdout)
        r=subprocess.run([sys.executable,'-m','bridge.cli','cover-in-main','--workspace',str(self.root)],capture_output=True,text=True,timeout=3)
        self.assertEqual(json.loads(r.stdout)['state'],'dry_run');self.assertEqual((self.root/'state.sqlite').read_bytes(),before)
