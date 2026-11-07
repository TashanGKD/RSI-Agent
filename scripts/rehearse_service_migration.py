"""Rehearse only disposable systemd/X/VNC units; never launch WeChat or enable boot."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rsi_agent.service_bundle import stage


def run(*argv, check=True):
    return subprocess.run(argv, check=check, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=40).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Create, exercise and remove isolated units as root.')
    args = parser.parse_args()
    if not args.execute:
        parser.print_help()
        return
    if sys.platform != 'linux' or os.getuid() != 0 or Path('/proc/1/comm').read_text().strip() != 'systemd':
        parser.error('An authorized Linux host with root and systemd PID 1 is required.')
    import pwd
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    prefix = 'rsi-wx-rehearsal-' + secrets.token_hex(5)
    runtime = Path('/run') / prefix
    saved_runtime = Path('/run') / (prefix + '-previous')
    display = ':' + str(next(n for n in range(193, 250)
        if not Path(f'/tmp/.X{n}-lock').exists() and not Path(f'/tmp/.X11-unix/X{n}').exists()))
    account = pwd.getpwnam('wechat-gui')
    names = {p.name: p.name.replace('wechat-gui', prefix)
             for p in (ROOT / 'deploy/wechat-gui/systemd').iterdir() if p.is_file()}
    services = [names['wechat-gui-' + part + '.service'] for part in ('x', 'desktop', 'web')]
    target, gateway = names['wechat-gui.target'], names['wechat-gui-proxy.socket']
    owned_files = {}
    claimed = False
    production = {name: run('systemctl', 'show', name, '--property=MainPID', '--value')
                  for name in ('wechat-gui-x.service', 'wechat-gui-desktop.service', 'wechat-gui-web.service')}
    report = {'scope': 'isolated units; desktop is sleep, no WeChat/account access or boot enable',
              'prefix': prefix, 'display': display, 'phases': {}}

    def write_new(path, text):
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        owned_files[path] = text.encode()

    def remove_owned(path):
        if path.exists():
            if path.is_symlink() or path.read_bytes() != owned_files[path]:
                raise RuntimeError('Fixture definition changed; preserve it: ' + str(path))
            path.unlink()

    def stop_fixture():
        if not claimed:
            return
        rows = run('systemctl', 'list-units', '--all', '--plain', '--no-legend', '--no-pager', prefix + '*')
        units = [line.split()[0] for line in rows.splitlines() if line.split()[1] == 'loaded' and line.split()[0].startswith(prefix)
                 and line.split()[0].endswith(('.service', '.socket', '.target'))]
        if units:
            run('systemctl', 'stop', *units)
            run('systemctl', 'reset-failed', *units, check=False)

    def transient_start():
        runtime.mkdir(mode=0o700)
        os.chown(runtime, account.pw_uid, account.pw_gid)
        helper = str(ROOT / 'deploy/wechat-gui/prepare_runtime.py')
        run('runuser', '-u', 'wechat-gui', '--', 'python3', helper, 'prepare', '--root', str(runtime), '--display', display)
        for name in services:
            command = next(line.removeprefix('ExecStart=') for line in rendered[name].splitlines() if line.startswith('ExecStart='))
            properties = ['--property=UMask=0077', '--property=RuntimeMaxSec=180']
            if name == services[2]:
                properties += ['--property=PrivateNetwork=yes']
            run('systemd-run', '--quiet', '--unit=' + name, '--service-type=exec',
                '--uid=wechat-gui', '--gid=wechat-gui', *properties, '--', *shlex.split(command))
            if name == services[0]:
                run('runuser', '-u', 'wechat-gui', '--', 'python3', helper, 'wait', '--root', str(runtime), '--display', display)
        run('systemctl', 'start', gateway)

    def probe():
        # Full private chain: Unix gateway -> shared network namespace -> noVNC -> X/VNC.
        deadline = time.monotonic() + 12
        while True:
            try:
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(runtime / 'web.sock'))
                    client.sendall(b'GET /vnc.html HTTP/1.0\r\nHost: localhost\r\n\r\n')
                    page = b''
                    while part := client.recv(65536):
                        page += part
                    if b' 200 ' not in page.split(b'\r\n', 1)[0] or b'noVNC' not in page:
                        raise ValueError('noVNC HTTP page unavailable')
                with socket.socket(socket.AF_UNIX) as client:
                    client.settimeout(3)
                    client.connect(str(runtime / 'web.sock'))
                    client.sendall(b'GET /websockify HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n')
                    data = b''
                    while b'\r\n\r\n' not in data:
                        part = client.recv(4096)
                        if not part:
                            raise ValueError('WebSocket ended before handshake')
                        data += part
                    header, payload = data.split(b'\r\n\r\n', 1)
                    if b' 101 ' not in header.split(b'\r\n', 1)[0]:
                        raise ValueError('WebSocket upgrade failed')
                    while b'RFB ' not in payload:
                        part = client.recv(4096)
                        if not part:
                            raise ValueError('VNC banner missing from WebSocket')
                        payload += part
                for filename in ('web.sock', 'vnc.sock', 'Xauthority'):
                    if (runtime / filename).stat().st_mode & 0o777 != 0o600:
                        raise ValueError('Fixture permission mismatch')
                return {'http': 200, 'websocket': 101, 'rfb_banner': True, 'private_modes': '0600'}
            except (OSError, ValueError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)

    def paths():
        return {name: run('systemctl', 'show', name, '--property=FragmentPath', '--value') for name in services}

    with tempfile.TemporaryDirectory(prefix=prefix + '-') as scratch:
        try:
            stage(ROOT.as_posix(), Path(scratch) / 'bundle')
            rendered = {}
            for original, name in names.items():
                text = (Path(scratch) / 'bundle' / original).read_text()
                for old, new in names.items():
                    text = text.replace(old, new)
                text = text.replace('/run/wechat-gui', str(runtime)).replace('RuntimeDirectory=wechat-gui', 'RuntimeDirectory=' + prefix).replace(':92', display)
                text = text.replace('/data/docker/volumes/teamctx-mattermost_caddy_data/_data/wechat-gui', str(runtime))
                text = text.replace('RequiresMountsFor=/data/docker/volumes/teamctx-mattermost_caddy_data/_data', 'RequiresMountsFor=/run')
                if name == services[1]:
                    text = '\n'.join('ExecStart=/usr/bin/sleep infinity' if line.startswith('ExecStart=') else line for line in text.splitlines()) + '\n'
                rendered[name] = text
                for base in ('/etc/systemd/system', '/run/systemd/system', '/run/systemd/transient'):
                    if (Path(base) / name).exists() or (Path(base) / name).is_symlink():
                        raise RuntimeError('Fixture name already exists')
            if any(p.exists() or p.is_symlink() for p in (runtime, saved_runtime)):
                raise RuntimeError('Fixture runtime already exists')
            claimed = True
            for name in (gateway, names['wechat-gui-proxy@.service']):
                write_new(Path('/run/systemd/system') / name, rendered[name])
            run('systemctl', 'daemon-reload')
            transient_start()
            report['phases']['transient'] = {'paths': paths(), **probe()}
            for name, text in rendered.items():
                write_new(Path('/etc/systemd/system') / name, text)
            run('systemctl', 'daemon-reload')
            shadowed = paths()
            if not all(p.startswith('/run/systemd/transient/') for p in shadowed.values()):
                raise RuntimeError('Transient load-priority hypothesis was false')
            report['transient_still_shadows_etc_after_reload'] = True
            stop_fixture()
            run('systemctl', 'daemon-reload')
            if any((Path('/run/systemd/transient') / name).exists() for name in services):
                raise RuntimeError('Stopped transient definitions did not unload')
            runtime.rename(saved_runtime)
            run('systemctl', 'start', target)
            persistent = paths()
            if not all(p.startswith('/etc/systemd/system/') for p in persistent.values()):
                raise RuntimeError('Persistent definitions were not selected')
            report['phases']['persistent'] = {'paths': persistent, **probe()}
            run('systemctl', 'stop', target)
            report['runtime_present_on_target_stop_return'] = runtime.exists()
            # Waiting for the target's own job does not wait for all propagated stops.
            stop_fixture()
            if runtime.exists():
                raise RuntimeError('RuntimeDirectory was not cleaned on target stop')
            for path in owned_files:
                if path.parent == Path('/etc/systemd/system'):
                    remove_owned(path)
            run('systemctl', 'daemon-reload')
            transient_start()
            report['phases']['rollback'] = {'paths': paths(), **probe()}
        finally:
            stop_fixture()
            for path in owned_files:
                remove_owned(path)
            run('systemctl', 'daemon-reload')
            for folder in (runtime, saved_runtime):
                if claimed and folder.exists():
                    if folder.parent != Path('/run') or not folder.name.startswith(prefix) or folder.is_symlink():
                        raise RuntimeError('Refuse cleanup outside the owned fixture')
                    shutil.rmtree(folder)
            after = {name: run('systemctl', 'show', name, '--property=MainPID', '--value') for name in production}
            report['production_service_pids_unchanged'] = after == production
            report['cleanup_complete'] = not any(p.exists() for p in owned_files) and not runtime.exists() and not saved_runtime.exists()
            print(json.dumps(report, indent=2))
            if after != production:
                raise RuntimeError('Production PID changed during rehearsal; investigate')


if __name__ == '__main__':
    main()
