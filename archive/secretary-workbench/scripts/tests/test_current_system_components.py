"""Portable current-system contracts; synthetic data and no running employee."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


class CurrentSystemComponents(unittest.TestCase):
    def test_unified_inbound_and_monitor_sources_exported(self):
        for rel in ['host/continuity/runtime.py', 'host/continuity/native_source.py',
                    'host/continuity/delivery_health.py', 'monitor/backend/work_observer.py',
                    'monitor/backend/online_sync.py', 'monitor/web/src/App.tsx']:
            self.assertTrue((ROOT / rel).is_file(), rel)

    def test_no_operator_directory_or_routes_are_defaults(self):
        sys.path.insert(0, str(ROOT / 'monitor/backend'))
        sys.path.insert(0, str(ROOT / 'host'))
        with patch.dict(os.environ, {}, clear=True):
            import collect
            import work_observer
            import send_tool_observer
            self.assertEqual(collect.IDS, {})
            self.assertEqual(collect.ALLOWED, [])
            self.assertEqual(work_observer.KNOWN, {})
            self.assertEqual(work_observer.SUPPORT, {})
            self.assertEqual(work_observer.PEERS, {})
            self.assertEqual(send_tool_observer.CLIENTS, {})

    def test_monitor_has_no_write_or_private_file_route(self):
        sys.path.insert(0, str(ROOT / 'monitor/backend'))
        import serve
        self.assertFalse(hasattr(serve.Handler, 'do_POST'))
        for url in ['/private/state.json', '/@fs/etc/passwd', '/../credentials']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                serve.resolve_static(url)

    def test_mcp_source_is_an_executable_adapter_with_no_live_import(self):
        sys.path.insert(0, str(ROOT / 'host/aup-sender'))
        file = ROOT / 'host/aup-sender/sender_work_tools.py'
        self.assertTrue(file.is_file())
        with patch.dict(os.environ, {}, clear=True), \
             patch('subprocess.run', side_effect=AssertionError('no host call')), \
             patch('subprocess.Popen', side_effect=AssertionError('no process')):
            spec = importlib.util.spec_from_file_location('portable_mcp_fixture', file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertTrue(callable(module.operation))

    def test_installation_config_rejects_duplicate_keys(self):
        sys.path.insert(0, str(ROOT / 'host'))
        import installation_config as cfg
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'installation.json'
            file.write_text('{"version":1,"version":1}')
            with self.assertRaises(ValueError): cfg.read(file)

    def test_readable_relative_tilde_and_symlink_configuration(self):
        import json
        sys.path.insert(0, str(ROOT / 'host'))
        import installation_config as cfg
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            selected = root / 'selected'
            selected.mkdir()
            storage = root / 'storage'
            storage.mkdir()
            home = root / 'home'
            home.mkdir()
            (home / 'home.txt').write_text('home fixture')
            payload = root / 'payload'
            payload.mkdir()
            (payload / 'data.txt').write_text('relative fixture')
            (selected / 'data-link').symlink_to(payload, target_is_directory=True)
            file = storage / 'ordinary.json'
            file.write_text(json.dumps({
                'version': 1,
                'modules': {'fixture': {
                    'notes': 'x' * 300000,
                    'sources': ['data-link/data.txt', '~/home.txt'],
                    'roots': {'work': 'data-link'},
                    'files': {'work': ['data-link/data.txt']},
                    'roles': {'fixture-thread': ['worker', 'Worker', 'data-link', 'data-link/data.txt']}}},
                'paths': {'relative': 'data-link/data.txt', 'home': '~/home.txt'}}))
            file.chmod(0o644)
            link = selected / 'installation.json'
            link.symlink_to(file)
            old_cwd = Path.cwd()
            try:
                os.chdir(root)
                with patch.dict(os.environ, {'SECRETARY_INSTALLATION_CONFIG': 'selected/installation.json', 'HOME': str(home)}, clear=True):
                    try: parsed = cfg.read()
                    except (ValueError, OSError) as error:
                        self.fail('ordinary readable operator config rejected: ' + str(error))
                    self.assertEqual(len(parsed['modules']['fixture']['notes']), 300000)
                    self.assertEqual(cfg.path('relative'), selected / 'data-link/data.txt')
                    self.assertEqual(cfg.path('relative').read_text(), 'relative fixture')
                    self.assertEqual(cfg.path('home'), home / 'home.txt')
                    self.assertEqual(cfg.path_list('fixture', 'sources'), [selected / 'data-link/data.txt', home / 'home.txt'])
                    self.assertEqual(cfg.path_map('fixture', 'roots')['work'], selected / 'data-link')
                    self.assertEqual(cfg.path_map('fixture', 'files', lists=True)['work'], [selected / 'data-link/data.txt'])
                    self.assertEqual(cfg.role_map('fixture', 'roles')['fixture-thread'][2:], (selected / 'data-link', selected / 'data-link/data.txt'))
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(cfg.path('unconfigured'), ROOT / 'var/unconfigured/unconfigured')
            finally:
                os.chdir(old_cwd)
