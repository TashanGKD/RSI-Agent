"""Offline contracts for the portable refresh; never opens a real account."""
import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class RefreshContract(unittest.TestCase):
    def test_shared_skill_complete(self):
        skill = ROOT / 'skills/digital-employee'
        files = [p for p in skill.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        self.assertEqual(len(files), 30)
        for name in ['SKILL.md', 'references/working-habits.md',
                     'references/system-onboarding.md', 'scripts/workbook.py',
                     'templates/new-employee/STATE.template.json']:
            self.assertTrue((skill / name).is_file(), name)

    def test_specific_original_case_not_distributed(self):
        sys.path.insert(0, str(ROOT / 'wechat'))
        module = importlib.import_module('operations.original_deviation')
        self.assertIsNone(module.CASE)
        with tempfile.TemporaryDirectory() as directory:
            before = list(Path(directory).iterdir())
            self.assertIsNone(module.verify(Path(directory), {'id': 'fixture-job'}))
            self.assertFalse(module.audit_match(Path(directory), {'id': 'fixture-job'}, {}, {}))
            self.assertIsNone(module.load_record(Path(directory)))
            self.assertEqual(before, list(Path(directory).iterdir()))

    def test_current_policy_is_attribution_not_tenant_authority(self):
        sys.path.insert(0, str(ROOT / 'wechat'))
        from operations.driver import Policy
        policy = Policy({'version': 2, 'account': 'wxid_fixture_operator', 'clients': {}})
        policy.check({'client': 'fixture', 'peer': 'wxid_fixture_person', 'action': 'send_text'})
        self.assertIn('send_text', policy.allowed({}, 'wxid_fixture_person'))

    def test_native_host_missing_configuration_never_starts_daemon(self):
        import importlib.util
        file = ROOT / 'host/aup-sender/sender_native.py'
        with patch.dict('os.environ', {}, clear=True):
            spec = importlib.util.spec_from_file_location('portable_sender_native_fixture', file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with patch('subprocess.run', side_effect=AssertionError('no daemon')), \
                 patch('subprocess.Popen', side_effect=AssertionError('no proxy')):
                with self.assertRaises(ValueError):
                    module.Native()


if __name__ == '__main__':
    unittest.main()
