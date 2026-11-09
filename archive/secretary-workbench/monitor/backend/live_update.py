"""One non-overlapping read-only incremental monitor cycle. --execute is required."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, copy, datetime, fcntl, json, os, subprocess, time, uuid
from pathlib import Path
from collect import ROOT, PRIVATE, IDS, bj
from live_core import atomic_json, digest, merge_changes, publish, unique
from live_sources import baseline_state, read_messages, read_notes
from live_analysis import analyze
from build_snapshot import field, plain, short
LIVE = ROOT / 'live'
STATE = PRIVATE / 'live-state.json'
NODE = _install.setting('monitor.live_update','NODE','node')

def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def initial():
    base = PRIVATE / 'live-baseline'
    base.mkdir(exist_ok=True)
    for file in ['snapshot.json', 'sources.json']:
        if not (base / file).exists():
            atomic_json(base / file, json.loads((ROOT / 'web/public' / file).read_text()))
    runtime = json.loads((PRIVATE / 'runtime.json').read_text())
    return {'employees': baseline_state(), 'cycles': 0, 'runtimeTurnIds': {n: [t['id'] for t in e['turns'] if t.get('durationMs') is not None and t.get('status') in ['completed', 'failed', 'interrupted']] for (n, e) in runtime['employees'].items()}}

def current_data():
    if (LIVE / 'live.json').exists():
        p = json.loads((LIVE / 'live.json').read_text())
        folder = LIVE / 'versions' / p['revision']
    else:
        folder = PRIVATE / 'live-baseline'
    return (json.loads((folder / 'snapshot.json').read_text()), json.loads((folder / 'sources.json').read_text()))
ORG_IDS = _install.setting('monitor.live_update', 'ORG_IDS', {})

def structured_changes(name, note_state, sources):
    out = []
    for (path, n) in note_state.items():
        text = n.get('text', '')
        if Path(path).name == 'CURRENT.md' or not field(text, '事情'):
            continue
        matches = [s for s in sources.values() if s.get('path') == path and s.get('text') == text]
        if matches:
            out.append((path, text, [max(matches, key=lambda r: r['time'])]))
    return out

def update_notebooks(tasks, name, changes):
    out = copy.deepcopy(tasks)
    for (path, text, records) in changes:
        if Path(path).name == 'CURRENT.md' or not records:
            continue
        head = text.split('<!-- secretary-work-current:end -->')[0].split('<!-- employee-work:end -->')[0]
        if not field(head, '事情'):
            continue
        ident = ORG_IDS.get(Path(path).name[:2], 'task-' + digest(path)[:14]) if name == 'organoid' else 'task-' + digest(path)[:14]
        old = next((t for t in out if t['id'] == ident), None)
        t = copy.deepcopy(old) if old else {'id': ident, 'employee': name, 'kind': 'notebook', 'trajectory': [], 'evidence': []}
        t['kind'] = 'notebook'
        state = field(head, '现在怎么样') or '待核实'
        nxt = plain(field(head, '下一步'))
        t.update(title=field(head, '事情'), state=state, pending='无' if state in ['已办好', '已完成', '不做了', '不用管了'] else '等待：' + nxt if state == '等反馈' else nxt, next=nxt, goal=plain(field(head, '这次想做到什么')), origin=plain(field(head, '怎么来的')), thought=plain(field(head, '我的想法')), time=field(head, '时间'), who_owes=('主秘书' if name == 'secretary' else '本员工') if state != '等反馈' else '见笔记等待对象', confidence='原笔记当前摘要')
        source = records[0]
        t['evidence'] = unique(t['evidence'] + [{'id': source['id'], 'quote': short(head, 600)}], ['id', 'quote'])
        if old and any((t.get(k) != old.get(k) for k in ['state', 'pending', 'title'])):
            t['trajectory'] = unique(t['trajectory'] + [{'time': source['time'], 'event': '笔记当前摘要更新：' + state + '；' + nxt, 'source_id': source['id']}], ['time', 'event', 'source_id'])
        if old:
            out[out.index(next((x for x in out if x['id'] == ident)))] = t
        else:
            out.append(t)
    return out

def batches(records, limit=38000):
    batch = []
    size = 0
    for r in records:
        if batch and size + len(r['text']) > limit:
            yield batch
            batch = []
            size = 0
        if len(r['text']) > limit:
            for i in range(0, len(r['text']), limit):
                if batch:
                    yield batch
                    batch = []
                    size = 0
                yield [{**r, 'text': r['text'][i:i + limit]}]
        else:
            batch.append(r)
            size += len(r['text'])
    if batch:
        yield batch

def run_cycle():
    PRIVATE.mkdir(exist_ok=True)
    with (PRIVATE / 'live.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'skipped': 'cycle already active'}
        return _run_locked()

def _run_locked():
    started = utc()
    start = time.monotonic()
    state = None
    if (LIVE / 'live.json').exists():
        revision = json.loads((LIVE / 'live.json').read_text())['revision']
        checkpoint = PRIVATE / 'live-checkpoints' / revision / 'state.json'
        if checkpoint.exists():
            state = json.loads(checkpoint.read_text())
    if state is None:
        state = json.loads(STATE.read_text()) if STATE.exists() else initial()
    (snap, sources) = current_data()
    health = {}
    counts = {}
    newstate = copy.deepcopy(state)
    for name in IDS:
        before = state['employees'][name]
        attempt = utc()
        newstate['employees'][name]['lastAttempt'] = attempt
        try:
            (ms, st, mc) = read_messages(name, before, started)
            (ns, st, changes, nc) = read_notes(name, st, attempt)
            staged_sources = {**sources, **{r['id']: r for r in ms + ns}}
            tasks = update_notebooks(snap['tasks'], name, structured_changes(name, st['notes'], staged_sources))
            records = ms + ([] if name == 'secretary' else [r for r in ns if not field(r['text'], '事情')])
            summary = None
            patchcount = 0
            sources = staged_sources
            snap['tasks'] = tasks
            st.update(lastSuccess=utc(), lastAttempt=attempt, error=None, lastCutoff=started, interpretationMode='source_records_only')
            newstate['employees'][name] = st
            counts[name] = {**mc, **nc, 'patches': patchcount}
            employee = next((e for e in snap['employees'] if e['id'] == name))
            if summary:
                employee['current'] = summary
            elif changes and name == 'secretary':
                active = [t['title'] for t in tasks if t['employee'] == name and t['kind'] != 'history' and (t['state'] in ['进行中', '待推进', '待处理'])]
                employee['current'] = '；'.join(active[:3]) or '当前工作本已读取，见下方事项。'
            employee['coverage']['messages'] += len(ms)
            employee['coverage']['notes'] = len(st['notes'])
            employee['coverage']['files'] = len(st['files'])
            if ms:
                employee['coverage']['last'] = max((r['time'] for r in ms))
                employee['lastActivity'] = employee['coverage']['last']
            employee['coverage']['reviewed'] = False
            employee['gap'] = '原工作本与原生收件直接读取；新增公开交流仅保留来源，不由监控重新推断任务或业务完成。媒体、业务接受及来源缺口分别保留。'
            if name == 'organoid' and any(('/workbook/' in p for p in st['notes'])):
                employee['notebook'] = _install.setting('monitor.live_update','notebook_label','Configured workbook; current view derives from original records')
        except Exception as e:
            newstate['employees'][name]['error'] = type(e).__name__ + ': ' + str(e)[:170]
            counts[name] = {'error': newstate['employees'][name]['error']}
        es = newstate['employees'][name]
        health[name] = {k: es.get(k) for k in ['lastSuccess', 'lastAttempt', 'lastCutoff', 'error']}
    for e in snap['employees']:
        if e['id'] not in ['secretary', 'organoid']:
            continue
        current = [t for t in snap['tasks'] if t['employee'] == e['id'] and t['kind'] != 'history']
        if not current:
            continue
        active = [t['title'] for t in current if t['state'] == '进行中']
        todo = [t['title'] for t in current if t['state'] in ['待推进', '待处理']]
        waiting = [t['title'] for t in current if t['state'] == '等反馈']
        e['current'] = '进行中：' + '；'.join(active[:2]) if active else '待推进：' + '；'.join(todo[:2]) if todo else '等待：' + '；'.join(waiting[:2]) if waiting else '当前已记录工作已交付或暂缓；见逐件笔记与后续反馈。'
    from employee_profiles import refresh_profiles
    (profiles, sources, profile_state) = refresh_profiles(snap, sources, newstate.get('profiles', {}), utc())
    snap['profiles'] = profiles
    newstate['profiles'] = profile_state
    try:
        from model_accounts import read_accounts
        accounts = read_accounts(previous=snap.get('modelAccounts'))
    except Exception:
        from account_contract import unavailable_accounts
        accounts = unavailable_accounts(snap.get('modelAccounts'), utc())
    if accounts is not None:
        snap['modelAccounts'] = accounts
    try:
        from work_observer import directory
        runtime_targets = {r['id']: r['threadId'] for r in directory()[0] if r['id'] != 'sender'}
        p = subprocess.run([NODE, str(Path(__file__).with_name('read_runtime.mjs')), json.dumps(runtime_targets)], capture_output=True, text=True, timeout=85)
        if p.returncode:
            raise ValueError('runtime failed')
        runtime = json.loads(p.stdout)
    except Exception:
        runtime = {n: {'status': 'unknown', 'queueCount': None, 'error': '原生连接不可用'} for n in IDS}
    try:
        from sender_runtime import read_runtime, SID
        runtime['sender'] = read_runtime()
    except Exception:
        from sender_runtime import SID
        runtime['sender'] = {'threadId': SID, 'host': 'aup', 'status': 'unknown', 'queueCount': None, 'turns': [], 'error': 'AUP正式inspect/read本轮不可读；不回退Mac归档'}
    for e in snap['employees']:
        r = runtime.get(e['id'], {})
        e['runtime'] = {'active': '执行中', 'idle': '空闲'}.get(r.get('status'), '未知')
        e['queueCount'] = r.get('queueCount')
        if 'runtimeTurnIds' not in newstate:
            baseline_runtime = json.loads((PRIVATE / 'runtime.json').read_text()) if (PRIVATE / 'runtime.json').exists() else {'employees': {}}
            newstate['runtimeTurnIds'] = {n: [t['id'] for t in x.get('turns', []) if t.get('durationMs') is not None and t.get('status') in ['completed', 'failed', 'interrupted']] for (n, x) in baseline_runtime['employees'].items()}
        known = set(newstate['runtimeTurnIds'].get(e['id'], []))
        seconds = 0
        for turn in r.get('turns', []):
            if turn.get('durationMs') is not None and turn.get('status') in ['completed', 'failed', 'interrupted'] and (turn['id'] not in known):
                seconds += turn['durationMs'] / 1000
                known.add(turn['id'])
        e['turnHours'] = round(e.get('turnHours', 0) + seconds / 3600, 3)
        newstate['runtimeTurnIds'][e['id']] = sorted(known)
        health.setdefault(e['id'], {})['runtimeError'] = r.get('error')
        health[e['id']]['runtimeAt'] = utc()
    runtime_sample_at = utc()
    from work_observer import refresh_work
    try:
        (snap, sources) = refresh_work(snap, sources, utc(), native_runtime=runtime)
        for p in snap.get('workOverview', {}).get('employees', []):
            if p.get('runtime'):
                health.setdefault(p['id'], {}).update(runtimeError=None if p['runtime']['state'] != '未知' else '原生回合未取得', runtimeAt=p['runtime']['sampledAt'])
    except Exception as e:
        if snap.get('workOverview'):
            snap['workOverview']['error'] = type(e).__name__ + ': 本轮目录读取失败，保留旧结果'
    newstate['cycles'] += 1
    newstate['lastCycle'] = started
    old_tasks = {t['id']: t for t in current_data()[0]['tasks'] if t['kind'] != 'history'}
    for t in list(snap['tasks']):
        if t['kind'] == 'history':
            continue
        old = old_tasks.get(t['id'])
        if old and all((t.get(k) == old.get(k) for k in ['state', 'pending', 'title', 'next'])):
            continue
        h = copy.deepcopy(t)
        h['kind'] = 'history'
        h['id'] = 'live-history-' + digest(t['id'] + '|' + str(t.get('state')) + '|' + str(t.get('pending')) + '|' + str(t.get('evidence', [])))[0:20]
        h['origin'] = '监控读取到的工作本/交流变化，非新交办。关联原事项：' + t['id']
        h['confidence'] = '变化发生时的记录状态，非当前欠项'
        if not any((x['id'] == h['id'] for x in snap['tasks'])):
            snap['tasks'].append(h)
    finished = utc()
    revision = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6]
    snap.update(generatedAt=bj(finished), historyCutoff=bj(started), runtimeAt=bj(runtime_sample_at), live={'revision': revision, 'intervalSeconds': 300, 'lastCycleStarted': started, 'lastCycleFinished': finished, 'health': health, 'cycles': newstate['cycles'], 'mode': 'read-only-incremental'})
    snap['warnings'] = [w for w in snap['warnings'] if not any((s in w for s in ['不是持续自动监控', '20:24:54', '20:27左右']))]
    if '每5分钟增量读取；休眠或程序离线时不更新，逐源失败保留上次成功数据。' not in snap['warnings']:
        snap['warnings'].insert(0, '每5分钟增量读取；休眠或程序离线时不更新，逐源失败保留上次成功数据。')
    checkpoint = PRIVATE / 'live-checkpoints' / revision
    atomic_json(checkpoint / 'state.json', newstate)
    publish(LIVE, snap, sources, revision)
    atomic_json(STATE, newstate)
    receipt = {'revision': revision, 'started': started, 'finished': finished, 'elapsedSeconds': round(time.monotonic() - start, 2), 'cycle': newstate['cycles'], 'counts': counts, 'runtime': {n: {'status': r.get('status'), 'queueCount': r.get('queueCount'), 'error': r.get('error')} for (n, r) in runtime.items()}, 'readOnly': True}
    atomic_json(PRIVATE / 'live-last-cycle.json', receipt)
    logs = PRIVATE / 'live-cycles'
    atomic_json(logs / (revision + '.json'), receipt)
    for f in sorted(logs.glob('*.json'))[:-100]:
        f.unlink()
    import shutil
    for f in sorted((PRIVATE / 'live-checkpoints').iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[3:]:
        shutil.rmtree(f)
    analysis = PRIVATE / 'live-analysis'
    if analysis.exists():
        for f in sorted(analysis.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[60:]:
            if f.is_dir() and (not f.is_symlink()):
                shutil.rmtree(f)
    print(json.dumps(receipt, ensure_ascii=False), flush=True)
    return receipt
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    if a.execute:
        run_cycle()
    else:
        p.print_help()
