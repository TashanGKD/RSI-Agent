"""Read-only checks of the configured Linux desktop, without opening chat data."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

from .config import ROOT, WECHAT_LINUX
from .wechat import doctor, environment

SERVICES = ('wechat-gui-x.service', 'wechat-gui-desktop.service', 'wechat-gui-web.service')
REPLY_SERVICES = ('rsi-owner-replies.service', 'rsi-group-replies.service')


def audit(config, run=None, proc=Path('/proc'), profile='server'):
    if profile not in ('server', 'wsl'):
        raise ValueError('Unknown desktop service profile.')
    report = {
        'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
        'desktop_profile': profile,
        'health': 'unsupported', 'checks': {}, 'findings': [],
        'scope': 'Process, layout and installation checks; no message read/send or recovery test.',
    }
    if sys.platform != 'linux':
        report['findings'].append('LINUX_REQUIRED')
        return report
    run = run or subprocess.run
    status = doctor(config)
    checks = report['checks']
    checks['installation_prerequisites'] = all((status['read']['ready'],
        status['desktop']['dependencies_ready'], status['operations']['ready']))
    if not checks['installation_prerequisites']:
        report['findings'].append('INSTALLATION_PREREQUISITES_INCOMPLETE')
    wx = config['wechat']
    env = dict(environment(config), DISPLAY=wx['display'], XAUTHORITY=wx['xauthority'])

    def command(args):
        result = run(args, env=env, capture_output=True, text=True, timeout=5)
        if result.returncode or len(result.stdout) > 100000:
            raise OSError('Runtime metadata unavailable')
        return result.stdout

    # A new current pointer does not upgrade either resident reply process.
    report['reply_services'] = {}
    for name in REPLY_SERVICES:
        check = name.removesuffix('.service').replace('-', '_') + '_source'
        try:
            unit = dict(line.split('=', 1) for line in command([
                'systemctl', 'show', name,
                '--property=LoadState,ActiveState,MainPID,WorkingDirectory']).splitlines())
            if unit['LoadState'] == 'not-found' or unit['ActiveState'] == 'inactive':
                report['reply_services'][name] = {'state': unit['ActiveState']}
                continue
            pid = int(unit['MainPID'])
            if pid <= 0 or unit['ActiveState'] != 'active':
                raise ValueError('Reply worker is not active')
            loaded = (Path(proc) / str(pid) / 'cwd').readlink().resolve(strict=True)
            configured = Path(unit['WorkingDirectory']).resolve(strict=True)
            expected = ROOT.resolve(strict=True)
            checks[check] = loaded == configured == expected
            report['reply_services'][name] = {
                'state': unit['ActiveState'], 'pid': pid,
                'loaded_source_matches': loaded == expected,
                'configured_source_matches': configured == expected,
            }
            if not checks[check]:
                report['findings'].append('REPLY_SERVICE_SOURCE_MISMATCH')
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
            checks[check] = False
            report['reply_services'][name] = {'state': 'unverified'}
            report['findings'].append('REPLY_SERVICE_SOURCE_UNVERIFIED')

    try:
        spec = importlib.util.spec_from_file_location('rsi_window_metadata', WECHAT_LINUX / 'operations/windows.py')
        windows = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(windows)
        main = [w for w in windows.parse_app_windows(command(['xwininfo', '-root', '-tree']))
                if w['title'] == 'Weixin' and 'Map State: IsViewable' in command(['xwininfo', '-id', w['id']])]
        if len(main) != 1:
            raise ValueError('Official main window is not unique')
        window = main[0]
        matches = re.findall(r'^_NET_WM_PID\(CARDINAL\) = ([0-9]+)$',
                             command(['xprop', '-id', window['id'], '_NET_WM_PID']), re.M)
        if len(matches) != 1:
            raise ValueError('Official process identity unavailable')
    except (OSError, ValueError, subprocess.TimeoutExpired):
        checks['official_client_visible'] = False
        report.update(health='blocked')
        report['findings'].append('OFFICIAL_CLIENT_UNAVAILABLE')
        return report

    checks['official_client_visible'] = True
    report['main_geometry'] = [window['width'], window['height']]
    checks['calibrated_main_geometry'] = report['main_geometry'] == [905, 667]
    if not checks['calibrated_main_geometry']:
        report['findings'].append('MAIN_LAYOUT_UNCALIBRATED')
    try:
        status = (Path(proc) / matches[0] / 'status').read_text()
        tracer = re.findall(r'^TracerPid:\s*([0-9]+)$', status, re.M)
        checks['ordinary_process'] = len(tracer) == 1 and int(tracer[0]) == 0
        if not checks['ordinary_process']:
            report['findings'].append('DEBUGGER_ATTACHED' if len(tracer) == 1 else 'PROCESS_STATE_UNAVAILABLE')
    except OSError:
        checks['ordinary_process'] = False
        report['findings'].append('PROCESS_STATE_UNAVAILABLE')
    try:
        services = SERVICES[:2] if profile == 'wsl' else SERVICES
        fragments = command(['systemctl', 'show', *services, '--property=FragmentPath', '--value']).split()
        checks['persistent_desktop_services'] = len(fragments) == len(services) and all(
            p.startswith(('/etc/systemd/system/', '/usr/lib/systemd/system/', '/lib/systemd/system/')) for p in fragments)
        if not checks['persistent_desktop_services']:
            report['findings'].append('SERVICES_NOT_PERSISTENT')
    except (OSError, subprocess.TimeoutExpired):
        checks['persistent_desktop_services'] = False
        report['findings'].append('SERVICES_UNVERIFIED')
    report['health'] = 'pass' if all(checks.values()) else 'degraded'
    return report
