from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from rsi_agent import engineering


@unittest.skipUnless(sys.platform == 'linux', 'uses the actual Linux validation command')
class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.remote = self.root / 'remote.git'
        self.workspace = self.root / 'workspace'
        subprocess.run(['git', 'init', '--bare', str(self.remote)], check=True, capture_output=True)
        subprocess.run(['git', 'clone', str(self.remote), str(self.workspace)], check=True, capture_output=True)
        for key, value in [('user.name', 'Fixture'), ('user.email', 'fixture@example.invalid')]:
            engineering.git(self.workspace, 'config', key, value)
        engineering.git(self.workspace, 'checkout', '-b', engineering.BRANCH)
        (self.workspace / 'scripts').mkdir()
        (self.workspace / 'scripts/check.py').write_text('print("fixture validation")\n')
        (self.workspace / 'README.md').write_text('before\n')
        engineering.git(self.workspace, 'add', '.')
        engineering.git(self.workspace, 'commit', '-m', 'fixture baseline')
        engineering.git(self.workspace, 'push', 'origin', 'HEAD:main')
        hook = patch.object(engineering, 'REMOTE', str(self.remote))
        hook.start()
        self.addCleanup(hook.stop)

    def test_real_git_change_is_committed_pushed_and_noop_does_not_commit_again(self):
        engineering.prepare(self.workspace)
        (self.workspace / 'README.md').write_text('after\n')
        result = engineering.publish(self.workspace)
        self.assertEqual(engineering.git(self.remote, 'rev-parse', engineering.BRANCH), result['commit'])
        self.assertEqual(engineering.git(self.workspace, 'status', '--porcelain'), '')
        self.assertIsNone(engineering.publish(self.workspace))

    def test_failed_gate_keeps_work_and_does_not_push(self):
        before = engineering.git(self.workspace, 'rev-parse', 'HEAD')
        (self.workspace / 'scripts/check.py').write_text('raise SystemExit(1)\n')
        with self.assertRaisesRegex(ValueError, 'failed the normal Linux gate'):
            engineering.publish(self.workspace)
        self.assertEqual(engineering.git(self.workspace, 'rev-parse', 'HEAD'), before)
        self.assertTrue(engineering.git(self.workspace, 'status', '--porcelain'))
        self.assertTrue((self.root / 'validation.log').exists())
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            engineering.prepare(self.workspace)

    def test_private_artifact_does_not_cross_git_publication(self):
        (self.workspace / 'private.png').write_bytes(b'private picture')
        with self.assertRaisesRegex(ValueError, 'private artifact'):
            engineering.publish(self.workspace)
        (self.workspace / 'private.png').unlink()
        (self.workspace / 'provider.py').write_text('key = "sk-' + 'x' * 32 + '"\n')
        with self.assertRaisesRegex(ValueError, 'credential'):
            engineering.publish(self.workspace)
