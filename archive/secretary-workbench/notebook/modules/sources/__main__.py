"""Safe-default SOURCE CLI; imports accept bounded stdin JSON, never source paths."""
import argparse
import base64
import json
import sys
from . import SourceRegistry
from .registry import MAX_BATCH_BYTES
from .tools import MAX_ASSET_BYTES


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local saved-source registry. No live collection or credentials.')
    parser.add_argument('--workspace', help='Explicit local workspace; required for every action')
    commands = parser.add_subparsers(dest='command')
    commands.add_parser('list', help='Read saved source manifests')
    query = commands.add_parser('query', help='Read a bounded saved-record page')
    query.add_argument('source_id')
    for option in ['start', 'end', 'keyword', 'conversation', 'sender', 'content-type', 'cursor']:
        query.add_argument('--' + option)
    query.add_argument('--limit', type=int, default=100)
    read = commands.add_parser('read', help='Read a saved record by stable ID')
    read.add_argument('source_id')
    read.add_argument('record_id')
    importing = commands.add_parser('import', help='Explicit write: import at most 8MiB JSON record array from stdin')
    importing.add_argument('--source-type', required=True)
    importing.add_argument('--account-id', required=True)
    importing.add_argument('--display-name')
    snapshots = commands.add_parser('snapshots', help='List immutable saved snapshot versions')
    snapshots.add_argument('source_id')
    versions = commands.add_parser('versions', help='List one native record in committed snapshot versions')
    versions.add_argument('source_id')
    versions.add_argument('record_id')
    version = commands.add_parser('read-version', help='Read one exact historical saved record')
    version.add_argument('source_id')
    version.add_argument('record_id')
    version.add_argument('snapshot')
    receipts = commands.add_parser('receipts', help='Read persisted exact-content receipts')
    receipts.add_argument('source_id')
    receipt = commands.add_parser('receipt-read', help='Read one persisted receipt')
    receipt.add_argument('source_id')
    receipt.add_argument('receipt_id')
    receipt_create = commands.add_parser('receipt-create', help='Explicit write: persist exact saved-text delivery receipt')
    receipt_create.add_argument('source_id')
    receipt_create.add_argument('snapshot')
    receipt_create.add_argument('record_ids', nargs='+')
    receipt_create.add_argument('--media-read', action='append', default=[])
    checkpoints = commands.add_parser('checkpoints', help='Read consumer retrieval/read/application acknowledgments')
    checkpoints.add_argument('source_id')
    checkpoints.add_argument('consumer_id')
    advance = commands.add_parser('checkpoint-advance', help='Explicit CAS write: acknowledge one source processing stage')
    advance.add_argument('source_id')
    advance.add_argument('consumer_id')
    advance.add_argument('stage', choices=['retrieved', 'read', 'applied'])
    advance.add_argument('snapshot')
    advance.add_argument('record_ids', nargs='+')
    advance.add_argument('--expected-revision', type=int, required=True)
    advance.add_argument('--receipt-id', action='append', default=[])
    advance.add_argument('--operation-ref', help='Required explicit downstream operation acknowledgment for applied')
    advance.add_argument('--detail', default='')
    assets = commands.add_parser('assets', help='List account-local managed attachments')
    assets.add_argument('source_id')
    asset_get = commands.add_parser('asset-get', help='Read managed bytes as bounded JSON/base64')
    asset_get.add_argument('source_id')
    asset_get.add_argument('asset_ref')
    asset_put = commands.add_parser('asset-put', help='Explicit write: store up to 8MiB raw stdin bytes; no input path')
    asset_put.add_argument('source_id')
    asset_put.add_argument('--mime', required=True)
    asset_put.add_argument('--name')
    asset_put.add_argument('--sha256')
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if not args.workspace:
        parser.error('--workspace is required; no default workspace is selected')
    try:
        registry = SourceRegistry(args.workspace)
        if args.command == 'list':
            result = {'sources': registry.list_sources()}
        elif args.command == 'read':
            result = registry.read(args.source_id, args.record_id)
        elif args.command == 'query':
            result = registry.query(args.source_id, **{key: getattr(args, key) for key in
                ['start', 'end', 'keyword', 'conversation', 'sender', 'content_type', 'cursor', 'limit']})
        elif args.command == 'snapshots':
            result = {'snapshots': registry.list_snapshots(args.source_id)}
        elif args.command == 'versions':
            result = {'versions': registry.list_record_versions(args.source_id, args.record_id)}
        elif args.command == 'read-version':
            result = registry.read_record_version(args.source_id, args.record_id, args.snapshot)
        elif args.command == 'receipts':
            result = {'receipts': registry.list_read_receipts(args.source_id)}
        elif args.command == 'receipt-read':
            result = registry.read_read_receipt(args.source_id, args.receipt_id)
        elif args.command == 'receipt-create':
            result = registry.persist_read_receipt(args.source_id, args.snapshot, args.record_ids,
                                                   media_reads=args.media_read)
        elif args.command == 'checkpoints':
            result = registry.get_checkpoints(args.source_id, args.consumer_id)
        elif args.command == 'checkpoint-advance':
            ack = {'operationRef': args.operation_ref, 'detail': args.detail} if args.operation_ref else None
            result = registry.advance_checkpoint(args.source_id, args.consumer_id, args.stage,
                expected_revision=args.expected_revision, snapshot=args.snapshot, record_ids=args.record_ids,
                receipt_ids=args.receipt_id, acknowledgment=ack)
        elif args.command == 'assets':
            result = {'assets': registry.list_assets(args.source_id)}
        elif args.command == 'asset-get':
            asset = registry.get_asset(args.source_id, args.asset_ref)
            result = dict(metadata=asset['metadata'], contentBase64=base64.b64encode(asset['content']).decode('ascii'))
        elif args.command == 'asset-put':
            content = sys.stdin.buffer.read(MAX_ASSET_BYTES + 1)
            result = registry.put_asset(args.source_id, content, mime=args.mime, name=args.name,
                                        expected_sha256=args.sha256)
        else:
            raw = sys.stdin.buffer.read(MAX_BATCH_BYTES + 1)
            if len(raw) > MAX_BATCH_BYTES:
                raise ValueError('stdin exceeds 8MiB')
            result = registry.import_records(args.source_type, args.account_id, json.loads(raw), display_name=args.display_name)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, KeyError, OSError, UnicodeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
