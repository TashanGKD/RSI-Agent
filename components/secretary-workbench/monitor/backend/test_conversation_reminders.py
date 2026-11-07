import copy,unittest
from conversation_reminders import project_pending,unique_threads

class ReminderTests(unittest.TestCase):
 def sample(self):
  return {'threadId':'t','observedAt':1793440000,'pending':1,'pendingEvidenceCount':3,'conversations':[{'account':'a','peer':'g','latestSourceId':'123','latestSourceTime':1793439999,'firstSourceTime':1793439900,'reminderCount':3}],'existingNotices':[],'events':[{'payload':'PRIVATE RAW MESSAGE'}]}
 def test_many_routes_one_role_one_read(self):
  self.assertEqual(unique_threads([{'threadId':'t'},{'threadId':'t'},{'threadId':'u'}]),['t','u'])
 def test_three_mentions_are_one_conversation(self):
  x=project_pending(self.sample(),'t',[{'id':'b','account':'a','peer':'g'}])
  self.assertEqual(x['pending'],1);self.assertEqual(x['pendingEvidenceCount'],3);self.assertNotIn('PRIVATE RAW MESSAGE',str(x))
 def test_foreign_thread_rejected(self):
  with self.assertRaises(ValueError):project_pending(self.sample(),'other',[{'id':'b','account':'a','peer':'g'}])
 def test_foreign_peer_rejected(self):
  with self.assertRaises(ValueError):project_pending(self.sample(),'t',[{'id':'b','account':'a','peer':'foreign'}])
 def test_duplicate_mirror_not_summed(self):
  raw=self.sample();raw['conversations']*=2;raw['pending']=2;raw['pendingEvidenceCount']=6
  with self.assertRaises(ValueError):project_pending(raw,'t',[{'id':'b','account':'a','peer':'g'}])
 def test_bad_units_and_counts_rejected(self):
  for change in ['time','count']:
   raw=self.sample()
   if change=='time':raw['conversations'][0]['latestSourceTime']*=1000
   else:raw['pending']=50
   with self.assertRaises(ValueError):project_pending(raw,'t',[{'id':'b','account':'a','peer':'g'}])
 def test_three_conversations_keep_three(self):
  raw=self.sample();raw['conversations']=[dict(raw['conversations'][0],peer=p,reminderCount=2) for p in ['g','h','i']];raw.update(pending=3,pendingEvidenceCount=6)
  x=project_pending(raw,'t',[{'id':p,'account':'a','peer':p} for p in ['g','h','i']]);self.assertEqual(len(x['conversations']),3)
 def test_empty_with_queued_notice_does_not_mean_read(self):
  raw=self.sample();raw.update(pending=0,pendingEvidenceCount=0,conversations=[],existingNotices=[{'id':'n','binding':'b','state':'queued','queue_id':'q','body':'PRIVATE FROZEN NOTICE'}])
  x=project_pending(raw,'t',[{'id':'b','account':'a','peer':'g'}]);self.assertEqual(x['pending'],0);self.assertEqual(len(x['existingNotices']),1);self.assertNotIn('PRIVATE FROZEN NOTICE',str(x));self.assertFalse(x['readingOrBusinessCompletionInferred'])

if __name__=='__main__':unittest.main()

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
