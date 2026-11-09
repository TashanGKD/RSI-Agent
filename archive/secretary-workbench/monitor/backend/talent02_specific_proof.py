"""Read only the one original author-accepted disposition; never normalize other text."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import hashlib, json, math, os, stat
from pathlib import Path
ROOT = _install.path('monitor.talent02_specific_proof.ROOT')
CASE = None
FILE_SHA = _install.setting('monitor.talent02_specific_proof', 'FILE_SHA', {})
MODE = 'explicit_specific_deviation_author_accepted'
KIND = 'text_specific_author_accepted'
ASSOCIATION_SHA = None

def digest(v):
    return hashlib.sha256(json.dumps(v, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def need(test):
    if not test:
        raise ValueError('specific original evidence mismatch')

def read_artifacts():
    if CASE is None:
        return {}
    out = {}
    for (name, expected) in FILE_SHA.items():
        path = ROOT / name
        need(not any((p.is_symlink() for p in [path, *path.parents])))
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            a = os.fstat(fd)
            need(stat.S_ISREG(a.st_mode) and a.st_uid == os.getuid() and (not a.st_mode & 18) and (a.st_size <= 65536))
            raw = os.read(fd, 65537)
            z = os.fstat(fd)
            need((a.st_ino, a.st_size, a.st_mtime_ns) == (z.st_ino, z.st_size, z.st_mtime_ns) and len(raw) == a.st_size and (hashlib.sha256(raw).hexdigest() == expected))
            out[name] = json.loads(raw)
        finally:
            os.close(fd)
    return out

def audit_summary(audit):
    if CASE is None:
        return None
    need(isinstance(audit, dict) and audit.get('allVerified') is True and (audit.get('stateWrites') == 0) and (audit.get('newSends') == 0))
    rows = audit.get('items')
    need(isinstance(rows, list) and len(rows) == 1)
    row = rows[0]
    expected = {'request_id': CASE['requestId'], 'status': 'verified', 'peer': CASE['peer'], 'serverId': CASE['nativeServerId'], 'nativeKind': 1, 'nativeCreateTime': CASE['nativeTime'], 'attemptStartedAt': CASE['attemptStartedAt'], 'attemptAndSingleExecutionEvent': True, 'textComparisonMode': MODE, 'canonicalTextExact': False, 'authorAcceptanceVerified': True}
    need(all((type(row.get(k)) is type(v) and row[k] == v for (k, v) in expected.items())))
    return expected

def expected_proof():
    if CASE is None:
        return None
    audit = {'request_id': CASE['requestId'], 'status': 'verified', 'peer': CASE['peer'], 'serverId': CASE['nativeServerId'], 'nativeKind': 1, 'nativeCreateTime': CASE['nativeTime'], 'attemptStartedAt': CASE['attemptStartedAt'], 'attemptAndSingleExecutionEvent': True, 'textComparisonMode': MODE, 'canonicalTextExact': False, 'authorAcceptanceVerified': True}
    return {'kind': KIND, 'peer': CASE['peer'], 'serverId': CASE['nativeServerId'], 'senderId': CASE['account'], 'nativeStatus': 2, 'nativeCreateTime': CASE['nativeTime'], 'uniqueCandidateCount': 1, 'comparisonMode': MODE, 'exact': False, 'expectedSHA256': CASE['expectedTextSHA256'], 'actualSHA256': CASE['actualTextSHA256'], 'expectedChars': 2000, 'actualChars': 1998, 'removedSuffixCodepoints': ['U+0020', 'U+000A'], 'globalNormalizationApplied': False, 'authorThreadId': CASE['authorThread'], 'authorDocumentSHA256': CASE['authorAcceptanceDocumentSHA256'], 'authorRecordSHA256': CASE['recordSHA256'], 'canonicalBodySHA256': CASE['canonicalBodySHA256'], 'canonicalContractSHA256': CASE['canonicalContractSHA256'], 'attemptSHA256': CASE['attemptSHA256'], 'executionCheckSHA256': CASE['executionCheckSHA256'], 'pinnedCaseSHA256': FILE_SHA['PINNED-CASE.private.json'], 'independentEvidenceSHA256': FILE_SHA['INDEPENDENT-READBACK.private.json'], 'auditSummarySHA256': digest(audit), 'ordinaryVerificationAtSend': 'unknown', 'attemptAndSingleExecutionEvent': True, 'evidence': 'explicit-specific-native-difference-current-author-accepted'}

def proof_for(job):
    if CASE is None:
        return None
    if job.get('id') != CASE['jobId']:
        return None
    try:
        need((job.get('client'), job.get('request_id'), job.get('peer'), job.get('action'), job.get('state')) == (CASE['client'], CASE['requestId'], CASE['peer'], 'send_text', 'succeeded'))
        need(all((job.get(k, CASE['authorThread']) == CASE['authorThread'] for k in ['ownerThreadId', 'authorThreadId', 'owner_thread_id', 'author_thread_id'])))
        text = (job.get('payload') or {}).get('text')
        need(isinstance(text, str) and len(text) == 2000 and text.endswith(' \n') and (not text[-3].isspace()) and (hashlib.sha256(text.encode()).hexdigest() == CASE['expectedTextSHA256']) and (hashlib.sha256(text[:-2].encode()).hexdigest() == CASE['actualTextSHA256']) and (hashlib.sha256(text.rstrip('\n').encode()).hexdigest() == ASSOCIATION_SHA))
        result = job.get('result') or {}
        tc = result.get('textComparison') or {}
        ack = result.get('authorAcceptance') or {}
        expected = {'state': 'accepted', 'peer': CASE['peer'], 'serverId': CASE['nativeServerId'], 'senderId': CASE['account'], 'nativeStatus': 2, 'nativeCreateTime': CASE['nativeTime'], 'uniqueCandidateCount': 1, 'attemptAndSingleExecutionEvent': True, 'canonicalAndAttemptUnchanged': True, 'ordinaryVerificationAtSend': 'unknown', 'automaticResend': False, 'evidence': 'explicit-specific-native-difference-current-author-accepted'}
        need(all((type(result.get(k)) is type(v) and result[k] == v for (k, v) in expected.items())))
        expected = {'mode': MODE, 'exact': False, 'expectedSHA256': CASE['expectedTextSHA256'], 'actualSHA256': CASE['actualTextSHA256'], 'expectedChars': 2000, 'actualChars': 1998, 'removedSuffixCodepoints': ['U+0020', 'U+000A'], 'globalNormalizationApplied': False}
        need(all((type(tc.get(k)) is type(v) and tc[k] == v for (k, v) in expected.items())))
        need(type(ack.get('verified')) is bool and type(ack.get('specificOriginalOnly')) is bool)
        need(ack == {'verified': True, 'threadId': CASE['authorThread'], 'documentSHA256': CASE['authorAcceptanceDocumentSHA256'], 'recordSHA256': CASE['recordSHA256'], 'specificOriginalOnly': True})
        receipt = result.get('nativeSnapshotReceipt') or {}
        need(receipt.get('consistency') == 'committed' and receipt.get('integrity') == 'ok')
        docs = read_artifacts()
        need(docs['PINNED-CASE.private.json'] == CASE)
        registered = docs['ACCEPTANCE-RECORD.private.json']
        need(registered['case'] == {k: v for (k, v) in CASE.items() if k != 'recordSHA256'} and registered.get('allowGlobalNormalization') is False and (registered.get('ordinaryVerificationAtSend') == 'unknown') and (registered.get('mode') == MODE))
        raw = registered['authorAcceptanceDocumentUTF8']
        need(hashlib.sha256(raw.encode()).hexdigest() == CASE['authorAcceptanceDocumentSHA256'] and json.loads(raw) == registered['authorAcceptanceDocument'])
        doc = json.loads(raw)
        need(all((doc.get(k) is True for k in ['callerAuthorAcceptsThisActualSentVersionAsCompleteBusinessDelivery', 'callerAcceptanceDoesNotChangeCanonicalOrBackfillProgrammaticExactVerification', 'exactWholeBusinessTextMatchBeforeFinalTwoChars', 'send1NoReplay'])))
        evidence = docs['INDEPENDENT-READBACK.private.json']
        need((evidence['jobId'], evidence['client'], evidence['requestId'], evidence['peer'], evidence['state']) == (CASE['jobId'], CASE['client'], CASE['requestId'], CASE['peer'], 'succeeded'))
        need(evidence['canonicalBodySHA256'] == CASE['canonicalBodySHA256'] and evidence['canonicalContractSHA256'] == CASE['canonicalContractSHA256'] and (evidence['attemptSHA256'] == CASE['attemptSHA256']))
        states = [e.get('state') for e in evidence['events']]
        need(states.count('executing') == 1 and states.count('confirmed') == 1 and (states.count('unknown') >= 1))
        audit_summary(evidence['audit'])
        audit_summary(job.get('_observerSpecificAudit', evidence['audit']))
        return expected_proof()
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None

def valid_cached(job):
    if CASE is None:
        return False
    return bool((job.get('jobId'), job.get('client'), job.get('request_id'), job.get('peer'), job.get('action'), job.get('state'), job.get('serverId'), job.get('contentHash')) == (CASE['jobId'], CASE['client'], CASE['requestId'], CASE['peer'], 'send_text', 'succeeded', CASE['nativeServerId'], ASSOCIATION_SHA) and isinstance(job.get('nativeProof'), dict) and (set(job['nativeProof']) == set(expected_proof())) and all((type(job['nativeProof'].get(k)) is type(v) and job['nativeProof'][k] == v for (k, v) in expected_proof().items())) and (job.get('scopeOwnerThreadId', CASE['authorThread']) == CASE['authorThread']))

def scoped_audit_request(request):
    if CASE is None:
        return False
    return request.get('op') == 'get_many' and request.get('client') == CASE['client'] and (request.get('request_ids') == [CASE['requestId']]) and (request.get('wait_seconds') == 0) and (request.get('audit') is True)

def associate(seeds, sources, output=None, when='now'):
    if CASE is None:
        return seeds
    output = sources if output is None else output
    candidates = []
    for seed in seeds:
        if seed['employee'] != 'secretary' or seed['ownerThreadId'] != CASE['authorThread']:
            continue
        current = sources.get(seed['sourceId'], {})
        path = current.get('path')
        anchors = []
        if not path:
            continue
        for (ident, value) in sources.items():
            if value.get('path') != path or CASE['jobId'] not in value.get('text', ''):
                continue
            text = value.get('text', '')
            if ident == 'work-' + hashlib.sha256((path + '\x00' + text).encode()).hexdigest()[:22]:
                anchors.append((ident, value))
        if anchors:
            candidates.append((seed, current, sorted(anchors, key=lambda x: x[0])[0]))
    if len(candidates) == 1:
        (seed, current, (anchor_id, anchor)) = candidates[0]
        seed['requestIds'] = list(dict.fromkeys(seed['requestIds'] + [CASE['requestId']]))[:30]
        metadata = {'jobId': CASE['jobId'], 'requestId': CASE['requestId'], 'ownerThreadId': CASE['authorThread'], 'businessId': seed['businessId'], 'currentSourceId': seed['sourceId'], 'historicalSourceId': anchor_id, 'historicalTextSHA256': hashlib.sha256(anchor['text'].encode()).hexdigest(), 'basis': 'same_original_workbook_explicit_job_id', 'deliveryClaim': False}
        path = '原业务交付关联:' + CASE['requestId']
        body = json.dumps(metadata, ensure_ascii=False, sort_keys=True)
        ident = 'work-' + hashlib.sha256((path + '\x00' + body).encode()).hexdigest()[:22]
        output[ident] = {'id': ident, 'path': path, 'label': '原晨报事项与准确原单的关联', 'text': body, 'time': when, 'role': '原监控已存来源的元数据关联；不公开原历史正文，不代替实际交付证据'}
        seed['associationEvidenceRefs'] = [ident]
    return seeds
