"""Local metadata for explicitly evidenced delivery commitments."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import concurrent.futures
import datetime
import hashlib
import json
import math
import re
from build_snapshot import field
from delivery_health import family
from delivery_receipt_cache import proof_valid
from send_tool_observer import CLIENTS, RID, project, readonly
OWNERS = _install.setting('monitor.delivery_obligations', 'OWNERS', {})
KINDS = {'prepared': ('committed_not_admitted', 'frozen_intent', 'verify_current_need_and_executor'), 'failed': ('terminal_no_send', 'verified_no_send', 'verify_layout_and_current_need'), 'authority': ('authority_wait', 'action_scope_missing', 'await_authority_and_verify_scope')}
GAPS = {'outside_explicit_sources', 'workbook_source_unavailable', 'identity_mismatch', 'exact_receipt_unavailable', 'source_read_or_format', 'morning_component_index_incomplete', 'conflicting_component_evidence', 'bp_capability_preparation_pending', 'bp_delivery_receipts_pending'}
ROW_FIELDS = {'employee', 'ownerThreadId', 'businessKey', 'requestId', 'componentCount', 'stage', 'reasonCode', 'nextCheckCondition', 'sourceRef', 'observedAt'}
UUID = re.compile('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}')
HASH = re.compile('[a-f0-9]{64}')
OPEN = {'待推进', '等反馈', '待处理', '进行中'}

def matches(claim, job):
    return job.get('client') == claim['client'] and job.get('peer') == claim['peer'] and (job.get('action') == claim['action']) and (job.get('scopeBusinessId', claim.get('scopeBusinessId', claim['businessKey'])) == claim.get('scopeBusinessId', claim['businessKey'])) and (job.get('scopeOwnerThreadId', claim['ownerThreadId']) == claim['ownerThreadId'])

def component_delivered(claim, component, job):
    if not matches(claim, job) or job.get('receiptConflict') or (not proof_valid(job)):
        return False
    if 'payloadSha256' in component:
        identity_matches = job.get('action') == 'send_image' and job['nativeProof'].get('payloadSha256') == component['payloadSha256']
    else:
        identity_matches = job.get('contentHash') == component.get('contentHash')
    return identity_matches and (family(job['request_id']) == family(component['requestId']) or component['requestId'] in job.get('supersedes', []))

def build(claims, exact, jobs, people, observed_at, gaps=(), policy_format_version=2):
    owners = {p['id']: p['threadId'] for p in people}
    gaps = set(gaps) | {'outside_explicit_sources'}
    rows = {}
    component_jobs = [*jobs, *(j for j in exact.values() if j.get('state') != 'not_found')]
    for claim in claims:
        if not claim['positive']:
            continue
        (employee, owner) = (claim['employee'], claim['ownerThreadId'])
        if owners.get(employee) != owner or OWNERS.get(employee) != owner or CLIENTS.get(claim['client']) != employee:
            gaps.add('identity_mismatch')
            continue
        claim = dict(claim)
        if policy_format_version == 2 and (claim.get('kind') == 'authority' or claim.get('ownerAuthorized')):
            claim.update(ownerAuthorized=True, capabilityReady=True)
        remaining = claim['componentCount']
        if claim.get('components'):
            remaining = sum((not any((component_delivered(claim, component, j) for j in component_jobs)) for component in claim['components']))
            if remaining == 0:
                continue
            if claim.get('ownerAuthorized') and (not claim.get('capabilityReady')):
                gaps.add('bp_capability_preparation_pending')
                continue
            if claim.get('ownerAuthorized') and claim.get('capabilityReady'):
                untouched = all((exact.get((claim['client'], c['requestId']), {}).get('state') == 'not_found' for c in claim['components']))
                if not untouched:
                    gaps.add('bp_delivery_receipts_pending')
                    continue
        rid = claim['requestId']
        original = exact.get((claim['client'], rid)) if rid else None
        fingerprint = claim.get('contentHash')
        if original and original['state'] != 'not_found':
            if not matches(claim, original) or (fingerprint and fingerprint != original.get('contentHash')):
                gaps.add('conflicting_component_evidence')
                continue
            fingerprint = fingerprint or original.get('contentHash')
        if rid and fingerprint and any((matches(claim, j) and j.get('contentHash') == fingerprint and (not j.get('receiptConflict')) and proof_valid(j) and (j['request_id'] == rid or family(j['request_id']) == family(rid) or rid in j.get('supersedes', [])) for j in [*jobs, *([original] if original else [])])):
            continue
        kind = claim['kind']
        if kind == 'authority':
            if policy_format_version != 2:
                gaps.add('source_read_or_format' if policy_format_version is None else 'bp_capability_preparation_pending')
                continue
            kind = 'prepared'
        if rid and original is None:
            gaps.add('exact_receipt_unavailable')
            continue
        if kind == 'prepared' and rid and (original['state'] != 'not_found'):
            if original['state'] != 'failed' or original.get('noSend') is not True or original.get('serverId'):
                if original['state'] in ('succeeded', 'failed', 'unknown'):
                    gaps.add('exact_receipt_unavailable')
                continue
            kind = 'failed'
        if kind == 'failed' and (not (original and original['state'] == 'failed' and (original.get('noSend') is True) and (not original.get('serverId')))):
            if original and original['state'] in ('succeeded', 'failed', 'unknown', 'not_found'):
                gaps.add('exact_receipt_unavailable')
            continue
        (stage, reason, next_check) = KINDS[kind]
        row = {k: claim[k] for k in ['employee', 'ownerThreadId', 'businessKey', 'requestId', 'componentCount', 'sourceRef']}
        row.update(stage=stage, reasonCode=reason, nextCheckCondition=next_check, observedAt=observed_at)
        row['componentCount'] = remaining
        rows[owner, claim['businessKey'], rid] = row
    return {'version': 1, 'observedAt': observed_at, 'coverage': {'bounded': True, 'gaps': sorted(gaps)}, 'rows': list(rows.values())}

def bp_authority_status(head, original, current, owner_authorized=False):
    raise ValueError('instance-specific authority adapter omitted; configure your own reviewed source adapter')

def bp_owner_authorized(value):
    return False

def validate(value, owners, sources):

    def valid_time(t):
        return type(t) in (int, float) and math.isfinite(t) and (t > 0)
    if set(value) != {'version', 'observedAt', 'coverage', 'rows'} or type(value['version']) is not int or value['version'] != 1 or (not valid_time(value['observedAt'])):
        raise ValueError('invalid obligation envelope')
    coverage = value['coverage']
    if set(coverage) != {'bounded', 'gaps'} or coverage['bounded'] is not True or (not isinstance(coverage['gaps'], list)) or (len(coverage['gaps']) > len(GAPS)) or any((not isinstance(g, str) or g not in GAPS for g in coverage['gaps'])):
        raise ValueError('invalid obligation coverage')
    if not isinstance(value['rows'], list) or len(value['rows']) > 200:
        raise ValueError('obligation row budget')
    seen = set()
    for row in value['rows']:
        if set(row) != ROW_FIELDS:
            raise ValueError('unexpected obligation field')
        (employee, owner, rid) = (row['employee'], row['ownerThreadId'], row['requestId'])
        if not isinstance(owner, str) or not UUID.fullmatch(owner) or owners.get(employee) != owner or (OWNERS.get(employee) != owner):
            raise ValueError('obligation identity')
        if not isinstance(row['businessKey'], str) or not RID.fullmatch(row['businessKey']) or (rid is not None and (not isinstance(rid, str) or not RID.fullmatch(rid))):
            raise ValueError('obligation identifiers')
        ref = row['sourceRef']
        if ref is not None and (not isinstance(ref, str) or not re.fullmatch('work-[a-f0-9]{22}', ref) or ref not in sources):
            raise ValueError('invalid obligation source reference')
        if type(row['componentCount']) is not int or not 1 <= row['componentCount'] <= 20 or (row['stage'], row['reasonCode'], row['nextCheckCondition']) not in KINDS.values() or (row['observedAt'] != value['observedAt']) or (not valid_time(row['observedAt'])):
            raise ValueError('invalid obligation state')
        key = (owner, row['businessKey'], rid)
        if key in seen:
            raise ValueError('duplicate obligation component')
        seen.add(key)

def exact_reads(claims):
    targets = {}
    for claim in claims:
        if claim['requestId']:
            targets.setdefault(claim['client'], set()).add(claim['requestId'])
        for component in claim.get('components', []):
            targets.setdefault(claim['client'], set()).add(component['requestId'])

    def read(client, ids):
        data = readonly({'op': 'get_many', 'client': client, 'request_ids': sorted(ids), 'wait_seconds': 0, 'audit': False})
        found = {}
        for row in data['jobs']:
            rid = row.get('request_id')
            if rid not in ids:
                continue
            if row.get('state') == 'not_found' and row.get('error', {}).get('code') == 'REQUEST_NOT_FOUND':
                found[client, rid] = {'state': 'not_found'}
            elif row.get('client') == client:
                projected = project(row)
                if projected:
                    found[client, rid] = projected
        return found
    (results, gaps) = ({}, set())
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(read, client, ids) for (client, ids) in targets.items()]
        for future in futures:
            try:
                results.update(future.result())
            except Exception:
                gaps.add('exact_receipt_unavailable')
    return (results, gaps)

def collect(roles, people, items, sources, jobs, when, observed_at, policy_format_version=None):
    return build([], {}, jobs, people, observed_at, ['outside_explicit_sources'], policy_format_version=policy_format_version)
