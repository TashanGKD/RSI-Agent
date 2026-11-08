import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rsi_agent.config import ROOT


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() != 0,
                     'requires an unprivileged Linux user')
class DoctorPermissionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix='rsi-doctor-permissions-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        self.profile = self.root / 'profile'
        (self.profile / 'db_storage').mkdir(parents=True)
        for path in (self.state / 'db-keys.json', self.state / 'native-ui.json',
                     self.state / 'operations-state/config.json', self.root / 'Xauthority'):
            path.parent.mkdir(exist_ok=True)
            path.write_text('{}')
            path.chmod(0o600)
        self.config = self.root / 'installation.json'
        self.config.write_text(json.dumps({'version': 1, 'wechat': {
            'profile': str(self.profile), 'runtime_root': str(self.state),
            'account': 'fixture_operator', 'operations_enabled': True,
            'xauthority': str(self.root / 'Xauthority')}}))
        self.before = {str(p.relative_to(self.root)): p.read_bytes()
                       for p in self.root.rglob('*') if p.is_file()}

    def invoke(self, *args, request=None):
        result = subprocess.run([sys.executable, '-B', '-m', 'rsi_agent', '--config',
            str(self.config), *args], cwd=ROOT, input=json.dumps(request) if request else None,
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.stderr, '')
        return result.returncode, json.loads(result.stdout)

    def verify_unchanged(self):
        self.assertEqual(self.before, {str(p.relative_to(self.root)): p.read_bytes()
                         for p in self.root.rglob('*') if p.is_file()})

    def verify_read_and_confirm_blocked(self):
        for args, request in ((('wechat', 'read'), {'action': 'resolve', 'peer': 'fixture_peer'}),
                (('wechat', 'operations'), {'op': 'confirm', 'client': 'fixture',
                    'request_id': 'original', 'token': 'fixture-token'})):
            code, report = self.invoke(*args, request=request)
            self.assertEqual(code, 2)
            self.assertEqual(report, {'state': 'blocked',
                'reason': 'WeChat prerequisites are incomplete; run doctor before reading or writing.'})

    def test_unsearchable_runtime_keeps_desktop_diagnosis(self):
        code, baseline = self.invoke('doctor')
        self.assertEqual(code, 0)
        self.assertTrue(baseline['read']['checks']['private_keys_present'])
        self.state.chmod(0)
        try:
            code, report = self.invoke('doctor')
            self.assertEqual(code, 0)
            self.assertFalse(report['read']['ready'])
            self.assertFalse(report['read']['checks']['private_keys_present'])
            self.assertFalse(report['operations']['ready'])
            self.assertFalse(report['operations']['checks']['operation_config_present'])
            self.assertEqual(report['desktop'], baseline['desktop'])
            self.verify_read_and_confirm_blocked()
        finally:
            self.state.chmod(0o700)
        self.verify_unchanged()

    def test_unsearchable_profile_keeps_private_file_diagnosis(self):
        code, baseline = self.invoke('doctor')
        self.assertEqual(code, 0)
        self.assertTrue(baseline['read']['checks']['profile_configured'])
        self.profile.chmod(0)
        try:
            code, report = self.invoke('doctor')
            self.assertEqual(code, 0)
            self.assertFalse(report['read']['ready'])
            self.assertFalse(report['read']['checks']['profile_configured'])
            self.assertTrue(report['read']['checks']['private_keys_present'])
            self.assertFalse(report['operations']['ready'])
            self.assertEqual(report['desktop'], baseline['desktop'])
            self.verify_read_and_confirm_blocked()
        finally:
            self.profile.chmod(0o700)
        self.verify_unchanged()
