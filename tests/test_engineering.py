from pathlib import Path
import json
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
        self.checkpoint = self.root / 'original.publication.json'
        self.binding = {'base': engineering.git(self.workspace, 'rev-parse', 'HEAD'),
                        'workspace': str(self.workspace), 'request': 'a' * 64,
                        'input_sha256': 'b' * 64, 'response_sha256': 'c' * 64}

    def publish(self):
        return engineering.publish(self.workspace, self.checkpoint, self.binding)

    def test_real_git_change_is_committed_pushed_and_noop_does_not_commit_again(self):
        engineering.prepare(self.workspace)
        (self.workspace / 'README.md').write_text('after\n')
        result = self.publish()
        self.assertEqual(engineering.git(self.remote, 'rev-parse', engineering.BRANCH), result['commit'])
        self.assertEqual(engineering.git(self.workspace, 'status', '--porcelain'), '')
        self.assertEqual(self.publish(), result)
        self.binding['base'] = result['commit']
        self.binding['request'] = 'd' * 64
        self.checkpoint = self.root / 'next.publication.json'
        self.assertIsNone(self.publish())

    def test_failed_gate_keeps_work_and_does_not_push(self):
        before = engineering.git(self.workspace, 'rev-parse', 'HEAD')
        (self.workspace / 'scripts/check.py').write_text('raise SystemExit(1)\n')
        with self.assertRaisesRegex(ValueError, 'failed the normal Linux gate'):
            self.publish()
        self.assertEqual(engineering.git(self.workspace, 'rev-parse', 'HEAD'), before)
        self.assertTrue(engineering.git(self.workspace, 'status', '--porcelain'))
        self.assertTrue((self.root / 'validation.log').exists())
        with self.assertRaisesRegex(ValueError, 'uncommitted'):
            engineering.prepare(self.workspace)

    def test_private_artifact_does_not_cross_git_publication(self):
        (self.workspace / 'private.png').write_bytes(b'private picture')
        with self.assertRaisesRegex(ValueError, 'private artifact'):
            self.publish()
        (self.workspace / 'private.png').unlink()
        self.checkpoint = self.root / 'credential.publication.json'
        (self.workspace / 'provider.py').write_text('key = "sk-' + 'x' * 32 + '"\n')
        with self.assertRaisesRegex(ValueError, 'credential'):
            self.publish()
        digest = engineering.git(self.workspace, 'hash-object', 'provider.py')
        result = subprocess.run(['git', '-C', str(self.workspace), 'cat-file', '-e', digest], capture_output=True)
        self.assertNotEqual(result.returncode, 0, 'Rejected private bytes must not enter Git objects')

    def test_staged_only_edit_is_not_lost(self):
        (self.workspace / 'README.md').write_text('already staged\n')
        engineering.git(self.workspace, 'add', 'README.md')
        result = self.publish()
        self.assertEqual(engineering.git(self.remote, 'show', result['commit'] + ':README.md'), 'already staged')

    def test_interrupted_ref_update_and_push_adopt_one_commit_without_another_gate(self):
        for action in ('update-ref', 'push'):
            with self.subTest(action=action):
                self.binding['base'] = engineering.git(self.workspace, 'rev-parse', 'HEAD')
                self.checkpoint = self.root / (action + '.publication.json')
                (self.workspace / 'README.md').write_text(action + '\n')
                real_git = engineering.git
                effects = []

                def interrupted(workspace, *args, **kwargs):
                    result = real_git(workspace, *args, **kwargs)
                    if args[0] == action:
                        effects.append(args[0])
                        raise TimeoutError('ack lost after actual ' + action)
                    return result

                with patch.object(engineering, 'git', side_effect=interrupted):
                    with self.assertRaises(TimeoutError):
                        self.publish()
                frozen = json.loads(self.checkpoint.read_text())
                commit = frozen['commit']
                real_run = subprocess.run

                def no_gate(command, **kwargs):
                    if command[0] == '/usr/bin/python3':
                        raise AssertionError('completed gate reran')
                    return real_run(command, **kwargs)

                def no_duplicate_effect(workspace, *args, **kwargs):
                    if args[0] == 'update-ref' or (action == 'push' and args[0] == 'push'):
                        raise AssertionError('confirmed Git effect repeated')
                    return real_git(workspace, *args, **kwargs)

                with patch.object(engineering.subprocess, 'run', side_effect=no_gate), \
                        patch.object(engineering, 'git', side_effect=no_duplicate_effect):
                    result = self.publish()
                self.assertEqual(result['commit'], commit)
                self.assertEqual(engineering.git(self.remote, 'rev-parse', engineering.BRANCH), commit)
                self.assertEqual(engineering.git(self.workspace, 'rev-list', '--count', self.binding['base'] + '..HEAD'), '1')
                self.assertEqual(effects, [action])
                self.assertEqual(self.publish(), result)

    def test_changed_source_stops_without_overwriting(self):
        (self.workspace / 'README.md').write_text('frozen\n')
        real_git = engineering.git

        def stop_before_push(workspace, *args, **kwargs):
            if args[0] == 'push':
                raise TimeoutError('before push')
            return real_git(workspace, *args, **kwargs)

        with patch.object(engineering, 'git', side_effect=stop_before_push):
            with self.assertRaises(TimeoutError):
                self.publish()
        frozen = json.loads(self.checkpoint.read_text())
        (self.workspace / 'README.md').write_text('foreign edit\n')
        with self.assertRaisesRegex(ValueError, 'source, index or head changed'):
            self.publish()
        self.assertEqual((self.workspace / 'README.md').read_text(), 'foreign edit\n')
        self.assertEqual(json.loads(self.checkpoint.read_text())['phase'], 'review')
        self.assertEqual(engineering.git(self.workspace, 'rev-parse', 'HEAD'), frozen['commit'])

    def test_live_validation_child_blocks_resume_without_killing_it(self):
        (self.workspace / 'README.md').write_text('frozen\n')
        child = subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(30)'], cwd=self.workspace)
        try:
            with self.assertRaises(BlockingIOError):
                self.publish()
            self.assertIsNone(child.poll())
            self.assertFalse(self.checkpoint.exists())
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_foreign_index_is_preserved_even_when_working_files_match(self):
        (self.workspace / 'README.md').write_text('frozen\n')
        real_run = subprocess.run

        def pause_gate(command, **kwargs):
            if command[0] == '/usr/bin/python3':
                raise TimeoutError('validation interrupted')
            return real_run(command, **kwargs)

        with patch.object(engineering.subprocess, 'run', side_effect=pause_gate):
            with self.assertRaises(TimeoutError):
                self.publish()
        (self.workspace / 'README.md').write_text('foreign staged edit\n')
        engineering.git(self.workspace, 'add', 'README.md')
        (self.workspace / 'README.md').write_text('frozen\n')
        before = engineering.git(self.workspace, 'write-tree')
        with self.assertRaisesRegex(ValueError, 'source, index or head changed'):
            self.publish()
        self.assertEqual(engineering.git(self.workspace, 'write-tree'), before)
        self.assertEqual((self.workspace / 'README.md').read_text(), 'frozen\n')

    def test_original_process_group_blocks_children_without_requiring_their_cwd(self):
        child = subprocess.Popen(['/usr/bin/python3', '-c', 'import time; time.sleep(30)'],
                                 cwd=self.root, start_new_session=True)
        try:
            with self.assertRaisesRegex(BlockingIOError, 'live children'):
                engineering.publisher_idle(self.workspace, child.pid)
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_changed_remote_is_not_pushed_over(self):
        (self.workspace / 'README.md').write_text('frozen\n')
        real_git = engineering.git

        def no_push(workspace, *args, **kwargs):
            if args[0] == 'push':
                raise TimeoutError('push not yet started')
            return real_git(workspace, *args, **kwargs)

        with patch.object(engineering, 'git', side_effect=no_push):
            with self.assertRaises(TimeoutError):
                self.publish()
        engineering.git(self.remote, 'update-ref', 'refs/heads/' + engineering.BRANCH, self.binding['base'])
        with self.assertRaisesRegex(ValueError, 'Remote owner branch changed'):
            self.publish()
        self.assertEqual(engineering.git(self.remote, 'rev-parse', engineering.BRANCH), self.binding['base'])
