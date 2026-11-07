#!/usr/bin/env python3
"""Read-only, local coverage/evidence gate. No arguments prints help, no writes.

Invariant: inspect only explicitly allowed bounded local files; never execute
source text, fetch a URL, reveal quote bodies, or write an output/source file.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from zoneinfo import ZoneInfo

MAX_PACKET_BYTES = 16 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024
DATE_BASES = {'native_timestamp', 'document_date', 'verified_mapping'}
STAGES = {'sent', 'received', 'accepted', 'published', 'signed', 'approved', 'paid', 'performed'}

def load_json_bytes(raw, max_bytes=MAX_PACKET_BYTES):
    if len(raw) > max_bytes:
        raise ValueError('input_too_large')
    def pairs(values):
        out = {}
        for key, value in values:
            if key in out:
                raise ValueError('duplicate_json_key')
            out[key] = value
        return out
    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid_json') from exc
    if not isinstance(result, dict):
        raise ValueError('packet_must_be_object')
    return result

def bounded_bytes(path, limit):
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(str(path), flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError('not_regular_file')
        with os.fdopen(fd, 'rb') as stream:
            fd = -1
            raw = stream.read(limit + 1)
    finally:
        if fd >= 0:
            os.close(fd)
    if len(raw) > limit:
        raise ValueError('file_too_large')
    return raw

def aware(value):
    if not isinstance(value, str):
        raise ValueError('timestamp_required')
    value = value.replace('Z', '+00:00')
    value = re.sub(r'(\.\d{6})\d+(?=[+-]\d\d:\d\d$)', r'\1', value)
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone_required')
    return parsed

def source_path(value, root, allowed_roots):
    if not isinstance(value, str) or not value or any(c in value for c in ['\0', '\n', '\r']) or '://' in value:
        raise ValueError('invalid_source_path')
    p = Path(value)
    if '..' in p.parts:
        raise ValueError('parent_traversal')
    p = (p if p.is_absolute() else root / p).resolve(strict=True)
    if not any(p == base or base in p.parents for base in allowed_roots):
        raise ValueError('source_outside_allowed_roots')
    if not p.is_file():
        raise ValueError('source_not_file')
    return p

def validate_packet(packet, root, source_roots=()):
    errors, gaps = [], []
    def issue(code, at, gap=False):
        (gaps if gap else errors).append({'code': code, 'at': at})
    def collection(key):
        value = packet.get(key)
        if not isinstance(value, list) or not all(isinstance(r, dict) for r in value):
            issue('invalid_collection', key)
            return []
        return value
    def ids(value, at):
        if not isinstance(value, list) or not all(isinstance(i, str) and i for i in value):
            issue('invalid_id_list', at)
            return []
        if len(set(value)) != len(value):
            issue('duplicate_reference', at)
        return value
    def index(rows, key):
        result = {}
        for i, row in enumerate(rows):
            identity = row.get('id')
            if not isinstance(identity, str) or not identity.strip() or len(identity) > 512:
                issue('invalid_id', '{}[{}]'.format(key, i))
            elif identity in result:
                issue('duplicate_{}_id'.format(key.rstrip('s')), '{}[{}]'.format(key, i))
            else:
                result[identity] = row
        return result
    def refs(value, known, at, required=False):
        values = ids(value, at)
        if required and not values:
            issue('required_evidence_missing', at)
        for identity in values:
            if identity not in known:
                issue('unknown_reference', at)
        return values
    if not isinstance(packet, dict):
        raise ValueError('packet_must_be_object')
    root = Path(root).resolve(strict=True)
    allowed = [root]
    for value in source_roots:
        p = Path(value).resolve(strict=True)
        if not p.is_dir() or p == Path(p.anchor) or p == Path.home().resolve():
            raise ValueError('source_root_too_broad')
        allowed.append(p)

    scope = packet.get('scope')
    cutoff = None
    if not isinstance(scope, dict):
        scope = {};issue('invalid_scope', 'scope')
    if scope.get('mode') not in {'source_window', 'as_of', 'due_day'}:
        issue('invalid_date_mode', 'scope.mode')
    if scope.get('mode') == 'due_day':
        try:
            dt.date.fromisoformat(scope['due_on'])
        except (KeyError, TypeError, ValueError):
            issue('due_day_missing', 'scope.due_on')
    try:
        zone = ZoneInfo(scope['timezone'])
        cutoff = aware(scope['as_of'])
        start = aware(scope['source_start']) if scope.get('source_start') is not None else None
        end = aware(scope['source_end_exclusive'])
        if start is not None and (start >= end or start > cutoff):
            issue('invalid_source_window', 'scope')
        for point in [p for p in [start, end] if p is not None]:
            if point.utcoffset() != point.astimezone(zone).utcoffset():
                issue('scope_timezone_offset_mismatch', 'scope')
    except (KeyError, TypeError, ValueError):
        issue('invalid_scope_time', 'scope')
    required_channels = ids(scope.get('required_channels'), 'scope.required_channels')
    if not required_channels:
        issue('required_channels_empty', 'scope.required_channels')
    exclusions = ids(scope.get('user_excluded_source_ids', []), 'scope.user_excluded_source_ids')
    channels = collection('channels');sources = collection('sources')
    evidence = collection('evidence');actions = collection('actions');followups = collection('followups')
    channel_by = index(channels, 'channels');source_by = index(sources, 'sources')
    evidence_by = index(evidence, 'evidence');action_by = index(actions, 'actions')
    index(followups, 'followups')
    listed = set()
    for cid in required_channels:
        if cid not in channel_by:
            issue('required_channel_missing', 'channels', True)
    for i, channel in enumerate(channels):
        at = 'channels[{}]'.format(i)
        if (channel.get('enumeration') != 'complete' or channel.get('pagination_exhausted') is not True
                or channel.get('identity_verified') is not True or channel.get('range_verified') is not True
                or not channel.get('enumeration_receipt')):
            issue('channel_not_complete', at, True)
        receipt = channel.get('enumeration_receipt')
        if not isinstance(receipt, dict):
            issue('inventory_receipt_invalid', at)
        else:
            try:
                receipt_path = source_path(receipt.get('source_file'), root, allowed)
                receipt_raw = bounded_bytes(receipt_path, MAX_SOURCE_BYTES)
                if hashlib.sha256(receipt_raw).hexdigest() != receipt.get('source_sha256'):
                    issue('inventory_receipt_hash_mismatch', at)
                else:
                    frozen = load_json_bytes(receipt_raw, MAX_SOURCE_BYTES)
                    frozen_ids = ids(frozen.get('inventory_ids'), at+'.receipt.inventory_ids')
                    declared = ids(channel.get('inventory_ids'), at+'.inventory_ids')
                    if set(frozen_ids) != set(declared) or frozen.get('channel') != channel.get('id'):
                        issue('inventory_differs_from_receipt', at, True)
                    if (not frozen.get('capture_basis') or frozen.get('pagination_exhausted') is not True
                            or frozen.get('identity_verified') is not True or frozen.get('range_verified') is not True):
                        issue('inventory_receipt_not_complete', at, True)
            except (ValueError, OSError, TypeError):
                issue('inventory_receipt_invalid', at)
        for sid in ids(channel.get('inventory_ids'), at+'.inventory_ids'):
            if sid in listed:
                issue('inventory_source_duplicated', at)
            listed.add(sid)
            if sid not in source_by:
                issue('inventory_source_missing', at, True)
            elif source_by[sid].get('channel') != channel.get('id'):
                issue('source_channel_mismatch', at)
    for sid in source_by:
        if sid not in listed:
            issue('source_not_in_inventory', 'sources')

    full = {}
    for i, source in enumerate(sources):
        at = 'sources[{}]'.format(i)
        total = source.get('units_total')
        ranges = source.get('read_ranges')
        well_formed = type(total) is int and total > 0 and isinstance(ranges, list)
        valid = []
        if well_formed:
            for value in ranges:
                if (not isinstance(value, list) or len(value) != 2 or not all(type(n) is int for n in value)
                        or not 1 <= value[0] <= value[1] <= total):
                    issue('invalid_read_range', at);well_formed = False
                else:
                    valid.append(value)
        elif source.get('status') != 'excluded':
            issue('invalid_unit_coverage', at)
        cursor = 1
        for lo, hi in sorted(valid):
            if lo < cursor:
                issue('overlapping_read_ranges', at);well_formed = False
            elif lo > cursor:
                well_formed = False
            cursor = max(cursor, hi + 1)
        covered = (well_formed and cursor == total + 1 and source.get('semantic_read') is True
                   and bool(source.get('unit_basis')))
        full[source.get('id')] = covered
        status = source.get('status')
        if status not in {'read', 'partial', 'unavailable', 'deferred', 'excluded'}:
            issue('invalid_source_status', at)
        if status == 'read':
            if not covered:
                issue('unread_units', at, True)
            if source.get('scope_verified') is not True or source.get('date_basis') not in DATE_BASES:
                issue('source_scope_unconfirmed', at, True)
        elif status != 'excluded':
            issue('source_not_read', at, True)
        if source.get('channel') not in channel_by or not source.get('kind'):
            issue('invalid_source_identity', at)
    for i, source in enumerate(sources):
        if source.get('status') != 'excluded':
            continue
        at = 'sources[{}]'.format(i);reason = source.get('exclusion_reason')
        if reason == 'user_excluded':
            if source.get('id') not in exclusions:
                issue('user_exclusion_unconfirmed', at)
        elif reason == 'outside_requested_dates':
            if source.get('date_basis') not in DATE_BASES or not source.get('exclusion_proof'):
                issue('exclusion_scope_unconfirmed', at)
        elif reason == 'confirmed_not_applicable':
            if not full.get(source.get('id')) or not source.get('exclusion_proof'):
                issue('exclusion_not_read', at)
        elif reason == 'exact_duplicate':
            target = source_by.get(source.get('duplicate_of'), {})
            digest = source.get('body_sha256')
            if (not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
                    or digest != target.get('body_sha256') or target.get('status') != 'read'
                    or not full.get(target.get('id')) or source.get('metadata_reviewed') is not True):
                issue('duplicate_body_unproven', at)
        else:
            issue('invalid_exclusion', at)

    cache = {}
    for i, item in enumerate(evidence):
        at = 'evidence[{}]'.format(i)
        for key in ['actor', 'occurred_at', 'kind', 'locator']:
            if not item.get(key):
                issue('evidence_metadata_missing', at+'.'+key)
        if item.get('source_id') not in source_by:
            issue('evidence_source_missing', at)
        if item.get('normalized_at'):
            try:
                timestamp = aware(item['normalized_at'])
                if cutoff and timestamp > cutoff:
                    issue('evidence_after_as_of', at)
                if item.get('date_basis') not in DATE_BASES:
                    issue('unconfirmed_normalized_date', at)
            except (ValueError, TypeError):
                issue('invalid_evidence_time', at)
        if item.get('quote_kind') == 'paraphrase':
            if not item.get('observation_receipt'):
                issue('paraphrase_receipt_missing', at)
            continue
        if item.get('quote_kind') != 'verbatim' or not isinstance(item.get('quote'), str) or not item['quote']:
            issue('invalid_quote', at);continue
        try:
            p = source_path(item.get('source_file'), root, allowed)
        except (ValueError, OSError):
            issue('source_path_rejected', at);continue
        try:
            if p not in cache:
                raw = bounded_bytes(p, MAX_SOURCE_BYTES)
                cache[p] = (hashlib.sha256(raw).hexdigest(), raw.decode('utf-8').splitlines())
            digest, lines = cache[p]
        except (ValueError, OSError, UnicodeError):
            issue('source_unreadable', at);continue
        if digest != item.get('source_sha256'):
            issue('source_hash_mismatch', at);continue
        lo, hi = item.get('line_start'), item.get('line_end')
        if type(lo) is not int or type(hi) is not int or not 1 <= lo <= hi <= len(lines):
            issue('invalid_quote_line_range', at);continue
        selected = '\n'.join(lines[lo-1:hi]);quote = item['quote']
        if item.get('normalize_whitespace') is True:
            selected, quote = ''.join(selected.split()), ''.join(quote.split())
        if quote not in selected:
            issue('quote_line_mismatch', at)

    for i, follow in enumerate(followups):
        at = 'followups[{}]'.format(i)
        if follow.get('parent_source_id') not in source_by or not follow.get('kind'):
            issue('invalid_followup_source', at)
        if follow.get('required') is not True:
            if not follow.get('resolution_basis'):
                issue('followup_optional_without_basis', at)
            continue
        if follow.get('status') == 'resolved':
            resolved = ids(follow.get('resolved_source_ids'), at+'.resolved_source_ids')
            if not resolved or any(s not in source_by or not full.get(s) for s in resolved):
                issue('followup_resolution_missing', at, True)
        elif follow.get('status') == 'not_applicable':
            if not follow.get('resolution_basis'):
                issue('followup_resolution_missing', at, True)
        else:
            issue('followup_unresolved', at, True)

    for i, action in enumerate(actions):
        at = 'actions[{}]'.format(i)
        for key in ['counterparty', 'action', 'proposed_at', 'deadline_text', 'status']:
            if not action.get(key):
                issue('action_field_missing', at+'.'+key)
        kind, status = action.get('kind'), action.get('status')
        if kind not in {'explicit', 'notice', 'reply', 'self_intent', 'waiting', 'candidate', 'information'}:
            issue('invalid_action_kind', at)
        if status not in {'open', 'waiting', 'conditional', 'unknown', 'done', 'cancelled', 'superseded'}:
            issue('invalid_action_status', at)
        references = refs(action.get('evidence_ids'), evidence_by, at+'.evidence_ids', True)
        attribution = action.get('attribution')
        if attribution not in {'self', 'possible_self', 'other', 'unknown'}:
            issue('invalid_attribution', at)
        if status == 'open' and (attribution != 'self' or (kind == 'notice' and action.get('applicability') != 'confirmed')):
            issue('unconfirmed_personal_obligation', at)
        if attribution == 'other' and kind not in {'information', 'candidate'}:
            issue('other_person_action', at)
        if kind == 'notice' and action.get('applicability') == 'confirmed':
            refs(action.get('applicability_evidence_ids'), evidence_by, at+'.applicability_evidence_ids', True)
        role = action.get('deadline_role')
        if role not in {'personal', 'none', 'unknown'}:
            issue('nonpersonal_deadline', at)
        if role == 'personal':
            refs(action.get('deadline_evidence_ids'), evidence_by, at+'.deadline_evidence_ids', True)
        if status in {'done', 'cancelled', 'superseded'}:
            refs(action.get('completion_evidence_ids'), evidence_by, at+'.completion_evidence_ids', True)
            if not action.get('completion_scope'):
                issue('completion_scope_missing', at)
        if status == 'done':
            required, completed = action.get('required_stage'), action.get('completion_stage')
            if required not in STAGES or completed not in STAGES:
                issue('completion_stage_missing', at)
            elif completed != required and not (required == 'sent' and completed == 'received'):
                issue('completion_stage_mismatch', at)
        if status == 'superseded' and action.get('superseded_by') not in action_by:
            issue('replacement_action_missing', at)
        if references and all(source_by.get(evidence_by.get(e, {}).get('source_id'), {}).get('status') == 'excluded'
                              and source_by.get(evidence_by.get(e, {}).get('source_id'), {}).get('exclusion_reason') != 'exact_duplicate'
                              for e in references):
            issue('action_outside_scope', at)
    return {'coverage_complete': not errors and not gaps, 'errors': errors, 'gaps': gaps,
            'counts': {'channels': len(channels), 'sources': len(sources), 'actions': len(actions),
                       'evidence': len(evidence), 'followups': len(followups)},
            'meaning': 'Ledger and citation checks only; semantic completeness requires the source-first review.',
            'network_used': False, 'files_written': False}

def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packet', nargs='?', help='Local audit JSON; read only')
    parser.add_argument('--source-root', action='append', default=[], help='Explicit additional local source directory')
    options = parser.parse_args(args)
    if options.packet is None:
        parser.print_help();return 0
    try:
        path = Path(options.packet).resolve(strict=True)
        packet = load_json_bytes(bounded_bytes(path, MAX_PACKET_BYTES))
        result = validate_packet(packet, path.parent, options.source_root)
    except (ValueError, OSError, KeyError, TypeError, RecursionError) as exc:
        print(json.dumps({'coverage_complete': False, 'errors': [{'code': 'invalid_input', 'at': 'packet'}],
                          'gaps': [], 'network_used': False, 'files_written': False}))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['coverage_complete'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
