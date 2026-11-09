import unittest
from send_tool_observer import readonly,project
class ToolObserverTests(unittest.TestCase):
 def test_mutating_operations_rejected(self):
  for op in ['submit','confirm','cancel','reconcile','preview']:
   with self.assertRaises(ValueError):readonly({'op':op},call=lambda r:self.fail('must not call transport'))
 def test_foreign_client_and_request_escape_refused(self):
  for r in [{'op':'list','client':'someone-else'},{'op':'get','client':'science','request_id':'../../auth','wait_seconds':0},{'op':'get','client':'science','request_id':'a','wait_seconds':20}]:
   with self.assertRaises(ValueError):readonly(r,call=lambda r:self.fail('must not call transport'))
 def test_secrets_and_preview_never_projected(self):
  x=project({'client':'science','request_id':'a','action':'send_text','payload':{'text':'hello'},'confirmation_token':'SECRET','preview':{'data':'IMAGE'},'result':{'rawXML':'private'}})
  self.assertNotIn('SECRET',str(x));self.assertNotIn('IMAGE',str(x));self.assertNotIn('private',str(x))
  self.assertIsNone(project({'client':'science','action':'save_attachment'}))
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
