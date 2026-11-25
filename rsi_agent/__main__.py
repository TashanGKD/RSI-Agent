import argparse
import json
import sys

from . import __version__
from .audit import audit
from .config import ROOT, load
from .service_bundle import stage
from .wechat import call, doctor
from .workbook import STATES as WORKBOOK_STATES


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
    workbook = commands.add_parser('workbook', help='Maintain per-item work notes and their derived view.')
    workbook_commands = workbook.add_subparsers(dest='mode', required=True)
    workbook_new = workbook_commands.add_parser('new', help='Create one eight-field work note.')
    workbook_new.add_argument('--root', required=True, help='Project memory directory containing workbook/.')
    workbook_new.add_argument('--title', required=True, help='Distinct result title.')
    workbook_new.add_argument('--source', required=True, help='Who asked, when and where.')
    workbook_new.add_argument('--goal', required=True, help='Observable result for this round.')
    workbook_new.add_argument('--next', dest='next_step', required=True, help='The next own step or waiting condition.')
    workbook_new.add_argument('--thought', default='待补充当前判断', help='Current understanding or open question.')
    workbook_new.add_argument('--time', default='未安排复看时间', help='Deadline, review time or resume condition.')
    workbook_new.add_argument('--state', choices=WORKBOOK_STATES, default='待推进')
    workbook_new.add_argument('--file', dest='file_name', help='Optional plain .md file name.')
    workbook_set = workbook_commands.add_parser('set', help='Update one active note current summary or append a process line.')
    workbook_set.add_argument('--root', required=True, help='Project memory directory containing workbook/.')
    workbook_set.add_argument('--title', help='Distinct result title; choose this or --file.')
    workbook_set.add_argument('--file', dest='file_name', help='Plain .md note name; choose this or --title.')
    workbook_set.add_argument('--source', help='Who asked, when and where.')
    workbook_set.add_argument('--goal', help='Observable result for this round.')
    workbook_set.add_argument('--thought', help='Current understanding or open question.')
    workbook_set.add_argument('--state', choices=WORKBOOK_STATES)
    workbook_set.add_argument('--next', dest='next_step', help='The next own step or waiting condition.')
    workbook_set.add_argument('--time', help='Deadline, review time or resume condition.')
    workbook_set.add_argument('--process-note', help='Short latest meaningful change for the current summary.')
    workbook_set.add_argument('--log', help='Append one dated line under 过程.')
    workbook_review = workbook_commands.add_parser('review', help='Show active work, archive count and limit status without writing.')
    workbook_review.add_argument('--root', required=True, help='Project memory directory containing workbook/.')
    workbook_archive = workbook_commands.add_parser('archive', help='Preview or move a closed note out of the current view.')
    workbook_archive.add_argument('--root', required=True, help='Project memory directory containing workbook/.')
    workbook_archive.add_argument('--title', help='Distinct result title; choose this or --file.')
    workbook_archive.add_argument('--file', dest='file_name', help='Plain .md note name; choose this or --title.')
    workbook_archive.add_argument('--execute', action='store_true', help='Move the closed note into workbook/archive/.')
    workbook_refresh = workbook_commands.add_parser('refresh', help='Preview or write CURRENT.workbook.md.')
    workbook_refresh.add_argument('--root', required=True, help='Project memory directory containing workbook/.')
    workbook_refresh.add_argument('--execute', action='store_true', help='Write the generated view.')
    workbook_check = workbook_commands.add_parser('check', help='Fail if the generated view differs from the notes.')
    workbook_check.add_argument('--root', required=True, help='Project memory directory containing workbook/.')
    memory = commands.add_parser('memory', help='Inspect owner private named memory without writing.')
    memory_commands = memory.add_subparsers(dest='mode', required=True)
    memory_review = memory_commands.add_parser('review', help='Show bounded memory metadata and current retrieval selection.')
    memory_review.add_argument('--db', required=True, help='Existing private owner inbox SQLite database.')
    memory_review.add_argument('--query', default='', help='Optional text used in the same bounded retrieval.')
    memory_review.add_argument('--show-values', action='store_true', help='Include stored values in the output.')
    knowledge = commands.add_parser('knowledge', help='Build, inspect or query the private owner text index.')
    knowledge_commands = knowledge.add_subparsers(dest='mode', required=True)
    knowledge_index = knowledge_commands.add_parser('index', help='Rebuild the index beside the private owner inbox.')
    knowledge_index.add_argument('--db', required=True, help='Existing private owner inbox SQLite database.')
    knowledge_index.add_argument('--root', required=True, help='Directory of UTF-8 .md, .markdown or .txt files.')
    knowledge_status = knowledge_commands.add_parser('status', help='Report index size, age and changed sources without writing.')
    knowledge_status.add_argument('--db', required=True, help='Existing private owner inbox SQLite database.')
    knowledge_search = knowledge_commands.add_parser('search', help='Run the same bounded retrieval without writing.')
    knowledge_search.add_argument('--db', required=True, help='Existing private owner inbox SQLite database.')
    knowledge_search.add_argument('--query', default='', help='Text used for bounded lexical retrieval.')
    knowledge_search.add_argument('--show-text', action='store_true', help='Include stored snippets in the output.')
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == 'sources':
        print((ROOT / 'SOURCES.lock.json').read_text(encoding='utf-8'))
        return 0
    if args.command == 'workbook':
        from .workbook import archive, check, create, refresh, review, update_note
        if args.mode == 'new':
            result = create(args.root, args.title, args.source, args.goal, args.next_step,
                            thought=args.thought, time=args.time, state=args.state,
                            file_name=args.file_name)
        elif args.mode == 'set':
            result = update_note(args.root, title=args.title, file_name=args.file_name,
                                 source=args.source, goal=args.goal, thought=args.thought,
                                 state=args.state, next_step=args.next_step, time=args.time,
                                 process_note=args.process_note, log=args.log)
        elif args.mode == 'review':
            result = review(args.root)
        elif args.mode == 'archive':
            result = archive(args.root, title=args.title, file_name=args.file_name,
                             execute=args.execute)
        elif args.mode == 'refresh':
            result = refresh(args.root, args.execute)
        else:
            result = check(args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'memory':
        from .memory import review as inspect_memory
        result = inspect_memory(args.db, args.query, args.show_values)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == 'knowledge':
        from .knowledge import index as build_index, search as search_index, status as inspect_index
        if args.mode == 'index':
            result = build_index(args.db, args.root)
        elif args.mode == 'status':
            result = inspect_index(args.db)
        else:
            result = search_index(args.db, args.query, args.show_text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
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
