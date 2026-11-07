"""Normalize exact AUP native article evidence. Pure validation, no I/O or sender calls.
The probe must already have run at the authorized AUP reader, returning metadata only.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import hashlib, json, math, re
from send_tool_observer import project, forward_fingerprint

def _require(value):
    if not value:
        raise ValueError('AUP evidence identity/provenance incomplete or inconsistent')
NAMES = {'RESULT.json', 'native-card-semantic-and-settlement-proof.json', 'reconciliation.json', 'send-window.json'}

def sha(v):
    return hashlib.sha256(v if isinstance(v, bytes) else v.encode()).hexdigest()

def canonical(v):
    return json.dumps(v, sort_keys=True, separators=(',', ':')).encode()

def parse(raw):

    def unique(pairs):
        d = {}
        for (k, v) in pairs:
            if k in d:
                raise ValueError('duplicate evidence key')
            d[k] = v
        return d
    if not isinstance(raw, (bytes, str)) or len(raw) > 65536:
        raise ValueError('bounded evidence required')
    return json.loads(raw, object_pairs_hook=unique)

def unwrap(j):
    if 'value' in j:
        if j.get('status') != 'fulfilled':
            raise ValueError('original source call not fulfilled')
        j = j['value']
    if j.get('isError') is not False:
        raise ValueError('original source error')
    texts = [v['text'] for v in j.get('content', []) if v.get('type') == 'text']
    if len(texts) != 1:
        raise ValueError('ambiguous original source')
    return parse(texts[0])

def qualify(manifest, files, probe_raw):
    try:
        return _qualify(manifest, files, probe_raw)
    except (AssertionError, KeyError, TypeError, AttributeError, IndexError, RecursionError) as e:
        raise ValueError('AUP evidence identity/provenance incomplete or inconsistent') from None

def _qualify(manifest, files, probe_raw):
    if manifest.get('originHost') != 'fixture-aup-host' or manifest.get('sourceWasReadOnly') is not True or set(files) != NAMES or (set(manifest['files']) != NAMES):
        raise ValueError('exact AUP source bundle required')
    docs = {}
    for name in sorted(NAMES):
        b = files[name]
        spec = manifest['files'][name]
        if not isinstance(b, bytes) or len(b) != spec['bytes'] or sha(b) != spec['sha256'] or (spec['origin'] != manifest['originRoot'] + '/' + name):
            raise ValueError('original copy hash/size/path mismatch')
        docs[name] = parse(b)
    job = unwrap(docs['reconciliation.json'])
    result = docs['RESULT.json']
    semantic = docs['native-card-semantic-and-settlement-proof.json']
    native = unwrap(docs['send-window.json'])
    envelope = parse(probe_raw)
    _require(envelope['exitCode'] == 0 and re.fullmatch('[a-f0-9]{64}', envelope['probeScriptSHA256']))
    p = envelope['result']
    out = p['outbound']
    source = p['source']
    scope = job['payload']
    _require(job['client'] == 'secretary' and job['action'] == 'forward' and (job['state'] == 'succeeded') and (job['result']['state'] == 'accepted'))
    _require(re.fullmatch('[a-f0-9]{32}', job['id']) and manifest['originRoot'].startswith(str(_install.path('monitor.delivery_aup_forward_evidence.path_1a2e769c'))) and manifest['originRoot'].endswith('/' + job['request_id']))
    for key in ['client', 'peer', 'action', 'request_id']:
        _require(result[key] == job[key])
    _require(result['state'] == 'succeeded' and result['nativeState'] == 'accepted' and (result['host'] == 'aup') and (result['jobId'] == job['id']))
    _require(p['originHost'] == 'fixture-aup-host' and p['reader'] == 'existing linux_tool.native isolated query-only snapshot' and (p['jobId'] == job['id']) and (p['client'] == job['client']) and (p['action'] == 'forward'))
    _require(result['serverId'] == p['serverId'] == job['result']['serverId'] and result['peer'] == p['peer'] == job['peer'] == out['peer'] and (out['serverId'] == p['serverId']))
    _require(semantic['jobId'] == job['id'] and semantic['peer'] == job['peer'])
    _require(semantic['sourcePeer'] == result['sourcePeer'] == p['sourcePeer'] == scope['source_peer'] == source['peer'])
    _require(semantic['sourceId'] == result['sourceId'] == p['sourceId'] == scope['source_id'] == source['serverId'])
    _require(semantic['attemptSHA256'] == p['attemptSHA256'] and semantic['forwardPhaseSHA256'] == p['forwardPhaseSHA256'])
    _require(semantic['nativeSourceKind'] == result['nativeKind'] == out['nativeKind'] == source['nativeKind'] == 49)
    _require(semantic['nativeSourceAppType'] == result['nativeAppType'] == out['nativeAppType'] == source['nativeAppType'] == 5)
    _require(result['nativeStatus'] == out['nativeStatus'] == 2 and result['senderId'] == out['senderId'] == 'wxid_fixture_operator')
    _require(semantic['sourceTitle'] == result['title'] == p['frozenTitle'] and source['titleSHA256'] == out['titleSHA256'] == sha(p['frozenTitle']))
    _require(semantic['sourcePublicURLSHA256'] == p['frozenURLSHA256'] == source['urlSHA256'] == out['urlSHA256'])
    identities = [semantic['articleIdentity'], result['articleIdentity'], source['articleIdentity'], out['articleIdentity']]
    _require(all((set(v) == {'__biz', 'mid', 'idx', 'sn'} and v == identities[0] and all((isinstance(x, str) and x for x in v.values())) for v in identities)))
    _require(p['rawXMLReturned'] is False and p['otherChatsQueried'] is False and (p['mediaRead'] is False) and (p['UIOrSenderActions'] == 0))
    snapshot = p['snapshotReceipt']
    _require(snapshot['source'] == 'message_0.db' and snapshot['consistency'] == 'committed' and (snapshot['integrity'] == 'ok') and (snapshot['gap'] is None) and snapshot.get('signature'))
    _require(p['snapshotReceiptSHA256'] == sha(canonical(snapshot)))
    cov = native['coverage']
    _require(native['state'] == 'ok' and native['account'] == out['senderId'] and (native['peer'] == job['peer']) and (cov['messageMetadataComplete'] is True) and (cov['gaps'] == []) and (cov['missingIds'] == []) and (cov['truncated'] is False))
    rows = [m for m in native['messages'] if m['serverId'] == p['serverId']]
    _require(len(rows) == 1)
    _require(all((rows[0][key] == out[field] for (key, field) in [('peer', 'peer'), ('serverId', 'serverId'), ('senderId', 'senderId'), ('kind', 'nativeKind'), ('time', 'nativeCreateTime')])))
    _require(type(out['nativeCreateTime']) in (int, float) and p['attemptStartedAt'] - 1 <= out['nativeCreateTime'] <= p['settledAt'] + 1 and (job['created'] <= out['nativeCreateTime'] <= job['updated'] + 2))
    n = project(job)
    _require(n is not None)
    proof = {'kind': 'forward_article_app5_aup', 'originHost': 'fixture-aup-host', 'reader': 'linux_tool.native', 'jobId': job['id'], 'peer': job['peer'], 'serverId': out['serverId'], 'senderId': out['senderId'], 'nativeStatus': 2, 'nativeKind': 49, 'appType': 5, 'nativeCreateTime': out['nativeCreateTime'], 'sourcePeer': scope['source_peer'], 'sourceId': scope['source_id'], 'titleSHA256': out['titleSHA256'], 'urlSHA256': out['urlSHA256'], 'sourceRowSHA256': source['rowSemanticSHA256'], 'outboundRowSHA256': out['rowSemanticSHA256'], 'attemptSHA256': p['attemptSHA256'], 'forwardPhaseSHA256': p['forwardPhaseSHA256'], 'snapshotReceiptSHA256': p['snapshotReceiptSHA256'], 'readerCodeSHA256': p['readerCodeSHA256'], 'parserCodeSHA256': p['parserCodeSHA256'], 'manifestSHA256': sha(canonical(manifest)), 'bundleSHA256': sha(canonical({name: sha(files[name]) for name in sorted(NAMES)})), 'probeSHA256': sha(probe_raw), 'probeScriptSHA256': envelope['probeScriptSHA256']}
    for (k, v) in proof.items():
        if k.endswith('SHA256') and (not re.fullmatch('[a-f0-9]{64}', v)):
            raise ValueError('invalid evidence digest')
    n.update(nativeReceiptVerified=True, nativeProof=proof, jobId=job['id'])
    from delivery_receipt_cache import proof_valid
    if not proof_valid(n):
        raise ValueError('not a complete scoped AUP article proof')
    return n
