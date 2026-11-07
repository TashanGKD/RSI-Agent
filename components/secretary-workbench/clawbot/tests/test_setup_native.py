"""Setup touches only fixture paths and a fake launchctl state machine."""
import contextlib
import fcntl
import io
import json
import os
import plistlib
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from bridge import setup_native as setup


class Launchctl:
    def __init__(self, override='', loaded=False, fail=None):
        self.override, self.loaded, self.fail = override, loaded, fail
        self.present = bool(override)
        self.calls = []
        self.before_mutation = None

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        action = argv[1]
        if action == 'getenv':
            return SimpleNamespace(returncode=0 if self.present else 1, stdout=self.override + '\n', stderr='')
        if action == 'print':
            return SimpleNamespace(returncode=0 if self.loaded else 113, stdout='', stderr='')
        if self.before_mutation:
            self.before_mutation()
        # Fail after a partial external mutation, not just before invocation.
        if action == 'setenv': self.override, self.present = argv[3], True
        if action == 'unsetenv': self.override, self.present = '', False
        if action == 'bootstrap': self.loaded = True
        if action == 'bootout': self.loaded = False
        if action == self.fail:
            self.fail = None
            raise subprocess.CalledProcessError(1, argv)
        return SimpleNamespace(returncode=0, stdout='', stderr='')


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.root = self.base / 'private'
        self.agents = self.base / 'LaunchAgents'
        self.root.mkdir(mode=0o700)
        self.agents.mkdir(mode=0o700)
        self.desktop = self.root / 'desktop'
        self.target = self.agents / (setup.LABEL + '.plist')
        self.config = self.root / 'native-context.json'
        self.backup = self.root / 'desktop-entry-backup.json'
        self.fake = Launchctl()

    def tearDown(self): self.temp.cleanup()

    def put(self, path, value, mode=0o600):
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(value)
        path.chmod(mode)

    def plan(self, restore=False):
        self.assertTrue(callable(getattr(setup, 'plan_setup', None)), 'read-only plan_setup required')
        return setup.plan_setup(self.root, launchagents_dir=self.agents, execute=self.fake, restore=restore)

    def apply(self, restore=False):
        return setup.apply_plan(self.plan(restore), execute=self.fake)

    def snapshot(self):
        return {str(p.relative_to(self.base)): (p.read_bytes(), p.stat().st_mode & 0o777)
                for parent in (self.root, self.agents) for p in parent.rglob('*')
                if p.is_file() and not p.name.endswith('.lock')}

    def assert_refused_unchanged(self, restore=False):
        before = self.snapshot()
        with self.assertRaises(ValueError): self.apply(restore)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(any(c[1] in ('setenv', 'unsetenv', 'bootstrap', 'bootout') for c in self.fake.calls))

    def test_foreign_agent_is_rejected_before_config_and_env_change(self):
        self.put(self.target, plistlib.dumps({'Label': 'foreign', 'ProgramArguments': ['/bin/false']}))
        self.assert_refused_unchanged()

    def test_matching_label_but_foreign_program_is_rejected(self):
        self.put(self.target, plistlib.dumps({'Label': setup.LABEL, 'ProgramArguments': ['/bin/false']}))
        self.assert_refused_unchanged()

    def test_symlink_wrapper_is_rejected(self):
        self.desktop.mkdir(mode=0o700)
        outside = self.base / 'foreign'
        self.put(outside, b'foreign')
        (self.desktop / 'codex-shared-entry').symlink_to(outside)
        self.assert_refused_unchanged()
        self.assertEqual(outside.read_bytes(), b'foreign')

    def test_unrelated_cli_override_is_rejected(self):
        self.fake.override = '/someone/elses/cli'
        self.assert_refused_unchanged()

    def test_foreign_native_context_is_rejected(self):
        self.put(self.config, b'{"thread_id":"another-thread","enabled":true}')
        self.assert_refused_unchanged()

    def test_plan_is_read_only(self):
        before = self.snapshot()
        self.plan()
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.desktop.exists())

    def test_desktop_wrapper_uses_openai_signed_runtime(self):
        script = self.plan().script.decode()
        self.assertIn('exec /Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node ', script)
        self.assertNotIn('/.nvm/', script)
        self.assertIn('if [ -x ', script)
        self.assertIn('exec ' + shlex.quote(setup.CLI) + ' "$@"', script)

    def test_reapply_migrates_legacy_node_wrapper_and_preserves_recovery(self):
        from bridge.native_runner import NODE as legacy_node
        self.apply()
        backup = self.backup.read_bytes()
        command = ('exec ' + shlex.quote(legacy_node) + ' ' +
                   shlex.quote(str(setup.ROOT / 'bridge/desktop_launcher.mjs')) + ' "$@"\n')
        for prefix in ['#!/bin/sh\n', '#!/bin/sh\nexport TASHAN_DESKTOP_SOCKET_ROOT=' + shlex.quote(str(self.desktop)) + '\n']:
            self.put(self.desktop / 'codex-shared-entry', (prefix + command).encode(), 0o700)
            self.apply()
            script = (self.desktop / 'codex-shared-entry').read_text()
            self.assertIn('exec /Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node ', script)
            self.assertEqual(backup, self.backup.read_bytes())

    def test_setup_backups_precede_global_changes_and_preserve_other_config(self):
        other = self.root / 'config.json'
        self.put(other, b'{"keep":"exact bytes"}\n')
        self.fake.before_mutation = lambda: self.assertTrue(self.backup.is_file())
        self.apply()
        self.assertEqual(other.read_bytes(), b'{"keep":"exact bytes"}\n')
        self.assertTrue(self.fake.loaded)
        wrapper = self.desktop / 'codex-shared-entry'
        self.assertEqual(self.fake.override, str(wrapper))
        script = wrapper.read_text()
        self.assertIn('desktop_launcher.mjs', script)
        self.assertIn('TASHAN_DESKTOP_SOCKET_ROOT=', script)
        self.assertIn('"$@"', script)
        self.assertNotIn('approval-policy', script)
        self.assertTrue(json.loads(self.config.read_text())['enabled'])
        self.assertEqual(wrapper.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_bootstrap_failure_restores_all_original_state(self):
        self.put(self.config, json.dumps({'thread_id': setup.THREAD, 'enabled': False, 'custom': 'keep'}).encode())
        before = self.snapshot()
        self.fake.fail = 'bootstrap'
        with self.assertRaises(subprocess.CalledProcessError): self.apply()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.fake.override, '')
        self.assertFalse(self.fake.loaded)
        self.assertFalse(self.desktop.exists())

    def test_environment_failure_restores_original_state(self):
        before = self.snapshot()
        self.fake.fail = 'setenv'
        with self.assertRaises(subprocess.CalledProcessError): self.apply()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.fake.override, '')
        self.assertFalse(self.fake.loaded)

    def test_reapply_failure_preserves_exact_existing_files(self):
        self.apply()
        self.put(self.config, json.dumps({'thread_id': setup.THREAD, 'enabled': False, 'custom': 'keep'}).encode() + b'\n')
        before = self.snapshot()
        self.fake.fail = 'setenv'
        with self.assertRaises(subprocess.CalledProcessError): self.apply()
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.fake.loaded)
        self.assertEqual(self.fake.override, str(self.desktop / 'codex-shared-entry'))

    def test_restore_preflight_refuses_foreign_agent_before_env_change(self):
        self.apply()
        self.put(self.target, plistlib.dumps({'Label': setup.LABEL, 'ProgramArguments': ['/bin/false']}))
        self.fake.calls.clear()
        self.assert_refused_unchanged(restore=True)

    def test_restore_suspends_native_mode_and_preserves_config_extensions(self):
        self.apply()
        cfg = json.loads(self.config.read_text()); cfg['custom'] = 'preserve'
        self.put(self.config, json.dumps(cfg).encode())
        self.apply(restore=True)
        self.assertEqual(self.fake.override, '')
        self.assertFalse(self.fake.loaded)
        self.assertFalse(self.target.exists())
        cfg = json.loads(self.config.read_text())
        self.assertFalse(cfg['enabled'])
        self.assertEqual(cfg['custom'], 'preserve')
        self.assertEqual(cfg['thread_id'], setup.THREAD)

    def test_restore_failure_restores_all_original_state(self):
        self.apply()
        before = self.snapshot()
        self.fake.fail = 'unsetenv'
        with self.assertRaises(subprocess.CalledProcessError): self.apply(restore=True)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(self.fake.loaded)
        self.assertEqual(self.fake.override, str(self.desktop / 'codex-shared-entry'))

    def test_stale_plan_is_rejected_before_mutation(self):
        plan = self.plan()
        self.put(self.target, plistlib.dumps({'Label': 'foreign'}))
        before = self.snapshot()
        with self.assertRaises(ValueError): setup.apply_plan(plan, execute=self.fake)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.fake.override, '')

    def test_explicit_empty_override_is_restored_exactly(self):
        self.fake.present = True
        self.fake.fail = 'bootstrap'
        with self.assertRaises(subprocess.CalledProcessError): self.apply()
        self.assertEqual(self.fake.override, '')
        self.assertTrue(self.fake.present)

    def test_restore_recovers_explicit_empty_override(self):
        self.fake.present = True
        self.apply()
        self.apply(restore=True)
        self.assertEqual(self.fake.override, '')
        self.assertTrue(self.fake.present)

    def test_symlink_agent_and_corrupt_backup_are_rejected(self):
        outside = self.base / 'foreign'
        self.put(outside, b'foreign')
        self.target.symlink_to(outside)
        self.assert_refused_unchanged()
        self.target.unlink()
        self.put(self.backup, b'{"previous_override":123}')
        self.assert_refused_unchanged()

    def test_unsafe_private_file_mode_is_rejected(self):
        self.put(self.config, b'{}', mode=0o644)
        self.assert_refused_unchanged()

    def test_oversized_context_is_rejected_before_backup(self):
        self.put(self.config, json.dumps({'padding': 'x' * 65536}).encode())
        self.assert_refused_unchanged()

    def test_existing_setup_lock_blocks_apply(self):
        plan = self.plan()
        lock = self.agents / ('.' + setup.LABEL + '.lock')
        self.put(lock, b'')
        with lock.open('r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'setup is running'):
                setup.apply_plan(plan, execute=self.fake)
        self.assertEqual(self.snapshot(), {})
        self.assertEqual(self.fake.override, '')

    def test_local_write_failure_rolls_back_exact_files(self):
        self.put(self.config, b'{"enabled":false,"custom":"keep"}\n')
        before = self.snapshot()
        original = setup._atomic
        def fail_plist_once(path, state):
            if path == self.target:
                raise OSError('fixture disk failure')
            return original(path, state)
        with patch.object(setup, '_atomic', side_effect=fail_plist_once):
            with self.assertRaises(OSError): self.apply()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.fake.override, '')
        self.assertFalse(self.fake.loaded)

    def test_changed_cli_override_invalidates_plan(self):
        plan = self.plan()
        self.fake.override = '/another/cli'
        with self.assertRaises(ValueError): setup.apply_plan(plan, execute=self.fake)
        self.assertEqual(self.snapshot(), {})
        self.assertEqual(self.fake.override, '/another/cli')

    def test_defaults_and_dry_run_do_not_call_launchctl(self):
        def never(*args, **kwargs): self.fail('default CLI called launchctl')
        with contextlib.redirect_stdout(io.StringIO()):
            setup.main([], execute=never, launchagents_dir=self.agents)
            setup.main(['--workspace', str(self.root)], execute=never, launchagents_dir=self.agents)
        self.assertFalse(self.desktop.exists())
        self.assertEqual(self.snapshot(), {})


if __name__ == '__main__': unittest.main()
