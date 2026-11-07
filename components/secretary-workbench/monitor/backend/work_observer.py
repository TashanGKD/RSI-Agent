"""Derived employee directory, notebooks and sender inbox. Reads only original sources.

No worker calls, source writes, timers, external requests or credential loading.
The only cache is owned by this monitor; it is not an employee reporting form.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import copy, datetime, json, re, sqlite3, time
from pathlib import Path
from collect import ROOT, PRIVATE, bj
from live_core import atomic_json, checked_path, stable_note, digest, RESTRICTED
from build_snapshot import field, plain
METHOD = _install.path('monitor.work_observer.METHOD')
REGISTRY = METHOD / 'unified-mention-runtime/registry.json'
SKILL = _install.path('monitor.work_observer.SKILL')
SENDER = _install.identity('monitor.work_observer.SENDER')
FORUM = _install.path('monitor.work_observer.FORUM')
PILOT = _install.path('monitor.work_observer.PILOT')
ORG = _install.path('monitor.work_observer.ORG')
SEC = _install.path('monitor.work_observer.SEC')
SCI = _install.path('monitor.work_observer.SCI')
KNOWN = _install.role_map('monitor.work_observer', 'KNOWN')
SUPPORT = _install.role_map('monitor.work_observer', 'SUPPORT')
PEERS = _install.setting('monitor.work_observer', 'PEERS', {})
CLOSED = ('已办好', '已完成', '已交付', '不做了', '不用管了', '已结束')

def public_text(v, limit=3000):
    s = str(v or '')
    s = '\n'.join((line for line in s.splitlines() if not re.search('(?i)password|口令|密码|验证码|authorization|access_token|refresh_token|api.?key|eyJ[A-Za-z0-9_-]+\\.|(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{12,}', line)))
    s = re.sub(str(_install.path('monitor.work_observer.path_ca3e445e')), '[Mac原件]', s)
    return s[:limit]

def bounded_text(path, roots):
    p = checked_path(path, roots)
    if any((x in str(p).lower() for x in RESTRICTED)):
        raise ValueError('restricted source')
    (text, st) = stable_note(p)
    return (text, st)

def ro(name):
    c = sqlite3.connect('file:' + str(_install.path('codex_home') / '') + '' + name + '?mode=ro', uri=True, timeout=2)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    return c

def group_bindings(bindings):
    groups = {}
    for b in bindings:
        groups.setdefault(b['threadId'], []).append(b)
    return groups

def directory(native_runtime=None):
    (text, _) = bounded_text(REGISTRY, [METHOD])
    j = json.loads(text)
    if j.get('ownerThread') != _install.identity('monitor.work_observer.identity_4e07f826'):
        raise ValueError('registry owner mismatch')
    groups = group_bindings(j['bindings'])
    out = []
    mapping_cache = {}
    try:
        mapping_cache = json.loads((PRIVATE / 'work-observer-cache.json').read_text()).get('_historyMappings', {})
    except (OSError, ValueError, TypeError):
        pass
    for (thread, (ident, name, root, entry)) in {**KNOWN, **SUPPORT}.items():
        bs = groups.get(thread, [])
        gaps = []
        chosen_entry = entry
        bookdirs = []
        for binding in bs:
            try:
                if binding.get('workEntry'):
                    p = checked_path(Path(binding['workEntry']), [root, entry.parent])
                    if not p.is_file():
                        raise ValueError('entry unavailable')
                    chosen_entry = p
                if binding.get('workbookDir'):
                    p = checked_path(Path(binding['workbookDir']), [root])
                    if p.name not in ['workbook', 'notebook', '工作本', '责任笔记']:
                        raise ValueError('unrecognized workbook folder')
                    bookdirs.append(p)
            except (OSError, ValueError, TypeError):
                gaps.append('本岗登记入口或工作本路径未通过范围/可用性核对；沿原入口，不影响其他员工')
        histories = [b.get('historyThreadId') for b in bs]
        valid = list(dict.fromkeys((h for h in histories if isinstance(h, str) and re.fullmatch('[a-f0-9-]{36}', h))))
        history = valid[0] if len(valid) == 1 and all((h == valid[0] for h in histories)) else thread
        if bs and (len(valid) != 1 or any((h != valid[0] for h in histories))):
            gaps.append('本岗登记的历史映射不一致；原生核对前保持未知')
        mapping_gap = None
        ref = mapping_cache.get(thread)
        if native_runtime is not None:
            from monitor_history_mapping import reconcile_native
            (history, ref, mapping_gap) = reconcile_native({'threadId': thread, 'historyThreadId': history}, native_runtime.get(ident), ref)
        elif ref:
            from monitor_history_mapping import resolve_mapping
            (history, mapping_gap) = resolve_mapping(thread, history, ref)
        from employee_identity import read_identity
        identity = read_identity({'id': ident, 'threadId': thread, 'root': root, 'name': name, 'entry': chosen_entry})
        aliases = identity['aliases'] if identity else []
        current_name = identity['name'] if identity else name
        out.append({'historyMappingGap': mapping_gap, 'historyReference': ref, 'adapterGaps': gaps, 'bookDirs': bookdirs, 'nativeMetadata': (native_runtime or {}).get(ident), 'identityMetadata': identity, 'aliases': aliases, 'id': ident, 'name': current_name, 'threadId': thread, 'historyThreadId': history, 'root': root, 'entry': chosen_entry, 'category': 'business' if thread in KNOWN else 'support', 'channels': [{'name': PEERS.get(b['peer'], b['peer']), 'peer': b['peer'], 'trigger': b.get('triggerMode', 'native_at')} for b in bs]})
    return (out, {'source': '统一系统registry + 已明确委托的原岗位入口', 'bindings': len(j['bindings']), 'unadaptedThreads': len(set(groups) - set(KNOWN) - set(SUPPORT))})

def source(out, path, text, when, label, role='原工作记录摘录'):
    body = public_text(text, 14000)
    if not body.strip():
        raise ValueError('empty or credential-only source')
    sid = 'work-' + digest(str(path) + '\x00' + body)[:22]
    out[sid] = {'id': sid, 'path': str(path), 'label': label, 'text': body, 'time': when, 'role': role}
    return sid

def commitment(origin, state):
    cand = bool(re.search('尚未承接|未承接|可能待办|候选|主动发现', origin))
    accepted = bool(re.search('本人.*交办|用户.*交办|已承接|明确要求|本人.*要求', origin))
    return 'unknown' if cand and accepted else 'candidate' if cand else 'accepted' if accepted else 'unknown'

def project_note(employee, path, text, sid, when):
    head = text.split('<!-- secretary-work-current:end -->')[0].split('<!-- employee-work:end -->')[0]
    title = plain(field(head, '事情'))
    if not title:
        return None
    origin = plain(field(head, '怎么来的'))
    state = plain(field(head, '现在怎么样')) or '待核实'
    return {'id': 'task-' + digest(path)[:14], 'employee': employee, 'title': public_text(title, 220), 'origin': public_text(origin), 'goal': public_text(plain(field(head, '这次想做到什么'))), 'thought': public_text(plain(field(head, '我的想法'))), 'state': public_text(state, 350), 'next': public_text(plain(field(head, '下一步'))), 'time': public_text(field(head, '时间')), 'commitment': commitment(origin, state), 'sourceId': sid, 'sourceLabel': Path(path).name, 'recordUpdatedAt': when, 'originKind': '原工作本', 'originalRequest': None, 'interpretationKind': '员工原工作本', 'evidence': [{'id': sid, 'quote': public_text(head, 900)}]}

def runtime(thread, history):
    with ro('thread_history_1.sqlite') as c:
        r = c.execute('select turn_id,status,started_at,completed_at from thread_turns where thread_id=? order by started_at desc,rollout_ordinal desc limit 1', (history,)).fetchone()
    with ro('queue_1.sqlite') as c:
        n = c.execute('select count(*) from queued_items where thread_id=?', (thread,)).fetchone()[0]
    return {'state': '活动中' if r and r['status'] == 'inProgress' else '空闲' if r and r['status'] in ['completed', 'failed', 'interrupted'] else '未知', 'queueCount': n, 'turnId': r['turn_id'] if r else None, 'sampledAt': bj(datetime.datetime.now(datetime.timezone.utc).isoformat())}

def receipt_state(j):
    if j.get('state') in ['pending', 'queued', 'prepared', 'submitted', 'running']:
        return 'pending'
    if j.get('state') in ['cancelled', 'canceled', 'superseded']:
        return 'cancelled'
    if j.get('state') == 'succeeded':
        proof = bool(j.get('serverId')) and any((j.get(k) for k in ['independentNativeExactText', 'exactText', 'textExact', 'independentReadback', 'independentNative']))
        parts = j.get('items') or j.get('parts')
        if parts:
            proof = all((x.get('state') == 'succeeded' and x.get('serverId') for x in parts)) and bool(j.get('independentReadback') or j.get('nativeOrderVerified') or j.get('textExact'))
        if proof:
            return 'sent'
    return 'unknown'

def note_paths(role):
    root = role['root']
    paths = []
    if role['id'] == 'notebook':
        root.stat()
    folders = [root / name for name in ['notebook', 'workbook', '工作本', '责任笔记']] + role.get('bookDirs', [])
    for folder in dict.fromkeys(folders):
        checked_path(folder, [root])
        if folder.is_dir():
            paths += sorted(folder.glob('*.md'))
    return sorted({p for p in paths if not any((w in str(p).lower() for w in RESTRICTED))})

def safe_coverage(role):
    p = role['root'] / 'STATE.json'
    if p.is_file():
        (raw, _) = bounded_text(p, [role['root']])
        j = json.loads(raw)
        cur = j.get('read_cursor', {})
        end = cur.get('end_exclusive')
        if isinstance(end, (int, float)):
            return {'readThrough': bj(datetime.datetime.fromtimestamp(end, datetime.timezone.utc).isoformat()), 'note': '原STATE记载的消息读取截止；不代表媒体全部已读', 'source': '原STATE.read_cursor'}
    return {'readThrough': None, 'note': '未取得统一的逐源已读终点；笔记已采集不代表群消息全部已读', 'source': None}

def read_modes(out, when):
    (raw, _) = bounded_text(SKILL / 'references/working-habits.md', [SKILL])
    rows = []
    for line in raw.splitlines():
        if not line.startswith('| ') or '**' not in line:
            continue
        cols = line.strip('|').split('|')
        if len(cols) != 3:
            continue
        options = re.findall('\\*\\*([^*]+)\\*\\*', cols[1])
        default = plain(cols[2]).strip()
        if not options:
            continue
        rows.append({'dimension': cols[0].strip(), 'options': options, 'default': public_text(default, 300), 'roleOverride': None, 'currentChoice': None})
    sid = source(out, SKILL / 'references/working-habits.md', '\n'.join((r['dimension'] + '：' + r['default'] + '；可选：' + '、'.join(r['options']) for r in rows)), when, '共同工作方式', '规范要求，不等于全员实际采用')
    return {'dimensions': rows, 'sourceId': sid, 'note': '岗位例外从原约定展开查看；未单独记录本次采用时保持未知，不以规范推断行为。'}

def system_observation(out, when):
    p = METHOD / 'unified-mention-runtime/runtime/status.json'
    (raw, _) = bounded_text(p, [METHOD])
    j = json.loads(raw)
    bindings = {}
    for (key, value) in j.get('bindings', {}).items():
        reason = value.get('sourceGapReason')
        if not isinstance(reason, str) or not re.fullmatch('[a-z][a-z0-9_]{0,79}', reason):
            reason = None
        bindings[key] = {'sourceReady': value.get('sourceReady'), 'lastSourceAt': value.get('lastSourceAt'), 'sourceGapReason': reason}
    complete = j.get('sourceCoverageComplete')
    event = {'sampledAt': when, 'producerUpdatedAt': j.get('updatedAt'), 'sourceReady': j.get('sourceReady'), 'sourceCoverageComplete': complete if type(complete) is bool else None, 'bindings': bindings, 'note': '来源连接状态与登记来源覆盖分别记录。逐来源就绪及缺口见bindings，绑定数量按来源统计；员工实际读到哪里仍查原岗位记录。'}
    sid = source(out, p, json.dumps(event, ensure_ascii=False), bj(when), '统一事件来源状态', '当前采样，不代替真实业务交付验收')
    reviews = []
    ps = [METHOD / 'daily-review/ISSUES.md'] + sorted((METHOD / 'daily-review/reports').glob('*/REPORT.md'), key=lambda x: x.stat().st_mtime, reverse=True)[:2]
    for p in ps:
        try:
            (raw, st) = bounded_text(p, [METHOD])
            body = public_text(raw, 7000)
            rid = source(out, p, body, bj(datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat()), '原每日复核 · ' + p.parent.name, '系统负责人原报告，不是监控重新审查')
            reviews.append({'title': raw.splitlines()[0].lstrip('# '), 'sourceId': rid, 'recordUpdatedAt': bj(datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat()), 'excerpt': public_text(raw[:1200])})
        except Exception:
            continue
    return {'eventSourceId': sid, 'event': event, 'reviews': reviews}

def notebook_items(role, out, cache, when):
    items = []
    files = {}
    errors = []
    try:
        current = note_paths(role)
    except (OSError, ValueError) as exc:
        current = []
        errors.append('工作本目录暂不可读；保留已知笔记（' + type(exc).__name__ + ', errno=' + str(getattr(exc, 'errno', None)) + '）')
    paths = sorted(set(current) | {Path(p) for p in cache})
    if len(paths) > 500:
        errors.append('工作本超过本轮500篇预算；超出新笔记未读，旧笔记保留并标陈旧')
    for (number, p) in enumerate(paths):
        prev = cache.get(str(p), {})
        stale = False
        modified = when
        try:
            if number >= 500:
                raise OSError('note budget')
            checked_path(p, [role['root']])
            st = p.stat()
            sig = [st.st_mtime_ns, st.st_size]
            text = bounded_text(p, [role['root']])[0]
            modified = bj(datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat())
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append(p.name + ': ' + type(error).__name__)
            if not prev.get('text'):
                continue
            text = prev['text']
            sig = prev.get('signature', [])
            stale = True
            if sig:
                modified = bj(datetime.datetime.fromtimestamp(sig[0] / 1000000000.0, datetime.timezone.utc).isoformat())
        head = text.split('<!-- secretary-work-current:end -->')[0].split('<!-- employee-work:end -->')[0]
        if any((w in head.lower() for w in RESTRICTED)) or not field(head, '事情'):
            continue
        clean = public_text(head, 14000)
        files[str(p)] = {'signature': sig, 'text': clean, 'sourceStale': stale}
        sid = source(out, p, clean, modified, p.name + (' · 上次可读记录' if stale else ''), '当前源暂不可读，沿上次记录；不推断完成' if stale else '原工作记录摘录')
        item = project_note(role['id'], str(p), clean, sid, modified)
        if not item:
            continue
        item['sourceStale'] = stale
        from delivery_health import note_seed
        item['_deliverySeed'] = note_seed(role, p, head, item['id'], sid)
        if role['id'] == 'research-secretary':
            from research_secretary_scope import recorded_requests
            item['_deliverySeed']['requestIds'] = list(dict.fromkeys(item['_deliverySeed']['requestIds'] + recorded_requests(text)))[:30]
        if prev.get('signature') == sig and prev.get('deliveryIndexVersion') == 4:
            item['_deliverySeed']['requestIds'] = list(dict.fromkeys(item['_deliverySeed']['requestIds'] + prev.get('receiptIds', [])))[:30]
        item['_deliverySeed']['operationEvidenceIds'] = list(dict.fromkeys(item['_deliverySeed']['operationEvidenceIds'] + (prev.get('operationEvidenceIds', []) if prev.get('deliveryIndexVersion') == 4 else [])))
        files[str(p)]['operationEvidenceIds'] = item['_deliverySeed']['operationEvidenceIds']
        files[str(p)]['receiptIds'] = item['_deliverySeed']['requestIds']
        files[str(p)]['deliveryIndexVersion'] = 4
        for name in ['decisionReferences', 'forwardReferences']:
            files[str(p)][name] = copy.deepcopy(prev.get(name, []))
            item['_' + name] = files[str(p)][name]
        items.append(item)
    return (items, files, errors)

def science_items(role, out):
    p = SCI / 'CURRENT_RESEARCH.json'
    (raw, st) = bounded_text(p, [SCI])
    j = json.loads(raw)
    items = []
    entries = list(j.items())
    for (parent, value) in j.items():
        if isinstance(value, dict):
            for (child, node) in value.items():
                if isinstance(node, dict) and isinstance(node.get('status'), str) and (node.get('source_serverId') or node.get('request')):
                    entries.append((parent + '.' + child, node))
    for (key, v) in entries:
        if not isinstance(v, dict) or not isinstance(v.get('status'), str):
            continue
        data = {k: v[k] for k in ['status', 'question', 'target', 'request', 'source_serverId', 'source', 'result', 'next', 'notes', 'path'] if k in v and (not isinstance(v[k], (dict, list)))}
        text = public_text(json.dumps({key: data}, ensure_ascii=False), 6000)
        if any((w in text.lower() for w in RESTRICTED)):
            continue
        when = bj(j.get('latest_updated_utc', '')) or bj(datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat())
        sid = source(out, p, text, when, '科研记录 · ' + key)
        items.append({'id': 'research-' + digest(key)[:14], 'employee': 'science', 'title': public_text(v.get('question') or v.get('target') or v.get('request') or key, 220), 'originKind': '原科研JSON', 'origin': public_text(v.get('source', '原研究记录')), 'originalRequest': None, 'goal': public_text(v.get('target') or v.get('question') or ''), 'thought': public_text(v.get('result') or v.get('notes') or ''), 'state': public_text(v['status'], 500), 'next': public_text(v.get('next') or ''), 'time': '原科研记录，业务提出时间未单列', 'commitment': 'unknown', 'sourceId': sid, 'sourceLabel': 'CURRENT_RESEARCH · ' + key, 'recordUpdatedAt': when, 'interpretationKind': '原专业记录，未改写成明确承诺', 'evidence': [{'id': sid, 'quote': text[:900]}]})
    for (i, action) in enumerate(j.get('next_actions', [])):
        if not isinstance(action, str):
            continue
        sid = source(out, p, public_text(action), bj(j.get('latest_updated_utc', '')), '科研下一步建议')
        items.append({'id': 'science-next-' + digest(action)[:14], 'employee': 'science', 'title': public_text(action, 220), 'state': '候选建议', 'next': public_text(action), 'origin': '原next_actions；原planning_note说明不是本人新指令', 'originKind': '原科研JSON', 'commitment': 'candidate', 'goal': '', 'thought': '', 'time': '', 'originalRequest': None, 'interpretationKind': '原研究建议', 'sourceId': sid, 'sourceLabel': 'CURRENT_RESEARCH.next_actions', 'recordUpdatedAt': bj(j.get('latest_updated_utc', '')), 'evidence': [{'id': sid, 'quote': public_text(action)}]})
    return items

def text_input(j):
    if 'UserInput' in j:
        j = j['UserInput']
    return '\n'.join((x.get('text', '') for x in j.get('content', []) if x.get('type') == 'text'))

def sender_inbox(out, when, sender_role=None):
    if ((sender_role or {}).get('nativeMetadata') or {}).get('host') == 'aup':
        from sender_runtime import inbox
        observed = inbox(sender_role, out, when)
        return {'items': [], 'sampledAt': observed['sampledAt'], 'queueCount': observed['queueCount'], 'activeAssignments': None, 'historyReviewed': len(sender_role['nativeMetadata'].get('turns', [])), 'note': observed['gap'], 'error': None}
    rows = []
    results = {}
    folders = []
    history = (sender_role or {}).get('historyThreadId', SENDER)
    for folder in sorted((SEC / 'work').glob('20??????-centralized-wechat-sending'))[-7:]:
        if not folder.is_symlink():
            folders += list(folder.glob('*/RESULT.json'))
    for p in sorted(folders, key=lambda p: p.stat().st_mtime)[-350:]:
        try:
            (raw, _) = bounded_text(p, [SEC / 'work'])
            j = json.loads(raw)
            key = j.get('assignmentId') or j.get('assignment') or p.parent.name
            results[key] = (p, j)
        except Exception:
            continue
    from inbox_reader import queue_rows, describe_request, meaningful_summary
    with ro('queue_1.sqlite') as c:
        queued = queue_rows([dict(x) for x in c.execute('select id,payload_json,created_at_ms,queue_order from queued_items where thread_id=? order by queue_order limit 150', (SENDER,))])
    with ro('thread_history_1.sqlite') as c:
        active = [dict(x) for x in c.execute("select i.item_id as id,i.item_json as payload_json,i.created_at_ms from thread_items i join thread_turns t on t.thread_id=i.thread_id and t.turn_id=i.turn_id where i.thread_id=? and i.item_type='userMessage' and t.status='inProgress' and t.turn_id=(select turn_id from thread_turns where thread_id=? order by started_at desc,rollout_ordinal desc limit 1) order by i.created_at_ms limit 30", (history, history))]
        recent = [dict(x) for x in c.execute("select i.item_id as id,i.item_json as payload_json,i.created_at_ms from thread_items i where i.thread_id=? and i.item_type='userMessage' order by i.created_at_ms desc limit 150", (history,))]
    seen = set()
    for (phase, inputs) in [('processing', active), ('queued', queued), ('unknown', recent)]:
        for x in inputs:
            text = text_input(json.loads(x['payload_json']))
            if not text or any((w in text.lower() for w in RESTRICTED)):
                continue
            if not re.search('发送|发件|send_text|send_file|send_image', text):
                continue
            header = text.splitlines()[0]
            if not header.startswith('发送交办') and re.search('维护回报|协作回报|恢复前提已核|工具.*回报|原两单恢复发送', header):
                continue
            match = next(((k, results[k][0], results[k][1]) for k in sorted(results, key=len, reverse=True) if k in header), None)
            ids = re.findall('(?:request_id|requestId|发送交办|发件单|请求ID)\\s*[=：: ]\\s*[`\\"\\\']?([a-zA-Z][a-zA-Z0-9_-]{8,})', text)
            heading_ids = re.findall('[a-z][a-z0-9]*(?:[-_][a-zA-Z0-9]+){2,}', header)
            if not match and (not ids) and (not heading_ids):
                continue
            key = match[0] if match else heading_ids[0] if heading_ids else ids[0] if ids else 'inbox-' + x['id']
            if key in seen:
                continue
            seen.add(key)
            state = receipt_state(match[2]) if match else 'pending' if phase == 'queued' else 'unknown'
            if state == 'cancelled':
                label = '已撤销／被后续取代'
            elif state == 'sent':
                label = '有发送依据'
            else:
                label = {'queued': '排队中', 'processing': '发送员工已接住', 'unknown': '结果待核'}[phase]
            owner = 'forum' if re.search('forum[-_]|论坛|会务', key) else 'science' if key.startswith('science') else 'organoid' if key.startswith('organoid') else 'secretary' if key.startswith('secretary') else 'unknown'
            peer = match[2].get('peer') if match else None
            if not peer:
                peers = re.findall('(?<![0-9])[0-9]{8,}@chatroom(?![A-Za-z0-9])|wxid_fixture_owner', text)
                peer = peers[-1] if peers else None
            info = describe_request(text)
            peer = info.get('peer') or peer
            synopsis = info['summary']
            prepared = info.get('body')
            attachments = info.get('attachments', [])
            planpath = None
            candidates = []
            for f in sorted((SEC / 'work').glob('20??????-centralized-wechat-sending'))[-7:]:
                p = f / key / 'plan.json'
                if p.exists():
                    candidates.append(p)
            if candidates:
                try:
                    planpath = candidates[-1]
                    (raw, _) = bounded_text(planpath, [planpath.parent])
                    plan = json.loads(raw)
                    peer = plan.get('peer') or peer
                    prepared = '\n\n'.join((public_text(r.get('text', '')) for r in plan.get('rows', []) if r.get('action') == 'send_text')) or prepared
                    attachments = [Path(r.get('file_path', r.get('path', ''))).name for r in plan.get('rows', []) if r.get('action') in ['send_image', 'send_file'] and r.get('file_path', r.get('path'))] or attachments
                except Exception:
                    pass
            synopsis = meaningful_summary(info['requestExcerpt'], prepared or '', attachments)
            labelsrc = '中央发送 · ' + label
            body = '交办摘要：' + synopsis + '\n当前：' + label + '\n目标：' + PEERS.get(peer, peer or '原单未明确群名')
            if prepared:
                body += '\n冻结正文：\n' + prepared
            sid = source(out, planpath or (info['referencePaths'][0] if info['referencePaths'] else '原生队列:' + x['id'] if phase == 'queued' else '原发送对话:' + x['id']), body, when, labelsrc, '原交办引用的定稿/附件与队列状态，非新发件')
            proof = None
            if match:
                (_, p, j) = match
                minimal = {k: j.get(k) for k in ['assignmentId', 'assignment', 'state', 'peer', 'serverId', 'sentCount', 'phoneReceiptConfirmed', 'independentNativeExactText', 'independentReadback', 'exactText'] if k in j}
                proof = source(out, p, json.dumps(minimal, ensure_ascii=False), when, '原发送结果摘要', '原发送方记录；非本监控重新发件或独立读微信')
            rows.append({'id': key, 'employee': owner, 'destination': PEERS.get(peer, peer or '收件人未在可读交办中明确'), 'peer': peer, 'title': synopsis, 'body': prepared, 'bodyKind': '原交办引用的定稿' if prepared else '依据附件名/交办要点整理，完整正文未取得', 'summary': synopsis, 'attachments': attachments, 'phase': phase, 'state': state, 'label': label, 'reason': '原队列中等待接续' if phase == 'queued' else '原发送回合处理中；具体阻碍见原记录' if phase == 'processing' else '已消费交办，发送结果需原单核对', 'sourceId': sid, 'proofSourceId': proof, 'requestedAt': bj(datetime.datetime.fromtimestamp(x['created_at_ms'] / 1000, datetime.timezone.utc).isoformat()), 'receivedAtMs': x['created_at_ms'], 'queuePosition': x.get('queuePosition', 0) if phase != 'unknown' else None, 'nativeQueueOrder': x.get('queue_order'), 'nativeItemId': x['id'], 'relatedItemIds': []})
    return {'items': rows, 'sampledAt': when, 'queueCount': len(queued), 'activeAssignments': len(active), 'historyReviewed': len(recent), 'note': '读取原生发送队列、当前回合、最近150条交办和近7个有记录日期的结果摘要；不是全部历史。缺统一冻结正文时只显示交办摘要，不冒称发件内容。', 'error': None}

def enrich_sending(sending, out, when):
    from send_tool_observer import read_tools, CLIENTS
    known = sending.pop('_knownDeliveryRequests', [])
    for folder in sorted((SEC / 'work').glob('20??????-centralized-wechat-sending'))[-7:]:
        plans = sorted(folder.glob('*/plan.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in plans[:30]:
            if (p.parent / 'RESULT.json').exists():
                continue
            try:
                (raw, _) = bounded_text(p, [folder])
                j = json.loads(raw)
                for r in j.get('rows', []):
                    if j.get('client') in CLIENTS and r.get('request_id'):
                        known.append((j['client'], r['request_id']))
            except Exception:
                continue
    tools = read_tools(known)
    sending['_deliveryJobs'] = tools['jobs']
    sending['_deliveryGaps'] = tools['gaps']
    sending['toolCoverage'] = {'gaps': tools['gaps'], 'indexed': len(tools['jobs']), 'targetedReads': tools['targetedReads'], 'workerLive': tools['status'].get('workerLive'), 'heartbeatFresh': tools['status'].get('heartbeatFresh'), 'policyFormatVersion': tools['status'].get('policyFormatVersion'), 'sampledAt': when}
    for job in tools['jobs']:
        rid = job['request_id']
        matches = [r for r in sending['items'] if rid == r['id'] or rid.startswith(r['id'] + '-')]
        already_sent = bool(matches and matches[0]['state'] == 'sent')
        active = job['state'] in ['queued', 'preparing', 'awaiting_confirmation', 'confirmed', 'executing', 'needs_attention']
        sent = job.get('nativeReceiptVerified') is True
        from delivery_health import family
        relevant = any((c == job['client'] and family(r) == family(rid) for (c, r) in known))
        recent_failure = job.get('recent') and job['state'] == 'failed' and (not __import__('delivery_health').ack(rid))
        if not active and (not matches) and (not relevant) and (not recent_failure):
            continue
        body = public_text(job.get('text') or '', 5000)
        label = '工具已受理：' + str(job['state']) if active else '工具有发送依据' if sent else '工具结果待核：' + str(job['state'])
        safe = {k: job.get(k) for k in ['jobId', 'client', 'request_id', 'peer', 'action', 'state', 'created', 'updated', 'serverId', 'noSend', 'reason', 'contentHash', 'nativeProof', 'kind', 'supersedes']}
        safe['nativeReceiptVerified'] = job.get('nativeReceiptVerified', False)
        sid = source(out, '原微信工具:' + job['client'] + '/' + rid, json.dumps(safe, ensure_ascii=False), when, '微信工具请求 · ' + label, '只读get/list；没有submit/confirm/reconcile')
        job['sourceId'] = sid
        if already_sent:
            continue
        if not active and (not matches) and (not recent_failure):
            continue
        if matches:
            r = matches[0]
            r.setdefault('toolOperations', []).append({'requestId': rid, 'state': job['state'], 'sourceId': sid, 'serverId': job.get('serverId')})
            r['proofSourceId'] = sid
            if active:
                r.update(label=label, phase='processing', reason='微信工具已受理，状态见操作依据；不重发')
            if body and (not r['body']):
                r.update(body=body, bodyKind='原工具已冻结正文')
        else:
            if recent_failure:
                label = '失败记录／业务关联待核'
            sending['items'].append({'id': 'tool-' + job['client'] + '-' + rid, 'employee': job['employee'], 'destination': PEERS.get(job['peer'], job['peer']), 'peer': job['peer'], 'title': {'send_text': '文字', 'send_image': '图片', 'send_file': '文件'}.get(job['action'], '消息') + '发送失败；是否仍需补交待核' if recent_failure else body[:160] or job['action'] + ' · ' + rid, 'body': None if recent_failure else body or None, 'bodyKind': '失败元数据；未公开原消息正文' if recent_failure else '原工具已冻结正文' if body else '媒体／转发内容见原交办', 'summary': job['action'] if recent_failure else body[:200] or job['action'], 'attachments': [], 'phase': 'processing' if active else 'unknown', 'state': 'pending' if active else 'sent' if sent else 'unknown', 'label': label, 'reason': '原工具失败；尚未和当前业务交付建立明确关联，不自动列为新待办' if recent_failure else '原工具当前状态；不是再次提交', 'sourceId': sid, 'proofSourceId': sid, 'requestedAt': bj(datetime.datetime.fromtimestamp(job['created'], datetime.timezone.utc).isoformat()) if isinstance(job['created'], (int, float)) else '原工具时间待核', 'nativeItemId': None, 'relatedItemIds': []})
    if tools['status'].get('policyFormatVersion') == 2:
        sending['note'] += ' 当前已读Policy v2：client为作者/业务标签，不是收件人或动作许可；来源归属与实际交付仍分别核。'
    sending['note'] += ' 工具层只读：旧列表100＋最近摘要20＋已知业务ID批量get_many；各项预算与缺口保留，非全历史覆盖。'
    return sending

def profile_for(role, out, when):
    (raw, st) = bounded_text(role['entry'], [role['root'], role['entry'].parent, SKILL, Path(str(_install.path('codex_home') / 'skills/notebook-secretary'))])
    excerpts = []
    for line in raw.splitlines():
        if re.search('职责|负责|服务|授权|暂缓|暂停|停用|私聊|发送|飞书|工作本|默认', line) and (not any((w in line.lower() for w in RESTRICTED))):
            excerpts.append(line)
    body = public_text('\n'.join(excerpts[:24]), 6000) or public_text(raw[:2500])
    sid = source(out, role['entry'], body, bj(datetime.datetime.fromtimestamp(st.st_mtime, datetime.timezone.utc).isoformat()), role['name'] + ' · 原岗位约定')
    ev = [{'id': sid, 'quote': body[:500]}]
    if role.get('identityMetadata'):
        identity = role['identityMetadata']
        identity_text = json.dumps({k: identity[k] for k in ['name', 'aliases', 'threadId']}, ensure_ascii=False)
        identity_sid = source(out, identity['sourcePath'], identity_text, when, '当前岗位称呼及旧名', '原STATE.identity与ROLE同身份核对；不是新岗位')
        ev = [{'id': identity_sid, 'quote': identity_text}] + ev
    relations = [{'id': role['id'] + '-channel-' + digest(c['peer'])[:8], 'label': c['name'], 'kind': 'channel', 'realId': c['peer'], 'types': ['communicates'], 'scope': '原系统登记的接续渠道；不扩展读取和公开范围', 'evidence': ev} for c in role['channels']]
    profile = {'employee': role['id'], 'roleName': role['name'], 'aliases': role.get('aliases', []), 'purpose': '原岗位职责和边界见依据；不按岗位名推断能力', 'identityEvidence': ev, 'responsibilities': [{'text': body[:350], 'evidence': ev}], 'relations': relations, 'boundaries': [{'text': '保持原岗位授权与发送分工；监控不写回', 'evidence': ev}], 'routines': [], 'resources': [{'label': '原岗位工作入口', 'kind': 'role', 'note': '原文摘录，不新建监控表', 'evidence': ev}], 'capabilities': [], 'lifecycle': {'state': 'unknown', 'note': '已确认岗位，生命周期结论以原约定为准', 'evidence': ev}, 'history': [], 'observedHistory': [], 'health': {'lastSuccess': when, 'lastAttempt': when, 'error': None}, 'sourceIds': [sid]}
    if role['id'] == 'notebook' and role['threadId'] == _install.identity('monitor.work_observer.identity_332ec844'):
        profile['boundaries'].append({'text': '此处显示员工自身责任与接续，不是组织业务新真源；本岗保存已交不代表邀请等原业务已完成。03点实际更新与来源覆盖依原记录，不因本监控读到笔记就认定自然运行已验。', 'evidence': ev})
        for (filename, kind, label) in [('ROLE.md', 'role', '本岗职责与既有例外'), ('CURRENT.md', 'current', '自身责任的派生总览')]:
            try:
                (text, _) = bounded_text(role['root'] / filename, [role['root']])
                body = public_text(text, 6000)
                sid = source(out, role['root'] / filename, body, when, label, '员工自己的岗位记录；不读取或代写组织事项库')
                profile['sourceIds'].append(sid)
                profile['resources'].append({'label': label, 'kind': kind, 'note': '原作者本岗记录，原业务事实及保存收据留原处', 'evidence': [{'id': sid, 'quote': body[:500]}]})
            except (OSError, ValueError, TypeError):
                profile['health']['error'] = '本岗职责或总览暂不可读；逐件记录独立保留'
        profile['resources'].append({'label': '自身逐件责任笔记', 'kind': 'workbook', 'note': '从原同目录workbook读取；与共同记事本组织业务分开，保存完成与邀请完成分别判断', 'evidence': ev})
    return profile

def refresh_work(snapshot, sources, when, native_runtime=None):
    """Add a bounded observer projection. Preserve last good data per failed employee."""
    old = snapshot.get('workOverview', {})
    out = dict(sources)
    cachepath = PRIVATE / 'work-observer-cache.json'
    cache = json.loads(cachepath.read_text()) if cachepath.exists() else {}
    newcache = {'_historyMappings': copy.deepcopy(cache.get('_historyMappings', {}))}
    items = []
    people = []
    delivery_seeds = []
    decision_references = []
    forward_references = []
    (roles, discovery) = directory(native_runtime=native_runtime)
    (registry_text, _) = bounded_text(REGISTRY, [METHOD])
    bindings_by_thread = group_bindings(json.loads(registry_text)['bindings'])
    for role in roles:
        try:
            (notes, files, errs) = notebook_items(role, out, cache.get(role['id'], {}), when)
            newcache[role['id']] = files
            errs += role.get('adapterGaps', [])
            if role.get('historyReference'):
                newcache['_historyMappings'][role['threadId']] = role['historyReference']
            if role['id'] == 'science':
                notes += science_items(role, out)
            for n in notes:
                matches = [t for t in snapshot['tasks'] if t['employee'] == role['id'] and t['kind'] != 'history' and any((sources.get(e['id'], {}).get('path') == next((p for p in files if 'task-' + digest(p)[:14] == n['id']), '') for e in t['evidence']))]
                if matches:
                    n['id'] = matches[0]['id']
                frefs = n.pop('_forwardReferences', [])
                if frefs:
                    forward_references.append((role, frefs))
                refs = n.pop('_decisionReferences', [])
                if refs:
                    decision_references.append((role, refs))
                seed = n.pop('_deliverySeed', None)
                if seed:
                    seed['businessId'] = n['id']
                    delivery_seeds.append(seed)
            remote = (role.get('nativeMetadata') or {}).get('host') == 'aup'
            try:
                rt = {'state': '未知', 'queueCount': None, 'turnId': None, 'sampledAt': bj(when)} if remote else runtime(role['threadId'], role['historyThreadId'])
            except Exception:
                rt = {'state': '未知', 'queueCount': None, 'turnId': None, 'sampledAt': bj(when)}
            meta = role.get('nativeMetadata')
            if meta and (not meta.get('error')) and (meta.get('threadId') == role['threadId']):
                rt.update(state={'active': '活动中', 'idle': '空闲'}.get(meta.get('status'), '未知'), queueCount=meta.get('queueCount'), turnId=(meta.get('turns') or [{}])[0].get('id'), sampledAt=bj(meta.get('sampledAt') or when))
            try:
                coverage = safe_coverage(role)
            except (OSError, ValueError, TypeError) as exc:
                coverage = {'readThrough': None, 'note': '原读取位置暂不可读，不推断已读', 'source': None}
                errs.append('原读取位置暂不可读（' + type(exc).__name__ + ', errno=' + str(getattr(exc, 'errno', None)) + '）')
            person = {k: role[k] for k in ['id', 'name', 'threadId', 'historyThreadId', 'category', 'channels']}
            person['aliases'] = role.get('aliases', [])
            person.update(runtime=rt, coverage=coverage, notebooks=len(files), observedAt=when, error='；'.join(errs + ([role['historyMappingGap']] if role.get('historyMappingGap') else [])) or None)
            mode_lines = []
            try:
                (roletext, _) = bounded_text(role['entry'], [role['entry'].parent])
            except (OSError, ValueError):
                roletext = ''
                person['error'] = '岗位入口暂不可读；工作本与收件独立保留'
            for line in roletext.splitlines():
                if re.search('图文|简短|Word|飞书|载体|阶段反馈|经验|协作取向|通常怎样工作', line) and (not any((w in line.lower() for w in RESTRICTED))):
                    mode_lines.append(line)
            if mode_lines:
                excerpt = public_text('\n'.join(mode_lines[:10]), 3000)
                person['modeNotes'] = {'excerpt': excerpt, 'sourceId': source(out, role['entry'], excerpt, when, role['name'] + ' · 原岗位工作方式相关约定')}
            from conversation_reminders import read_pending
            try:
                reminders = read_pending(role['threadId'], bindings_by_thread.get(role['threadId'], []))
                for conv in reminders['conversations']:
                    conv['name'] = PEERS.get(conv['peer'], conv['peer'])
                reminders['observedAt'] = when
                reminders['error'] = None
                reminders['sourceId'] = source(out, '统一待看会话:' + role['threadId'], json.dumps(reminders, ensure_ascii=False), bj(when), role['name'] + ' · 待看会话', '原系统只读--pending，不表示已阅读、已回复或业务完成' if reminders['state'] == 'known' else '当前登记范围，未取得该岗位其他入口的待看结果')
            except Exception:
                previous = next((p for p in old.get('employees', []) if p['id'] == role['id']), {})
                reminders = {**copy.deepcopy(previous.get('reminders', {'state': 'unknown', 'pending': None, 'conversations': [], 'existingNotices': []})), 'error': '待看来源本轮未取得，保留上次结果', 'lastAttempt': when}
            person['workRead'] = {'state': 'structured' if notes else 'native_only', 'format': '原专业JSON' if role['id'] == 'science' else '原逐件笔记', 'indexedNotes': len(files), 'items': len(notes), 'staleItems': sum((bool(n.get('sourceStale')) for n in notes)), 'gaps': errs}
            person['reminders'] = reminders
            from inbox_reader import read_employee_inbox
            try:
                person['inbox'] = read_employee_inbox(role, out, when)
                current_state = person['inbox']['runtimeState']
                if current_state != 'unknown':
                    person['runtime'].update(state='活动中' if current_state == 'inProgress' else '空闲', queueCount=person['inbox']['queueCount'])
            except Exception:
                previous = next((p for p in old.get('employees', []) if p['id'] == role['id']), {})
                person['inbox'] = {**copy.deepcopy(previous.get('inbox', {'items': [], 'queueCount': None})), 'error': '原生收件暂不可读；保留上次结果', 'lastAttempt': when}
            people.append(person)
            items += notes
            profile = snapshot.get('profiles', {}).get(role['id'])
            previous_profile = copy.deepcopy(profile)
            if not profile or role['id'] not in ['secretary', 'science', 'organoid']:
                try:
                    snapshot.setdefault('profiles', {})[role['id']] = profile_for(role, out, when)
                except Exception as exc:
                    person['error'] = '岗位属性来源暂不可读；事项读取独立保留（' + type(exc).__name__ + ', errno=' + str(getattr(exc, 'errno', None)) + '）'
            elif role.get('identityMetadata'):
                identity = role['identityMetadata']
                body = identity.get('evidenceText') or json.dumps({k: identity[k] for k in ['name', 'aliases', 'threadId']}, ensure_ascii=False)
                sid = source(out, identity['sourcePath'], body, when, '当前岗位称呼及旧名', '原岗位权威身份专段；不更改业务身份或权限')
                profile.update(roleName=role['name'], aliases=role.get('aliases', []), identityEvidence=[{'id': sid, 'quote': body}] + [e for e in profile.get('identityEvidence', []) if e.get('id') != sid])
            employee = next((e for e in snapshot['employees'] if e['id'] == role['id']), None)
            if not employee:
                employee = {'id': role['id'], 'threadId': role['threadId'], 'name': role['name'], 'role': '业务岗位' if role['category'] == 'business' else '系统支撑', 'notebook': str(role['root']).replace(str(_install.path('monitor.work_observer.path_154d9af3')), '[Mac]/'), 'current': '见原工作记录；尚未单列事项不等于无任务', 'lastActivity': '', 'gap': coverage['note'], 'turnHours': 0, 'coverage': {'messages': 0, 'files': 0, 'notes': len(files), 'first': '未在监控重建历史', 'last': '原笔记采样 ' + bj(when), 'reviewed': False}}
                snapshot['employees'].append(employee)
            employee.update(name=role['name'], aliases=role.get('aliases', []), runtime={'活动中': '执行中', '空闲': '空闲'}.get(rt['state'], '未知'), queueCount=rt['queueCount'])
            if role['id'] == 'notebook':
                employee['notebook'] = str(role['root']).replace(str(_install.path('monitor.work_observer.path_154d9af3')), '[Mac]/') + ' · 本岗自身责任入口'
                employee.setdefault('coverage', {})['notes'] = len(files)
                employee['current'] = '原自身工作本：' + '；'.join((n['title'] + '（' + n['state'] + '）' for n in notes[:3])) if notes else '本岗自身责任本本轮未取得；原生收件与覆盖分别核'
            if remote:
                gap = person.get('inbox', {}).get('gap', 'AUP正式来源本轮尚未取得')
                person['coverage'] = {'readThrough': None, 'note': gap, 'source': None}
                person['workRead']['gaps'].append(gap)
                employee.update(notebook='AUP原发送岗位；正式inspect/read最近8回合', gap=gap, current=gap)
                profile = snapshot.get('profiles', {}).get(role['id'])
                if (role.get('nativeMetadata') or {}).get('error') and previous_profile:
                    profile = previous_profile
                    profile.setdefault('health', {}).update(lastAttempt=when, error='AUP本轮不可读，保留上次已知公开工作')
                    snapshot['profiles'][role['id']] = profile
                if profile:
                    refs = []
                    for turn in (role.get('nativeMetadata') or {}).get('turns', [])[:8]:
                        body = '\n'.join(turn.get('final', []))
                        if not body:
                            continue
                        sid = source(out, 'AUP正式发送对话:' + SENDER + '/' + turn['id'], body, when, '中央发送 · AUP公开结果', '正式read公开答复；不当独立交付证明')
                        refs.append({'id': sid, 'quote': body[:240]})
                    if refs:
                        profile['resources'] = [{'label': 'AUP最近公开工作（最多8回合）', 'kind': 'journal', 'note': gap, 'evidence': refs}] + [x for x in profile.get('resources', []) if x.get('label') != 'AUP最近公开工作（最多8回合）']
                    elif (role.get('nativeMetadata') or {}).get('error'):
                        prev = next((p for p in old.get('employees', []) if p['id'] == role['id']), {})
                        if prev.get('coverage', {}).get('note'):
                            person['coverage']['note'] += ' 上次已知（非本轮重核）：' + prev['coverage']['note']
                            employee['current'] = person['coverage']['note']
                    profile['boundaries'].append({'text': '当前运行在AUP；未提供完整原始输入/排队正文/全历史，Mac归档不当现行工作。', 'evidence': refs})
            for n in notes:
                existing = next((t for t in snapshot['tasks'] if t['id'] == n['id']), None)
                if existing and role['id'] in ['secretary', 'science', 'organoid']:
                    continue
                projected = {'id': n['id'], 'employee': role['id'], 'title': n['title'], 'state': n['state'] if n['state'] in CLOSED + ('待推进', '进行中', '等反馈', '先放放') else '待核实', 'pending': n['next'], 'next': n['next'], 'goal': n['goal'], 'origin': n['origin'], 'thought': n['thought'], 'time': n['time'], 'confidence': '原工作记录投影', 'evidence': n['evidence'], 'trajectory': existing.get('trajectory', []) if existing else [], 'kind': 'notebook'}
                if existing:
                    existing.update(projected)
                else:
                    snapshot['tasks'].append(projected)
        except Exception as e:
            previous = next((p for p in old.get('employees', []) if p['id'] == role['id']), None)
            people.append({**(previous or {k: role[k] for k in ['id', 'name', 'threadId', 'category', 'channels']}), 'error': type(e).__name__ + ': 原来源暂不可读，保留上次结果', 'observedAt': when})
            items += [i for i in old.get('items', []) if i['employee'] == role['id']]
            newcache[role['id']] = cache.get(role['id'], {})
    from delivery_decision_evidence import index_references, apply_references
    for (role, refs) in decision_references:
        delivery_seeds = index_references(delivery_seeds, refs)
    from delivery_forward_evidence import index_references as index_forward, apply_references as apply_forward
    for (role, refs) in forward_references:
        delivery_seeds = index_forward(delivery_seeds, refs)
    from talent02_specific_proof import associate
    delivery_seeds = associate(delivery_seeds, {**sources, **out}, out, when)
    from delivery_receipt_cache import prepare_receipts, apply_receipts, remember_receipts
    (delivery_seeds, receipt_entries, receipt_gaps) = prepare_receipts(items, delivery_seeds, out, cache.get('_verifiedDeliveryReceipts', {'version': 1, 'entries': []}))
    try:
        sender = sender_inbox(out, when, sender_role=next((r for r in roles if r['id'] == 'sender'), None))
        from send_tool_observer import CLIENTS
        sender['_knownDeliveryRequests'] = [(c, r) for field in ['legacyRequeryIds', 'currentRequestIds', 'factRequestIds'] for seed in delivery_seeds for (c, e) in CLIENTS.items() if e == seed['employee'] for r in seed.get(field, [])]
        try:
            sender = enrich_sending(sender, out, when)
        except Exception:
            sender['toolCoverage'] = {'gaps': ['微信工具读取失败；原对话交办仍保留'], 'sampledAt': when}
    except Exception as e:
        sender = {**old.get('sending', {'items': []}), 'error': type(e).__name__ + ': 发送来源暂不可读，保留上次结果', 'lastAttempt': when}
    from delivery_health import build_health, attach_health
    delivery_jobs = sender.pop('_deliveryJobs', [])
    delivery_gaps = sender.pop('_deliveryGaps', []) + receipt_gaps
    (delivery_jobs, retained_gaps) = apply_receipts(items, delivery_seeds, delivery_jobs, out, receipt_entries)
    delivery_gaps += retained_gaps
    for (role, refs) in decision_references:
        (delivery_seeds, delivery_jobs, decision_gaps) = apply_references(role, items, delivery_seeds, delivery_jobs, out, refs, when)
        delivery_gaps += decision_gaps
    for (role, refs) in forward_references:
        (delivery_seeds, delivery_jobs, forward_gaps) = apply_forward(role, items, delivery_seeds, delivery_jobs, out, refs, when)
        delivery_gaps += forward_gaps
    sender.pop('_knownDeliveryRequests', None)
    if sender.get('error') or not sender.get('toolCoverage'):
        delivery_gaps.append('本轮发送来源缺失；不是交付健康')
    proven_requests = set()
    for proof in out.values():
        path = proof.get('path', '')
        if path.startswith('原微信工具:'):
            pair = path.split(':', 1)[1].split('/', 1)
            if len(pair) == 2:
                proven_requests.add(tuple(pair))
    delivery_health = build_health(items=items, seeds=delivery_seeds, jobs=delivery_jobs, gaps=delivery_gaps, observed_at=time.time(), previous=old.get('deliveryHealth'), proven_requests=proven_requests)
    from monitor_consistency import guard_deliveries, summarize
    delivery_health = guard_deliveries(delivery_health, delivery_jobs, out)
    sender = attach_health(sender, delivery_health, delivery_jobs, out, when, source, PEERS)
    (receipt_cache, receipt_store_gaps) = remember_receipts(delivery_health, delivery_jobs, out, {'version': 1, 'entries': receipt_entries})
    newcache['_verifiedDeliveryReceipts'] = receipt_cache
    delivery_health['coverage']['gaps'] += receipt_store_gaps
    delivery_health['coverage']['retainedReceiptComponents'] = len(receipt_cache['entries'])
    delivery_health['coverage']['retainedObservationGaps'] = len(retained_gaps)
    for s in sender['items']:
        for n in items:
            if n['employee'] == s['employee'] and s['id'] in n['origin'] + n['next'] + n['thought']:
                s['relatedItemIds'].append(n['id'])
    modes = read_modes(out, when)
    try:
        observation = system_observation(out, when)
    except Exception:
        observation = old.get('observation')
    discovery['consistency'] = summarize(roles, people, items, delivery_health)
    snapshot['workOverview'] = {'version': 1, 'sampledAt': when, 'employees': people, 'items': items, 'sending': sender, 'modes': modes, 'discovery': discovery, 'observation': observation, 'deliveryHealth': delivery_health, 'readOnly': True}
    if sender.get('toolCoverage', {}).get('policyFormatVersion') == 2:
        agreement = '当前工具Policy v2：client只记作者与业务，不是逐对象/动作许可。旧岗位原文中的只文字、待文件权限等不作为当前许可；具体任务、暂停、隐私和实际交付仍分别核。'
        ref = source(out, '当前微信工具Policy语义', agreement, when, '当前工具Policy v2与旧约定的区别', '正常只读status取得worker.policyFormatVersion=2；配置解除不等业务已交')
        for profile in snapshot.get('profiles', {}).values():
            profile['capabilities'] = [v for v in profile.get('capabilities', []) if v.get('label') != '当前微信工具Policy']
            profile['capabilities'].append({'label': '当前微信工具Policy', 'agreement': agreement, 'evidence': [{'id': ref, 'quote': agreement}]})
            if ref not in profile.setdefault('sourceIds', []):
                profile['sourceIds'].append(ref)
    from delivery_obligations import collect as collect_obligations, validate as validate_obligations
    try:
        obligations = collect_obligations(roles, people, items, out, delivery_jobs, when, time.time(), policy_format_version=sender.get('toolCoverage', {}).get('policyFormatVersion'))
        validate_obligations(obligations, {p['id']: p['threadId'] for p in people}, out)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        obligations = {'version': 1, 'observedAt': time.time(), 'coverage': {'bounded': True, 'gaps': ['outside_explicit_sources', 'source_read_or_format']}, 'rows': []}
    snapshot['workOverview']['deliveryObligations'] = obligations
    atomic_json(cachepath, newcache)
    return (snapshot, out)
