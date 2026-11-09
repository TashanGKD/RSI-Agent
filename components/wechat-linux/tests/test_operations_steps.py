import unittest,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.steps import validate_step,step_patch
class StepTests(unittest.TestCase):
 def test_outside_window(self):
  with self.assertRaises(ValueError):validate_step({'kind':'click','point':[-1,900]},[100,100,1000,800],['alias'])
 def test_arbitrary_shell_not_supported(self):
  with self.assertRaises(ValueError):validate_step({'kind':'shell','command':'rm -rf x'},[0,0,100,100],[])
 def test_cannot_inject_unfrozen_text(self):
  with self.assertRaises(ValueError):validate_step({'kind':'paste','point':[10,10],'text':'new unauthorized message'},[0,0,100,100],['alias'])
 def test_only_declared_payload_fields(self):
  with self.assertRaises(ValueError):validate_step({'kind':'paste','point':[10,10],'field':'password'},[0,0,100,100],['alias'])
 def test_no_enter_step(self):
  with self.assertRaises(ValueError):validate_step({'kind':'key','key':'Enter'},[0,0,100,100],[])
 def test_valid_click(self):self.assertEqual(validate_step({'kind':'click','point':[20,20]},[0,0,100,100],[])['point'],[20,20])
 def test_friend_submit_requires_a_confirmed_visible_point(self):
  with self.assertRaises(ValueError):validate_step({'kind':'commit_friend_request'},[0,0,100,100],[])
  self.assertEqual(validate_step({'kind':'commit_friend_request','point':[50,50]},[0,0,100,100],[])['kind'],'commit_friend_request')
