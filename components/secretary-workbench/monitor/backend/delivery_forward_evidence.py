"""Exact references to normal, independently read native article-card evidence.
No directory scan, source-feed refresh, XML export, operation or business writes.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, hashlib, json, re, xml.etree.ElementTree as ET
from pathlib import Path
from live_core import checked_path, stable_note
from send_tool_observer import project, forward_fingerprint, CLIENTS

def sha(v):
    return hashlib.sha256(v if isinstance(v, bytes) else v.encode()).hexdigest()

def checksum(ref):
    return sha(json.dumps({k: v for (k, v) in ref.items() if k != 'bindingChecksum'}, ensure_ascii=False, sort_keys=True))

def load(path, role):
    p = checked_path(Path(path), [role['root'] / 'work'])
    if any((x.lower() in ['private', '.private', '.runtime'] for x in p.relative_to(role['root']).parts)):
        raise ValueError('not a normal evidence file')
    (raw, _) = stable_note(p)
    return (p, raw)

def read_proof(role, files, old, new):
    if set(files) != {'identity', 'native', 'decision', 'export', 'receipt'}:
        raise ValueError('exact evidence files required')
    raw = {k: load(p, role)[1] for (k, p) in files.items()}
    j = {k: json.loads(v) for (k, v) in raw.items() if k != 'export'}
    q = project(old)
    n = project(new)
    if not q or not n or CLIENTS.get(q['client']) != role['id'] or (q['client'] != n['client']) or (q['action'] != 'forward') or (n['action'] != 'forward') or (q['peer'] != n['peer']) or (not q['contentHash']) or (q['contentHash'] != n['contentHash']) or (q['state'] != 'failed') or (q['noSend'] is not True) or (n['state'] != 'succeeded') or (n['resultState'] != 'accepted') or (new['result'].get('peer') != n['peer']) or (not re.fullmatch('[1-9][0-9]{0,19}', str(n['serverId']))):
        raise ValueError('not an exact failed-card recovery')
    expected = {k: new[k] for k in ['client', 'request_id', 'peer', 'action', 'payload']}
    if any((j['decision'].get('job', {}).get(k) != v for (k, v) in expected.items())):
        raise ValueError('business source decision mismatch')
    card = j['identity']['actualNativeCard']
    native = j['native']
    receipt = j['receipt']
    coverage = native.get('coverage', {})
    if card.get('serverId') != n['serverId'] or card.get('nativeChat') != n['peer'] or str(card.get('appType')) != '5' or (not card.get('title')) or (not card.get('url')):
        raise ValueError('card identity absent')
    if native.get('state') != 'ok' or native.get('peer') != n['peer'] or coverage.get('messageMetadataComplete') is not True or (coverage.get('gaps') != []) or (coverage.get('truncated') is not False):
        raise ValueError('native coverage incomplete')
    rows = [m for m in native.get('messages', []) if str(m.get('serverId')) == n['serverId']]
    if len(rows) != 1:
        raise ValueError('not unique native message')
    m = rows[0]
    if m.get('kind') != 49 or m.get('peer') != n['peer'] or m.get('senderId') != native.get('account') or (m.get('senderId') != card.get('senderId')) or (not isinstance(m.get('time'), (int, float))) or (not n['created'] <= m['time'] <= n['updated'] + 2):
        raise ValueError('native sender/type/time mismatch')
    data = raw['export'].encode()
    if receipt.get('status') != 'complete' or receipt.get('failures') != [] or receipt.get('outputSha256') != sha(data) or (receipt.get('outputBytes') != len(data)):
        raise ValueError('Mac export receipt mismatch')
    needle = n['serverId']
    rows = []
    for line in raw['export'].splitlines():
        if needle in line:
            row = json.loads(line)
            if str(row.get('serverId')) == needle:
                rows.append((line, row))
    if len(rows) != 1:
        raise ValueError('exact Mac row absent or duplicated')
    (line, row) = rows[0]
    if row.get('nativeChat') != n['peer'] or row.get('senderId') != m['senderId'] or row.get('kind') != 49 or (abs(row.get('timeUnix', 0) - m['time']) > 2):
        raise ValueError('Mac row identity mismatch')
    xml = row.get('raw', '')
    if not isinstance(xml, str) or len(xml) > 262144 or re.search('<!\\s*(?:DOCTYPE|ENTITY)', xml, re.I):
        raise ValueError('unsafe card XML')
    xml = xml[xml.find('<'):].replace('\\n', '\n').replace('\\t', '\t')
    try:
        app = ET.fromstring(xml).find('appmsg')
    except ET.ParseError:
        raise ValueError('malformed card XML')
    if app is None or app.findtext('type') != '5' or app.findtext('title') != card['title'] or (app.findtext('url') != card['url']):
        raise ValueError('exact article title/URL mismatch')
    return {'kind': 'forward_article_app5', 'peer': n['peer'], 'serverId': n['serverId'], 'senderId': m['senderId'], 'nativeKind': 49, 'appType': 5, 'nativeCreateTime': m['time'], 'sourcePeer': new['payload']['source_peer'], 'sourceId': new['payload']['source_id'], 'titleSHA256': sha(card['title']), 'urlSHA256': sha(card['url']), 'nativeRowSHA256': sha(line), 'macExportSHA256': sha(data), 'macReceiptSHA256': sha(raw['receipt']), 'nativeReadbackSHA256': sha(raw['native']), 'articleIdentitySHA256': sha(raw['identity']), 'sourceDecisionSHA256': sha(raw['decision'])}

def register_reference(role, business_id, files, old, new):
    proof = read_proof(role, files, old, new)

    def safe(j):
        return {k: v for (k, v) in project(j).items() if k not in ['text', 'assetName', 'outcomeState', 'resultState', 'recoveryOwnerThreadId']}
    ref = {'version': 1, 'businessId': business_id, 'employee': role['id'], 'ownerThreadId': role['threadId'], 'client': old['client'], 'files': {k: str(v) for (k, v) in files.items()}, 'old': safe(old), 'new': safe(new), 'proof': proof}
    ref['bindingChecksum'] = checksum(ref)
    return ref

def index_references(seeds, refs):
    out = copy.deepcopy(seeds)
    for ref in refs[:20]:
        if ref.get('bindingChecksum') != checksum(ref):
            continue
        for s in out:
            if (s['businessId'], s['employee'], s['ownerThreadId']) == (ref['businessId'], ref['employee'], ref['ownerThreadId']):
                s['requestIds'] = list(dict.fromkeys(s['requestIds'] + [ref['old']['request_id'], ref['new']['request_id']]))
    return out

def apply_references(role, items, seeds, jobs, sources, refs, when):
    from work_observer import source
    from delivery_receipt_cache import proof_valid, identity_conflict, SAFE_FIELDS
    from delivery_health import digest
    ss = copy.deepcopy(seeds)
    js = copy.deepcopy(jobs)
    gaps = []
    for ref in refs[:20]:
        if ref.get('bindingChecksum') != checksum(ref) or ref.get('employee') != role['id'] or ref.get('ownerThreadId') != role['threadId']:
            continue
        s = next((s for s in ss if (s['businessId'], s['employee'], s['ownerThreadId']) == (ref['businessId'], ref['employee'], ref['ownerThreadId'])), None)
        if not s or ref['businessId'] not in {i['id'] for i in items}:
            continue
        old = ref['old']
        new = ref['new']
        proof = ref['proof']
        conflict = False
        for (k, hashkey) in [('native', 'nativeReadbackSHA256'), ('identity', 'articleIdentitySHA256'), ('decision', 'sourceDecisionSHA256'), ('receipt', 'macReceiptSHA256'), ('export', 'macExportSHA256')]:
            try:
                (_, raw) = load(ref['files'][k], role)
                if sha(raw) != proof[hashkey]:
                    conflict = True
            except OSError:
                gaps.append('原生转发已核证明沿原缓存保留；本轮原件暂不可读')
            except (ValueError, KeyError, TypeError):
                conflict = True
        proven = dict(new, nativeReceiptVerified=True, nativeProof=proof)
        if not proof_valid(proven):
            gaps.append('原生转发证明不完整，不采纳')
            continue
        cid = 'delivery-' + digest(ref['businessId'] + '|' + role['id'] + '|' + old['request_id'])[:24]
        for base in [old, proven]:
            found = next((j for j in js if j.get('client') == ref['client'] and j['request_id'] == base['request_id'] and (j.get('scopeBusinessId', ref['businessId']) == ref['businessId'])), None)
            if found and (identity_conflict(base, found) or found.get('receiptConflict')):
                conflict = True
        sid = source(sources, '原生转发证明:' + cid, json.dumps({'businessId': ref['businessId'], 'client': ref['client'], 'originalRequestId': old['request_id'], 'deliveredRequestId': new['request_id'], 'proof': proof}, ensure_ascii=False), when, '同源原生文章卡补交证明', '只读正常产物、准确原生消息及Mac精确行；不表示其他卡片已交')
        for base in [old, proven]:
            js = [j for j in js if not (j.get('client') == ref['client'] and j['request_id'] == base['request_id'] and (j.get('scopeBusinessId', ref['businessId']) == ref['businessId']))]
            row = copy.deepcopy(base)
            row.update(scopeBusinessId=ref['businessId'], scopeOwnerThreadId=ref['ownerThreadId'], knownComponentId=cid, associationSourceId=sid)
            if conflict:
                row.update(nativeReceiptVerified=False, receiptConflict=True, conflictSourceIds=[sid])
            op = source(sources, '原微信工具:' + ref['client'] + '/' + row['request_id'], json.dumps({k: row.get(k) for k in SAFE_FIELDS}, ensure_ascii=False), when, '原生转发回执元数据', '原失败与同源补交分别保留，不公开XML或鉴权')
            row['sourceId'] = op
            js.append(row)
            if row['request_id'] not in s['requestIds']:
                s['requestIds'].append(row['request_id'])
        if conflict:
            gaps.append('原生转发当前身份或原件证据冲突；保留待核，不借旧成功闭环')
    return (ss, js, gaps)
