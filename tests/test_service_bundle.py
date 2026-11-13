import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rsi_agent import __main__ as cli
from rsi_agent.config import ROOT
from rsi_agent.service_bundle import stage


class ServiceBundleTests(unittest.TestCase):
    def test_stage_is_offline_and_records_exact_reviewed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'bundle'
            with patch('rsi_agent.__main__.load') as load, patch('subprocess.run') as run:
                with contextlib.redirect_stdout(io.StringIO()) as stdout:
                    self.assertEqual(cli.main(['services', 'stage', '--release', '/opt/rsi/releases/test',
                                               '--output', str(output)]), 0)
                load.assert_not_called()
                run.assert_not_called()
            plan = json.loads(stdout.getvalue())
            self.assertFalse(plan['activated'])
            self.assertEqual(len(plan['unit_sha256']), 6)
            self.assertEqual(plan, json.loads((output / 'plan.json').read_text()))
            for name, digest in plan['unit_sha256'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), digest)
            self.assertIn('/opt/rsi/releases/test/deploy/wechat-gui/session.sh',
                          (output / 'wechat-gui-desktop.service').read_text())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / 'review'
            marker.write_text('keep')
            with self.assertRaises(ValueError):
                stage('/opt/rsi/releases/test', folder)
            self.assertEqual(marker.read_text(), 'keep')
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_unsafe_or_root_release_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'bundle'
            for release in ('relative', '/', '/.', '/opt/../tmp', '/opt/$HOME', '/opt/%u', '/opt/test\n'):
                with self.subTest(release=release), self.assertRaises(ValueError):
                    stage(release, output)
                self.assertFalse(output.exists())


@unittest.skipUnless(sys.platform == 'linux', 'requires real Linux X/VNC and systemd tools')
class LinuxDesktopBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('prepare_runtime', ROOT / 'deploy/wechat-gui/prepare_runtime.py')
        cls.runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runtime)

    def test_existing_vnc_preserves_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            authority = root / 'Xauthority'
            authority.write_text('existing-private-fixture')
            authority.chmod(0o600)
            with socket.socket(socket.AF_UNIX) as existing:
                existing.bind(str(root / 'vnc.sock'))
                with self.assertRaisesRegex(ValueError, 'Existing VNC socket'):
                    self.runtime.prepare(root, ':193')
            self.assertEqual(authority.read_text(), 'existing-private-fixture')

    def test_missing_socket_fails_bounded_readiness(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'readiness timed out'):
                self.runtime.wait_ready(folder, ':193', seconds=.2)

    def test_real_private_xvnc_startup_and_x_authorization(self):
        # An unused display and an owned child only: no WeChat, real profile or live service.
        number = next(n for n in range(193, 250)
                      if not Path(f'/tmp/.X{n}-lock').exists() and not Path(f'/tmp/.X11-unix/X{n}').exists())
        display = ':' + str(number)
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryFile() as log:
            root = Path(folder)
            self.runtime.prepare(root, display)
            command = ['Xtigervnc', display, '-geometry', '905x667', '-depth', '24', '-rfbport', '-1',
                       '-rfbunixpath', str(root / 'vnc.sock'), '-rfbunixmode', '0600',
                       '-SecurityTypes', 'None', '-localhost', '-nolisten', 'tcp',
                       '-auth', str(root / 'Xauthority')]
            process = subprocess.Popen(command, stdout=log, stderr=log)
            try:
                try:
                    self.runtime.wait_ready(root, display, seconds=8)
                except ValueError as error:
                    log.seek(0)
                    self.fail(f'{error}; Xvnc exit={process.poll()}; '
                              + log.read().decode(errors='replace')[-4000:])
                self.assertIsNone(process.poll())
                for name in ('Xauthority', 'vnc.sock'):
                    self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o600)
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(root / 'vnc.sock'))
                    self.assertTrue(client.recv(12).startswith(b'RFB '))
                unauthorized = subprocess.run(['xdpyinfo', '-display', display],
                    env=dict(os.environ, XAUTHORITY=str(root / 'absent-authority')),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                self.assertNotEqual(unauthorized.returncode, 0)
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    def test_complete_unit_graph_passes_systemd_verify_without_installing(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'bundle'
            plan = stage(ROOT.as_posix(), output)
            result = subprocess.run(plan['verify_argv'],
                env=dict(os.environ, SYSTEMD_UNIT_PATH=str(output) + ':'),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout)
