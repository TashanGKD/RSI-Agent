"""Loopback UI + independent read-only 300-second collector. No worker wakeups."""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import argparse, datetime, fcntl, json, os, signal, threading, time
from pathlib import Path
from http.server import ThreadingHTTPServer
from serve import Handler
from live_update import run_cycle, ROOT, LIVE, PRIVATE, utc
from live_core import atomic_json

def run(port):
    lock = (PRIVATE / 'service.lock').open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('This observer service is already running.')
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stop = threading.Event()

    def shutdown(*_):
        stop.set()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    while not stop.is_set():
        mono = time.monotonic()
        started = utc()
        status = {'collectorState': 'checking', 'scheduledAt': started, 'intervalSeconds': 300, 'nextCheckAt': None, 'pid': os.getpid()}
        atomic_json(LIVE / 'status.json', status)
        try:
            result = run_cycle()
            status['lastResult'] = 'skipped-overlap' if result.get('skipped') else 'completed'
            status['error'] = None
        except Exception as e:
            status.update(lastResult='failed', error=type(e).__name__ + ': ' + str(e)[:150])
        if status.get('lastResult') == 'completed':
            try:
                from online_sync import sync_online
                synced = sync_online()
                status['onlineSync'] = {k: synced[k] for k in ['enabled', 'revision', 'syncedAt', 'publicUrl'] if k in synced}
            except Exception:
                status['onlineSync'] = {'enabled': True, 'error': '在线同步失败；本机采集与游标保留，下轮重试'}
        remaining = max(1, 300 - (time.monotonic() - mono))
        status.update(collectorState='waiting', lastCycleEnded=utc(), nextCheckAt=(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=remaining)).isoformat())
        atomic_json(LIVE / 'status.json', status)
        stop.wait(remaining)
    server.shutdown()
    server.server_close()
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--port', type=int, default=18974)
    a = p.parse_args()
    if a.execute:
        run(a.port)
    else:
        p.print_help()
