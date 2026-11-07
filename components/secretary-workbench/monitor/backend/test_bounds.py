import unittest,tempfile
from pathlib import Path
from collect import safe_source,clean_text

class Bounds(unittest.TestCase):
    def test_secret_path(self):
        with self.assertRaises(ValueError):safe_source(Path('/home/operator/.codex/auth.json'))
    def test_restricted(self):
        with self.assertRaises(ValueError):safe_source(Path('/home/operator/Secretary/.restricted-archive/a.md'))
    def test_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.symlink_to('/etc/passwd')
            with self.assertRaises(ValueError):safe_source(p)
    def test_token_not_displayed(self):
        self.assertNotIn('sk-1234567890abcdefghijklmnop',clean_text('token sk-1234567890abcdefghijklmnop'))
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
