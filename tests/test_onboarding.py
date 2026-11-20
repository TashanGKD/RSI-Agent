import contextlib
import hashlib
import http.server
import io
import json
import shutil
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from rsi_agent import __main__ as cli
from rsi_agent import onboarding
from rsi_agent.config import ROOT


class ReviewedClientTests(unittest.TestCase):
    def test_authorization_manifest_matches_the_pinned_installers(self):
        approved = onboarding.capture_module().release()
        self.assertEqual(approved['capture_offset'], 0x87b3cf0)
        for name in ('deploy/wechat-wsl/Install-WeChat.ps1', 'deploy/wechat-wsl/install-first.sh',
                     'deploy/wechat-gui/start-official-client.sh'):
            self.assertIn(approved['package_sha256'], (ROOT / name).read_text())
            if name.endswith('.sh'):
                self.assertIn(approved['version'], (ROOT / name).read_text())
        self.assertIn(approved['binary_sha256'], (ROOT / 'deploy/wechat-wsl/install-first.sh').read_text())


class PairingTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='rsi pairing ')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.codex = self.root / 'codex.exe'
        self.identity = self.root / 'identity'
        self.codex.write_bytes(b'fixture executable')
        self.identity.write_bytes(b'fixture identity')
        self.output = self.root / 'new instance'
        self.thread = '11111111-1111-4111-8111-111111111111'

    def stage(self, **changes):
        values = dict(output=self.output, codex=str(self.codex), thread=self.thread,
                      ssh='fixture-tunnel', identity_file=str(self.identity))
        values.update(changes)
        return onboarding.stage_pairing(**values)

    def test_new_pairing_shares_transport_token_without_activating_account(self):
        result = self.stage()
        receiver = json.loads((self.output / 'local-codex.json').read_text())
        backend = json.loads((self.output / 'linux/codex/model.json').read_text())
        check = json.loads((self.output / 'linux/receiver-check.json').read_text())
        installation = json.loads((self.output / 'linux/installation.json').read_text())
        token = (self.output / 'linux/codex/token.txt').read_text()
        self.assertEqual(receiver['token'], token)
        self.assertEqual(check['token'], token)
        self.assertEqual(receiver['desktop_thread_id'], self.thread)
        self.assertEqual(backend['endpoint'], 'http://127.0.0.1:8766')
        self.assertFalse(backend['engineering'])
        self.assertFalse(installation['wechat']['operations_enabled'])
        self.assertIsNone(installation['wechat']['account'])
        self.assertIsNone(installation['wechat']['profile'])
        self.assertFalse(result['activated'])
        self.assertFalse(result['paired'])
        self.assertNotIn(token, json.dumps(result))
        self.assertEqual(list((self.output / 'receiver-state').iterdir()), [])
        self.assertEqual(result, json.loads((self.output / 'plan.json').read_text()))
        if sys.platform == 'linux':
            self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
            for file in self.output.rglob('*'):
                if file.is_file():
                    self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)

    def test_second_pairing_preserves_original_token_and_queue(self):
        self.stage()
        token = (self.output / 'local-codex.json').read_bytes()
        queue = self.output / 'receiver-state/jobs.sqlite'
        queue.write_bytes(b'original queue must survive')
        with self.assertRaisesRegex(ValueError, 'NEW directory'):
            self.stage()
        self.assertEqual((self.output / 'local-codex.json').read_bytes(), token)
        self.assertEqual(queue.read_bytes(), b'original queue must survive')

    def test_invalid_pairing_does_not_create_output(self):
        for changes in ({'thread': 'nickname'}, {'ssh': '-oProxyCommand=bad'},
                        {'port': 8766}, {'remote_port': 22}, {'remote_root': '/opt/../etc'},
                        {'runtime_root': '/var/lib/rsi-agent'}, {'runtime_root': '/var/lib/rsi-agent/codex'},
                        {'codex': 'relative'}, {'identity_file': str(self.root / 'missing')}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.stage(**changes)
            self.assertFalse(self.output.exists())

    def test_cli_pairing_output_never_prints_transport_token(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = cli.main(['setup', 'pair', '--output', str(self.output), '--codex', str(self.codex),
                '--thread', self.thread, '--ssh', 'fixture-tunnel', '--identity-file', str(self.identity)])
        self.assertEqual(code, 0)
        token = (self.output / 'linux/codex/token.txt').read_text()
        self.assertNotIn(token, output.getvalue())

    @unittest.skipUnless(sys.platform == 'linux', 'native backend validates Linux private ownership')
    def test_staged_linux_backend_loads_after_copy_with_the_same_token(self):
        from trigger.codex_backend import CodexBackend
        with tempfile.TemporaryDirectory(prefix='rsi-coordinator-') as folder:
            installed = Path(folder)
            self.stage(remote_root=str(installed))
            shutil.copytree(self.output / 'linux/codex', installed / 'codex')
            backend = CodexBackend(installed / 'codex/model.json')
            receiver = json.loads((self.output / 'local-codex.json').read_text())
            self.assertEqual(backend.token, receiver['token'])
            self.assertFalse(backend.engineering)


@unittest.skipUnless(sys.platform == 'linux', 'account preparation requires Linux ownership checks')
class CapturePreparationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.binary = self.root / 'wechat'
        self.binary.write_bytes(b'reviewed fixture executable')
        self.module = onboarding.capture_module()
        approved = dict(self.module.release(), binary_paths=[str(self.binary)],
                        binary_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest())
        mocked = patch.object(self.module, 'release', return_value=approved)
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_preparation_is_own_child_only_and_idempotent(self):
        with patch('subprocess.run') as run, patch('subprocess.Popen') as popen:
            script = self.module.prepare(binary=self.binary, root=self.root)
            before = script.read_bytes()
            self.assertEqual(self.module.prepare(binary=self.binary, root=self.root), script)
            run.assert_not_called()
            popen.assert_not_called()
        self.assertEqual(script.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(script.stat().st_mode), 0o600)
        text = script.read_text()
        self.assertIn(str(self.binary), text)
        self.assertIn('return True', text)
        self.assertLess(text.index('reviewed child executable changed'), text.index('\nstarti\n'))
        self.assertTrue(text.endswith('continue\ndetach\nquit\n'))
        self.assertFalse(any(line.startswith('attach ') for line in text.splitlines()))
        self.assertFalse((self.root / 'capture-secret.hex').exists())

    def test_modified_binary_cannot_prepare_a_capture(self):
        self.binary.write_bytes(b'unreviewed new version')
        with self.assertRaisesRegex(ValueError, 'reviewed executable'):
            self.module.prepare(binary=self.binary, root=self.root)
        self.assertFalse((self.root / 'capture-child.gdb').exists())

    def test_existing_secret_and_different_script_are_preserved(self):
        script = self.root / 'capture-child.gdb'
        script.write_text('original preparation')
        with self.assertRaisesRegex(ValueError, 'preserved'):
            self.module.prepare(binary=self.binary, root=self.root)
        self.assertEqual(script.read_text(), 'original preparation')
        secret = self.root / 'capture-secret.hex'
        secret.write_text('existing private material')
        with self.assertRaisesRegex(ValueError, 'existing authorization'):
            self.module.prepare(binary=self.binary, root=self.root)
        self.assertEqual(secret.read_text(), 'existing private material')

    def test_unreviewed_offset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'reviewed client capture offset'):
            self.module.prepare(offset=1234, binary=self.binary, root=self.root)
        self.assertFalse((self.root / 'capture-child.gdb').exists())


class ReceiverReadinessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.requests = []
        self.token = 'a' * 64
        self.thread = '11111111-1111-4111-8111-111111111111'
        self.health = {'backend': 'local-codex', 'ready': True,
                       'desktop_all_requests': True, 'desktop_thread_id': self.thread}
        self.mode = 'normal'
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                if self.headers.get('Authorization') != 'Bearer ' + owner.token:
                    self.send_response(403)
                    self.end_headers()
                elif owner.mode == 'redirect':
                    self.send_response(302)
                    self.send_header('Location', '/must-not-follow')
                    self.end_headers()
                else:
                    data = json.dumps(owner.health).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)
        port = self.server.server_address[1]
        self.config = {'token': self.token, 'desktop_thread_id': self.thread,
                       'desktop_all_requests': True, 'port': port, 'remote_port': port}
        self.path = self.root / 'receiver.json'
        self.write_config()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)

    def write_config(self):
        self.path.write_text(json.dumps(self.config))
        self.path.chmod(0o600)

    def test_network_probe_requires_explicit_option(self):
        self.assertEqual(onboarding.receiver_stage(self.path)['state'], 'configured')
        self.assertEqual(self.requests, [])
        self.assertEqual(onboarding.receiver_stage(self.path, probe=True)['state'], 'ready')
        self.assertEqual(self.requests, ['/health'])

    def test_wrong_token_and_changed_target_are_redacted(self):
        self.config['token'] = 'b' * 64
        self.write_config()
        result = onboarding.receiver_stage(self.path, probe=True)
        self.assertEqual(result['code'], 'RECEIVER_AUTH_REJECTED')
        self.assertNotIn(self.token, json.dumps(result))
        self.config['token'] = self.token
        self.write_config()
        self.health['desktop_thread_id'] = '22222222-2222-4222-8222-222222222222'
        self.assertEqual(onboarding.receiver_stage(self.path, probe=True)['state'], 'blocked')

    def test_authenticated_health_never_follows_redirect(self):
        self.mode = 'redirect'
        self.assertEqual(onboarding.receiver_stage(self.path, probe=True)['code'], 'RECEIVER_HTTP_ERROR')
        self.assertEqual(self.requests, ['/health'])

    def test_ready_receiver_does_not_claim_wechat_delivery(self):
        status = {'read': {'ready': False, 'checks': {'crypto_installed': True}},
                  'desktop': {'dependencies_ready': False, 'checks': {'pillow_installed': True, 'gtk_installed': True}},
                  'operations': {'ready': False, 'checks': {'enabled': False}}}
        with patch('rsi_agent.onboarding.sys.platform', 'linux'), \
                patch('rsi_agent.onboarding.private_file', return_value=True), \
                patch('rsi_agent.onboarding.doctor', return_value=status), \
                patch('rsi_agent.onboarding.shutil.which', return_value='/fixture/tool'), \
                patch('rsi_agent.onboarding.capture_module') as capture:
            capture.return_value.release.return_value = {'version': 'fixture'}
            result = onboarding.check(receiver_config=self.path, probe=True)
        self.assertEqual(result['stages']['receiver']['state'], 'ready')
        self.assertFalse(result['ready_for_acceptance'])
        self.assertEqual(result['live_delivery'], 'not_verified')
        self.assertEqual(result['stages']['account']['state'], 'blocked')

    @unittest.skipUnless(sys.platform == 'linux', 'complete Linux readiness uses native file ownership')
    def test_configured_installation_still_requires_native_acceptance(self):
        status = {'read': {'ready': True, 'checks': {'crypto_installed': True}},
                  'desktop': {'dependencies_ready': True, 'checks': {'pillow_installed': True, 'gtk_installed': True}},
                  'operations': {'ready': True, 'checks': {'enabled': True}}}
        from rsi_agent.config import load
        config = load()
        config['wechat']['runtime_root'] = str(self.root)
        with patch('rsi_agent.onboarding.load', return_value=config), \
                patch('rsi_agent.onboarding.doctor', return_value=status), \
                patch('rsi_agent.onboarding.shutil.which', return_value='/fixture/tool'), \
                patch('rsi_agent.onboarding.capture_module') as capture:
            capture.return_value.release.return_value = {'version': 'fixture'}
            result = onboarding.check(receiver_config=self.path, probe=True)
        self.assertTrue(result['ready_for_acceptance'])
        self.assertEqual(result['state'], 'configured')
        self.assertEqual(result['live_delivery'], 'not_verified')
        self.assertFalse(result['stages']['account']['native_read_verified'])
        self.assertFalse(result['stages']['display']['login_verified'])
