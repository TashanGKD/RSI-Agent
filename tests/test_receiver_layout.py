import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from rsi_agent.config import ROOT


class ReceiverLayoutTests(unittest.TestCase):
    def run_copied(self, names):
        with tempfile.TemporaryDirectory(prefix='接收器 ') as folder:
            for name in names:
                shutil.copy(ROOT / 'receiver' / name, Path(folder) / name)
            return subprocess.run([sys.executable, '-B', str(Path(folder) / 'codex_worker.py'), '--help'],
                                  capture_output=True, text=True, encoding='utf-8', timeout=30,
                                  env=dict(os.environ, PYTHONIOENCODING='utf-8'))

    def test_copied_receiver_directory_runs_as_a_script(self):
        result = self.run_copied(['codex_worker.py', 'delivery_updates.py', 'desktop_requeue.py'])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_sibling_module_fails_at_startup(self):
        result = self.run_copied(['codex_worker.py'])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('delivery_updates', result.stderr)


class PowerShellSourceTests(unittest.TestCase):
    def test_scripts_read_the_same_in_windows_powershell_5(self):
        # Windows PowerShell 5.1 decodes BOM-less scripts with the ANSI code page.
        for path in ROOT.rglob('*.ps1'):
            data = path.read_bytes()
            self.assertTrue(data.isascii() or data.startswith(b'\xef\xbb\xbf'), path)

