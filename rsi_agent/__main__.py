import argparse
import json
import sys

from . import __version__
from .audit import audit
from .config import ROOT, load
from .service_bundle import stage
from .wechat import call, doctor


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='RSI Agent: connect authorized WeChat input to the local Codex receiver.',
        epilog='Local Codex receiver: python -m receiver.codex_worker --help.',
    )
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--config', help='Private JSON configuration for the selected command.')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('doctor', help='Report prerequisites without reading messages or operating the GUI.')
    runtime_audit = commands.add_parser('audit', help='Inspect the real Linux client process, layout and service persistence without input.')
    runtime_audit.add_argument('--profile', choices=['server', 'wsl'], default='server',
                               help='Desktop service profile to inspect (default: server).')
    commands.add_parser('sources', help='Show the pinned source repositories and commits.')
    model = commands.add_parser('model', help='Use a privately configured model; no WeChat input or send.')
    model.add_argument('mode', choices=['check', 'reply'])
    replies = commands.add_parser('replies', help='Trigger for authorized private WeChat messages.')
    replies.add_argument('mode', choices=['check', 'once', 'run'])
    groups = commands.add_parser('groups', help='Trigger for enabled WeChat groups.')
    groups.add_argument('mode', choices=['check', 'once', 'run'])
    services = commands.add_parser('services', help='Stage service definitions for review; no live activation.')
    service_commands = services.add_subparsers(dest='mode', required=True)
    service_stage = service_commands.add_parser('stage')
    service_stage.add_argument('--release', required=True, help='Absolute Linux path of the source release.')
    service_stage.add_argument('--output', required=True, help='A NEW directory for the review bundle.')
    service_stage.add_argument('--owner-config', help='Confirmed private owner coordinator; WSL only, no activation.')
    service_stage.add_argument('--python', default='/usr/bin/python3', help='Linux runtime interpreter in the staged owner unit.')
    service_stage.add_argument('--profile', choices=['server', 'wsl'], default='server',
                               help='Server X/VNC stack (default), or a local WSLg/Xephyr desktop.')
    setup = commands.add_parser('setup', help='Prepare pairing or inspect installation stages; no client restart or send.')
    setup_commands = setup.add_subparsers(dest='mode', required=True)
    pairing = setup_commands.add_parser('pair', help='Stage a NEW instance configuration; does not activate it.')
    for name in ('output', 'codex', 'thread', 'ssh', 'identity-file'):
        pairing.add_argument('--' + name, required=True)
    pairing.add_argument('--port', type=int, default=8765)
    pairing.add_argument('--remote-port', type=int, default=8766)
    pairing.add_argument('--remote-root', default='/var/lib/rsi-agent')
    pairing.add_argument('--runtime-root', default='/var/lib/rsi-agent/wechat')
    setup_check = setup_commands.add_parser('check', help='Inspect prerequisites without reading chats or operating the client.')
    setup_check.add_argument('--receiver-config')
    setup_check.add_argument('--probe', action='store_true', help='Explicit authenticated loopback /health check.')
    setup_check.add_argument('--remote', action='store_true', help='Probe the Linux end of the original SSH tunnel.')
    setup_check.add_argument('--binary', default='/opt/wechat/wechat')
    setup_capture = setup_commands.add_parser('prepare-capture', help='Write the reviewed own-child authorization script only.')
    setup_capture.add_argument('--binary', default='/opt/wechat/wechat')
    wx = commands.add_parser('wechat', help='Use the original on-demand WeChat SDK.')
    wx.add_argument('mode', choices=['read', 'operations'], help='One JSON request from stdin.')
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == 'sources':
        print((ROOT / 'SOURCES.lock.json').read_text(encoding='utf-8'))
        return 0
    if args.command == 'setup':
        from .onboarding import check, prepare_capture, stage_pairing
        if args.mode == 'pair':
            result = stage_pairing(args.output, args.codex, args.thread, args.ssh, args.identity_file,
                                   args.port, args.remote_port, args.remote_root, args.runtime_root)
        elif args.mode == 'prepare-capture':
            if not args.config:
                raise ValueError('An explicit private installation configuration is required.')
            result = prepare_capture(args.config, args.binary)
        else:
            result = check(args.config, args.receiver_config, args.probe, args.remote, args.binary)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['state'] == 'incomplete' else 0
    if args.command == 'model':
        from .model import ModelClient
        if not args.config:
            raise ValueError('An explicit private model configuration is required.')
        client = ModelClient(args.config)
        result = client.check() if args.mode == 'check' else {
            'state': 'ok', 'model': client.model, 'text': client.reply(sys.stdin.read(32769))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'replies':
        from trigger.owner_reply import run
        print(json.dumps(run(args.config, args.mode), ensure_ascii=False))
        return 0
    if args.command == 'groups':
        from trigger.group_reply import run
        print(json.dumps(run(args.config, args.mode), ensure_ascii=False))
        return 0
    if args.command == 'services':
        print(json.dumps(stage(args.release, args.output, args.profile,
            owner_config=args.owner_config, python=args.python), ensure_ascii=False, indent=2))
        return 0
    config = load(args.config)
    if args.command == 'doctor':
        print(json.dumps(doctor(config), ensure_ascii=False, indent=2))
        return 0
    if args.command == 'audit':
        report = audit(config, profile=args.profile)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report['health'] == 'pass' else 2 if report['health'] == 'unsupported' else 1
    raw = sys.stdin.read(1500001)
    if len(raw.encode()) > 1500000:
        raise ValueError('Request too large.')
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON key in request.')
            value[key] = item
        return value
    return call(config, args.mode, json.loads(raw, object_pairs_hook=unique_object))


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(json.dumps({'state': 'blocked', 'reason': str(error)}, ensure_ascii=False))
        raise SystemExit(2)
