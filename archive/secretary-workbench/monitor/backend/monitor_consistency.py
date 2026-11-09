"""Shared read-side invariants. No source/employee writes or new workflow state."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, json
from delivery_receipt_cache import member, proof_valid

def guard_deliveries(health, jobs, sources):
    out = copy.deepcopy(health)
    gaps = []
    for inc in out['incidents']:
        if inc['status'] != 'resolved':
            continue
        proven = False
        for job in jobs:
            if job.get('client') != inc['client'] or job.get('request_id') not in inc['requestIds'] or job.get('scopeBusinessId', inc['businessId']) != inc['businessId'] or (job.get('scopeOwnerThreadId', inc['ownerThreadId']) != inc['ownerThreadId']) or job.get('receiptConflict'):
                continue
            try:
                recorded = member(sources[job['sourceId']], inc['client'])
                if proof_valid(recorded) and all((recorded.get(k) == job.get(k) for k in ['client', 'request_id', 'peer', 'action', 'contentHash', 'nativeProof'])):
                    proven = True
                    break
            except (KeyError, ValueError, TypeError):
                continue
        if not proven:
            inc.update(status='unknown', nativeReceiptVerified=False, reasonCode='native_proof_incomplete')
            gaps.append('关联组件缺少完整且同范围的原生证明，保留待核：' + inc['id'])
    out['coverage']['gaps'] += gaps
    return out

def summarize(roles, people, items, health):
    checks = []
    for role in roles:
        p = next((x for x in people if x['id'] == role['id']), {})
        inbox = p.get('inbox', {})
        ref = role.get('historyReference')
        native = role.get('nativeMetadata')
        gaps = []
        if role.get('historyMappingGap'):
            gaps.append(role['historyMappingGap'])
        if inbox.get('error'):
            gaps.append(inbox['error'])
        if (native or {}).get('host') == 'aup' and inbox.get('gap'):
            gaps.append(inbox['gap'])
        if inbox.get('historyThreadId') not in [None, role['historyThreadId']]:
            gaps.append('目录与收件历史不一致，未据此判断无工作')
        if p.get('error'):
            gaps.append(p['error'])
        if p.get('workRead', {}).get('state') == 'native_only':
            gaps.append('未取得统一逐件工作本；0项不代表无工作，收件与运行范围分别核对')
        rows = [i for i in items if i['employee'] == role['id']]
        checks.append({'employee': role['id'], 'threadId': role['threadId'], 'historyThreadId': role['historyThreadId'], 'identity': 'verified' if native and (not native.get('error')) and ref and (not role.get('historyMappingGap')) else 'cached' if ref and (not role.get('historyMappingGap')) else 'unverified', 'items': len(rows), 'staleItems': sum((bool(i.get('sourceStale')) for i in rows)), 'queueRead': inbox.get('readQueueCount'), 'gaps': list(dict.fromkeys(gaps))})
    return {'version': 1, 'employees': checks, 'checkedEmployees': len(checks), 'verifiedIdentities': sum((c['identity'] == 'verified' for c in checks)), 'employeesWithGaps': sum((bool(c['gaps']) for c in checks)), 'businessItems': len(items), 'deliveryComponents': len(health['incidents']), 'provenDelivered': sum((i['status'] == 'resolved' and i['nativeReceiptVerified'] for i in health['incidents'])), 'note': '统一核对的是本轮已接入范围；非结构化责任、附件内容与未提供的发送依据仍留缺口，不代表全库零遗漏'}
