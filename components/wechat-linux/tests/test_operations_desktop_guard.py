import unittest,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.lease import publish,release
from desktop_control import ensure_operation_window_free
class DesktopGuardTests(unittest.TestCase):
 def test_active_operations_block_mutating_desktop_but_not_view(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td).resolve();publish(root)
   with self.assertRaises(ValueError):ensure_operation_window_free('compose',root)
   ensure_operation_window_free('view',root);release(root);ensure_operation_window_free('compose',root)
 def test_dead_desktop_session_does_not_block_queued_operations(self):
  from operations.lease import desktop_busy
  now=100;x={'expiresAt':200,'mode':'compose','processes':[{'pid':11,'birth':'saved'}]}
  self.assertFalse(desktop_busy(x,now,process_birth=lambda pid:None))
  self.assertFalse(desktop_busy(x,now,process_birth=lambda pid:'other-process'))
  self.assertTrue(desktop_busy(x,now,process_birth=lambda pid:'saved'))
  self.assertFalse(desktop_busy(dict(x,mode='view'),now,process_birth=lambda pid:'saved'))
 def test_unknown_legacy_process_identity_is_not_assumed_dead(self):
  from operations.lease import desktop_busy
  self.assertTrue(desktop_busy({'mode':'compose','expiresAt':200},100,process_birth=lambda pid:None))
