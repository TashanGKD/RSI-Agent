"""Read employee-native input order and the substance of explicitly linked send briefs.

No models, worker input, queue writes, external fetches or media copies.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import datetime, json, re
from pathlib import Path
from live_core import checked_path, stable_note, digest, RESTRICTED
DOC_ROOTS = _install.path_list('monitor.inbox_reader', 'DOC_ROOTS')
PEER_PATTERN = '(?:[0-9]{8,}@chatroom|wxid_[A-Za-z0-9_-]+)'

def read_document(path, roots=None):
    allowed = roots or DOC_ROOTS
    p = checked_path(Path(path), allowed)
    relative = next((p.relative_to(r.resolve()).parts for r in allowed if r.resolve() == p or r.resolve() in p.parents), ())
    if p.suffix.lower() not in ['.txt', '.md'] or re.search('(?i)password|credential|login|(?:^|[._-])secrets?(?:[._-]|$)|access_token|refresh_token|auth\\.json|口令|密码|验证码', p.name) or 'private' in relative or any((x in str(p).lower() for x in RESTRICTED)):
        raise ValueError('not an approved business text reference')
    if p.stat().st_size > 64000:
        raise ValueError('reference too large')
    (text, _) = stable_note(p)
    return text

def references(text):
    return list(dict.fromkeys(re.findall(str(_install.path('monitor.inbox_reader.path_341d3451')), text) + re.findall('(?<=\\s)/private/var/[^\\n\\s]+?\\.(?:md|txt)\\b', text)))

def _paths(text):
    return list(dict.fromkeys(references(text) + re.findall('/(?:private/)?(?:var|tmp)/[^\\n\\s，；。`\\"\\\')）]+?\\.(?:md|txt)\\b', text)))

def clean_sentence(s):
    from work_observer import public_text
    s = public_text(s, 12000)
    s = re.sub('/[^\\s，；。`\\"\\\']+\\.(?:md|txt|json)', '', s)
    s = re.sub('(?<![A-Za-z0-9])[a-z][a-z0-9]*(?:[-_][A-Za-z0-9]+){2,}(?![A-Za-z0-9])', '', s)
    s = re.sub('(?i)(?:SHA(?:256)?|MD5)\\s*[=:：]?\\s*[a-f0-9]{16,}', '', s)
    s = re.sub('(?<![0-9])[0-9]{15,}(?![0-9])', '', s)
    s = s.replace('[Mac原件]', '')
    s = re.sub('[#*`]+', '', s)
    s = re.sub('^(?:发送交办|发件单|消息交办)[，,：:\\s]*', '', s)
    s = re.sub('\\s+', ' ', s).strip(' 【】[]，,：:；;-')
    return s

def meaningful_summary(request, body='', attachments=()):
    if request.lstrip().startswith('<heartbeat>'):
        return '定时工作接续'
    if request.lstrip().startswith('<send_user_message_question_reply>'):
        try:
            payload = json.loads(request.split('>', 1)[1].rsplit('</send_user_message_question_reply>', 1)[0])
            entry = payload[0]
            question = str(entry.get('question', ''))
            answer = str(entry.get('answer', ''))
            if re.search('(?i)密码|口令|验证码|password|api.?key|access_token|refresh_token', question + ' ' + answer):
                return '敏感确认回复（内容不展示）'
            return '确认回复：' + clean_sentence(answer)[:60] + '；' + clean_sentence(question)[:80]
        except (ValueError, TypeError, IndexError, KeyError):
            return '确认回复（具体文字未取得）'
    names = list(dict.fromkeys((re.sub('[_ ]+', ' ', Path(a).stem) for a in attachments if a)))
    if names:
        names = list(dict.fromkeys(names))
        return '、'.join(names[:2])[:110] + ('（' + ('图片＋文件' if any((Path(a).suffix.lower() in ['.png', '.jpg', '.jpeg'] for a in attachments)) and any((Path(a).suffix.lower() not in ['.png', '.jpg', '.jpeg'] for a in attachments)) else '附件交付') + '）')
    candidates = []
    for (prefer, raw) in [(True, body), (False, request)]:
        for (n, line) in enumerate(re.split('[。\\n]+', raw)):
            s = clean_sentence(line)
            if len(s) < 5 or re.search('自然新来源|真实核后|原关系进展定稿|^(?:无|不|禁止|严禁|发前|unknown|独立原生|SHA|request_id)|^\\[来源|^【?(?:来源|真实群ID|请求ID|消息ID|发信人)', s):
                continue
            if not prefer and re.search('账号|scope|timer|client|权限|绑定|守护|仅.*队列|工具维护', s):
                continue
            score = (30 if prefer else 0) + min(len(s), 75) / 10 - n * 1.5
            if re.search('[A-Z][0-9]{2,}|钱学森|地点|会场|方案|报告|课程|海报|讲座|会议|PPT|Word|UI', s):
                score += 7
            if s in ['收到', '已收到', '好的', '继续'] or s.startswith(('发送交办', '原关系')):
                continue
            candidates.append((score, s))
    if not candidates:
        return '交办内容待提取'
    best = max(candidates, key=lambda x: x[0])[1]
    first = clean_sentence(re.split('[。\\n]+', body)[0]) if body else ''
    if first and len(first) < 38 and (first != best) and (not first.startswith(('我会', '我来', '收到', '好的', '先'))):
        best = first + '；' + best
    return best[:130] + ('…' if len(best) > 130 else '')

def describe_request(text, roots=None):
    from work_observer import public_text
    allowed = roots or DOC_ROOTS
    documents = []
    errors = []
    for path in _paths(text)[:4]:
        try:
            documents.append((path, read_document(path, allowed)))
        except (ValueError, OSError):
            errors.append(Path(path).name)
    for (path, body) in list(documents):
        for nested in _paths(body)[:3]:
            if any((p == nested for (p, _) in documents)):
                continue
            if Path(nested).suffix != '.txt':
                continue
            try:
                documents.append((nested, read_document(nested, allowed)))
            except (ValueError, OSError):
                errors.append(Path(nested).name)
    peers = []
    for raw in [*(d[1] for d in documents), text]:
        peers += re.findall('(?:→|\\bpeer\\s*[=:：]|目标\\s*[=:：])\\s*[`\\"\\\']?(' + PEER_PATTERN + ')', raw)
    peer = peers[0] if peers and len(set(peers)) == 1 else None
    if not peers:
        allpeers = re.findall(PEER_PATTERN, text + '\n' + '\n'.join((x[1] for x in documents)))
        peer = next(iter(set(allpeers))) if len(set(allpeers)) == 1 else None
    frozen = [x for x in documents if Path(x[0]).suffix == '.txt']
    body = public_text(frozen[0][1], 10000) if frozen else ''
    combined = '\n'.join((x[1] for x in documents)) or text
    attachment_lines = [line for line in combined.splitlines() if re.search('send_image|send_file|附件[：:]|原文件[：:]|待发文件[：:]', line) and (not re.search('不发|不要发|不传|严禁|内部报告|验收截图', line))]
    attachments = list(dict.fromkeys((Path(x).name for x in re.findall(str(_install.path('monitor.inbox_reader.path_9a2cca3c')), '\n'.join(attachment_lines), re.I))))
    request = public_text(combined, 10000)
    return {'peer': peer, 'body': body or None, 'attachments': attachments[:15], 'summary': meaningful_summary(request, body, attachments), 'requestExcerpt': request, 'referencePaths': [p for (p, _) in documents], 'referenceErrors': errors}

def queue_rows(rows):
    return [{**r, 'queuePosition': i + 1} for (i, r) in enumerate(sorted(rows, key=lambda x: (x['queue_order'], x['created_at_ms'], x['id'])))]

def visible_activity(rows):
    labels = []
    seen = set()
    states = {'inProgress': '进行中', 'running': '进行中', 'completed': '已结束', 'failed': '失败', 'declined': '未执行'}
    for j in rows:
        kind = j.get('type')
        if kind == 'subAgentActivity':
            name = Path(j.get('agentPath') or '').name
            if not re.fullmatch('[A-Za-z0-9_-]{1,80}', name) or name in seen:
                continue
            seen.add(name)
            name = name.replace('_', ' ').capitalize()
            state = {'completed': '已结束', 'spawned': '已启动', 'interacted': '有交流记录'}.get(j.get('kind'), '有活动记录')
            labels.append('协作 ' + name + '：' + state)
        elif kind in ['commandExecution', 'fileChange', 'imageView', 'webSearch', 'mcpToolCall']:
            if kind in seen:
                continue
            seen.add(kind)
            label = {'commandExecution': '执行命令', 'fileChange': '更新文件', 'imageView': '查看图像', 'webSearch': '网页检索', 'mcpToolCall': '调用工具'}[kind]
            status = j.get('status')
            labels.append(label + '：' + states.get(status if isinstance(status, str) else None, '有公开记录'))
    return '；'.join(labels[:3])

def read_employee_inbox(role, out, when):
    if (role.get('nativeMetadata') or {}).get('host') == 'aup':
        from sender_runtime import inbox
        return inbox(role, out, when)
    from work_observer import ro, source, public_text, text_input
    from collect import bj
    ident = role['threadId']
    history = role['historyThreadId']
    candidates = [history]
    cut = None
    if role['id'] == 'research-secretary':
        from research_secretary_scope import boundary
        cut = boundary()
    if not role['channels'] and (not role.get('historyReference')):
        with ro('state_5.sqlite') as c:
            r = c.execute('select rollout_path from threads where id=?', (ident,)).fetchone()
            if r:
                candidates += re.findall('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', Path(r['rollout_path']).name)[-1:]
    candidates = list(dict.fromkeys(candidates))
    metadata = role.get('nativeMetadata')
    latest_native = None
    read_gap = role.get('historyMappingGap')
    if metadata and metadata.get('threadId') == ident and (not metadata.get('error')) and metadata.get('turns'):
        latest_native = sorted(enumerate(metadata['turns']), key=lambda x: (x[1].get('startedAt') or 0, -x[0]), reverse=True)[0][1]['id']
    with ro('queue_1.sqlite') as c:
        total = c.execute('select count(*) from queued_items where thread_id=?', (ident,)).fetchone()[0]
        queued = queue_rows([dict(r) for r in c.execute('select id,queue_order,created_at_ms,payload_json from queued_items where thread_id=? order by queue_order,created_at_ms limit 150', (ident,))])
    with ro('thread_history_1.sqlite') as c:
        turn = c.execute('select thread_id,turn_id,status,started_at,rollout_ordinal from thread_turns where thread_id in (' + ','.join(('?' for _ in candidates)) + ')' + (' and turn_id=?' if latest_native else '') + ' order by started_at desc,rollout_ordinal desc limit 1', candidates + ([latest_native] if latest_native else [])).fetchone()
        if cut and turn:
            from research_secretary_scope import after_birth
            if not after_birth(turn, cut):
                raise ValueError('inherited parent turn excluded from child work')
        if cut:
            queued = [q for q in queued if q['created_at_ms'] >= cut['startedAt'] * 1000]
            total = len(queued)
        if latest_native and (not turn):
            read_gap = '最新原生回合尚未同步到已核历史；当前内容待核，不以旧回合替代'
        active = []
        progress = ''
        progress_kind = 'none'
        if turn and turn['status'] == 'inProgress':
            active = [dict(r) for r in c.execute("select item_id as id,item_json as payload_json,created_at_ms from thread_items where thread_id=? and turn_id=? and item_type='userMessage' order by created_at_ms asc limit 31", (turn['thread_id'], turn['turn_id']))]
            if len(active) > 30:
                active = active[:30]
                read_gap = '当前回合输入超过30项，只展示前30项；未覆盖补充仍待核'
            for r in c.execute("select item_json from thread_items where thread_id=? and turn_id=? and item_type='agentMessage' order by created_at_ms desc limit 4", (turn['thread_id'], turn['turn_id'])):
                msg = json.loads(r[0])
                progress = public_text(msg.get('text', ''), 800)
                if progress:
                    progress_kind = 'public_response'
                    break
            if not progress:
                select = "select json_object('type',json_extract(item_json,'$.type'),'status',json_extract(item_json,'$.status'),'kind',json_extract(item_json,'$.kind'),'agentPath',json_extract(item_json,'$.agentPath')) as item_json from thread_items where thread_id=? and turn_id=? and "
                agents = [json.loads(r['item_json']) for r in c.execute(select + "item_type='subAgentActivity' order by max(rollout_ordinal,coalesce(updated_at_ordinal,0)) desc limit 8", (turn['thread_id'], turn['turn_id']))]
                tools = [json.loads(r['item_json']) for r in c.execute(select + "item_type in ('commandExecution','fileChange','imageView','webSearch','mcpToolCall') order by max(rollout_ordinal,coalesce(updated_at_ordinal,0)) desc limit 4", (turn['thread_id'], turn['turn_id']))]
                visible = agents + tools
                progress = visible_activity(visible)
                if progress:
                    progress_kind = 'visible_activity'
    rows = []
    seen_inputs = set()
    for (phase, inputs) in [('processing', active[:1]), ('queued', queued)]:
        for r in inputs:
            payload = json.loads(r['payload_json'])
            raw = text_input(payload)
            if phase == 'processing' and len(active) > 1:
                raw = '\n\n'.join((text_input(json.loads(part['payload_json'])) for part in active))
            inner = payload.get('UserInput', payload)
            client_id = inner.get('client_id') or payload.get('clientId')
            stable_id = ident + '/' + (client_id if isinstance(client_id, str) and re.fullmatch('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', client_id) else r['id'])
            if stable_id in seen_inputs:
                continue
            seen_inputs.add(stable_id)
            restricted = any((w in raw.lower() for w in RESTRICTED))
            info = describe_request(raw) if not restricted else {'summary': '受限交办，仅保留处理位置', 'body': None, 'requestExcerpt': '此项内容不在监控展示范围', 'referencePaths': []}
            if phase == 'processing' and len(raw) > 9000:
                read_gap = '本回合原输入超过展示长度，详情保留有界摘录；不能当已完整展示'
            summary = '定时接续 · ' + role['name'] if raw.lstrip().startswith('<heartbeat>') else info['summary']
            body = public_text(raw, 9000) if not restricted else info['requestExcerpt']
            if summary == '交办内容待提取' and phase == 'processing' and progress:
                summary = meaningful_summary(progress)
            sid = source(out, '原生收件:' + ident + '/' + r['id'], body or '原生输入未取得可展示文字，保留处理位置', when, role['name'] + ' · ' + ('当前处理' if phase == 'processing' else '等待接手'), '原生可见交办；排队不等于已接手，处理不等于业务完成')
            proof = None
            if phase == 'processing' and progress and (not restricted):
                proof = source(out, '原生公开活动:' + turn['thread_id'] + '/' + turn['turn_id'], progress, when, role['name'] + ' · ' + ('公开答复' if progress_kind == 'public_response' else '公开工具/协作活动'), '只读当前回合公开条目；不含隐藏推理或命令参数，不表示业务已验收')
            rows.append({'id': stable_id, 'employee': role['id'], 'phase': phase, 'queuePosition': r.get('queuePosition', 0), 'nativeQueueOrder': r.get('queue_order'), 'summary': summary, 'requestText': body, 'preparedBody': info.get('body'), 'progress': progress if phase == 'processing' and (not restricted) else '', 'progressKind': progress_kind, 'proofSourceId': proof, 'receivedAt': bj(datetime.datetime.fromtimestamp(r['created_at_ms'] / 1000, datetime.timezone.utc).isoformat()), 'receivedAtMs': r['created_at_ms'], 'startedAt': bj(datetime.datetime.fromtimestamp(turn['started_at'], datetime.timezone.utc).isoformat()) if phase == 'processing' and turn and turn['started_at'] else None, 'sourceId': sid, 'threadId': ident, 'restricted': restricted})
    return {'employee': role['id'], 'items': rows, 'queueCount': total, 'readQueueCount': len(queued), 'historyThreadId': turn['thread_id'] if turn else history, 'runtimeState': turn['status'] if turn else 'unknown', 'sampledAt': when, 'error': read_gap, 'gap': '；'.join(([read_gap] if read_gap else []) + (['队列超过150项，当前只展示前150项'] if total > 150 else [])) or None}
