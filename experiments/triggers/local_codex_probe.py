"""One isolated remote-event -> local App Server -> remote receipt experiment.

No production inbox, existing desktop thread or WeChat sender is opened.
The operator supplies an existing SSH destination/key and local Codex binary.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import queue
import secrets
import subprocess
import threading
import time


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def run_codex(binary, folder, journal):
    events = queue.Queue()
    with (folder / 'app-server.stderr.log').open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(
            [binary, 'app-server', '--stdio'], cwd=folder, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=stderr, text=True, encoding='utf-8')
        def read():
            for line in process.stdout:
                events.put(json.loads(line))
            events.put(None)
        threading.Thread(target=read, daemon=True).start()
        def send(method, params, identity=None):
            value = {'method': method, 'params': params}
            if identity is not None:
                value['id'] = identity
            process.stdin.write(json.dumps(value) + '\n')
            process.stdin.flush()
        send('initialize', {'clientInfo': {
            'name': 'rsi_event_probe', 'title': 'RSI event experiment', 'version': '0.1.0'}}, 0)
        deadline = time.monotonic() + 240
        started = time.monotonic()
        with (folder / 'app-server.jsonl').open('w', encoding='utf-8') as log:
            while time.monotonic() < deadline:
                event = events.get(timeout=max(0.1, deadline - time.monotonic()))
                if event is None:
                    raise RuntimeError('app-server exited before turn/completed')
                log.write(json.dumps(event, ensure_ascii=False) + '\n')
                log.flush()
                if 'error' in event:
                    raise RuntimeError('app-server rejected request: ' + str(event['error']))
                if event.get('id') == 0:
                    send('initialized', {})
                    send('thread/start', {
                        'cwd': str(folder), 'sandbox': 'read-only',
                        'approvalPolicy': 'never', 'ephemeral': True,
                        'developerInstructions': 'This is an isolated trigger experiment. '
                        'Do not delegate, edit files, access the network, or use MCP tools. '
                        'Use the local shell only to read the requested challenge file.'}, 1)
                elif event.get('id') == 1:
                    journal['thread_id'] = event['result']['thread']['id']
                    journal['phase'] = 'running'
                    save(folder / 'journal.json', journal)
                    send('turn/start', {'threadId': journal['thread_id'], 'input': [
                        {'type': 'text', 'text': journal['input']['instruction']}]}, 2)
                elif event.get('id') == 2:
                    journal['turn_id'] = event['result']['turn']['id']
                    journal['event_to_turn_seconds'] = round(time.monotonic() - started, 3)
                if event.get('method') == 'item/completed':
                    item = event['params']['item']
                    if item.get('type') == 'agentMessage':
                        journal['text'] = item['text']
                    if item.get('type') == 'commandExecution':
                        journal.setdefault('command_exits', []).append(item.get('exitCode'))
                if event.get('method') == 'turn/completed':
                    turn = event['params']['turn']
                    journal['turn_status'] = turn['status']
                    if turn['status'] != 'completed':
                        raise RuntimeError('turn did not complete: ' + str(turn.get('error')))
                    journal['phase'] = 'completed'
                    journal['total_seconds'] = round(time.monotonic() - started, 3)
                    save(folder / 'journal.json', journal)
                    process.stdin.close()
                    process.wait(timeout=20)
                    return
        raise TimeoutError('isolated turn timed out; preserve journal and inspect original process')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--ssh', required=True, help='Existing SSH destination, e.g. user@host')
    parser.add_argument('--identity', required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--remote-port', type=int, default=35471)
    args = parser.parse_args()
    folder = args.state.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    challenge = secrets.token_hex(24)
    (folder / 'challenge.txt').write_text(challenge, encoding='utf-8')
    token = secrets.token_hex(32)
    payload = {'id': 'fixture-' + secrets.token_hex(12), 'instruction':
               'Read challenge.txt with the local shell. Reply with only its exact contents.'}
    encoded = json.dumps(payload, sort_keys=True).encode()
    journal = {'phase': 'waiting_event', 'input': payload,
               'input_sha256': hashlib.sha256(encoded).hexdigest(), 'generations': 0}
    save(folder / 'journal.json', journal)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            if self.path != '/event' or not secrets.compare_digest(
                    self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.send_error(403)
                return
            body = self.rfile.read(min(int(self.headers.get('Content-Length', '0')), 8193))
            try:
                incoming = json.loads(body)
            except (ValueError, UnicodeDecodeError):
                self.send_error(400)
                return
            digest = hashlib.sha256(json.dumps(incoming, sort_keys=True).encode()).hexdigest()
            with lock:
                if digest != journal['input_sha256']:
                    self.send_error(409)
                    return
                cached = journal['phase'] == 'completed'
                if journal['phase'] == 'waiting_event':
                    journal.update(phase='accepted', generations=1)
                    save(folder / 'journal.json', journal)
                    try:
                        run_codex(args.codex, folder, journal)
                    except Exception as error:
                        journal.update(phase='review', error=str(error))
                        save(folder / 'journal.json', journal)
                if journal['phase'] != 'completed':
                    self.send_error(409)
                    return
                result = dict(journal, cached=cached)
            data = json.dumps(result).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ssh = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
           '-o', 'ConnectTimeout=12', '-i', args.identity]
    with (folder / 'ssh-forward.log').open('w') as log:
        tunnel = subprocess.Popen(ssh + ['-o', 'ExitOnForwardFailure=yes', '-N', '-R',
            f'127.0.0.1:{args.remote_port}:127.0.0.1:{server.server_port}', args.ssh],
            stdout=log, stderr=log)
        try:
            remote = """
import json,time,urllib.request,urllib.error,pathlib
c=CONFIG
url='http://127.0.0.1:%d/event'%c['port']
request=urllib.request.Request(url,data=json.dumps(c['payload']).encode(),
    headers={'Authorization':'Bearer '+c['token'],'Content-Type':'application/json'})
for attempt in range(30):
    try:
        first=json.load(urllib.request.urlopen(request,timeout=300));break
    except urllib.error.URLError as error:
        if isinstance(error,urllib.error.HTTPError):raise
        time.sleep(.2)
else:raise RuntimeError('SSH reverse forward unavailable')
second=json.load(urllib.request.urlopen(request,timeout=20))
changed=dict(c['payload'],instruction='changed fixture')
conflict=urllib.request.Request(url,data=json.dumps(changed).encode(),headers=request.headers)
try:urllib.request.urlopen(conflict,timeout=20);rejected=False
except urllib.error.HTTPError as error:rejected=error.code==409
result={'first':first,'duplicate':second,'changed_input_rejected':rejected,
        'remote_event':True,'wechat_transport':False,'desktop_thread_wakeup':False}
print(json.dumps(result))
""".replace('CONFIG', repr({'payload': payload, 'port': args.remote_port, 'token': token}))
            response = subprocess.run(ssh + [args.ssh, '/usr/bin/python3', '-B', '-'],
                input=remote, text=True, encoding='utf-8', capture_output=True, timeout=330)
            (folder / 'remote.stderr.log').write_text(response.stderr, encoding='utf-8')
            if response.returncode:
                raise RuntimeError('remote event failed; inspect private remote.stderr.log')
            receipt = json.loads(response.stdout)
            receipt['nonce_matches_actual_file'] = receipt['first'].get('text', '').strip() == challenge
            receipt['single_generation'] = journal['generations'] == 1
            receipt['source_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            save(folder / 'acceptance.json', receipt)
            print(json.dumps({k: receipt[k] for k in ('nonce_matches_actual_file',
                'single_generation', 'changed_input_rejected', 'remote_event',
                'wechat_transport', 'desktop_thread_wakeup')}))
            print('event_to_turn_seconds', journal['event_to_turn_seconds'])
            print('total_seconds', journal['total_seconds'])
            print('receipt', str(folder / 'acceptance.json'))
        finally:
            tunnel.terminate()
            tunnel.wait(timeout=15)
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    main()
