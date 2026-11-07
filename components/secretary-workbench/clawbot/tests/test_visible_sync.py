import hashlib,json,os,tempfile,unittest
from pathlib import Path
from bridge.store import Store
from bridge.worker import Worker

class VisibleSyncTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();r=Path(self.tmp.name).resolve();os.chmod(r,0o700);self.s=Store(r/'s.sqlite','bot','peer',all_messages=True)
 def tearDown(self):self.s.close();self.tmp.cleanup()
 def batch(self,text='done',job=None):return {'state':'scanned','after_turn_id':'new','turns':[{'turn_id':'new','item_ids':['f'],'reply':text,'job_id':job}]}
 def test_initialization_and_restart_do_not_replay(self):
  self.s.apply_visible_scan({'state':'initialized','after_turn_id':'old','turns':[]});self.assertEqual(self.s.visible_checkpoint(),'old');self.assertEqual(self.s.snapshot()['outbox'],{})
  self.s.apply_visible_scan(self.batch());self.s.apply_visible_scan(self.batch());self.assertEqual(self.s.snapshot()['outbox'],{'pending':1})
 def test_clawbot_reply_uses_same_original_outbox_id(self):
  self.s.ingest([{'message_id':'1','message_type':1,'message_state':2,'from_user_id':'peer','context_token':'ctx','item_list':[{'type':1,'text_item':{'text':'hello'}}]}],'c')
  j=self.s.claim_job();a=self.s.complete_job(j['id'],'done');self.s.apply_visible_scan(self.batch(job='1'));self.assertEqual(self.s.snapshot()['outbox'],{'pending':1});self.assertEqual(self.s.db.execute('select id from outbox').fetchone()[0],a['id'])
 def test_sync_before_job_completion_still_deduplicates(self):
  self.s.ingest([{'message_id':'1','message_type':1,'message_state':2,'from_user_id':'peer','item_list':[{'type':1,'text_item':{'text':'hello'}}]}],'c');j=self.s.claim_job();self.s.apply_visible_scan(self.batch(job='1'));self.s.complete_job(j['id'],'done');self.assertEqual(self.s.snapshot()['outbox'],{'pending':1})
 def test_transaction_rolls_back_cursor_and_all_enqueues(self):
  self.s.apply_visible_scan({'state':'initialized','after_turn_id':'old','turns':[]});b=self.batch();b['turns'].append({'turn_id':'bad','item_ids':[],'reply':'','job_id':None})
  with self.assertRaises(ValueError):self.s.apply_visible_scan(b)
  self.assertEqual(self.s.visible_checkpoint(),'old');self.assertEqual(self.s.snapshot()['outbox'],{})
 def test_changed_reply_is_not_new_message(self):
  self.s.apply_visible_scan(self.batch())
  with self.assertRaises(ValueError):self.s.apply_visible_scan(self.batch('changed'))
 def test_unknown_send_is_not_requeued_by_sync(self):
  self.s.apply_visible_scan(self.batch());o=self.s.claim_outbox();self.s.finish_outbox(o['id'],'unknown',{'reason':'network'});self.s.apply_visible_scan(self.batch());self.assertEqual(self.s.snapshot()['outbox'],{'unknown':1})
 def test_direct_send_requires_real_visible_assistant_source(self):
  self.s._set('context','ctx');self.s.enqueue_text('unseen','manual');sent=[]
  class API:
   def send_text(self,*a):sent.append(a);return {}
  class Native:
   native=True
   def outgoing_source(self,item):return None
  out=Worker(self.s,API(),Native()).flush_one();self.assertEqual(out['state'],'visible_source_missing');self.assertEqual(sent,[]);self.assertEqual(self.s.snapshot()['outbox'],{'failed':1})
 def test_visible_manual_final_and_automatic_sync_send_only_once(self):
  self.s._set('context','ctx');self.s.enqueue_text('done','manual');sent=[]
  class API:
   def send_text(self,*a):sent.append(a);return {}
  class Native:
   native=True
   def outgoing_source(self,item):return {'turn_id':'new','item_ids':['f']}
  Worker(self.s,API(),Native()).flush_one();self.s.apply_visible_scan(self.batch());self.assertEqual(len(sent),1);self.assertEqual(self.s.snapshot()['outbox'],{'accepted':1})

if __name__=='__main__':unittest.main()
