"""Fixed scope and the verified first adoption of this explicitly created child role."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
from pathlib import Path
THREAD = _install.identity('monitor.research_secretary_scope' + '.' + 'THREAD')
ROOT = _install.path('monitor.research_secretary_scope.ROOT')
INITIAL_TURN = _install.identity('monitor.research_secretary_scope' + '.' + 'INITIAL_TURN')
INITIAL_MARKER = _install.setting('monitor.research_secretary_scope', 'INITIAL_MARKER', '')
STARTED_AT = _install.setting('monitor.research_secretary_scope', 'STARTED_AT', 0)
PEER = _install.identity('monitor.research_secretary_scope' + '.' + 'PEER')
ROOM = _install.identity('monitor.research_secretary_scope' + '.' + 'ROOM')
ACTIONS = {'send_text', 'send_image', 'send_file', 'reply', 'forward'}

def in_scope(peer, action):
    return __import__('send_tool_observer').observed_delivery(peer, action)

def boundary():
    if not THREAD or not INITIAL_TURN or not INITIAL_MARKER or not STARTED_AT:
        raise ValueError('configure a verified role boundary before reading')
    from work_observer import ro
    with ro('thread_history_1.sqlite') as connection:
        rows = connection.execute('select thread_id,started_at,rollout_ordinal from thread_turns where turn_id=?', (INITIAL_TURN,)).fetchall()
        if len(rows) != 1 or rows[0]['thread_id'] != THREAD or rows[0]['started_at'] != STARTED_AT:
            raise ValueError('child adoption boundary unavailable')
        marker = connection.execute("select 1 from thread_items where thread_id=? and turn_id=? and item_type='userMessage' and instr(item_json,?)>0 limit 1", (THREAD, INITIAL_TURN, INITIAL_MARKER)).fetchone()
    if not marker:
        raise ValueError('child adoption marker not verified')
    return {'startedAt': STARTED_AT, 'ordinal': rows[0]['rollout_ordinal']}

def after_birth(turn, cut):
    return bool(turn and turn['started_at'] >= cut['startedAt'] and (turn['rollout_ordinal'] >= cut['ordinal']))

def public_metadata(snapshot, sources):
    """Limit this role's online projection to metadata, preserving the local originals."""
    metadata_text = '科研秘书岗位记录的元数据视图，原文保存在Mac。'
    redacted = {ident for (ident, source) in sources.items() if source.get('path', '').startswith(str(ROOT) + '/') or source.get('path', '').startswith('原生收件:' + (THREAD or '__unconfigured__') + '/') or source.get('path', '').startswith('原生公开活动:' + (THREAD or '__unconfigured__') + '/')}
    projected_sources = dict(sources)
    for ident in redacted:
        projected_sources[ident] = dict(sources[ident], text=metadata_text, path='科研秘书本地岗位记录', label='科研秘书元数据', role='原件保存在Mac，在线仅显示元数据')
    work = snapshot.get('workOverview', {})
    for incident in work.get('deliveryHealth', {}).get('incidents', []):
        if incident.get('client') == 'research_secretary':
            for ident in incident.get('evidenceRefs', []):
                source = sources.get(ident, {})
                if source.get('path', '').startswith('交付组件:'):
                    redacted.add(ident)
                    projected_sources[ident] = dict(source, text=metadata_text, path='科研秘书本地交付记录', label='科研秘书交付元数据', role='原件保存在Mac，在线仅显示元数据')
    for task in [*snapshot.get('tasks', []), *work.get('items', [])]:
        if task.get('employee') != 'research-secretary':
            continue
        task.update(title='科研材料准备', origin='本人交办的本岗事项', goal='准备科研材料并核实交付', thought='原判断保存在本地工作本', next='按本岗原工作本接续', pending='按本岗原工作本接续', time='按原事项时间核对', originalRequest=None, sourceLabel='本岗工作记录', originKind='本岗工作本元数据')
        for change in task.get('trajectory', []):
            change['event'] = '本岗工作记录更新'
    for employee in snapshot.get('employees', []):
        if employee.get('id') == 'research-secretary':
            employee.update(current='科研材料准备，当前状态见本岗事项', notebook='本岗独立工作本，原件在Mac', gap='详细来源覆盖保存在本机')
    for employee in work.get('employees', []):
        if employee.get('id') != 'research-secretary':
            continue
        employee.pop('modeNotes', None)
        for item in employee.get('inbox', {}).get('items', []):
            item.update(summary='本岗科研材料交办', requestText='原文保存在Mac', preparedBody=None, progress='公开活动的详细内容保存在Mac')
    for message in work.get('sending', {}).get('items', []):
        if message.get('employee') == 'research-secretary':
            message.update(title='科研秘书发件记录', body=None, summary='本岗发件元数据', destination='科研秘书专属群' if message.get('peer') == ROOM else '本人私聊' if message.get('peer') == PEER else message.get('destination') or message.get('peer') or '目标待核', reason='详细回执保存在Mac', attachments=['本地附件' for _ in message.get('attachments', [])])
    for incident in work.get('deliveryHealth', {}).get('incidents', []):
        if incident.get('client') == 'research_secretary':
            incident['businessTitle'] = '科研秘书交付事项'
    profile = snapshot.get('profiles', {}).get('research-secretary')
    if profile:
        profile['purpose'] = '科研材料准备与交付'
        for statement in profile.get('responsibilities', []):
            statement['text'] = '负责本岗科研材料的核实、准备与交付接续'
        for resource in profile.get('resources', []):
            resource['note'] = '本岗原件保存在Mac，按实际工作接续'
        profile.get('lifecycle', {})['note'] = '工作与接续阶段按本岗实际记录核对'

    def fix_quotes(value):
        if isinstance(value, dict):
            if value.get('id') in redacted and 'quote' in value:
                value['quote'] = metadata_text
            for child in value.values():
                fix_quotes(child)
        elif isinstance(value, list):
            for child in value:
                fix_quotes(child)
    fix_quotes(snapshot)
    return projected_sources

def recorded_requests(text):
    """Association hints from this child's explicitly cited normal delivery results only.
    Public exact job reads still prove identity and actual native delivery.
    """
    import json, re
    from live_core import checked_path, stable_note
    paths = re.findall('(?<![A-Za-z0-9_.:/-])(work/(?:[A-Za-z0-9_一-龥.-]+/)*(?:RESULT|dispatch-result|manifest)\\.json)', text)
    for short in re.findall('(?<![A-Za-z0-9_.:/-])([A-Za-z0-9_.-]+/(?:RESULT|dispatch-result|manifest)\\.json)', text):
        directory = short.split('/')[0]
        anchors = set(re.findall('work/(?:[A-Za-z0-9_.-]+/)*' + re.escape(directory) + '(?![A-Za-z0-9_.-])', text))
        if len(anchors) == 1:
            paths.append(next(iter(anchors)) + '/' + short.split('/')[1])
    out = []
    for relative in list(dict.fromkeys(paths))[:8]:
        try:
            path = checked_path(ROOT / relative, [ROOT])
            if any((x.lower() in ['private', '.private', '.runtime'] for x in path.relative_to(ROOT).parts)):
                continue
            (raw, _) = stable_note(path)
            value = json.loads(raw)
            rows = value.get('jobs', []) if isinstance(value, dict) else []
            if value.get('client') == 'research_secretary' and __import__('send_tool_observer').observed_delivery(value.get('peer'), 'send_text'):
                rows = [value] + value.get('items', [])
            for row in rows[:100]:
                if not isinstance(row, dict):
                    continue
                rid = row.get('request_id', '')
                if not isinstance(rid, str) or not re.fullmatch('research[-_]secretary-[A-Za-z0-9._-]{4,76}', rid):
                    continue
                if row.get('id'):
                    from send_tool_observer import project
                    if project(row) is None:
                        continue
                else:
                    accepted = row.get('state') in ['accepted', 'succeeded'] and row.get('nativeAccepted') is True and bool(re.fullmatch('[1-9][0-9]{0,19}', str(row.get('serverId', ''))))
                    frozen = path.name == 'manifest.json' and row.get('state') == 'frozen_not_admitted_pending_existing_writer_target' and (row.get('batch_id') == rid) and bool(re.fullmatch('[a-f0-9]{64}', str(row.get('textSHA256', '')))) and (row.get('client') == 'research_secretary') and __import__('send_tool_observer').observed_delivery(row.get('peer'), 'send_text')
                    if not (accepted or frozen):
                        continue
                if rid not in out:
                    out.append(rid)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return out[:30]
