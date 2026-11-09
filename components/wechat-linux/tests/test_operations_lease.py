import unittest,tempfile,os,json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.lease import active,publish,release
class LeaseTests(unittest.TestCase):
 def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name).resolve()
 def tearDown(self):self.t.cleanup()
 def test_live_and_release(self):publish(self.root);self.assertTrue(active(self.root));release(self.root);self.assertFalse(active(self.root))
 def test_stale_not_active(self):
  p=self.root/'display-lease.json';p.write_text(json.dumps({'pid':999999999,'birth':'x','expiresAt':time.time()+300}));p.chmod(0o600);self.assertFalse(active(self.root))
 def test_symlink_refused(self):
  (self.root/'display-lease.json').symlink_to('/etc/passwd')
  with self.assertRaises(ValueError):active(self.root)
 def test_kernel_guard_blocks_after_heartbeat_expiry_even_without_notice(self):
  import fcntl
  fd=os.open(self.root/'display-guard.lock',os.O_CREAT|os.O_RDWR,0o600)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   self.assertTrue(active(self.root))
  finally:os.close(fd)
  self.assertFalse(active(self.root))
