"""Delivery components derived from original current notebooks and bounded receipts.
No commands, worker queues, media reads or business writes. Only metadata is public.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import hashlib, json, re
from pathlib import Path
CLOSED = {'已办好', '已完成', '已交付', '不做了', '不用管了', '已结束'}
CANCELLED = {'不做了', '不用管了', '已结束'}
ACTIVE = {'queued', 'preparing', 'awaiting_confirmation', 'confirmed', 'executing', 'needs_attention', 'pending'}
UUID = re.compile('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\\Z')
REQUEST = re.compile('(?<![A-Za-z0-9._/-])(?:secretary|science|organoid|forum|employee|method|hr)[-_][A-Za-z0-9._-]{4,180}(?![A-Za-z0-9._/-])')

def digest(v):
    return hashlib.sha256(v.encode()).hexdigest()

def family(rid):
    return re.sub('-r\\d+$', '', rid)

def safe_title(v):
    s = str(v or '')
    if re.search('(?i)password|口令|密码|验证码|token|api.?key|authorization|sk-[a-z0-9]{12}|eyJ\\w+\\.', s):
        return '业务交付（摘要已隐藏）'
    return re.sub('/Users/[^\\s]+', '[本机原件]', s)[:160]

def ack(rid):
    return bool(re.search('(?:^|-)ack(?:-|$)|reading-ack', rid))

def recorded_retries(head, known):
    """Resolve only positively recorded short suffixes against one unambiguous local family."""
    out = []
    for line in head.splitlines():
        full = [m for m in REQUEST.finditer(line) if m.group() in known]
        for short in list(re.finditer('(?<![A-Za-z0-9._-])(-r[0-9]{1,3})\\s*(?=成功|实发|已发送|succeeded)', line, re.I))[:8]:
            prefix = line[max(0, short.start() - 16):short.start()]
            if not re.search('(?:只用|仅用|改用|使用)\\s*$', prefix) or re.search('计划|未来|如果|可以|可能', prefix):
                continue
            bases = {family(m.group()) for m in full if m.end() <= short.start()}
            if len(bases) == 1:
                rid = next(iter(bases)) + short.group(1)
                if len(rid) <= 96:
                    out.append(rid)
    return list(dict.fromkeys(out))

def retired_drafts(head, nxt, known):
    """A current explicit decision + that original failed draft's local context, not a later success."""
    clauses = re.split('[。；，\n]', nxt)
    explicit = any((re.search('旧[^。；，\\n]{0,18}(?:稿|回复)[^。；，\\n]{0,6}(?:不补|作废|不再补发)', c) and (not re.search('可能|是否|待定|未决定|尚未决定', c)) for c in clauses))
    out = []
    for line in head.splitlines():
        matches = [m for m in REQUEST.finditer(line) if m.group() in known]
        for (n, m) in enumerate(matches):
            span = line[m.end():min(matches[n + 1].start() if n + 1 < len(matches) else len(line), m.end() + 5000)]
            direct = bool(re.match('\\s*(?:已|明确)?(?:作废|撤销|不再补发|不补)', span))
            old_context = explicit and bool(re.search('failed|noSend|未发', span)) and bool(re.search('(?:首次|旧|原)[^。；\\n]{0,40}(?:拟理解|理解发件|理解稿)[^。；\\n]{0,100}(?:超越|作废|不补|不再补发)', span))
            if direct or old_context:
                out.append(m.group())
    return list(dict.fromkeys(out))

def note_seed(role, path, head, business_id, source_id):
    from send_tool_observer import CLIENTS
    client = next((c for (c, e) in CLIENTS.items() if e == role['id']), None)
    receipt_requests = receipt_ids(head, client, [role['root'] / 'work' if role['id'] == 'secretary' else role['root']], relative_root=role['root'])
    ids = [x for x in dict.fromkeys(REQUEST.findall(head) + receipt_requests) if len(x) <= 96 and (x in receipt_requests or x.startswith({'secretary': 'secretary-', 'science': 'science-', 'forum': 'forum-', 'organoid': 'organoid', 'employee-pilot': 'employee-', 'system': ('method-', 'hr-')}.get(role['id'], 'no-automatic-'))) and (not x.endswith(('.json', '.md', '.txt'))) and re.search('20\\d{6}', x) and (not ack(x) or client == 'employee_method') and (not re.search('(?i)password|token|credential|auth', x))]
    ids = list(dict.fromkeys(ids + recorded_retries(head, ids)))
    from build_snapshot import field
    nxt = field(head, '下一步')
    state = field(head, '现在怎么样')
    current_delivery = not (state in ['先放放', '暂缓'] or re.search('不再等发送|不再等.*修复|已.*实际问出|已.*实际回.*等', nxt))
    return {'businessId': business_id, 'employee': role['id'], 'ownerThreadId': role['threadId'], 'requestIds': ids[:30], 'sourceId': source_id, 'currentDeliveryObligation': current_delivery, 'operationEvidenceIds': receipt_requests, 'retiredRequestIds': retired_drafts(head, nxt, ids), 'businessDeferred': state in ['先放放', '暂缓'], 'noLongerWaitingForSend': bool(re.search('不再等发送|不再等.*修复', nxt)), 'recurring': bool(re.search('每天|每日|晨报|定时', str(head.splitlines()[0])))}

def build_health(*, items, seeds, jobs, gaps, observed_at, previous=None, proven_requests=None):
    by_id = {i['id']: i for i in items}
    incidents = []
    associated = set()
    missing = 0
    excluded = {(s['businessId'], rid) for s in seeds for rid in s.get('excludedReceiptScopes', [])}

    def real_previous(i):
        return i.get('status') == 'blocked' if proven_requests is None else any(((i.get('client'), r) in proven_requests for r in i['requestIds']))
    for seed in seeds:
        item = by_id.get(seed['businessId'])
        if not item or item.get('commitment') == 'candidate':
            continue
        emp = seed['employee']
        expected_client = next((c for (c, e) in __import__('send_tool_observer').CLIENTS.items() if e == emp), None)
        if expected_client == 'aup_support' and seed['ownerThreadId'] != __import__('send_tool_observer').AUP_OWNER:
            gaps = list(gaps) + ['aup_support：原业务owner不匹配固定岗位，不建立交付关联']
            continue
        if expected_client == 'research_secretary' and seed['ownerThreadId'] != __import__('research_secretary_scope').THREAD:
            gaps = list(gaps) + ['research_secretary：原业务owner不匹配固定新岗位']
            continue
        scoped_jobs = [j for j in jobs if j.get('employee') == emp and j.get('client') == expected_client and (j.get('scopeBusinessId', seed['businessId']) == seed['businessId']) and (j.get('scopeOwnerThreadId', seed['ownerThreadId']) == seed['ownerThreadId'])]
        include_ack = lambda rid: expected_client == 'employee_method' and (rid in seed.get('retiredRequestIds', []) or any((j['request_id'] == rid and (j.get('nativeReceiptVerified') or j.get('state') in ACTIVE) for j in scoped_jobs)))
        known = [r for r in seed['requestIds'] if not ack(r) or include_ack(r)]
        relevant = [j for j in scoped_jobs if j.get('employee') == emp and j['request_id'] in known and (not ack(j['request_id']) or include_ack(j['request_id']))]
        for j in scoped_jobs:
            if j in relevant or j.get('employee') != emp or ack(j['request_id']):
                continue
            if any((j.get('peer') == old.get('peer') and j.get('action') == old.get('action') and (j.get('created', 0) >= old.get('created', 0)) and (j.get('contentHash') and j['contentHash'] == old.get('contentHash') and (family(j['request_id']) == family(old['request_id'])) or old['request_id'] in j.get('supersedes', [])) for old in relevant)):
                relevant.append(j)
        groups = []
        for j in sorted(relevant, key=lambda x: (x.get('created') or 0, x['request_id'])):

            def joins(g):
                if any(((o.get('nativeProof') or {}).get('kind') == 'text_specific_author_accepted' for o in [j] + g)) and any((o['request_id'] != j['request_id'] for o in g)):
                    return False
                cached_link = bool(j.get('knownComponentId') and any((o.get('knownComponentId') == j['knownComponentId'] for o in g)))
                delivered = {o.get('contentHash') for o in g if o.get('nativeReceiptVerified') and o.get('contentHash')}
                if delivered and j.get('contentHash') not in delivered and (not cached_link):
                    return False
                return any((o.get('peer') == j.get('peer') and o.get('action') == j.get('action') and (cached_link or (j.get('contentHash') and o.get('contentHash') == j['contentHash'] and (family(o['request_id']) == family(j['request_id']))) or o['request_id'] in j.get('supersedes', [])) for o in g))
            found = next((g for g in groups if joins(g)), None)
            if found is None:
                groups.append([j])
            else:
                found.append(j)
        for rid in known:
            if not any((j['request_id'] == rid for j in relevant)):
                missing += 1
                prior = any((i['businessId'] == seed['businessId'] and rid in i['requestIds'] and real_previous(i) for i in (previous or {}).get('incidents', [])))
                if expected_client in ['aup_support', 'research_secretary'] and (not prior):
                    continue
                if rid in seed.get('operationEvidenceIds', []) or prior:
                    groups.append([{'request_id': rid, 'employee': emp, 'state': 'unknown'}])
        for group in groups:
            first = group[0]
            latest = max(group, key=lambda j: (j.get('created') or 0, j.get('updated') or 0))
            verified = [j for j in group if j.get('nativeReceiptVerified') and (j['request_id'] == latest['request_id'] or (j.get('contentHash') and j.get('contentHash') == latest.get('contentHash')))]
            success = max(verified, key=lambda j: (j.get('created') or 0, j.get('updated') or 0)) if verified else None
            conflicted = any((j.get('receiptConflict') or j.get('retirementConflict') for j in group))
            closed = item.get('state', '').strip() in CLOSED
            retired = all((j['request_id'] in seed.get('retiredRequestIds', []) for j in group))
            deferred = bool(seed.get('businessDeferred') and latest.get('state') == 'failed' and (latest.get('noSend') is True) and (not success) and (not retired))
            status = 'unknown' if conflicted else 'resolved' if success else 'not_required' if item.get('state', '').strip() in CANCELLED else 'not_required' if retired else 'pending' if deferred else 'unknown' if closed else 'blocked' if latest.get('state') == 'needs_attention' or (latest.get('state') == 'failed' and seed.get('currentDeliveryObligation', True)) else 'pending' if latest.get('state') in ACTIVE else 'unknown'
            reason = (latest.get('reason') or 'needs_attention' if latest.get('state') == 'needs_attention' else latest.get('reason')) if status == 'blocked' else 'native_accepted' if status == 'resolved' else ('business_closed_receipt_unverified' if closed else 'no_current_receipt') if status == 'unknown' else status
            if status == 'resolved' and success and ((success.get('nativeProof') or {}).get('kind') == 'text_specific_author_accepted'):
                reason = 'native_author_accepted_difference'
            if conflicted:
                reason = 'retirement_evidence_conflict' if any((j.get('retirementConflict') for j in group)) else 'receipt_identity_conflict'
            if status == 'not_required' and retired:
                reason = next((seed['retirementEvidence'][j['request_id']].get('reasonCode', 'question_answered_by_source') for j in group if j['request_id'] in seed.get('retirementEvidence', {})), 'draft_retired_by_current_business')
            if status == 'pending' and deferred:
                reason = 'business_deferred_unsent'
            if not isinstance(reason, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', reason):
                reason = 'tool_failure' if status == 'blocked' else 'no_current_receipt'
            recovery = next((j.get('recoveryOwnerThreadId') for j in reversed(group) if UUID.fullmatch(str(j.get('recoveryOwnerThreadId', '')))), None)
            if deferred:
                recovery = None
            ids = list(dict.fromkeys((j['request_id'] for j in group)))
            ids = ids if len(ids) <= 20 else ids[:1] + ids[-19:]
            associated.update(((emp, r) for r in ids))
            incidents.append({'id': 'delivery-' + digest(seed['businessId'] + '|' + emp + '|' + first['request_id'])[:24], 'businessId': seed['businessId'], 'employee': emp, 'businessTitle': safe_title(item.get('title')), 'ownerThreadId': seed['ownerThreadId'], 'status': status, 'updatedAt': max([j.get('updated') or 0 for j in group] + [seed.get('retirementEvidence', {}).get(j['request_id'], {}).get('evidenceAt', 0) for j in group] + [_time(item.get('recordUpdatedAt')) or 0 if (retired or deferred) and (not any((j['request_id'] in seed.get('retirementEvidence', {}) for j in group))) else 0]) or _time(item.get('recordUpdatedAt')) or 1, 'requestIds': ids[:20], 'client': latest.get('client') or next((c for (c, e) in __import__('send_tool_observer').CLIENTS.items() if e == emp), ''), 'reasonCode': reason, 'recoveryOwnerThreadId': recovery, 'nativeReceiptVerified': bool(status == 'resolved' and success and (not conflicted)), 'evidenceRefs': list(dict.fromkeys([seed['sourceId']] + seed.get('associationEvidenceRefs', []) + [j['sourceId'] for j in group if j.get('sourceId') and j['request_id'] in ids] + [j['associationSourceId'] for j in group if j.get('associationSourceId')] + [ref for j in group for ref in j.get('conflictSourceIds', [])] + [ref for j in group for ref in j.get('decisionSourceIds', [])]))[:21]})
    for old in (previous or {}).get('incidents', []):
        if all(((old['businessId'], rid) in excluded for rid in old['requestIds'])):
            continue
        if old['id'] not in {i['id'] for i in incidents} and old['businessId'] in by_id and (old['status'] not in ['resolved', 'not_required']) and real_previous(old):
            current = by_id[old['businessId']]
            incidents.append({**old, 'status': 'not_required' if current.get('state') in CANCELLED else 'unknown', 'nativeReceiptVerified': False, 'reasonCode': 'source_unavailable'})
    notes = list(gaps)
    if missing:
        notes.append(f'{missing}个原笔记请求未取得当前原工具结果；保留待核，不据此重发')
    return {'version': 1, 'observedAt': observed_at, 'incidents': incidents, 'coverage': {'bounded': True, 'sampledAt': observed_at, 'gaps': notes, 'businessItemsExamined': len(items), 'openItemsWithoutReceiptIndex': sum((i.get('state') not in CLOSED and i.get('commitment') != 'candidate' and (i['id'] not in {s['businessId'] for s in seeds}) for i in items)), 'referencedComponents': len(incidents), 'missingCurrentReceipts': missing, 'scope': '原工作本当前摘要精确ID＋公共最近20项＋原已知请求定向读取；非全历史/全私聊扫描'}}

def _time(v):
    import datetime
    try:
        d = datetime.datetime.fromisoformat(v)
        return (d if d.tzinfo else d.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))).timestamp()
    except (ValueError, TypeError):
        return None

def attach_health(sending, health, jobs, out, when, source, peers):
    for incident in health['incidents']:
        matches = [j for j in jobs if j.get('employee') == incident['employee'] and j['request_id'] in incident['requestIds']]
        if not matches:
            continue
        latest = max(matches, key=lambda j: (j.get('created') or 0, j.get('updated') or 0))
        rid = latest['request_id']
        state = incident['status']
        sid = source(out, '交付组件:' + incident['id'], json.dumps(incident, ensure_ascii=False), when, '交付情况 · ' + incident['businessTitle'], '只读业务关联与原发送回执，维修接手不代表已送达')
        incident['evidenceRefs'] = list(dict.fromkeys(incident['evidenceRefs'] + [sid]))
        rows = [r for r in sending['items'] if any((j['request_id'] == r['id'] for j in matches)) or r.get('id') == 'tool-' + latest['client'] + '-' + rid or incident['id'] == r.get('deliveryId')]
        row = rows[0] if rows else {'id': 'delivery-view-' + incident['id'], 'employee': incident['employee'], 'destination': peers.get(latest.get('peer'), latest.get('peer') or '目标待核'), 'peer': latest.get('peer'), 'title': incident['businessTitle'] + ' · ' + {'send_text': '文字', 'send_image': '图片', 'send_file': '文件'}.get(latest['action'], latest['action']), 'body': None, 'bodyKind': '业务交付摘要；原始内容留本机', 'summary': incident['businessTitle'], 'attachments': [], 'phase': 'unknown', 'state': 'unknown', 'label': '交付待核', 'reason': '', 'sourceId': sid, 'proofSourceId': sid, 'requestedAt': __import__('datetime').datetime.fromtimestamp(latest.get('created') or 0, __import__('datetime').timezone.utc).isoformat(), 'nativeItemId': None, 'relatedItemIds': []}
        if not rows:
            sending['items'].append(row)
        row['relatedItemIds'] = list(dict.fromkeys(row.get('relatedItemIds', []) + [incident['businessId']]))
        row.update(deliveryId=incident['id'], deliveryStatus=state, deliveryReason=incident['reasonCode'], recoveryOwnerThreadId=incident['recoveryOwnerThreadId'], proofSourceId=sid)
        row['toolOperations'] = [{'requestId': j['request_id'], 'state': j['state'], 'sourceId': j.get('sourceId') or sid, 'serverId': j.get('serverId')} for j in matches]
        if state == 'blocked':
            row.update(state='failed', label='未送达／工具故障', reason='等待原机制负责人恢复' if incident['recoveryOwnerThreadId'] else '等待业务负责人接续；恢复责任待核')
        elif state == 'resolved':
            row.update(state='sent', label='已补交（原生已核）' if len(matches) > 1 else '已送达（原生已核）', reason='该件已交付；旧失败保留。未核对方已读')
        if state == 'resolved' and incident['reasonCode'] == 'native_author_accepted_difference':
            row.update(label='已送达（作者接受明确差异）', reason='原生与作者接受已核；非逐字相同，原稿与实收SHA分别保留；旧unknown不回写')
        if state == 'unknown':
            row.update(state='unknown', label='交付待核', reason='原生回执身份或内容不一致；历史证明保留，需核对，不自动重发' if incident['reasonCode'] == 'receipt_identity_conflict' else '缺少同件当前原生回执；不能当作已送达')
        elif state == 'not_required':
            row.update(state='cancelled', label='本轮不再欠交', reason='原业务已关闭或原件已撤销；不代表发送成功')
        if state == 'not_required' and incident['reasonCode'] == 'draft_retired_by_current_business':
            row.update(title=incident['businessTitle'] + ' · 旧理解稿（未发）', label='旧稿作废／不再补发', reason='原业务明确不补这份未发旧稿；新结果独立保留，不把旧稿写成已送达')
        if state == 'not_required' and incident['reasonCode'] == 'ack_cancelled_by_ready_draft':
            row.update(title=incident['businessTitle'] + ' · 旧承接稿', label='旧承接已取消／不再发送', reason='准备前取消旧承接，改用已审核成熟稿；旧稿未发，成稿交付另核')
        if state == 'not_required' and incident['reasonCode'] == 'question_answered_by_source':
            row.update(title=incident['businessTitle'] + ' · 旧确认问题', label='已获答复／不再需要发送', reason='本人准确新源已给答案；原failed/noSend保留，不表示旧DM已发或父任务已完成')
        if state == 'resolved' and any((i['businessId'] == incident['businessId'] and i['reasonCode'] == 'draft_retired_by_current_business' for i in health['incidents'])):
            row['title'] = incident['businessTitle'] + ' · 新完成结果'
        if state == 'pending' and incident['reasonCode'] == 'business_deferred_unsent':
            row.update(state='pending', phase='unknown', label='已知未发／业务暂缓', reason='原失败/noSend已知；条件满足且仍有价值时再判断，不催发、不自动派修')
    return sending

def receipt_ids(head, client, roots, relative_root=None):
    """Only explicitly named normal JSON with actual client/action/peer/request identities."""
    if not client:
        return []
    from live_core import checked_path, stable_note
    from send_tool_observer import RID
    paths = re.findall('/[^\\s`\\]）)<>"，；。]+\\.json', head)
    out = []
    if relative_root is not None:
        for match in re.findall('(?<![A-Za-z0-9_.:/-])((?:[A-Za-z0-9_一-龥.-]+/)+[^\\s`\\]）)<>"，；。]+\\.json)', head):
            paths.append(str(Path(relative_root) / match))

    def jobs(value, depth=0):
        if depth > 4:
            return
        if isinstance(value, list):
            for item in value[:100]:
                yield from jobs(item, depth + 1)
        elif isinstance(value, dict):
            if value.get('request_id') and value.get('peer') and (value.get('client', client) == client) and (value.get('action') in ['send_text', 'send_image', 'send_file', 'reply', 'forward']):
                yield value
            for key in ['job', 'jobs', 'items', 'rows']:
                if key in value:
                    yield from jobs(value[key], depth + 1)
    for path in list(dict.fromkeys(paths))[:8]:
        try:
            p = checked_path(Path(path), roots)
            root = next((r.resolve() for r in roots if r.resolve() in p.parents or r.resolve() == p))
            if any((part.lower() in ['private', '.private', '.runtime'] for part in p.relative_to(root).parts)):
                continue
            (raw, _) = stable_note(p)
            value = json.loads(raw)
            for row in jobs(value):
                rid = row['request_id']
                if client in ['aup_support', 'research_secretary'] and __import__('send_tool_observer').project(row) is None:
                    continue
                if isinstance(rid, str) and RID.fullmatch(rid) and (not ack(rid) or client == 'employee_method') and (not re.search('(?i)password|token|credential|auth', rid)):
                    out.append(rid)
        except (OSError, ValueError, TypeError):
            continue
    return list(dict.fromkeys(out))[:30]
