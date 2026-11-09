# Independent saved-source tools, version 1

The Python implementation is `modules/sources/registry.py` and `modules/sources/tools.py`. It uses only Python's standard library. It imports no notebook, secretary, scheduler, executor, app server or credential service. The CLI runs from the app directory with `python3 -m modules.sources`. No arguments print help; every action requires an explicit `--workspace`.

This contract covers **explicit saved-data imports and local access**, not connected upstream adapters. `status=cached_only`, `liveFetched=false`, `upstreamComplete=false`, `live_not_connected` and `upstream_coverage_unknown` remain true limitations. Caller-supplied coverage cannot remove them. No acquisition scan, account login, credential copy, background work or automation is started by these tools.

## Public Python interface

```python
from modules.sources import SourceRegistry, CheckpointConflictError
r = SourceRegistry(explicit_workspace)
r.import_records(source_type, account_id, records, *, display_name=None,
                 gaps=None, coverage=None)
r.list_sources()
r.query(source_id, start=None, end=None, keyword=None, conversation=None,
        sender=None, content_type=None, limit=100, cursor=None)
r.read(source_id, record_id)
r.list_snapshots(source_id)
r.list_record_versions(source_id, record_id)
r.read_record_version(source_id, record_id, snapshot)
r.persist_read_receipt(source_id, snapshot, record_ids, *, media_reads=None)
r.list_read_receipts(source_id)
r.read_read_receipt(source_id, receipt_id)
r.get_checkpoints(source_id, consumer_id)
r.advance_checkpoint(source_id, consumer_id, stage, *, expected_revision,
                     snapshot, record_ids, receipt_ids=None, acknowledgment=None)
r.put_asset(source_id, content, *, mime, name=None, expected_sha256=None)
r.get_asset(source_id, asset_ref)
r.list_assets(source_id)
```

All `list*`, `query`, `read*`, `get*` operations are read only. Construction and reading an empty workspace do not initialize storage. Explicit writes are `import_records`, `persist_read_receipt`, `advance_checkpoint` and `put_asset`. The module does not return or accept arbitrary source-file paths.

## Stable identities and immutable versions

`sourceId=source_type:account_id`; both components are 1–64 ASCII letters/digits/underscore/hyphen, starting with a letter/digit. A stable `rec_<40 hex>` ID hashes the source ID and original native ID. Original native IDs may include Unicode and slashes, but are never paths. `nativeVersion`, original time precision, text, sender, conversation, locator and provenance remain source facts. Top-level task/semantic state fields are rejected.

Each import creates an immutable bounded snapshot and atomically replaces `source.json`. Exact repeats do not create another snapshot. `source.json.snapshotHistory` records committed snapshot IDs with SHA-256 and byte size. The existing current-snapshot shape is preserved. A previous manifest without `snapshotHistory` anchors only its current snapshot; older files lacking a committed hash anchor are **not silently adopted**.

`list_snapshots` returns a list with `snapshot`, `sha256`, `size`, `recordCount`, `current`, `at`, `integrity`, `liveFetched=false` and `upstreamComplete=false`. A locally present snapshot absent from committed hash history is visible as `integrity=uncommitted`. This means “not anchored in the current manifest”; it can be an old unindexed file or an interrupted-write orphan. It is not trusted reading/checkpoint evidence. Committed missing files or hash mismatches raise errors. A missing source manifest is not rebuilt by reads.

`list_record_versions` returns a list of occurrences of a stable native record in committed snapshots, including snapshot metadata, `recordId`, `nativeId`, `nativeVersion`, `contentHash` and `recordHash`. An unchanged record can occur in multiple projection snapshots. It does not claim all upstream native versions are present. `read_record_version` returns `{record, snapshot, gaps}` for the exact requested committed version. Current `read` behavior remains unchanged.

The import `contentHash` hashes the original imported record JSON. `recordHash` hashes the complete normalized stored record. JSON hashes use UTF-8, sorted keys, no insignificant whitespace and no NaN/Infinity. Snapshot hashes cover exact stored bytes. Hashes detect drift in this local store; they are not remote-platform signatures or cryptographic attestations against an owner who can rewrite the entire store.

## Persisted exact-content reading receipts

A query's existing `receipt` describes its returned page and is not persisted. It cannot advance a reading checkpoint. Use `persist_read_receipt` explicitly with one committed snapshot and 1–100 distinct record IDs. The call returns and persists a `receipt_<32 hex>` object containing:

- `sourceId`, `snapshot`, `snapshotHash`, time, operation and a canonical `receiptHash`;
- per record: stable/native IDs, import `contentHash`, full normalized `recordHash`, exact saved text, canonical text JSON hash, readability and reading nature;
- per attachment: the original declared metadata, whether a verified local asset is known, and `not_read` or `bytes_read`;
- the source gaps and explicit `upstreamComplete=false` / `liveFetched=false`.

Absent `readable` means the imported saved text is available. Explicit `readable=false` is retained with `readingNature=not_read` and its missing reason. Such a receipt cannot supply readable-content checkpoint evidence. An empty but available text body is still the exact saved body; no body is fabricated.

Media defaults to `not_read`, even when an upstream attachment declaration says `readable=true`. The tool may verify a locally known asset's integrity without counting this as an explicit media read. `media_reads` optionally names only managed `asset:<sha256>` references attached to the selected rows; the call reads/verifies those local bytes and records `bytes_read` with their exact hash. External or missing media cannot be marked read. Byte access does not assert transcription, visual inspection, semantic understanding or human reading.

Receipts are immutable local evidence files. Reading verifies receipt schema/hash and exact normalized content against the committed snapshot, including original unreadable flags and attachment declarations. A fabricated receipt ID, another source's receipt or another snapshot/version cannot be substituted as evidence.

## Retrieval, reading and application checkpoints

`get_checkpoints(source_id, consumer_id)` returns `{sourceId, consumerId, revision, stages, history, upstreamComplete:false}` plus schema version. New consumers have revision 0 and three null stages. `consumer_id` uses the same safe identifier alphabet as account IDs.

`advance_checkpoint` serializes writes using the source directory lock and compares the exact nonnegative `expected_revision`. Mismatch raises `CheckpointConflictError`, a subclass of `ValueError`, without writing. Each successful call adds one history event and increments the consumer revision once. It retains prior events; it does not silently prune history.

Stages are exact, independent technical observations:

| Stage | Required evidence | Meaning |
| --- | --- | --- |
| `retrieved` | committed snapshot hash and explicit IDs present in it | These exact saved record versions are available to this consumer. |
| `read` | prior `retrieved` events covering the same snapshot/record hashes, and persisted readable-content receipt IDs covering them | The local tool delivered these exact saved text versions. |
| `applied` | prior `read` events covering the same snapshot/record hashes, matching persisted receipts, and explicit `acknowledgment` | The downstream consumer explicitly acknowledges an operation. |

For `applied`, `acknowledgment` must contain a nonempty bounded `operationRef` and may contain `detail`. Other fields, including task state, are rejected. This is a **caller-supplied downstream acknowledgment**: the source module does not execute or validate the downstream operation, infer secretary processing, alter notebook tasks, or prove semantic understanding. Source tools never auto-advance any stage when importing/querying/reading. A newer snapshot cannot borrow receipt evidence from an older snapshot, even for the same native ID. Record sets and hashes are the coverage boundary; no timestamp watermark or upstream cursor completeness is invented.

## Account-local managed attachments

`put_asset` accepts bytes, never an input file path or URL. It returns metadata including `assetRef=asset:<sha256>`, `sourceId`, exact `sha256`, size, MIME, optional display label, time and `localOnly=true`. Put the returned reference into an explicit source-record import to associate it. The display label never becomes a path; Unicode and slash characters remain inert text, while control characters are rejected.

`get_asset` returns `{metadata, content: bytes}`. `list_assets` returns verified metadata. Access is scoped by source/account; identical hashes in another account are unavailable until explicitly stored there. Exact bytes are hash/size checked each time. Repeated puts are idempotent and retain the original metadata; a conflicting MIME declaration is rejected. Metadata-only/broken committed assets produce an error rather than an empty inventory.

Allowed MIME types: `application/octet-stream`, UTF-8 `text/plain`, `application/pdf`, `image/png`, `image/jpeg`, `image/gif`, `image/webp`, `audio/wav`, `audio/ogg`, `audio/mpeg`, `audio/mp4`, `video/mp4`. Declared media/PDF types get basic magic-signature checks; this is not full decoding or malware inspection. Other types must use `application/octet-stream`. HTML and executable MIME declarations are rejected. HTTP adapters must set safe download headers and must not inject display labels into headers without their own encoding.

## Storage, bounds and copying

```text
<workspace>/sources/<physical-type>/<physical-account>/
  source.json
  snapshot_<uuid>.json
  receipts/receipt_<uuid>.json
  checkpoints/<consumer>.json
  assets/<sha256>.blob
  assets/<sha256>.json
```

Every managed descendant is traversed by held directory handles with `O_NOFOLLOW`; symlink directories/files, traversal components, special files and oversized files are rejected. Writes lock the account directory, prepare bounded data and use atomic replacement where a mutable commit pointer is required. Failed precommit writes clean temporary/new files. An error after atomic commit/directory sync may leave the new committed state readable; callers should read back before retrying.

Existing bounds remain: import 1,000 records / 8MiB per batch, 256KiB per record, 10,000 records / 16MiB per projection, 16 retained snapshots, 1–500 records per query page. New bounds: 8MiB per asset, 128 blobs and 64MiB total per source; 256 receipts, 8MiB per receipt and 64MiB aggregate; 100 records and 64 explicit media reads per receipt; 128 consumers and 256 checkpoint events per consumer. Quotas reject further writes and do not silently delete original history. These are local bounded foundations, not unlimited upstream archival.

To relocate while writers are stopped, copy the entire workspace's `sources/` tree, or a complete account directory into a destination workspace's `sources/<physical-type>/<physical-account>/`. Keep the manifest, all retained snapshots, receipt/checkpoint folders and managed blobs together. Construct a new `SourceRegistry` with the destination workspace. No stored absolute paths or notebook dependencies need rewriting. Safe physical directory names may change; manifest source identity remains stable. Duplicate source IDs are rejected. Account authorization is not migrated: `authRef` stays null, and live adapters remain disconnected.

## CLI equivalents

Read-only commands: `list`, `query`, `read`, `snapshots`, `versions`, `read-version`, `receipts`, `receipt-read`, `checkpoints`, `assets`, `asset-get`. `asset-get` emits `{metadata, contentBase64}` JSON rather than opening local paths.

Explicit writes: `import` (bounded JSON array on stdin), `receipt-create`, `checkpoint-advance` (mandatory `--expected-revision`, optional repeated `--receipt-id`, required `--operation-ref` when applied), `asset-put` (bounded raw stdin bytes, required `--mime`). Run each command with `--help` for positional arguments. No command selects a default workspace, scans a source or refreshes upstream state.

Invalid inputs, path/symlink violations, content mismatches and quotas raise `ValueError`; missing identities raise `KeyError`; filesystem failures may raise `OSError`. The CLI emits errors as JSON to stderr and exits 2. Successful CLI commands emit JSON to stdout and exit 0.
