"""Read-cache for immutable, source-backed deliveries. Uses the existing observer cache.
No I/O, worker calls, media, private payloads, new ledger or background lifecycle.
Legacy projection flags supply exact requery IDs only; they never manufacture proof.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, hashlib, json, math, re
MAX_ENTRIES = 1000
MAX_CACHE_BYTES = 4000000
HEX = re.compile('[a-f0-9]{64}\\Z')
SAFE_FIELDS = {'jobId', 'client', 'request_id', 'peer', 'action', 'state', 'created', 'updated', 'serverId', 'noSend', 'reason', 'contentHash', 'nativeReceiptVerified', 'nativeProof', 'kind', 'supersedes'}

def proof_valid(j):
    p = j.get('nativeProof') or {}
    sha = j.get('contentHash')
    if not isinstance(p, dict) or not isinstance(sha, str) or (not HEX.fullmatch(sha)):
        return False
    if j.get('state') != 'succeeded' or j.get('nativeReceiptVerified') is not True or j.get('noSend') is True or (p.get('peer') != j.get('peer')) or (p.get('serverId') != j.get('serverId')) or (not re.fullmatch('[0-9]{1,20}', str(p.get('serverId', '')))) or (int(p['serverId']) == 0):
        return False
    kind = p.get('kind')
    common = {'kind', 'peer', 'serverId'}
    if kind == 'text_specific_author_accepted':
        return __import__('talent02_specific_proof').valid_cached(j)
    if kind == 'text_exact_sha256':
        allowed = common | {'senderId', 'nativeStatus', 'nativeCreateTime', 'uniqueCandidateCount', 'expectedSHA256', 'actualSHA256', 'evidence'}
        return set(p) <= allowed and j.get('action') == 'send_text' and isinstance(p.get('senderId'), str) and bool(re.fullmatch('[A-Za-z0-9_.@-]{1,160}', p['senderId'])) and (p.get('nativeStatus') == 2) and (p.get('uniqueCandidateCount') == 1) and (type(p.get('nativeCreateTime')) in (int, float)) and math.isfinite(p['nativeCreateTime']) and (p['nativeCreateTime'] > 0) and (p.get('evidence') == 'native-sender-status-and-operation-semantics') and (p.get('expectedSHA256') == sha == p.get('actualSHA256'))
    if kind == 'text_single_terminal_lf_removed':
        extras = {'comparisonMode', 'normalizedExpectedSHA256', 'removedTerminalLFCount', 'expectedChars', 'actualChars'}
        if p.get('comparisonMode') != 'single_terminal_lf_removed' or type(p.get('removedTerminalLFCount')) is not int or p['removedTerminalLFCount'] != 1 or (p.get('normalizedExpectedSHA256') != sha) or (not HEX.fullmatch(str(p.get('expectedSHA256', '')))) or (p['expectedSHA256'] == sha) or (type(p.get('expectedChars')) is not int) or (type(p.get('actualChars')) is not int) or (p['actualChars'] <= 0) or (p['expectedChars'] != p['actualChars'] + 1):
            return False
        exact = {k: v for (k, v) in p.items() if k not in extras}
        exact.update(kind='text_exact_sha256', expectedSHA256=p['normalizedExpectedSHA256'])
        return proof_valid(dict(j, nativeProof=exact))
    if kind == 'forward_article_app5':
        from send_tool_observer import forward_fingerprint
        hashes = {'titleSHA256', 'urlSHA256', 'nativeRowSHA256', 'macExportSHA256', 'macReceiptSHA256', 'nativeReadbackSHA256', 'articleIdentitySHA256', 'sourceDecisionSHA256'}
        return set(p) == common | hashes | {'senderId', 'nativeKind', 'appType', 'nativeCreateTime', 'sourcePeer', 'sourceId'} and j.get('action') == 'forward' and (p.get('nativeKind') == 49) and (p.get('appType') == 5) and isinstance(p.get('senderId'), str) and bool(re.fullmatch('[A-Za-z0-9_.@-]{1,160}', p['senderId'])) and (type(p.get('nativeCreateTime')) in (int, float)) and math.isfinite(p['nativeCreateTime']) and (p['nativeCreateTime'] > 0) and all((HEX.fullmatch(str(p.get(k, ''))) for k in hashes)) and (sha == forward_fingerprint({'source_peer': p.get('sourcePeer'), 'source_id': p.get('sourceId')}))
    if kind == 'forward_article_app5_aup':
        from send_tool_observer import forward_fingerprint
        hashes = {'titleSHA256', 'urlSHA256', 'sourceRowSHA256', 'outboundRowSHA256', 'attemptSHA256', 'forwardPhaseSHA256', 'snapshotReceiptSHA256', 'readerCodeSHA256', 'parserCodeSHA256', 'manifestSHA256', 'bundleSHA256', 'probeSHA256', 'probeScriptSHA256'}
        return set(p) == common | hashes | {'originHost', 'reader', 'jobId', 'senderId', 'nativeStatus', 'nativeKind', 'appType', 'nativeCreateTime', 'sourcePeer', 'sourceId'} and j.get('action') == 'forward' and (p.get('originHost') == 'fixture-aup-host') and (p.get('reader') == 'linux_tool.native') and (p.get('jobId') == j.get('jobId')) and bool(re.fullmatch('[a-f0-9]{32}', str(p.get('jobId', '')))) and (p.get('senderId') == 'wxid_fixture_operator') and (p.get('nativeStatus') == 2) and (p.get('nativeKind') == 49) and (p.get('appType') == 5) and (type(p.get('nativeCreateTime')) in (int, float)) and math.isfinite(p['nativeCreateTime']) and (p['nativeCreateTime'] > 0) and all((HEX.fullmatch(str(p.get(k, ''))) for k in hashes)) and (sha == forward_fingerprint({'source_peer': p.get('sourcePeer'), 'source_id': p.get('sourceId')}))
    if kind == 'file_name_size_md5':
        return set(p) <= common | {'assetId', 'localId', 'nativeFilenameMatch', 'nativeSizeMatch', 'nativeMD5Match'} and j.get('action') == 'send_file' and (p.get('assetId') == sha) and (type(p.get('localId')) is int) and (p['localId'] > 0) and all((p.get(k) is True for k in ['nativeFilenameMatch', 'nativeSizeMatch', 'nativeMD5Match']))
    if kind == 'image_native_committed':
        return set(p) <= common | {'assetId', 'localId', 'payloadSha256', 'evidence'} and j.get('action') == 'send_image' and (p.get('assetId') == sha) and (type(p.get('localId')) is int) and (p['localId'] > 0) and (p.get('evidence') == 'sender-native-committed') and bool(HEX.fullmatch(str(p.get('payloadSha256', ''))))
    return False

def source_json(s, prefix):
    if not isinstance(s, dict) or set(s) - {'id', 'path', 'label', 'text', 'time', 'role'}:
        raise ValueError('invalid cached source')
    path = s.get('path', '')
    text = s.get('text', '')
    if not isinstance(path, str) or not path.startswith(prefix) or (not isinstance(text, str)) or (len(text.encode()) > 8000):
        raise ValueError('unbounded receipt source')
    if s.get('id') != 'work-' + hashlib.sha256((path + '\x00' + text).encode()).hexdigest()[:22]:
        raise ValueError('cached source checksum mismatch')
    return json.loads(text)

def member(s, client):
    from send_tool_observer import CLIENTS, RID
    j = source_json(s, '原微信工具:' + client + '/')
    if set(j) - SAFE_FIELDS or j.get('client') != client or (not RID.fullmatch(str(j.get('request_id', '')))) or (s['path'] != '原微信工具:' + client + '/' + j['request_id']) or (not j.get('peer')) or (j.get('action') not in ['send_text', 'send_image', 'send_file', 'reply', 'forward']) or (not HEX.fullmatch(str(j.get('contentHash', '')))):
        raise ValueError('receipt identity absent')
    if any((type(j.get(k)) not in (int, float) or not math.isfinite(j[k]) or j[k] <= 0 for k in ['created', 'updated'])):
        raise ValueError('invalid receipt times')
    if client == 'aup_support' and (not __import__('send_tool_observer').observed_delivery(j.get('peer'), j.get('action')) or not re.fullmatch('[a-f0-9]{32}', str(j.get('jobId', '')))):
        raise ValueError('aup receipt fixed scope')
    if client == 'research_secretary':
        from research_secretary_scope import STARTED_AT
        if not __import__('send_tool_observer').observed_delivery(j.get('peer'), j.get('action')) or j['created'] < STARTED_AT or (not re.fullmatch('[a-f0-9]{32}', str(j.get('jobId', '')))):
            raise ValueError('research secretary receipt scope')
    if j.get('nativeReceiptVerified') and (not proof_valid(j)):
        raise ValueError('flag without native proof')
    if (j.get('nativeProof') or {}).get('kind') == 'text_specific_author_accepted':
        j['scopeOwnerThreadId'] = __import__('talent02_specific_proof').CASE['authorThread']
    return dict(j, employee=CLIENTS[client], sourceId=s['id'])

def decode(e):
    from send_tool_observer import CLIENTS
    if not isinstance(e, dict) or set(e) != {'businessId', 'employee', 'ownerThreadId', 'client', 'componentId', 'componentSource', 'memberSources'}:
        raise ValueError('invalid receipt cache entry')
    if CLIENTS.get(e['client']) != e['employee'] or not isinstance(e['memberSources'], list) or (not 1 <= len(e['memberSources']) <= 20):
        raise ValueError('receipt cache scope')
    if e['client'] == 'aup_support' and e['ownerThreadId'] != __import__('send_tool_observer').AUP_OWNER:
        raise ValueError('aup cached owner scope')
    if e['client'] == 'research_secretary' and e['ownerThreadId'] != __import__('research_secretary_scope').THREAD:
        raise ValueError('research secretary cached owner')
    inc = source_json(e['componentSource'], '交付组件:')
    if any((inc.get(k) != e[k] for k in ['businessId', 'employee', 'ownerThreadId', 'client'])) or inc.get('id') != e['componentId'] or e['componentSource']['path'] != '交付组件:' + e['componentId'] or (inc.get('status') != 'resolved') or (inc.get('nativeReceiptVerified') is not True):
        raise ValueError('component attestation mismatch')
    jobs = [member(s, e['client']) for s in e['memberSources']]
    if any(((j.get('nativeProof') or {}).get('kind') == 'text_specific_author_accepted' for j in jobs)) and (e['ownerThreadId'] != __import__('talent02_specific_proof').CASE['authorThread'] or len(jobs) != 1 or jobs[0]['request_id'] != __import__('talent02_specific_proof').CASE['requestId']):
        raise ValueError('specific cached original-only scope')
    if len({j['request_id'] for j in jobs}) != len(jobs) or any((j['request_id'] not in inc.get('requestIds', []) or j['sourceId'] not in inc.get('evidenceRefs', []) for j in jobs)) or (not any((proof_valid(j) for j in jobs))):
        raise ValueError('component native evidence absent')
    return jobs

def scope(e):
    return (e['businessId'], e['employee'], e['ownerThreadId'], e['client'])

def matching_seed(e, s):
    return scope(e) == (s['businessId'], s['employee'], s['ownerThreadId'], e['client'])

def legacy_indexes(sources, positive_only=False):
    """Only the already-held component/operation sources, not chats or external files."""
    from send_tool_observer import CLIENTS, RID
    result = []
    seen = set()
    count = 0
    for s in sources.values():
        if not s.get('path', '').startswith('交付组件:'):
            continue
        count += 1
        if count > 2000:
            break
        try:
            c = source_json(s, '交付组件:')
            if c.get('status') not in ['blocked', 'unknown', 'pending', 'resolved', 'not_required'] or CLIENTS.get(c.get('client')) != c.get('employee'):
                continue
            for ref in c.get('evidenceRefs', [])[:22]:
                old = sources.get(ref, {})
                if not old.get('path', '').startswith('原微信工具:' + c['client'] + '/'):
                    continue
                v = source_json(old, '原微信工具:' + c['client'] + '/')
                rid = v.get('request_id', '')
                if not RID.fullmatch(rid) or rid not in c.get('requestIds', []) or v.get('client') != c['client'] or (v.get('state') not in ['succeeded', 'failed', 'cancelled', 'queued', 'preparing', 'awaiting_confirmation', 'confirmed', 'executing', 'needs_attention', 'pending']) or (v.get('action') not in ['send_text', 'send_file', 'send_image', 'forward', 'reply']) or (not v.get('peer')):
                    continue
                if positive_only and (v.get('state') != 'succeeded' or v.get('nativeReceiptVerified') is not True):
                    continue
                key = (c['businessId'], c['employee'], c['ownerThreadId'], c['client'], rid)
                if key not in seen:
                    result.append(key)
                    seen.add(key)
        except (ValueError, KeyError, TypeError):
            continue
    return result

def prepare_receipts(items, seeds, sources, stored):
    entries = []
    gaps = []
    for e in (stored or {}).get('entries', [])[:MAX_ENTRIES]:
        try:
            decode(e)
            entries.append(copy.deepcopy(e))
        except (ValueError, KeyError, TypeError):
            gaps.append('历史回执缓存缺少完整证明或范围不符；保留观测缺口，不采用标记')
    rich_scopes = {}
    for entry in entries:
        for job in decode(entry):
            rich_scopes.setdefault((entry['client'], job['request_id']), set()).add(scope(entry))

    def admitted(seed, client, rid):
        known = rich_scopes.get((client, rid))
        return not known or (seed['businessId'], seed['employee'], seed['ownerThreadId'], client) in known
    legacy = legacy_indexes(sources)
    positive_legacy = legacy_indexes(sources, positive_only=True)
    prepared = []
    if sum((str(s.get('path', '')).startswith('交付组件:') for s in sources.values())) > 2000:
        gaps.append('历史关联来源超过2000项索引预算；未覆盖部分保留缺口')
    for original in seeds:
        s = copy.deepcopy(original)
        from send_tool_observer import CLIENTS
        client = next((c for (c, e) in CLIENTS.items() if e == s['employee']), None)
        rejected = {rid for rid in s['requestIds'] if not admitted(s, client, rid)}
        rejected.update((rid for (bid, emp, owner, c, rid) in legacy if (bid, emp, owner) == (s['businessId'], s['employee'], s['ownerThreadId']) and (not admitted(s, c, rid))))
        s['excludedReceiptScopes'] = sorted(rejected)
        s['requestIds'] = [rid for rid in s['requestIds'] if rid not in rejected]
        s['operationEvidenceIds'] = [rid for rid in s.get('operationEvidenceIds', []) if rid not in rejected]
        s['currentRequestIds'] = list(s['requestIds'])
        s['legacyRequeryIds'] = []
        s['factRequestIds'] = []
        for e in entries:
            if matching_seed(e, s):
                s['factRequestIds'] += [j['request_id'] for j in decode(e)]
        for (bid, emp, owner, c, rid) in legacy:
            if (bid, emp, owner) == (s['businessId'], s['employee'], s['ownerThreadId']) and rid not in s['factRequestIds'] and admitted(s, c, rid):
                s['legacyRequeryIds'].append(rid)
        s['requestIds'] = list(dict.fromkeys(s['currentRequestIds'] + s['legacyRequeryIds'] + s['factRequestIds']))
        s['positiveRequeryIds'] = [rid for (bid, emp, owner, c, rid) in positive_legacy if (bid, emp, owner) == (s['businessId'], s['employee'], s['ownerThreadId'])]
        s['knownReceiptScopes'] = [(bid, emp, owner, c, rid) for (bid, emp, owner, c, rid) in legacy if rid in s['requestIds']]
        prepared.append(s)
    return (prepared, entries, list(dict.fromkeys(gaps)))

def identity_conflict(old, new):
    for k in ['client', 'request_id', 'peer', 'action', 'contentHash']:
        if new.get(k) is not None and new.get(k) != old.get(k):
            return True
    if proof_valid(old):
        if old.get('jobId') and new.get('jobId') and (old['jobId'] != new['jobId']):
            return True
        if new.get('state') == 'failed' and new.get('noSend') is True:
            return True
        if new.get('serverId') and new['serverId'] != old['serverId']:
            return True
        p = new.get('nativeProof') or {}
        op = old.get('nativeProof') or {}
        if p.get('senderId') and p['senderId'] != op.get('senderId'):
            return True
    return False

def apply_receipts(items, seeds, current, sources, entries):
    """Requery absence affects coverage only. Identity conflicts never use cached success."""
    bindings = {}
    proven_bindings = {}
    decoded = []
    active = {(s['businessId'], s['employee'], s['ownerThreadId']) for s in seeds}
    effective = []
    gaps = []
    for s in seeds:
        for (bid, emp, owner, c, rid) in s.get('knownReceiptScopes', []):
            bindings.setdefault((c, rid), set()).add((bid, emp, owner, c))
    for e in entries:
        js = decode(e)
        decoded.append((e, js))
        for j in js:
            key = (j['client'], j['request_id'])
            proven_bindings.setdefault(key, set()).add(scope(e))
    bindings.update(proven_bindings)
    raw = {(j['client'], j['request_id']): j for j in current}
    used = set()
    for (e, js) in decoded:
        if scope(e)[:3] not in active:
            continue
        for src in [e['componentSource']] + e['memberSources']:
            sources.setdefault(src['id'], copy.deepcopy(src))
        conflict = any((identity_conflict(j, raw[j['client'], j['request_id']]) for j in js if (j['client'], j['request_id']) in raw))
        for old in js:
            key = (old['client'], old['request_id'])
            fresh = raw.get(key)
            used.add(key)
            if conflict:
                j = copy.deepcopy(fresh or old)
                j['nativeReceiptVerified'] = False
                j['receiptConflict'] = True
                j['conflictSourceIds'] = [old['sourceId']] + ([fresh['sourceId']] if fresh and fresh.get('sourceId') else [])
            elif fresh and fresh.get('peer') and fresh.get('contentHash') and (not proof_valid(old) or proof_valid(fresh)):
                j = copy.deepcopy(fresh)
            else:
                j = copy.deepcopy(old)
                j['retainedReceipt'] = True
                gaps.append('历史已核交付沿原生证明保留；本轮未完整复核 ' + key[0] + '/' + key[1])
            j.update(scopeBusinessId=e['businessId'], scopeOwnerThreadId=e['ownerThreadId'], knownComponentId=e['componentId'], associationSourceId=e['componentSource']['id'])
            effective.append(j)
    for seed in seeds:
        if not seed.get('businessDeferred'):
            continue
        for attestation in list(sources.values()):
            if not attestation.get('path', '').startswith('交付组件:'):
                continue
            try:
                inc = source_json(attestation, '交付组件:')
                if inc.get('status') != 'pending' or inc.get('reasonCode') != 'business_deferred_unsent' or any((inc.get(k) != seed[k] for k in ['businessId', 'employee', 'ownerThreadId'])):
                    continue
                for ref in inc.get('evidenceRefs', [])[:22]:
                    src = sources.get(ref, {})
                    if not src.get('path', '').startswith('原微信工具:' + inc['client'] + '/'):
                        continue
                    old = source_json(src, '原微信工具:' + inc['client'] + '/')
                    rid = old.get('request_id')
                    key = (inc['client'], rid)
                    if key in used or key in raw or any((re.sub('-r\\d+$', '', r) == re.sub('-r\\d+$', '', str(rid)) for r in seed.get('positiveRequeryIds', []) + seed.get('factRequestIds', []))) or (rid not in seed['requestIds']) or (rid not in inc['requestIds']) or (old.get('client') != inc['client']) or (old.get('state') != 'failed') or (old.get('noSend') is not True):
                        continue
                    if set(old) - SAFE_FIELDS or old.get('nativeReceiptVerified') or (not old.get('peer')) or (old.get('action') not in ['send_text', 'send_file', 'send_image']):
                        continue
                    from send_tool_observer import CLIENTS
                    if CLIENTS.get(inc['client']) != seed['employee']:
                        continue
                    effective.append(dict(old, employee=seed['employee'], sourceId=ref, scopeBusinessId=seed['businessId'], scopeOwnerThreadId=seed['ownerThreadId'], knownComponentId=inc['id'], associationSourceId=attestation['id'], retainedReceipt=True))
                    used.add(key)
                    gaps.append('暂缓事项沿原失败/noSend依据保留；本轮未复核 ' + inc['client'] + '/' + rid)
            except (KeyError, ValueError, TypeError):
                continue
    for (key, j) in raw.items():
        if key in used:
            continue
        allowed = bindings.get(key)
        if allowed:
            for (bid, emp, owner, c) in allowed:
                if (bid, emp, owner) in active:
                    effective.append(dict(j, scopeBusinessId=bid, scopeOwnerThreadId=owner))
        else:
            effective.append(j)
    return (effective, list(dict.fromkeys(gaps)))

def fact_signature(e):
    return sorted(((j['client'], j['request_id'], j['peer'], j['action'], j['contentHash'], j.get('serverId') if proof_valid(j) else None, json.dumps(j.get('nativeProof'), sort_keys=True) if proof_valid(j) else None) for j in decode(e)))

def remember_receipts(health, jobs, sources, stored):
    from send_tool_observer import CLIENTS
    existing = {}
    gaps = []
    for e in (stored or {}).get('entries', [])[:MAX_ENTRIES]:
        try:
            decode(e)
            existing[scope(e), e['componentId']] = e
        except (ValueError, KeyError, TypeError):
            gaps.append('旧回执缓存证明无效，未将其当成已交付')
    for c in health['incidents']:
        if c['status'] != 'resolved' or not c['nativeReceiptVerified']:
            continue
        js = [j for j in jobs if j.get('client') == c['client'] and j.get('employee') == c['employee'] and (j['request_id'] in c['requestIds']) and (j.get('scopeBusinessId', c['businessId']) == c['businessId']) and (not j.get('receiptConflict'))]
        refs = list(dict.fromkeys((j.get('sourceId') for j in js if j.get('sourceId'))))
        comp = next((sources[x] for x in reversed(c['evidenceRefs']) if x in sources and sources[x].get('path') == '交付组件:' + c['id']), None)
        if not any((proof_valid(j) for j in js)):
            gaps.append('已交记录尚无可持久保留的完整原生证明：' + c['id'])
            continue
        e = {'businessId': c['businessId'], 'employee': c['employee'], 'ownerThreadId': c['ownerThreadId'], 'client': c['client'], 'componentId': c['id'], 'componentSource': copy.deepcopy(comp), 'memberSources': [copy.deepcopy(sources[x]) for x in refs if x in sources]}
        try:
            decoded = decode(e)
            if any((any((j.get(k) != s.get(k) for k in ['client', 'request_id', 'peer', 'action', 'contentHash', 'nativeProof'])) for j in js for s in decoded if j['request_id'] == s['request_id'])):
                raise ValueError('job/source proof mismatch')
        except (ValueError, KeyError, TypeError):
            gaps.append('原生证明或组件关联不完整，未缓存为送达事实：' + c['id'])
            continue
        key = (scope(e), e['componentId'])
        if key in existing and fact_signature(existing[key]) == fact_signature(e):
            continue
        candidate = dict(existing)
        candidate[key] = e
        state = {'version': 1, 'entries': list(candidate.values())}
        if len(candidate) > MAX_ENTRIES or len(json.dumps(state, ensure_ascii=False).encode()) > MAX_CACHE_BYTES:
            gaps.append('历史回执缓存达到预算；原证明保留，新事实未进入缓存')
            continue
        existing = candidate
    return ({'version': 1, 'entries': list(existing.values())}, list(dict.fromkeys(gaps)))
