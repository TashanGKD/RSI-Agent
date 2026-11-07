"""Read-only checks of the configured Linux desktop, without opening chat data."""
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import re
import subprocess
import sys

from .config import WORKBENCH
from .wechat import doctor, environment

SERVICES = ('wechat-gui-x.service', 'wechat-gui-desktop.service', 'wechat-gui-web.service')


def audit(config, run=None, proc=Path('/proc')):
    report = {
        'schema_version': 1, 'checked_at': datetime.now(timezone.utc).isoformat(),
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

    try:
        spec = importlib.util.spec_from_file_location('rsi_window_metadata', WORKBENCH / 'wechat/operations/windows.py')
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
        fragments = command(['systemctl', 'show', *SERVICES, '--property=FragmentPath', '--value']).split()
        checks['persistent_desktop_services'] = len(fragments) == len(SERVICES) and all(
            p.startswith(('/etc/systemd/system/', '/usr/lib/systemd/system/', '/lib/systemd/system/')) for p in fragments)
        if not checks['persistent_desktop_services']:
            report['findings'].append('SERVICES_NOT_PERSISTENT')
    except (OSError, subprocess.TimeoutExpired):
        checks['persistent_desktop_services'] = False
        report['findings'].append('SERVICES_UNVERIFIED')
    report['health'] = 'pass' if all(checks.values()) else 'degraded'
    return report
