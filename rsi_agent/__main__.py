import argparse
import json
from pathlib import Path
import subprocess
import sys

from . import __version__
from .config import MAC, ROOT, WORKBENCH, load
from .wechat import call, doctor


def main(argv=None):
    parser = argparse.ArgumentParser(description='RSI Agent: notebook, Linux WeChat, and Mac source checks.')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--config', help='Private installation JSON; never commit real account settings.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('doctor', help='Report prerequisites without reading messages or operating the GUI.')
    commands.add_parser('sources', help='Show the pinned source repositories and commits.')
    wx = commands.add_parser('wechat', help='Use the original on-demand WeChat SDK.')
    wx.add_argument('mode', choices=['read', 'operations'], help='One JSON request from stdin.')
    notebook = commands.add_parser('notebook', help='Start the existing local notebook.')
    notebook.add_argument('--workspace', required=True)
    notebook.add_argument('--port', type=int, default=8876)
    notebook.add_argument('--demo', action='store_true', help='Create synthetic data in a NEW directory first.')
    mac = commands.add_parser('mac', help='Mac-specific source checks; not a Linux application.')
    mac.add_argument('mode', choices=['verify'])
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == 'sources':
        print((ROOT / 'SOURCES.lock.json').read_text(encoding='utf-8'))
        return 0
    if args.command == 'mac':
        return subprocess.call([sys.executable, '-B', 'tools/verify_package.py'], cwd=MAC)
    if args.command == 'notebook':
        if not 1 <= args.port <= 65535:
            raise ValueError('Port must be between 1 and 65535.')
        workspace = Path(args.workspace).expanduser().absolute()
        if args.demo:
            if workspace.exists():
                raise ValueError('The demo directory already exists; existing data will not be overwritten.')
            subprocess.run([sys.executable, '-B', 'examples/seed_demo.py', '--workspace', str(workspace), '--apply'], cwd=WORKBENCH, check=True)
        if not workspace.is_dir():
            raise ValueError('Workspace missing; use --demo with a new directory or supply an existing notebook.')
        return subprocess.call([sys.executable, '-B', 'notebook/local_server.py', '--workspace', str(workspace), '--port', str(args.port)], cwd=WORKBENCH)
    config = load(args.config)
    if args.command == 'doctor':
        print(json.dumps(doctor(config), ensure_ascii=False, indent=2))
        return 0
    raw = sys.stdin.read(1500001)
    if len(raw.encode()) > 1500000:
        raise ValueError('Request too large.')
    return call(config, args.mode, json.loads(raw))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(json.dumps({'state': 'blocked', 'reason': str(error)}, ensure_ascii=False))
        raise SystemExit(2)
