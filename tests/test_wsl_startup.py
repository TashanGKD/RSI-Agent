import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from rsi_agent.config import ROOT


@unittest.skipUnless(sys.platform == 'win32', 'requires Windows PowerShell and Task Scheduler types')
class WindowsStartupTests(unittest.TestCase):
    def test_startup_scripts_parse_in_windows_powershell(self):
        for name in ('Start-Local.ps1', 'Register-Startup.ps1', 'Install-WeChat.ps1', 'Show-Login.ps1'):
            script = str(ROOT / 'deploy/wechat-wsl' / name).replace("'", "''")
            command = ("$tokens=$null; $errors=$null; "
                "[System.Management.Automation.Language.Parser]::ParseFile('" + script
                + "',[ref]$tokens,[ref]$errors) | Out-Null; "
                "if ($errors.Count) { $errors | Out-String | Write-Error; exit 1 }")
            result = subprocess.run([
                str(Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
                '-NoProfile', '-NonInteractive', '-Command', command],
                capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)

    def run_registration(self, action, existing=False):
        with tempfile.TemporaryDirectory(prefix='rsi startup ') as folder:
            root = Path(folder)
            release = root / "release with spaces and 'quote"
            launcher = release / 'deploy/wechat-wsl/Start-Local.ps1'
            launcher.parent.mkdir(parents=True)
            launcher.write_text('throw "Fixture launcher must never run"')
            receiver = release / 'receiver/codex_worker.py'
            receiver.parent.mkdir()
            receiver.write_text('raise RuntimeError("Fixture receiver must never run")')
            config = root / "private 'config.json"
            config.write_text('fixture-secret-must-not-appear')
            def literal(value):
                return "'" + str(value).replace("'", "''") + "'"
            harness = root / 'check.ps1'
            harness.write_text('''$ErrorActionPreference = 'Stop'
$global:registered = $null
function Get-ScheduledTask { param($TaskName, $ErrorAction) EXISTING }
function New-ScheduledTaskAction { param($Execute, $Argument, $WorkingDirectory) @{ Execute=$Execute; Arguments=$Argument; Directory=$WorkingDirectory } }
function New-ScheduledTaskTrigger { param([switch]$AtLogOn, $User) @{ User=$User } }
function New-ScheduledTaskPrincipal { param($UserId, $LogonType, $RunLevel) @{ User=$UserId; Logon=$LogonType; RunLevel=$RunLevel } }
function New-ScheduledTaskSettingsSet { param($MultipleInstances, $RestartCount, $RestartInterval, $ExecutionTimeLimit, [switch]$AllowStartIfOnBatteries, [switch]$DontStopIfGoingOnBatteries) @{ Instances=$MultipleInstances; Restarts=$RestartCount; Limit=$ExecutionTimeLimit.TotalSeconds } }
function Register-ScheduledTask { param($TaskName, $Action, $Trigger, $Principal, $Settings, $Description) $global:registered=@{ Name=$TaskName; Action=$Action; Principal=$Principal; Settings=$Settings } }
function Start-ScheduledTask { throw 'Must not start a task' }
function Unregister-ScheduledTask { throw 'Must not remove a task' }
'''.replace('EXISTING', "[PSCustomObject]@{State='Ready'; Description='existing'}" if existing else '$null')
                + '\n& ' + literal(ROOT / 'deploy/wechat-wsl/Register-Startup.ps1')
                + ' -Action ' + action + ' -Release ' + literal(release)
                + ' -Config ' + literal(config) + ' -Python ' + literal(sys.executable)
                + '\n$global:registered | ConvertTo-Json -Depth 5 -Compress\n', encoding='utf-8-sig')
            result = subprocess.run([
                str(Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'),
                '-NoProfile', '-NonInteractive', '-File', str(harness)],
                capture_output=True, text=True, timeout=20)
            self.assertNotIn('fixture-secret-must-not-appear', result.stdout + result.stderr)
            return result

    def test_check_does_not_register_or_read_secret(self):
        result = self.run_registration('Check')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('Registered RSI-', result.stdout)

    def test_register_creates_interactive_logon_task_without_starting(self):
        result = self.run_registration('Register')
        self.assertEqual(result.returncode, 0, result.stderr)
        task = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(task['Name'], 'RSI-WeChat-Receiver')
        self.assertEqual(task['Principal']['Logon'], 'Interactive')
        self.assertEqual(task['Principal']['RunLevel'], 'Limited')
        self.assertEqual(task['Settings'], {'Instances': 'IgnoreNew', 'Restarts': 3, 'Limit': 0})
        self.assertIn(' -File "', task['Action']['Arguments'])
        self.assertIn("release with spaces and 'quote", task['Action']['Arguments'])
        self.assertIn("private 'config.json", task['Action']['Arguments'])

    def test_existing_registration_is_preserved(self):
        result = self.run_registration('Register', existing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('existing task is preserved', result.stderr)

    def test_launcher_refuses_missing_owner_service_before_starting_receiver(self):
        # The launcher's keepalive client may still hold the fake wsl.exe during cleanup.
        with tempfile.TemporaryDirectory(prefix='rsi launcher ', ignore_cleanup_errors=True) as folder:
            root = Path(folder)
            fake_windows = root / 'Windows/System32'
            fake_windows.mkdir(parents=True)
            release = root / 'release'
            (release / 'receiver').mkdir(parents=True)
            (release / 'receiver/codex_worker.py').write_text(
                'import os,pathlib\npathlib.Path(os.environ["RSI_FIXTURE_MARKER"]).touch()\n')
            config = root / 'config.json'
            config.write_text('{}')
            marker = root / 'receiver-started'
            powershell = str(Path(os.environ['WINDIR']) / 'System32/WindowsPowerShell/v1.0/powershell.exe')
            def literal(value):
                return "'" + str(value).replace("'", "''") + "'"
            source = 'public class Stub { public static int Main(string[] args) { return string.Join(" ",args).Contains("is-active") && System.Environment.GetEnvironmentVariable("RSI_FIXTURE_OWNER_ACTIVE")!="1" ? 7 : 0; } }'
            compiled = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-Command',
                'Add-Type -TypeDefinition ' + literal(source) + ' -OutputAssembly '
                + literal(fake_windows / 'wsl.exe') + ' -OutputType ConsoleApplication'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            harness = root / 'launch.ps1'
            harness.write_text('$ErrorActionPreference="Stop"\n$env:WINDIR=' + literal(root / 'Windows')
                + '\n& ' + literal(ROOT / 'deploy/wechat-wsl/Start-Local.ps1')
                + ' -Release ' + literal(release) + ' -Config ' + literal(config)
                + ' -Python ' + literal(sys.executable), encoding='utf-8-sig')
            for active in ('0', '1'):
                result = subprocess.run([powershell, '-NoProfile', '-NonInteractive', '-File', str(harness)],
                    env=dict(os.environ, RSI_FIXTURE_OWNER_ACTIVE=active, RSI_FIXTURE_MARKER=str(marker)),
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(marker.exists(), active == '1')
                self.assertEqual(result.returncode == 0, active == '1', result.stderr)
