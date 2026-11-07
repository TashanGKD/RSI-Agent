"""Private Xauthority creation and bounded X/VNC readiness, run as wechat-gui."""
import argparse
import os
from pathlib import Path
import re
import secrets
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
    socket = root / 'vnc.sock'
    if socket.exists() or socket.is_symlink():
        raise ValueError('Existing VNC socket is preserved; stop the owned X service first')
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


def wait_ready(root, display, seconds=20):
    root = Path(root)
    env = dict(os.environ, XAUTHORITY=str(root / 'Xauthority'))
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if (root / 'vnc.sock').is_socket():
            try:
                result = subprocess.run(['xdpyinfo', '-display', display], env=env,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
                if result.returncode == 0:
                    return
            except subprocess.TimeoutExpired:
                pass
        time.sleep(.1)
    raise ValueError('Private X/VNC readiness timed out')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'wait'])
    parser.add_argument('--root', required=True)
    parser.add_argument('--display', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        (prepare if args.action == 'prepare' else wait_ready)(args.root, args.display)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        parser.exit(1, str(error) + '\n')
