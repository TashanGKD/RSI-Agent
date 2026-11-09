import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from operations.service import unit
class ServiceTests(unittest.TestCase):
 def test_consumes_explicit_queue_only(self):
  v=unit();self.assertIn('operations.cli run --execute',v);self.assertIn('--seconds 3600',v);self.assertNotIn('poll.py',v);self.assertNotIn('codex exec',v);self.assertIn('UMask=0077',v);self.assertIn('Restart=always',v)
