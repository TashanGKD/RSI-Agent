"""Threaded parent must never run Python callbacks between fork and exec.

Reject invalid budget, relative executable and pipe output before spawning.
All programs and outputs are isolated local fixtures; no phone/accounts.
"""
import ast,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
try:
    from bridge.child_exec import limited_argv,run_limited
except ImportError:limited_argv=run_limited=None

class ChildLaunchTests(unittest.TestCase):
    def test_production_call_sites_have_no_preexec_python_callback(self):
        for name in ['media.py','voice_text.py']:
            tree=ast.parse((Path(__file__).resolve().parents[1]/'bridge'/name).read_text())
            self.assertFalse(any(k.arg=='preexec_fn' for n in ast.walk(tree) if isinstance(n,ast.Call) for k in n.keywords),name)
    def test_invalid_budget_relative_command_and_unbounded_pipe_are_rejected(self):
        self.assertIsNotNone(run_limited,'bounded fresh-interpreter launcher missing')
        for limit in [0,-1,True,100*1024*1024+1]:
            with self.assertRaises(ValueError):limited_argv([sys.executable,'-c','pass'],limit)
        for argv in [['python','-c','pass'],[],[sys.executable,'\0']]:
            with self.assertRaises(ValueError):limited_argv(argv,1024)
        with self.assertRaises(ValueError):run_limited([sys.executable,'-c','pass'],1024,stdout=subprocess.PIPE,timeout=1)
    def test_active_parent_thread_and_literal_arguments_launch_without_deadlock(self):
        self.assertIsNotNone(run_limited)
        hold=threading.Lock();started=threading.Event();release=threading.Event()
        def background():
            with hold:started.set();release.wait(5)
        t=threading.Thread(target=background);t.start();self.assertTrue(started.wait(1))
        try:
            for _ in range(5):
                with tempfile.TemporaryFile() as out:
                    r=run_limited([sys.executable,'-I','-c','import sys,json;print(json.dumps(sys.argv[1:]))','a;echo BAD','$(whoami)',''],4096,stdout=out,timeout=2)
                    self.assertEqual(r.returncode,0);out.seek(0)
                    self.assertEqual(json.loads(out.read()),['a;echo BAD','$(whoami)',''])
            self.assertFalse(release.is_set())
        finally:release.set();t.join(1)
    def test_timeout_and_file_output_cap_apply_to_execed_process(self):
        self.assertIsNotNone(run_limited)
        with tempfile.TemporaryFile() as out:
            begin=time.monotonic()
            with self.assertRaises(subprocess.TimeoutExpired):run_limited([sys.executable,'-c','import time;time.sleep(10)'],4096,stdout=out,timeout=.2)
            self.assertLess(time.monotonic()-begin,2)
        with tempfile.TemporaryFile() as out:
            r=run_limited([sys.executable,'-c','import os;os.write(1,b"x"*65536);os.write(1,b"y")'],4096,stdout=out,timeout=2)
            self.assertNotEqual(r.returncode,0);self.assertLessEqual(out.tell(),4096)
    def test_helper_without_arguments_only_prints_help(self):
        self.assertIsNotNone(limited_argv)
        helper=Path(__file__).resolve().parents[1]/'bridge/child_exec.py'
        r=subprocess.run([sys.executable,'-I',str(helper)],capture_output=True,text=True,timeout=2)
        self.assertEqual(r.returncode,0);self.assertIn('Usage:',r.stdout)
