"""Read the existing AUP sender's inspect/read surface, never status or assignment.

This is an adapter in the existing sampler, not an employee registry or a service.
Recent public finals are source statements, never independent delivery receipts.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import datetime, json, re, sys
from pathlib import Path
from live_core import checked_path, stable_note
SID = _install.identity('monitor.sender_runtime.SID')
ROUTES = _install.path('monitor.sender_runtime.ROUTES')
ENDPOINT = str(_install.path('monitor.sender_runtime.path_d7f73245'))
UUID = re.compile('[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\\Z')
SOURCE = 'AUP正式wechat_sender inspect/read（最近8回合，不含完整收件）'

def validate_route(routes):
    route = routes.get('routes', {}).get(SID, {})
    if not SID or routes.get('version') != 1 or any((route.get(k) != v for (k, v) in {'host': 'aup', 'endpoint': ENDPOINT, 'stage': 'active', 'oldMac': 'archived-paused'}.items())):
        raise ValueError('sender route not the existing active AUP owner')

def project(routes, inspect, read, when):
    from work_observer import public_text
    validate_route(routes)
    owner = inspect.get('owner', {})
    if inspect.get('id') != SID or read.get('threadId') != SID or owner.get('threadId') != SID or (owner.get('host') != 'aup') or (owner.get('phase') != 'active') or (owner.get('macExecution') != 'archived-paused') or (inspect.get('cwd') != str(_install.path('monitor.sender_runtime.path_c63a33ea'))):
        raise ValueError('AUP sender identity mismatch')
    turns = read.get('turns')
    queued = inspect.get('queued')
    status = inspect.get('status', {}).get('type')
    if not isinstance(turns, list) or len(turns) > 8 or type(queued) != int or (queued < 0) or (status not in ['active', 'idle', 'notLoaded', 'systemError']):
        raise ValueError('invalid bounded sender metadata')
    safe = []
    for t in turns:
        if not isinstance(t, dict) or not UUID.fullmatch(str(t.get('id', ''))) or t.get('status') not in ['completed', 'inProgress', 'failed', 'interrupted'] or (not isinstance(t.get('final'), list)) or (len(t['final']) > 8) or any((not isinstance(v, str) or len(v) > 64000 for v in t['final'])):
            raise ValueError('invalid public sender turn')
        safe.append({'id': t['id'], 'status': t['status'], 'final': [public_text(v, 2500) for v in t['final']]})
    if len({t['id'] for t in safe}) != len(safe):
        raise ValueError('duplicate sender turns')
    return {'threadId': SID, 'host': 'aup', 'sampledAt': when, 'status': status, 'queueCount': queued, 'queueMore': queued > 0, 'turns': safe, 'error': None}

def read_runtime(route_path=ROUTES, call=None):
    path = Path(route_path)
    checked_path(path, [path.parent])
    (raw, _) = stable_note(path)
    if len(raw) > 16000:
        raise ValueError('route too large')
    routes = json.loads(raw)
    validate_route(routes)
    if call is None:
        sys.path.insert(0, str(_install.path('monitor.sender_runtime.path_45fd6e72')))
        from wechat_sender import call
    return project(routes, call({'op': 'inspect'}), call({'op': 'read', 'limit': 8}), datetime.datetime.now(datetime.timezone.utc).isoformat())

def inbox(role, out, when):
    from work_observer import source
    meta = role.get('nativeMetadata') or {}
    turns = meta.get('turns', [])
    gap = 'AUP正式inspect/read仅提供最近8回合公开结果与队列数量，未提供当前原始输入、排队正文或全历史；不是零业务待办。'
    if meta.get('error'):
        gap = 'AUP正式读取本轮不可读；不回退已归档Mac副本。' + gap
    rows = []
    for t in turns:
        final = '\n'.join(t.get('final', []))
        if final:
            sid = source(out, 'AUP正式发送对话:' + SID + '/' + t['id'], final, when, '中央发送 · AUP公开结果', '原正式read可见答复；不是监控独立验收送达或业务闭环')
            rows.append((sid, final))
    if rows:
        gap += ' 最近公开工作：' + rows[0][1][:230]
    return {'employee': 'sender', 'items': [], 'queueCount': meta.get('queueCount') if meta.get('queueCount') == 0 else None, 'readQueueCount': 0, 'historyThreadId': SID, 'runtimeState': 'unknown', 'sampledAt': meta.get('sampledAt', when), 'error': None, 'gap': gap}
