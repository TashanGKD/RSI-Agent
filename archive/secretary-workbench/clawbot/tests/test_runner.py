import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from bridge.runner import CodexRunner

class RunnerTests(unittest.TestCase):
    def test_command_is_tool_disabled_and_output_validated(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();os.chmod(p,0o700);policy=p/'POLICY.md';policy.write_text('Shared rules')
            calls=[]
            def run(argv,**kwargs):
                calls.append((argv,kwargs));Path(argv[argv.index('-o')+1]).write_text('已收到。');return SimpleNamespace(returncode=0)
            r=CodexRunner(p,executable=sys.executable,policy=policy,execute=run)
            self.assertEqual(r('hi',[]),'已收到。')
            argv,kw=calls[0];self.assertIn('--ephemeral',argv);self.assertIn('shell_tool',argv);self.assertEqual(kw['shell'],False)
            self.assertNotIn('hi',argv);self.assertIn('hi',kw['input'])
    def test_nonzero_exit_and_missing_reply_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d).resolve();os.chmod(p,0o700);policy=p/'POLICY.md';policy.write_text('rules')
            for code in (1,0):
                with self.assertRaises(RuntimeError):CodexRunner(p,executable=sys.executable,policy=policy,execute=lambda *a,**k:SimpleNamespace(returncode=code))('hi',[])

if __name__=='__main__':unittest.main()
