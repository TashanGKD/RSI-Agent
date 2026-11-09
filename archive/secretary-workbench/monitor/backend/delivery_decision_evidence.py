"""Scoped references to existing, structured business decision artifacts.
They retire only an answered question; never a parent business or a WeChat send.
References live in the existing per-note observer cache, with the original evidence.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, hashlib, json, re
from pathlib import Path
from live_core import checked_path, stable_note

def digest(x):
    return hashlib.sha256(x).hexdigest()

def checksum(ref):
    return digest(json.dumps({k: v for (k, v) in ref.items() if k != 'bindingChecksum'}, ensure_ascii=False, sort_keys=True).encode())

def read_artifact(role, path, rid, decision):
    p = checked_path(Path(path), [role['root'] / 'work'])
    if p.name != 'OWNER-DECISION-SUPERSEDED.json' or any((part.lower() in ['private', '.private', '.runtime'] for part in p.relative_to(role['root']).parts)):
        raise ValueError('not an authorized normal evidence artifact')
    if p.stat().st_size > 32768:
        raise ValueError('decision evidence cap')
    (raw, st) = stable_note(p)
    j = json.loads(raw)
    if not isinstance(j, dict) or j.get('originalQuestionId') != rid or j.get('originalQuestionRemains') != 'failed/noSend' or (j.get('r1NotAdmitted') is not True) or (type(j.get('newDecisionQuestionSends')) is not int) or (j['newDecisionQuestionSends'] != 0) or (not re.search('(?<!\\d)' + re.escape(decision) + '(?!\\d)', str(j.get('reason', '')))):
        raise ValueError('decision does not retire this exact question')
    return ({'originalQuestionId': rid, 'originalQuestionRemains': 'failed/noSend', 'r1NotAdmitted': True, 'newDecisionQuestionSends': 0, 'decisionSourceId': decision, 'artifactSHA256': digest(raw.encode())}, st.st_mtime)

def register_reference(role, business_id, path, decision_source_id, original_question, current_head):
    from send_tool_observer import CLIENTS, RID
    q = original_question
    if CLIENTS.get(q.get('client')) != role['id'] or not RID.fullmatch(str(q.get('request_id', ''))) or q.get('state') != 'failed' or (q.get('noSend') is not True) or (q.get('action') != 'send_text') or (not q.get('peer')):
        raise ValueError('unverified original question scope')
    if not re.fullmatch('[0-9]{15,20}', decision_source_id) or decision_source_id not in current_head:
        raise ValueError('owner source not linked to this work')
    (evidence, at) = read_artifact(role, path, q['request_id'], decision_source_id)
    question = {k: q.get(k) for k in ['client', 'request_id', 'peer', 'action', 'state', 'created', 'updated', 'noSend', 'reason', 'contentHash']}
    question.update(employee=role['id'], nativeReceiptVerified=False)
    ref = {'version': 1, 'businessId': business_id, 'employee': role['id'], 'ownerThreadId': role['threadId'], 'client': q['client'], 'originalRequestId': q['request_id'], 'artifactPath': str(Path(path)), 'decisionSourceId': decision_source_id, 'evidence': evidence, 'evidenceAt': at, 'question': question, 'initialNoteSHA256': digest(current_head.encode())}
    ref['bindingChecksum'] = checksum(ref)
    return ref

def apply_references(role, items, seeds, jobs, sources, references, when):
    from work_observer import source
    out = copy.deepcopy(seeds)
    effective = copy.deepcopy(jobs)
    gaps = []
    by_id = {i['id']: i for i in items}
    for ref in references[:20]:
        if not isinstance(ref, dict) or ref.get('bindingChecksum') != checksum(ref):
            gaps.append('业务决定引用的范围校验不符；未据此关闭交付')
            continue
        seed = next((s for s in out if s['businessId'] == ref.get('businessId') and s['employee'] == ref.get('employee') and (s['ownerThreadId'] == ref.get('ownerThreadId'))), None)
        if not seed or ref.get('businessId') not in by_id or ref.get('employee') != role['id'] or (ref.get('ownerThreadId') != role['threadId']):
            continue
        rid = ref['originalRequestId']
        q = ref['question']
        if q.get('client') != ref['client'] or q.get('request_id') != rid or ref['evidence'].get('originalQuestionId') != rid:
            continue
        conflict = False
        evidence = ref['evidence']
        evidence_at = ref['evidenceAt']
        try:
            (current, at) = read_ack_artifacts(role, ref['artifactPaths'], q) if ref.get('artifactKind') == 'cancelled_ack_replaced' else read_artifact(role, ref['artifactPath'], rid, ref['decisionSourceId'])
            if current != evidence:
                if ref.get('artifactKind') == 'cancelled_ack_replaced':
                    conflict = True
                else:
                    evidence = current
                    evidence_at = at
        except OSError:
            gaps.append('原问题已获答复的证明沿原记录保留；本轮存证读取不可用 ' + ref['client'] + '/' + rid)
        except (ValueError, KeyError, TypeError):
            conflict = True
            gaps.append('原问题的业务决定存证出现不一致，保留待核 ' + ref['client'] + '/' + rid)
        sid = source(sources, ref['artifactPath'], json.dumps({'businessId': ref['businessId'], 'client': ref['client'], 'evidence': evidence, 'evidenceAt': evidence_at}, ensure_ascii=False), when, '旧承接已由审核成稿取代' if ref.get('artifactKind') == 'cancelled_ack_replaced' else '本人新源已回答原确认问题', '结构化原业务存证；只终止旧问题，不代表发件成功或父任务完成')
        existing = next((j for j in effective if j.get('client') == q['client'] and j.get('request_id') == rid and (j.get('scopeBusinessId', ref['businessId']) == ref['businessId'])), None)
        if existing is not None and (any((existing.get(k) is not None and existing.get(k) != q.get(k) for k in ['client', 'request_id', 'peer', 'action', 'contentHash'])) or existing.get('nativeReceiptVerified')):
            conflict = True
            gaps.append('旧确认的操作身份与退役依据冲突，保留待核 ' + ref['client'] + '/' + rid)
        if existing is None:
            op = source(sources, '原问题历史:' + q['client'] + '/' + rid, json.dumps(q, ensure_ascii=False), when, '旧确认的failed/noSend历史', '原已核公共回执元数据；本轮不发问、不准入')
            existing = dict(q, sourceId=op, scopeBusinessId=ref['businessId'], scopeOwnerThreadId=ref['ownerThreadId'])
            effective.append(existing)
        if rid not in seed['requestIds']:
            seed['requestIds'].append(rid)
        seed.setdefault('operationEvidenceIds', [])
        if rid not in seed['operationEvidenceIds']:
            seed['operationEvidenceIds'].append(rid)
        existing.setdefault('decisionSourceIds', []).append(sid)
        if conflict:
            existing['retirementConflict'] = True
        else:
            if rid not in seed.setdefault('retiredRequestIds', []):
                seed['retiredRequestIds'].append(rid)
            seed.setdefault('retirementEvidence', {})[rid] = {'sourceId': sid, 'evidenceAt': evidence_at, 'reasonCode': 'ack_cancelled_by_ready_draft' if ref.get('artifactKind') == 'cancelled_ack_replaced' else 'question_answered_by_source'}
    return (out, effective, gaps)

def index_references(seeds, references):
    from send_tool_observer import CLIENTS, RID
    out = copy.deepcopy(seeds)
    for ref in references[:20]:
        if not isinstance(ref, dict) or ref.get('bindingChecksum') != checksum(ref):
            continue
        for seed in out:
            if (seed['businessId'], seed['employee'], seed['ownerThreadId']) != (ref.get('businessId'), ref.get('employee'), ref.get('ownerThreadId')):
                continue
            if CLIENTS.get(ref.get('client')) != seed['employee'] or not RID.fullmatch(str(ref.get('originalRequestId', ''))):
                continue
            if ref['originalRequestId'] not in seed['requestIds']:
                seed['requestIds'].append(ref['originalRequestId'])
            replacement = ref.get('evidence', {}).get('replacementRequestId')
            if ref.get('artifactKind') == 'cancelled_ack_replaced' and isinstance(replacement, str) and RID.fullmatch(replacement) and (replacement not in seed['requestIds']):
                seed['requestIds'].append(replacement)
    return out

def read_ack_artifacts(role, paths, q):
    """Only the producer's three exact normal artifacts; cancellation alone is insufficient."""
    names = {'cancelled': 'OLD-ACK-CANCELLED-BY-READY-DRAFT.json', 'acceptance': 'MAIN-DRAFT-ACCEPTANCE.json', 'frozen': 'MATURE-DRAFT-FROZEN.json'}
    if set(paths) != set(names):
        raise ValueError('exact readiness artifacts required')
    docs = {}
    hashes = {}
    times = []
    for (k, name) in names.items():
        p = checked_path(Path(paths[k]), [role['root'] / 'work'])
        if p.name != name or any((x.lower() in ['private', '.private', '.runtime'] for x in p.relative_to(role['root']).parts)) or p.stat().st_size > 32768:
            raise ValueError('not a normal readiness artifact')
        (raw, st) = stable_note(p)
        docs[k] = json.loads(raw)
        hashes[k] = digest(raw.encode())
        times.append(st.st_mtime)
    cancel = docs['cancelled']
    accept = docs['acceptance']
    frozen = docs['frozen']
    if any((cancel.get(k) != q.get(k) for k in ['client', 'request_id', 'peer', 'action', 'state'])) or q.get('state') != 'cancelled' or q.get('noSend') is not True or (cancel.get('result', {}).get('noSend') is not True) or (cancel.get('result', {}).get('reason') != 'caller_cancelled_before_preparation'):
        raise ValueError('not the exact unprepared cancelled acknowledgement')
    if any((accept.get(k) is not True for k in ['readComplete', 'oldAckReplacedIfQueued', 'approvedForTalentInternalReviewOnly'])):
        raise ValueError('replacement not reviewed')
    if not isinstance(frozen, list) or len(frozen) != 1:
        raise ValueError('ambiguous replacement')
    new = frozen[0].get('job', {})
    from send_tool_observer import RID, CLIENTS
    text = new.get('payload', {}).get('text')
    if CLIENTS.get(q.get('client')) != role['id'] or q.get('action') != 'send_text' or any((new.get(k) != q[k] for k in ['client', 'peer', 'action'])) or (not RID.fullmatch(str(new.get('request_id', '')))) or (new['request_id'] == q['request_id']) or (not isinstance(text, str)) or (not text.strip()):
        raise ValueError('replacement scope/content mismatch')
    return ({'originalQuestionId': q['request_id'], 'originalState': 'cancelled/noSend', 'replacementRequestId': new['request_id'], 'replacementContentSHA256': digest(text.rstrip('\n').encode()), 'artifactSHA256s': hashes}, max(times))

def register_ack_reference(role, business_id, paths, q):
    from send_tool_observer import RID
    if not RID.fullmatch(str(q.get('request_id', ''))):
        raise ValueError('invalid original ID')
    (evidence, at) = read_ack_artifacts(role, paths, q)
    question = {k: q.get(k) for k in ['client', 'request_id', 'peer', 'action', 'state', 'created', 'updated', 'noSend', 'reason', 'contentHash']}
    question.update(employee=role['id'], nativeReceiptVerified=False)
    ref = {'version': 1, 'artifactKind': 'cancelled_ack_replaced', 'businessId': business_id, 'employee': role['id'], 'ownerThreadId': role['threadId'], 'client': q['client'], 'originalRequestId': q['request_id'], 'artifactPaths': paths, 'artifactPath': paths['cancelled'], 'evidence': evidence, 'evidenceAt': at, 'question': question}
    ref['bindingChecksum'] = checksum(ref)
    return ref
