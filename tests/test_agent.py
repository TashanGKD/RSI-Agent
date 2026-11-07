import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rsi_agent import __main__ as cli
from rsi_agent.config import ROOT, load
from rsi_agent.wechat import call, doctor, environment


class AgentTests(unittest.TestCase):
    def test_unconfigured_installation_is_not_read_or_send_ready(self):
        result = doctor(load())
        self.assertFalse(result['read']['ready'])
        self.assertFalse(result['operations']['ready'])
        self.assertEqual(result['live_acceptance'], 'not verified by this command')

    def test_gi_without_the_gtk_namespace_is_not_desktop_ready(self):
        from unittest.mock import Mock
        gi = Mock()
        gi.require_version.side_effect = ValueError('Namespace Gtk not available')
        with patch('rsi_agent.wechat.importlib.util.find_spec', return_value=True), patch('rsi_agent.wechat.importlib.import_module', return_value=gi):
            self.assertFalse(doctor(load())['desktop']['checks']['gtk_installed'])

    def test_missing_x11_tools_block_operations_but_not_database_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'db_storage').mkdir()
            config = load()
            config['wechat'].update(account='wxid_fixture_operator', profile=folder, operations_enabled=True)
            for missing in ('xwininfo', 'xprop', None):
                with self.subTest(missing=missing), patch('rsi_agent.wechat.sys.platform', 'linux'), \
                        patch('rsi_agent.wechat.private_file', return_value=True), \
                        patch('rsi_agent.wechat.importlib.util.find_spec', return_value=True), \
                        patch('rsi_agent.wechat.gtk_available', return_value=True), \
                        patch('rsi_agent.wechat.shutil.which', side_effect=lambda name: None if name == missing else '/fixture/bin/' + name), \
                        patch('rsi_agent.wechat.subprocess.run') as delegate:
                    result = doctor(config)
                    self.assertTrue(result['read']['ready'])
                    self.assertEqual(result['desktop']['dependencies_ready'], missing is None)
                    self.assertEqual(result['operations']['ready'], missing is None)
                    if missing:
                        with self.assertRaisesRegex(ValueError, 'prerequisites are incomplete'):
                            call(config, 'operations', {'op': 'confirm', 'client': 'fixture',
                                                        'request_id': 'original', 'token': 'fixture-token'})
                        delegate.assert_not_called()

    def test_configuration_paths_use_the_configuration_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'version': 1, 'wechat': {'profile': 'profile', 'runtime_root': 'state'}}))
            result = load(path)['wechat']
            self.assertEqual(Path(result['profile']), Path(folder) / 'profile')
            self.assertEqual(Path(result['runtime_root']), Path(folder) / 'state')

    def test_invalid_display_and_enable_flag_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            for value in ({'display': 'remote:0'}, {'operations_enabled': 'false'}, {'unknown': 1}):
                path.write_text(json.dumps({'version': 1, 'wechat': value}))
                with self.assertRaises(ValueError):
                    load(path)

    def test_read_cannot_be_used_as_a_send_entry(self):
        with patch('rsi_agent.wechat.subprocess.run') as run:
            with self.assertRaises(ValueError):
                call(load(), 'read', {'action': 'send_text', 'text': 'not sent'})
            run.assert_not_called()

    def test_missing_configuration_does_not_launch_an_upstream_tool(self):
        with patch('rsi_agent.wechat.subprocess.run') as run:
            with self.assertRaises(ValueError):
                call(load(), 'read', {'action': 'messages'})
            run.assert_not_called()

    def test_existing_request_id_and_body_are_forwarded_without_rewrite(self):
        request = {'op': 'get', 'client': 'owner', 'request_id': 'original'}
        with patch('rsi_agent.wechat.sys.platform', 'linux'), patch('rsi_agent.wechat.private_file', return_value=True), \
                patch('rsi_agent.wechat.doctor') as readiness, patch('rsi_agent.wechat.subprocess.run') as run:
            run.return_value.returncode = 0
            self.assertEqual(call(load(), 'operations', request), 0)
            readiness.assert_not_called()
            args, kwargs = run.call_args
            self.assertEqual(json.loads(kwargs['input']), request)
            self.assertIn('operations.cli', args[0])

    def test_cli_rejects_duplicate_request_keys_before_delegation(self):
        cases = [
            ('read', '{"action":"resolve","peer":"wxid_fixture_first","peer":"wxid_fixture_second"}'),
            ('operations', '{"op":"get","client":"fixture","request_id":"original","request_id":"replacement"}'),
            ('operations', '{"op":"submit","job":{"payload":{"text":"first","text":"replacement"}}}'),
            ('read', '{"action":"resolve","peer":"wxid_fixture_first","\\u0070eer":"wxid_fixture_second"}'),
        ]
        for mode, raw in cases:
            with self.subTest(raw=raw), patch('sys.stdin', io.StringIO(raw)), patch('rsi_agent.__main__.call', return_value=0) as delegate:
                with self.assertRaisesRegex(ValueError, '[Dd]uplicate'):
                    cli.main(['wechat', mode])
                delegate.assert_not_called()

    def test_cli_preserves_valid_unicode_and_json_like_message_text(self):
        request = {'op': 'submit', 'job': {'client': 'fixture', 'request_id': 'original',
                   'peer': 'wxid_fixture_target', 'action': 'send_text',
                   'payload': {'text': '中文 🧪\n{"peer":"first","peer":"second"}'}}}
        with patch('sys.stdin', io.StringIO(json.dumps(request, ensure_ascii=False))), patch('rsi_agent.__main__.call', return_value=0) as delegate:
            self.assertEqual(cli.main(['wechat', 'operations']), 0)
            self.assertEqual(delegate.call_args.args[2], request)

    def test_read_boundary_applies_to_a_ready_installation_too(self):
        with patch('rsi_agent.wechat.doctor', return_value={'read': {'ready': True}}), patch('rsi_agent.wechat.subprocess.run') as run:
            with self.assertRaises(ValueError):
                call(load(), 'read', {'action': 'send_image'})
            run.assert_not_called()

    def test_display_and_xauthority_are_shared_with_original_helpers(self):
        spec = importlib.util.spec_from_file_location('rsi_runtime_env', ROOT / 'components/secretary-workbench/wechat/rsi_runtime_env.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with patch.dict(os.environ, environment(load())):
            self.assertEqual(module.display(), ':92')
            self.assertEqual(module.xauthority('/unused'), '/run/wechat-gui/Xauthority')
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(module.display(), ':97')
            self.assertEqual(module.xauthority('/state'), str(Path('/state') / 'Xauthority'))

    def test_demo_cannot_overwrite_a_workspace(self):
        with tempfile.TemporaryDirectory() as folder, patch('rsi_agent.__main__.subprocess.run') as run:
            with self.assertRaises(ValueError):
                cli.main(['notebook', '--workspace', folder, '--demo'])
            run.assert_not_called()

    def test_invalid_notebook_port_does_not_create_demo_data(self):
        with tempfile.TemporaryDirectory() as folder, patch('rsi_agent.__main__.subprocess.run') as run:
            target = Path(folder) / 'new-demo'
            with self.assertRaises(ValueError):
                cli.main(['notebook', '--workspace', str(target), '--demo', '--port', '0'])
            run.assert_not_called()
            self.assertFalse(target.exists())

    def test_source_lock_contains_both_actual_imports(self):
        value = json.loads((ROOT / 'SOURCES.lock.json').read_text())
        self.assertEqual(len(value['sources']), 2)
        for source in value['sources']:
            self.assertEqual(len(source['commit']), 40)
            self.assertTrue((ROOT / source['directory'] / 'README.md').is_file())


if __name__ == '__main__':
    unittest.main()
