"""Bounded read-only adapter: status/list/get/dispatch_summary/get_many only."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import concurrent.futures, hashlib, json, math, re, sys
CLIENTS = _install.setting('monitor.send_tool_observer', 'CLIENTS', {})
AUP_OWNER = _install.identity('monitor.send_tool_observer.AUP_OWNER')
RID = re.compile('[A-Za-z0-9][A-Za-z0-9._-]{0,95}\\Z')

def readonly(request, call=None):
    op = request.get('op')
    if op not in ['status', 'list', 'get', 'dispatch_summary', 'get_many']:
        raise ValueError('observer cannot execute operations')
    if op != 'status' and request.get('client') not in CLIENTS:
        raise ValueError('unmapped attribution client in this read adapter')
    if op in ['get', 'get_many']:
        ids = [request.get('request_id')] if op == 'get' else request.get('request_ids')
        if request.get('wait_seconds') != 0 or (request.get('audit', False) is not False and (not __import__('talent02_specific_proof').scoped_audit_request(request))) or (not isinstance(ids, list)) or (not 1 <= len(ids) <= 50) or any((not isinstance(v, str) or not RID.fullmatch(v) for v in ids)) or (len(set(ids)) != len(ids)):
            raise ValueError('invalid bounded read')
    if op == 'dispatch_summary' and (type(request.get('limit')) is not int or not 1 <= request['limit'] <= 20):
        raise ValueError('summary cap')
    if call is None:
        sys.path.insert(0, str(_install.REPO / 'host/tools'))
        from wechat_operations import call
    return call(request)

def forward_fingerprint(payload):
    if not isinstance(payload, dict) or not re.fullmatch('[A-Za-z0-9_.@-]{1,160}', str(payload.get('source_peer', ''))) or (not re.fullmatch('[1-9][0-9]{0,19}', str(payload.get('source_id', '')))):
        return None
    return hashlib.sha256(json.dumps(['forward', payload['source_peer'], str(payload['source_id'])], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def observed_delivery(peer, action):
    return isinstance(peer, str) and bool(re.fullmatch('[A-Za-z0-9_@.-]{1,120}', peer)) and ('..' not in peer) and (action in ['send_text', 'send_image', 'send_file', 'reply', 'forward'])

def project(job):
    if job.get('client') not in CLIENTS or job.get('action') not in ['send_text', 'send_image', 'send_file', 'reply', 'forward'] or (not RID.fullmatch(str(job.get('request_id', '')))):
        return None
    if job.get('client') in ['aup_support', 'research_secretary']:
        if not observed_delivery(job.get('peer'), job.get('action')) or not re.fullmatch('[a-f0-9]{32}', str(job.get('id', ''))) or job.get('state') not in ['queued', 'preparing', 'awaiting_confirmation', 'confirmed', 'executing', 'needs_attention', 'succeeded', 'failed', 'cancelled']:
            return None
        if any((type(job.get(k)) not in (int, float) or not math.isfinite(job[k]) or job[k] <= 0 for k in ['created', 'updated'])):
            return None
        if job['client'] == 'research_secretary' and job['created'] < __import__('research_secretary_scope').STARTED_AT:
            return None
        payload = job.get('payload')
        if not isinstance(payload, dict):
            return None
        if job['action'] in ['send_text', 'reply'] and (not isinstance(payload.get('text'), str) or not payload['text'].strip()):
            return None
        if job['action'] in ['send_image', 'send_file'] and (not re.fullmatch('[a-f0-9]{64}', str(payload.get('asset') or payload.get('asset_id') or payload.get('assetId') or ''))):
            return None
        if job['action'] == 'reply' and (not re.fullmatch('[1-9][0-9]{0,19}', str(payload.get('source_id', '')))):
            return None
        if job['action'] == 'forward' and forward_fingerprint(payload) is None:
            return None
    payload = job.get('payload') or {}
    result = job.get('result') or {}
    outcome = job.get('outcome') or {}
    dispatch = job.get('dispatch') or {}
    review = job.get('mechanismReview') or {}
    text = payload.get('text')
    fingerprint = hashlib.sha256(text.rstrip('\n').encode()).hexdigest() if isinstance(text, str) and text else None
    if job['action'] == 'forward':
        fingerprint = forward_fingerprint(payload)
    tc = result.get('textComparison') or {}
    identity = job.get('state') == 'succeeded' and result.get('state') == 'accepted' and (result.get('peer') == job.get('peer')) and bool(result.get('serverId')) and (result.get('nativeStatus') == 2) and (result.get('uniqueCandidateCount') == 1) and bool(result.get('nativeCreateTime'))
    verified = bool(job['action'] == 'send_text' and identity and fingerprint and (tc.get('expectedSHA256') == fingerprint) and (tc.get('actualSHA256') == fingerprint))
    normalized_lf = bool(job['action'] == 'send_text' and identity and isinstance(text, str) and (len(text) > 1) and text.endswith('\n') and (text[-2] not in '\r\n') and (tc.get('mode') == 'single_terminal_lf_removed') and (type(tc.get('removedTerminalLFCount')) is int) and (tc.get('removedTerminalLFCount') == 1) and (tc.get('expectedText') == text) and (tc.get('actualText') == text[:-1]) and (tc.get('expectedChars') == len(text)) and (tc.get('actualChars') == len(text) - 1) and (tc.get('expectedSHA256') == hashlib.sha256(text.encode()).hexdigest()) and (tc.get('actualSHA256') == fingerprint))
    verified = bool(verified or normalized_lf)
    asset = payload.get('asset') or payload.get('asset_id') or payload.get('assetId')
    if job['action'] in ['send_file', 'send_image']:
        fingerprint = asset if isinstance(asset, str) and re.fullmatch('[a-f0-9]{64}', asset) else None
        native_base = job.get('state') == 'succeeded' and result.get('state') == 'accepted' and (result.get('peer') == job.get('peer')) and re.fullmatch('[0-9]{1,20}', str(result.get('serverId', ''))) and bool(result.get('localId'))
        media_proof = all((result.get(k) is True for k in ['nativeFilenameMatch', 'nativeSizeMatch', 'nativeMD5Match'])) if job['action'] == 'send_file' else result.get('evidence') == 'sender-native-committed' and bool(re.fullmatch('[a-f0-9]{64}', str(result.get('payloadSha256', ''))))
        verified = bool(native_base and fingerprint and media_proof)
    owner = review.get('ownerThreadId')
    owner = owner if isinstance(owner, str) and re.fullmatch('[a-f0-9-]{36}', owner) else None
    from talent02_specific_proof import MODE, proof_for
    specific = proof_for(job) if tc.get('mode') == MODE else None
    if tc.get('mode') == MODE:
        verified = bool(specific)
    proof = None
    if verified:
        proof = {'peer': job.get('peer'), 'serverId': result.get('serverId')}
        if job['action'] == 'send_text':
            proof.update(kind='text_exact_sha256', senderId=result.get('senderId'), nativeStatus=result.get('nativeStatus'), nativeCreateTime=result.get('nativeCreateTime'), uniqueCandidateCount=result.get('uniqueCandidateCount'), expectedSHA256=tc.get('expectedSHA256'), actualSHA256=tc.get('actualSHA256'), evidence=result.get('evidence'))
        elif job['action'] == 'send_file':
            proof.update(kind='file_name_size_md5', assetId=asset, localId=result.get('localId'), nativeFilenameMatch=result.get('nativeFilenameMatch'), nativeSizeMatch=result.get('nativeSizeMatch'), nativeMD5Match=result.get('nativeMD5Match'))
        elif job['action'] == 'send_image':
            proof.update(kind='image_native_committed', assetId=asset, localId=result.get('localId'), payloadSha256=result.get('payloadSha256'), evidence=result.get('evidence'))
        if job['action'] == 'send_text' and normalized_lf:
            proof.update(kind='text_single_terminal_lf_removed', comparisonMode='single_terminal_lf_removed', normalizedExpectedSHA256=fingerprint, removedTerminalLFCount=1, expectedChars=len(text), actualChars=len(text) - 1)
    if specific:
        proof = specific
    projected = {'jobId': job.get('id'), 'client': job['client'], 'employee': CLIENTS[job['client']], 'request_id': job['request_id'], 'peer': job.get('peer'), 'action': job['action'], 'state': job.get('state'), 'created': job.get('created'), 'updated': job.get('updated'), 'text': text, 'assetName': payload.get('name'), 'serverId': result.get('serverId') or result.get('server_id'), 'noSend': result.get('noSend'), 'resultState': result.get('state'), 'outcomeState': outcome.get('status'), 'reason': result.get('code'), 'contentHash': fingerprint, 'nativeReceiptVerified': verified, 'nativeProof': proof, 'recoveryOwnerThreadId': owner, 'kind': dispatch.get('kind'), 'supersedes': [r for r in dispatch.get('supersedes', []) if isinstance(r, str) and RID.fullmatch(r)][:20]}
    if specific:
        projected['scopeOwnerThreadId'] = __import__('talent02_specific_proof').CASE['authorThread']
    from delivery_receipt_cache import proof_valid
    projected['nativeReceiptVerified'] = bool(verified and proof_valid(projected))
    return projected

def read_tools(known=()):
    jobs = {}
    gaps = []
    summaries = {}
    status = readonly({'op': 'status'})

    def listing(c):
        return (readonly({'op': 'list', 'client': c}), readonly({'op': 'dispatch_summary', 'client': c, 'limit': 20}))
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fs = {c: pool.submit(listing, c) for c in CLIENTS}
        for (c, f) in fs.items():
            try:
                (old, recent) = f.result()
                rows = old.get('jobs', [])
                summaries[c] = recent.get('items', [])
                if len(rows) >= 100:
                    gaps.append(c + '：旧列表达到100条上限；最近20项与工作本已知ID另定向读取')
                if recent.get('truncated'):
                    gaps.append(c + '：最近摘要仅20项，不代表全量')
                for raw in rows:
                    p = project(raw)
                    if p:
                        jobs[c, p['request_id']] = p
            except Exception:
                gaps.append(c + '：工具列表或最近摘要读取失败')
    targets = {c: [] for c in CLIENTS}
    for (c, r) in known:
        if c in targets and isinstance(r, str) and RID.fullmatch(r) and (r not in targets[c]):
            targets[c].append(r)
    for (c, rows) in summaries.items():
        for row in rows:
            rid = row.get('request_id')
            if isinstance(rid, str) and RID.fullmatch(rid) and (rid not in targets[c]):
                targets[c].append(rid)
    for (c, ids) in targets.items():
        if len(ids) > 100:
            gaps.append(c + '：已知ID超过本轮100项预算，超出部分保留缺口')
    targets = {c: ids[:100] for (c, ids) in targets.items()}
    reads = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        fs = [(c, ids[i:i + 50], pool.submit(readonly, {'op': 'get_many', 'client': c, 'request_ids': ids[i:i + 50], 'wait_seconds': 0, 'audit': False})) for (c, ids) in targets.items() for i in range(0, len(ids), 50)]
        for (c, ids, f) in fs:
            reads += len(ids)
            try:
                data = f.result()
                seen = set()
                for raw in data.get('jobs', []):
                    rid = raw.get('request_id')
                    seen.add(rid)
                    jobs.pop((c, rid), None)
                    if raw.get('client') == c and rid in ids:
                        p = project(raw)
                        if p:
                            jobs[c, rid] = p
                if len(seen.intersection(ids)) < len(ids):
                    gaps.append(c + '：部分定向请求缺结果，不能判已交付')
            except Exception:
                for rid in ids:
                    jobs.pop((c, rid), None)
                gaps.append(c + '：定向结果暂不可读，不能用旧列表判健康')
    from talent02_specific_proof import CASE, MODE
    key = (CASE['client'], CASE['requestId']) if CASE else None
    if key in jobs:
        try:
            raw = readonly({'op': 'get_many', 'client': CASE['client'], 'request_ids': [CASE['requestId']], 'wait_seconds': 0, 'audit': True})
            exact = [r for r in raw.get('jobs', []) if r.get('id') == CASE['jobId'] and r.get('client') == CASE['client'] and (r.get('request_id') == CASE['requestId'])]
            if len(exact) != 1:
                raise ValueError('original exact result missing')
            fresh = dict(exact[0], _observerSpecificAudit=raw.get('audit'))
            p = project(fresh)
            if p is None:
                raise ValueError('original exact scope mismatch')
            jobs[key] = p
            if not p['nativeReceiptVerified']:
                gaps.append('明确差异原单：本轮接受记录或同件原生审计不完整，保留待核，不重发')
        except Exception:
            jobs[key].update(nativeReceiptVerified=False, nativeProof=None)
            gaps.append('明确差异原单：精确审计本轮不可读，既有已核证明与新观测覆盖分开')
    recent = {(c, r['request_id']) for (c, rows) in summaries.items() for r in rows if isinstance(r, dict) and r.get('request_id')}
    for (key, job) in jobs.items():
        job['recent'] = key in recent
    if not any((j['client'] == 'aup_support' for j in jobs.values())):
        gaps.append('aup_support：本轮未取得该岗真实发件样本；登记/隔离测试不当业务已送达，不表示已覆盖全部历史')
    return {'jobs': list(jobs.values()), 'gaps': gaps, 'status': {**{k: status.get(k) for k in ['workerLive', 'heartbeatFresh', 'uiBusy', 'counts']}, 'policyFormatVersion': (status.get('worker') or {}).get('policyFormatVersion') if type((status.get('worker') or {}).get('policyFormatVersion')) is int else None}, 'listLimited': True, 'targetedReads': reads}
