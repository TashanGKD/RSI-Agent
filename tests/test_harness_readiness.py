import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import venv

from rsi_agent import group_reply, owner_reply
from rsi_agent.model import ModelError


@unittest.skipUnless(sys.platform == 'linux', 'checks configured Linux interpreters and private configurations')
class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        for name in ('state', 'workspace'):
            (self.root / name).mkdir(mode=0o700)
        self.write('key', 'fixture-not-a-real-secret', json_value=False)
        self.write('provider.json', {'base_url': 'https://fixture.invalid/v1', 'model': 'fixture',
                                     'api_key_file': str(self.root / 'key')})
        self.backend = {'backend': 'deepseek-harness', 'provider_config': str(self.root / 'provider.json'),
                        'python': str(self.root / 'missing-python'), 'state': str(self.root / 'state'),
                        'workspace': str(self.root / 'workspace')}
        self.config = {'installation': 'unused', 'binding': 'unused', 'binding_token': 'fixture',
                       'model': str(self.root / 'backend.json'), 'state': str(self.root / 'state'), 'enabled': True}
        self.write('owner.json', self.config)
        self.write('groups.json', {'groups': [str(self.root / 'owner.json')]})
        self.io = Mock(return_value={'enabled': True})
        for target in ('rsi_agent.owner_reply.Transport', 'rsi_agent.group_reply.GroupTransport'):
            hook = patch(target, return_value=self.io)
            hook.start(); self.addCleanup(hook.stop)
        hook = patch('rsi_agent.model.ModelClient.complete', side_effect=AssertionError('no network/model probe'))
        hook.start(); self.addCleanup(hook.stop)

    def write(self, name, value, json_value=True):
        path = self.root / name
        path.write_text(json.dumps(value) if json_value else value)
        path.chmod(0o600)

    def check(self, channel):
        self.write('backend.json', self.backend)
        return (owner_reply.run(self.root / 'owner.json', 'check') if channel == 'owner'
                else group_reply.run(self.root / 'groups.json', 'check'))

    def interpreter(self):
        venv.EnvBuilder(with_pip=False).create(self.root / 'venv')
        self.backend['python'] = str(self.root / 'venv/bin/python')
        return Path(subprocess.check_output([self.backend['python'], '-I', '-c',
            'import sysconfig;print(sysconfig.get_path("purelib"))'], text=True).strip())

    def packages(self, site):
        for package in ('deepseek-harness-sdk', 'deepseek-harness-runtime-bin'):
            dist = site / (package.replace('-', '_') + '-0.2.1rc2.dist-info')
            dist.mkdir()
            (dist / 'METADATA').write_text('Name: ' + package + '\nVersion: 0.2.1rc2\n')
        sdk = site / 'deepseek_harness'; sdk.mkdir()
        (sdk / '__init__.py').write_text('class DeepSeekHarness:\n def __init__(self,*a,**kw): raise AssertionError("must not start a Session")\n')
        runtime = site / 'deepseek_harness_runtime'; runtime.mkdir()
        (runtime / '__init__.py').write_text('from pathlib import Path\ndef bundled_runtime_path():\n p=Path(__file__).with_name("runtime")\n if not p.is_file(): raise FileNotFoundError()\n return p\n')
        binary = runtime / 'runtime'
        binary.write_text('This file must never be executed by a dependency check.\n')
        binary.chmod(0o700)
        return binary

    def test_missing_python_blocks_both_checks_before_any_transport(self):
        for channel in ('owner', 'groups'):
            with self.subTest(channel=channel), self.assertRaisesRegex(ModelError, 'HARNESS_PYTHON_UNAVAILABLE'):
                self.check(channel)
        self.io.assert_not_called()
        self.assertEqual(list((self.root / 'state').iterdir()), [])

    def test_empty_target_environment_cannot_borrow_sdk_from_pythonpath(self):
        self.interpreter()
        poison = self.root / 'poison'; poison.mkdir()
        (poison / 'deepseek_harness.py').write_text('raise AssertionError("PYTHONPATH must be ignored")\n')
        with patch.dict('os.environ', {'PYTHONPATH': str(poison)}):
            for channel in ('owner', 'groups'):
                with self.subTest(channel=channel), self.assertRaisesRegex(ModelError, 'HARNESS_SDK_UNAVAILABLE'):
                    self.check(channel)
        self.io.assert_not_called()

    def test_imports_and_bundle_checks_do_not_create_a_session_or_execute_the_binary(self):
        self.packages(self.interpreter())
        for channel in ('owner', 'groups'):
            with self.subTest(channel=channel):
                self.assertEqual(self.check(channel)['state'], 'prepared')
        self.assertEqual(list((self.root / 'state').iterdir()), [])

    def test_missing_bundle_and_wrong_sdk_pin_are_distinguished(self):
        site = self.interpreter(); binary = self.packages(site)
        binary.unlink()
        with self.assertRaisesRegex(ModelError, 'HARNESS_RUNTIME_UNAVAILABLE'):
            self.check('owner')
        (site / 'deepseek_harness_sdk-0.2.1rc2.dist-info/METADATA').write_text('Name: deepseek-harness-sdk\nVersion: 0.0.0\n')
        with self.assertRaisesRegex(ModelError, 'HARNESS_SDK_UNAVAILABLE'):
            self.check('groups')

    def test_direct_provider_checks_remain_offline(self):
        self.write('provider.json', {'base_url': 'https://fixture.invalid/v1', 'model': 'fixture',
                                     'api_key_file': str(self.root / 'key')})
        self.write('owner.json', dict(self.config, model=str(self.root / 'provider.json')))
        for channel in ('owner', 'groups'):
            self.assertEqual(self.check(channel)['state'], 'prepared')
