"""Explicit local CLI. No arguments prints help; no implicit source scan or model call."""
import argparse
import json
from pathlib import Path
import sys
from . import SecretaryService, SecretaryValidationError


def main(argv=None):
    parser = argparse.ArgumentParser(description='本地秘书：准备、运行或查看已保存输入；不扫描原始信源。')
    parser.add_argument('--workspace', required=True, help='显式私人工作区')
    parser.add_argument('--db', help='默认 <workspace>/notebook/notebook.sqlite3')
    parser.add_argument('--source-file', help='默认 <workspace>/source.json，仅旧导入')
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare', help='只保存任务，不调用模型')
    inputs = prepare.add_mutually_exclusive_group()
    inputs.add_argument('--message-id')
    inputs.add_argument('--text', help='保存一条新的原始留言')
    inputs.add_argument('--source-id', help='明确已保存信源；须同时 --record-id')
    prepare.add_argument('--record-id')
    prepare.add_argument('--request-id')
    run = commands.add_parser('run', help='前台有界运行或续跑一个任务')
    run.add_argument('job_id')
    status = commands.add_parser('status', help='只读任务状态')
    status.add_argument('job_id', nargs='?')
    args = parser.parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    # status reads only the job ledger, never creates/loads a notebook or imports old data.
    if args.command == 'status':
        ledger = workspace / 'secretary' / 'jobs.sqlite3'
        if not ledger.is_file() or ledger.is_symlink():
            parser.error('工作区尚无秘书任务账本')
        service = SecretaryService(None, workspace)
    else:
        from modules.notebook import NotebookService
        from modules.sources import SourceRegistry
        db_file = Path(args.db).expanduser().resolve() if args.db else workspace / 'notebook' / 'notebook.sqlite3'
        source_file = Path(args.source_file).expanduser().resolve() if args.source_file else workspace / 'source.json'
        service = SecretaryService(NotebookService(db_file, source_file, workspace), workspace,
                                   source_port=SourceRegistry(workspace))
    try:
        if args.command == 'prepare':
            message = args.message_id
            if args.source_id:
                if not args.record_id:
                    parser.error('--source-id 需要 --record-id')
                message = {'sourceId': args.source_id, 'recordId': args.record_id}
            elif args.record_id:
                parser.error('--record-id 需要 --source-id')
            elif args.text is not None:
                message = service.notebook.append_record({'text': args.text, 'actor': {'name': '我', 'kind': 'human'},
                          'requestId': ('input-' + args.request_id) if args.request_id else None})['id']
            result = service.prepare(message, args.request_id)
        elif args.command == 'run':
            result = service.run(args.job_id)
        else:
            result = service.get_job(args.job_id) if args.job_id else service.list_jobs()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if isinstance(result, dict) and result.get('status') == 'failed' else 0
    except (ValueError, KeyError) as exc:
        print('秘书操作失败：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
