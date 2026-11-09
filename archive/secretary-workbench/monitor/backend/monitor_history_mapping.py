"""Observer cache reference: exact native turn -> local history, never employee routing.
The caller supplies metadata from that user-facing chat, not directory-name guesses.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import hashlib, json, re, sqlite3
UUID = re.compile('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\\Z')

def checksum(ref):
    return hashlib.sha256(json.dumps({k: v for (k, v) in ref.items() if k != 'checksum'}, sort_keys=True).encode()).hexdigest()

def locate(turns):
    from work_observer import ro
    if not isinstance(turns, list) or not 1 <= len(turns) <= 3 or any((not UUID.fullmatch(str(t)) for t in turns)):
        raise ValueError('bounded exact native turns required')
    with ro('thread_history_1.sqlite') as c:
        rows = c.execute('select thread_id,turn_id from thread_turns where turn_id in (' + ','.join(('?' for _ in turns)) + ') limit 10', turns).fetchall()
    if {r['turn_id'] for r in rows} != set(turns) or len({r['thread_id'] for r in rows}) != 1 or any((not UUID.fullmatch(str(r['thread_id'])) for r in rows)):
        raise ValueError('native turn history absent or ambiguous')
    return rows[0]['thread_id']

def register_mapping(thread, previous, native_turns, source):
    if not UUID.fullmatch(thread) or not UUID.fullmatch(previous) or (not source):
        raise ValueError('mapping scope')
    history = locate(native_turns)
    r = {'threadId': thread, 'historyThreadId': history, 'previousHistoryThreadIds': [previous], 'nativeTurnIds': native_turns, 'metadataSource': source}
    r['checksum'] = checksum(r)
    return r

def resolve_mapping(thread, declared, ref):
    try:
        if ref.get('threadId') != thread or ref.get('checksum') != checksum(ref) or declared not in ref.get('previousHistoryThreadIds', []) + [ref.get('historyThreadId')]:
            raise ValueError('history reference scope mismatch')
        from sender_runtime import SID, SOURCE
        if thread == SID and ref.get('metadataSource') == SOURCE and (ref['historyThreadId'] == SID):
            return (SID, 'AUP历史身份待本轮正式inspect/read重核；不读Mac归档')
        if locate(ref['nativeTurnIds']) != ref['historyThreadId']:
            raise ValueError('history reference conflict')
        return (ref['historyThreadId'], None)
    except (ValueError, KeyError, TypeError, sqlite3.Error):
        return (declared, '历史映射依据缺失或冲突；未把空结果当无工作')

def reconcile_native(role, metadata, previous):
    """One canonical resolver for registered and unregistered roles, rechecked each sample."""
    declared = role['historyThreadId']
    thread = role['threadId']
    fallback = declared
    gap = None
    from sender_runtime import SID, SOURCE
    if thread == SID and isinstance(metadata, dict) and (metadata.get('host') == 'aup'):
        if metadata.get('threadId') != SID or metadata.get('error'):
            return (SID, previous, 'AUP正式身份本轮未核实；不回退Mac归档')
        old = previous if previous and previous.get('threadId') == SID and (previous.get('checksum') == checksum(previous)) else {}
        ref = {'threadId': SID, 'historyThreadId': SID, 'previousHistoryThreadIds': list(dict.fromkeys([declared] + old.get('previousHistoryThreadIds', [])))[-12:], 'nativeTurnIds': [t['id'] for t in metadata.get('turns', [])[:3]], 'metadataSource': SOURCE}
        ref['checksum'] = checksum(ref)
        return (SID, ref, None)
    if previous:
        (fallback, gap) = resolve_mapping(thread, declared, previous)
    if not isinstance(metadata, dict) or metadata.get('threadId') != thread or metadata.get('error'):
        return (fallback, previous, '原生身份元数据未核实；沿已知映射读取并保留缺口')
    turns = metadata.get('turns', [])
    if not turns:
        return (fallback, previous, '尚无原生回合可校验，不据此判无工作')
    latest = sorted(enumerate(turns), key=lambda x: (x[1].get('startedAt') or 0, -x[0]), reverse=True)[0][1]
    try:
        ref = register_mapping(thread, declared, [latest['id']], '本轮原生thread/read + turns/list准确turn反查')
        if previous and previous.get('threadId') == thread and (previous.get('checksum') == checksum(previous)):
            ref['previousHistoryThreadIds'] = list(dict.fromkeys(previous.get('previousHistoryThreadIds', []) + [previous['historyThreadId'], declared]))[-12:]
            ref['checksum'] = checksum(ref)
        return (ref['historyThreadId'], ref, None)
    except (ValueError, KeyError, TypeError, sqlite3.Error):
        return (fallback, previous, '本轮最新原生回合尚未唯一同步到历史；不以旧回合当当前工作')
