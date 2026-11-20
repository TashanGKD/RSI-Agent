"""Private Xauthority creation and bounded X/VNC readiness, run as wechat-gui."""
import argparse
import os
from pathlib import Path
import re
import secrets
import socket
import stat
import subprocess
import tempfile
import time


def prepare(root, display):
    root = Path(root)
    if not re.fullmatch(r':[0-9]+', display):
        raise ValueError('Explicit local display required')
    info = root.stat()
    if root.is_symlink() or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('Private runtime directory owned by the service user required')
    vnc_socket = root / 'vnc.sock'
    if vnc_socket.exists() or vnc_socket.is_symlink():
        raise ValueError('Existing VNC socket is preserved; stop the owned X service first')
    x_socket = Path('/tmp/.X11-unix') / ('X' + display[1:])
    if x_socket.exists() or x_socket.is_symlink():
        raise ValueError('Existing X socket is preserved; stop the owned X service first')
    with socket.socket(socket.AF_UNIX) as probe:
        probe.settimeout(.5)
        try:
            probe.connect('\0' + str(x_socket))
        except OSError:
            pass
        else:
            raise ValueError('Existing X socket is preserved; stop the owned X service first')
    target = root / 'Xauthority'
    if target.is_symlink() or (target.exists() and (
            not target.is_file() or target.stat().st_uid != os.getuid() or target.stat().st_mode & 0o077)):
        raise ValueError('Existing authorization is not a private owned regular file')
    fd, name = tempfile.mkstemp(prefix='.Xauthority-', dir=root)
    os.close(fd)
    try:
        result = subprocess.run(['xauth', '-f', name, 'source', '-'],
            input='add ' + display + ' . ' + secrets.token_hex(16) + '\n', text=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        if result.returncode:
            raise ValueError('Xauthority generation failed')
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def wait_ready(root, display, seconds=20, require_vnc=True):
    root = Path(root)
    env = dict(os.environ, XAUTHORITY=str(root / 'Xauthority'))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if not require_vnc or (root / 'vnc.sock').is_socket():
            try:
                result = subprocess.run(['xdpyinfo', '-display', display], env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=min(3, max(.01, end - time.monotonic())))
                if result.returncode == 0:
                    return
            except subprocess.TimeoutExpired:
                pass
        time.sleep(.1)
    raise ValueError('Private X/VNC readiness timed out' if require_vnc else 'Private X readiness timed out')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'wait'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--display', required=True)
    parser.add_argument('--x-only', action='store_true', help='Wait for X11 without requiring a VNC socket.')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == 'prepare':
            if args.x_only:
                raise ValueError('--x-only applies only to wait')
            prepare(args.root, args.display)
        else:
            wait_ready(args.root, args.display, require_vnc=not args.x_only)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + '\n')
