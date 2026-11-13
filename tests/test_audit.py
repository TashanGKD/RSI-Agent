import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rsi_agent import __main__ as cli
from rsi_agent.config import load
from rsi_agent.audit import audit
from rsi_agent.config import ROOT


class RuntimeAuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.proc = Path(self.folder.name)
        (self.proc / '42').mkdir()
        (self.proc / '42/status').write_text('Name:\twechat\nTracerPid:\t0\n')
        self.geometry = '905x667+0+0  +131+120'
        self.fragments = ['/etc/systemd/system/' + name + '.service'
                          for name in ('wechat-gui-x', 'wechat-gui-desktop', 'wechat-gui-web')]
        self.prerequisites = {'read': {'ready': True}, 'desktop': {'dependencies_ready': True},
                              'operations': {'ready': True}}
        self.reply_units = {}

    def run_command(self, command, **kwargs):
        if command[:3] == ['xwininfo', '-root', '-tree']:
            output = '  0x10 "Weixin": ("wechat" "wechat") ' + self.geometry + '\n'
            output += '  0x11 "Private Contact": ("wechat" "wechat") 623x667+0+0  +400+300\n'
        elif command[0] == 'xwininfo':
            output = 'Map State: IsViewable\n'
        elif command[0] == 'xprop':
            output = '_NET_WM_PID(CARDINAL) = 42\n'
        elif command[0] == 'systemctl':
            if command[2].startswith('rsi-'):
                output = self.reply_units.get(command[2], 'LoadState=not-found\nActiveState=inactive\n')
            else:
                output = '\n\n'.join(self.fragments) + '\n'
        else:
            self.fail('Audit attempted an unexpected command: ' + command[0])
        return SimpleNamespace(returncode=0, stdout=output)

    def inspect(self, run=None):
        with patch('rsi_agent.audit.sys.platform', 'linux'), patch('rsi_agent.audit.doctor', return_value=self.prerequisites):
            return audit(load(), run=run or self.run_command, proc=self.proc)

    def test_normal_visible_client_and_persistent_services_pass(self):
        result = self.inspect()
        self.assertEqual(result['health'], 'pass')
        self.assertEqual(result['main_geometry'], [905, 667])
        self.assertNotIn('Private Contact', json.dumps(result))

    def test_ready_doctor_does_not_hide_debugger_layout_or_transient_units(self):
        (self.proc / '42/status').write_text('TracerPid:\t77\n')
        self.geometry = '623x667+0+0  +131+120'
        self.fragments = ['/run/systemd/transient/a.service'] * 3
        result = self.inspect()
        self.assertEqual(result['health'], 'degraded')
        self.assertEqual(set(result['findings']), {'DEBUGGER_ATTACHED', 'MAIN_LAYOUT_UNCALIBRATED', 'SERVICES_NOT_PERSISTENT'})

    def test_display_timeout_blocks_without_printing_raw_errors(self):
        def unavailable(*args, **kwargs):
            raise subprocess.TimeoutExpired('private host details', 5)
        result = self.inspect(unavailable)
        self.assertEqual(result['health'], 'blocked')
        self.assertNotIn('private host details', json.dumps(result))

    def test_missing_process_status_is_unverified(self):
        (self.proc / '42/status').unlink()
        self.assertIn('PROCESS_STATE_UNAVAILABLE', self.inspect()['findings'])

    def test_unsupported_platform_does_not_probe(self):
        with patch('rsi_agent.audit.sys.platform', 'win32'), patch('rsi_agent.audit.subprocess.run') as run:
            self.assertEqual(audit(load())['health'], 'unsupported')
            run.assert_not_called()

    def test_reply_source_checks_both_resident_processes_not_only_current(self):
        owner, group = 'rsi-owner-replies.service', 'rsi-group-replies.service'
        for name, pid in ((owner, 101), (group, 102)):
            self.reply_units[name] = ('LoadState=loaded\nActiveState=active\nMainPID=' + str(pid)
                                      + '\nWorkingDirectory=' + str(ROOT) + '\n')
        # A reloaded unit already points to the new source; its running owner
        # process still imports the previous image locator.
        def resident(path):
            return self.proc if path.parent.name == '101' else ROOT
        with patch.object(Path, 'readlink', resident):
            result = self.inspect()
        self.assertEqual(result['health'], 'degraded')
        self.assertIn('REPLY_SERVICE_SOURCE_MISMATCH', result['findings'])
        self.assertFalse(result['checks']['rsi_owner_replies_source'])
        self.assertTrue(result['checks']['rsi_group_replies_source'])
        self.assertTrue(result['reply_services'][owner]['configured_source_matches'])
        with patch.object(Path, 'readlink', return_value=ROOT):
            self.assertEqual(self.inspect()['health'], 'pass')

    def test_reply_source_missing_process_is_unverified(self):
        self.reply_units['rsi-owner-replies.service'] = (
            'LoadState=loaded\nActiveState=active\nMainPID=101\nWorkingDirectory=' + str(ROOT) + '\n')
        with patch.object(Path, 'readlink', side_effect=FileNotFoundError):
            result = self.inspect()
        self.assertIn('REPLY_SERVICE_SOURCE_UNVERIFIED', result['findings'])

    def test_cli_returns_nonzero_for_a_degraded_runtime(self):
        with patch('rsi_agent.__main__.audit', return_value={'health': 'degraded'}):
            self.assertEqual(cli.main(['audit']), 1)
