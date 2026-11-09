"""Local persistent Codex consumer; the native client host only forwards requests."""
import argparse
import base64
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import queue
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import tomllib
import traceback


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def validate(value):
    if (set(value) != {'id', 'mode', 'scope', 'request', 'messages', 'schema'}
            or not re.fullmatch('[a-f0-9]{64}', value['id'])
            or value['mode'] not in ('chat', 'engineering')
            or not isinstance(value['scope'], list) or len(value['scope']) != 2
            or any(not isinstance(x, str) or not x or '\0' in x for x in value['scope'])
            or not isinstance(value['request'], list) or not value['request']
            or any(not isinstance(x, str) or not x.isdecimal() for x in value['request'])):
        raise ValueError('Original native Codex request required.')
    blocks(value['messages'])
    if value['schema'] is not None and not isinstance(value['schema'], dict):
        raise ValueError('Explicit response schema required.')


def blocks(messages):
    systems, inputs = [], []
    if not isinstance(messages, list) or not messages:
        raise ValueError('Frozen conversation required.')
    for message in messages:
        if message['role'] not in ('system', 'user', 'assistant'):
            raise ValueError('Invalid message role.')
        content = message['content']
        if isinstance(content, str):
            if message['role'] == 'system':
                systems.append(content)
            else:
                inputs.append({'type': 'text', 'text': message['role'] + ': ' + content})
        elif message['role'] == 'user' and isinstance(content, list):
            for part in content:
                if part['type'] == 'text' and isinstance(part.get('text'), str):
                    inputs.append({'type': 'text', 'text': part['text']})
                elif part['type'] == 'image_url':
                    url = part['image_url']['url']
                    match = re.fullmatch(r'data:image/(?:png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)', url)
                    if not match:
                        raise ValueError('Only verified inline images can cross the model port.')
                    base64.b64decode(match[1], validate=True)
                    inputs.append({'type': 'image', 'url': url})
                else:
                    raise ValueError('Unsupported Codex content block.')
        else:
            raise ValueError('User text/image blocks required.')
    return '\n'.join(systems), inputs


class Jobs:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.root / 'jobs.sqlite'
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,digest TEXT NOT NULL,body TEXT NOT NULL,'
                'state TEXT NOT NULL,result TEXT,thread_id TEXT,turn_id TEXT,error TEXT,updated REAL NOT NULL)')
            if 'desktop_message_id' not in {r[1] for r in db.execute('PRAGMA table_info(jobs)')}:
                db.execute('ALTER TABLE jobs ADD COLUMN desktop_message_id TEXT')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def accept(self, value):
        validate(value)
        raw = encoded(value);digest = hashlib.sha256(raw).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO jobs(id,digest,body,state,updated) VALUES(?,?,?,?,?)',
                       (value['id'], digest, raw.decode(), 'queued', time.time()))
            row = db.execute('SELECT * FROM jobs WHERE id=?', (value['id'],)).fetchone()
            if row['digest'] != digest:
                raise ValueError('Original Codex input changed.')
            return dict(row)

    def get(self, identity):
        with self.connect() as db:
            return dict(db.execute('SELECT * FROM jobs WHERE id=?', (identity,)).fetchone())

    def update(self, identity, **fields):
        assert set(fields) <= {'state', 'result', 'thread_id', 'turn_id', 'error', 'desktop_message_id'}
        fields['updated'] = time.time()
        with self.connect() as db:
            db.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in fields) + ' WHERE id=?',
                       [*fields.values(), identity])

    def claim(self, mode):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT * FROM jobs WHERE state='queued' AND json_extract(body,'$.mode')=? ORDER BY rowid LIMIT 1", (mode,)).fetchone()
            if row:
                db.execute("UPDATE jobs SET state='starting',updated=? WHERE id=? AND state='queued'", (time.time(), row['id']))
                return dict(row)

    def review_interrupted(self):
        with self.connect() as db:
            db.execute("UPDATE jobs SET state='review',error='Worker interrupted; inspect original thread/events/queue receipt, never regenerate',updated=? WHERE state IN ('starting','running','desktop_submitting')", (time.time(),))

    def desktop_task(self, identity, target):
        row = self.get(identity)
        if (not target or row['thread_id'] != target or not row['desktop_message_id']
                or json.loads(row['body'])['mode'] != 'engineering'):
            raise ValueError('Original task is not bound to this desktop conversation.')
        return {'id': identity, 'input_sha256': row['digest'], 'thread_id': target,
                'desktop_message_id': row['desktop_message_id'], 'state': row['state'],
                'body': json.loads(row['body']), 'text': row['result'], 'turn_id': row['turn_id']}

    def complete_desktop(self, value, target):
        if (set(value) != {'id', 'input_sha256', 'thread_id', 'turn_id', 'text'}
                or not target or value['thread_id'] != target
                or not isinstance(value['turn_id'], str) or not value['turn_id']
                or not isinstance(value['text'], str) or not value['text'].strip()
                or '\0' in value['text'] or len(value['text'].encode()) > 16384):
            raise ValueError('Frozen original desktop completion required.')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM jobs WHERE id=?', (value['id'],)).fetchone()
            if (not row or row['digest'] != value['input_sha256'] or row['thread_id'] != target
                    or not row['desktop_message_id'] or json.loads(row['body'])['mode'] != 'engineering'):
                raise ValueError('Original desktop task binding changed.')
            limit = 6000 if json.loads(row['body'])['scope'][1].endswith('@chatroom') else 16384
            if len(value['text'].encode()) > limit:
                raise ValueError('Completion exceeds the original native reply contract.')
            if row['state'] == 'completed':
                if (row['result'], row['turn_id']) != (value['text'], value['turn_id']):
                    raise ValueError('Completed desktop output cannot be replaced.')
            elif row['state'] == 'desktop_queued':
                db.execute("UPDATE jobs SET state='completed',result=?,turn_id=?,updated=? WHERE id=?",
                           (value['text'], value['turn_id'], time.time(), value['id']))
            else:
                raise ValueError('Uncertain desktop delivery must be reconciled, not replayed.')
        return {'id': value['id'], 'state': 'completed'}

    def counts(self):
        with self.connect() as db:
            return dict(db.execute('SELECT state,count(*) FROM jobs GROUP BY state'))


def tool_overrides(mode, config_path):
    # Child-process overrides only: never change the user's global configuration.
    config = tomllib.loads(Path(config_path).read_text(encoding='utf-8'))
    disabled = ['apps', 'plugins', 'multi_agent', 'browser_use', 'browser_use_external',
                'computer_use', 'in_app_browser', 'image_generation', 'sleep_tool', 'view_image',
                'code_mode', 'code_mode_host', 'request_permissions_tool']
    if mode == 'chat':
        disabled += ['shell_tool', 'unified_exec']
    result = {**{'features.' + name: False for name in disabled}, 'web_search': 'disabled'}
    result.update({'mcp_servers.' + name + '.enabled': False for name in config.get('mcp_servers', {})})
    if mode == 'chat':
        result['project_doc_max_bytes'] = 0
    return result


def workspace(config, request):
    root = Path(config['state']) / request['id']
    root.mkdir(mode=0o700, exist_ok=True)
    if request['mode'] == 'chat':
        return root
    repo = Path(config['repository'])
    # One runtime engineering task or reviewable PR at a time; ordinary chat is independent.
    opened = subprocess.check_output([config['gh'], 'pr', 'list', '--repo', 'Yu-Yang-Li/RSI-Agent',
        '--state', 'open', '--json', 'number'], text=True, timeout=40)
    if json.loads(opened):
        raise BlockingIOError('An existing PR must be delivered/reviewed first.')
    target = root / 'worktree'
    if target.exists():
        raise ValueError('Original engineering worktree exists; inspect without rerunning.')
    subprocess.run(['git', '-C', str(repo), 'fetch', 'origin', 'main'], check=True, capture_output=True, timeout=40)
    subprocess.run(['git', '-C', str(repo), 'worktree', 'add', '-b', 'codex/wechat-' + request['id'][:16],
        str(target), 'origin/main'], check=True, capture_output=True, timeout=40)
    return target


def run_codex(config, jobs, row):
    request = json.loads(row['body']);identity = request['id']
    cwd = workspace(config, request)
    folder = Path(config['state']) / identity
    system, inputs = blocks(request['messages'])
    overrides = tool_overrides(request['mode'], config['user_config'])
    command = [config['codex']]
    for key, value in overrides.items():
        command += ['-c', key + '=' + json.dumps(value)]
    command += ['app-server', '--stdio']
    events = queue.Queue()
    with (folder / 'app-server.stderr.log').open('a', encoding='utf-8') as stderr, (folder / 'events.jsonl').open('a', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=stderr, text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        (folder / 'execution.json').write_text(json.dumps({'pid': process.pid, 'mode': request['mode'],
            'cwd': str(cwd), 'overrides': overrides, 'started': time.time()}, ensure_ascii=False), encoding='utf-8')
        def read():
            for line in process.stdout:
                log.write(line);log.flush()
                event = json.loads(line)
                if event.get('method') in ('item/completed', 'turn/completed'):
                    os.fsync(log.fileno())
                events.put(event)
            events.put(None)
        reader = threading.Thread(target=read, daemon=True);reader.start()
        def send(method, params, number=None):
            value = {'method': method, 'params': params}
            if number is not None:
                value['id'] = number
            process.stdin.write(json.dumps(value, ensure_ascii=False) + '\n');process.stdin.flush()
        send('initialize', {'clientInfo': {'name': 'rsi_codex_worker', 'title': '星语微信', 'version': '1.0.0'}}, 0)
        final = None
        while True:
            event = events.get()
            if event is None:
                raise RuntimeError('Original App Server exited before completion; inspect private events.')
            if 'error' in event:
                raise RuntimeError('App Server rejected the original request: ' + str(event['error']))
            if event.get('id') == 0:
                send('initialized', {})
                params = {'cwd': str(cwd), 'approvalPolicy': 'never', 'ephemeral': True,
                    'sandbox': 'read-only' if request['mode'] == 'chat' else 'workspace-write',
                    'developerInstructions': system + '\n禁止生成子代理或委派其他代理。只输出本轮要求的最终答复。'}
                if request['mode'] == 'chat':
                    params['baseInstructions'] = '你是星语，通过微信桥接器参与对话。仅依据本轮资料回答，保持会话隔离；本轮无执行工具，不虚构执行结果。'
                else:
                    params['config'] = {'sandbox_workspace_write.network_access': True}
                    params['developerInstructions'] += ('\n本任务需要连接/诊断时，私有连接索引在 ' + config['operator_file']
                        + '，GitHub CLI 在 ' + config['gh'] + '。仅按本人当前要求使用，不输出秘密或无关私有记录。')
                send('thread/start', params, 1)
            elif event.get('id') == 1:
                thread = event['result']['thread']['id'];jobs.update(identity, thread_id=thread, state='running')
                params = {'threadId': thread, 'input': inputs}
                if request['schema'] is not None:
                    params['outputSchema'] = request['schema']
                send('turn/start', params, 2)
            elif event.get('id') == 2:
                jobs.update(identity, turn_id=event['result']['turn']['id'])
            elif event.get('method') == 'item/completed':
                item = event['params']['item']
                if item.get('type') == 'agentMessage' and item.get('phase') in (None, 'final_answer'):
                    final = item['text']
            elif event.get('method') == 'turn/completed':
                turn = event['params']['turn']
                if turn['status'] != 'completed' or not isinstance(final, str) or not final.strip():
                    raise RuntimeError('No completed original Codex response.')
                # Freeze before shutdown and before an HTTP client can observe completion.
                jobs.update(identity, result=final, state='completed')
                process.stdin.close();process.wait(timeout=20);reader.join(timeout=5);process.stdout.close()
                return


def notify_desktop(config, jobs, row):
    """Transfer the original owner task once; never start another model/tool turn."""
    request = json.loads(row['body']);target = config['desktop_thread_id']
    if request['mode'] != 'engineering' or not re.fullmatch('[a-f0-9-]{36}', target):
        raise ValueError('Verified owner task and fixed desktop thread required.')
    instruction = request['messages'][-1]
    if instruction['role'] != 'user' or not isinstance(instruction['content'], str):
        raise ValueError('Exact original owner instruction required.')
    folder = jobs.root / request['id'];folder.mkdir(mode=0o700, exist_ok=True)
    journal = folder / 'desktop-notification.json'
    if journal.exists():
        raise ValueError('Original desktop submission exists; inspect without requeueing.')
    jobs.update(request['id'], state='desktop_submitting', thread_id=target)
    original = folder / 'original.json'
    original.write_text(json.dumps({'input_sha256': row['digest'], 'thread_id': target,
        'body': request}, ensure_ascii=False, indent=2), encoding='utf-8');original.chmod(0o600)
    text = instruction['content']
    if len(text) > 8000:
        text = text[:8000] + '\n…（原文较长，全文保存在任务记录中）'
    message = ('【微信任务 · RSI-' + request['id'][:12] + '】\n' + text
        + '\n\n[原消息与回传记录](<' + original.as_posix() + '>)')
    proof = {'state': 'submitting', 'id': request['id'], 'input_sha256': row['digest'],
             'thread_id': target, 'message_sha256': hashlib.sha256(message.encode()).hexdigest()}
    journal.write_text(json.dumps(proof, indent=2), encoding='utf-8');journal.chmod(0o600)
    with journal.open('r+b') as stream:
        stream.flush();os.fsync(stream.fileno())
    result = subprocess.run([config['codex'], 'queue', '--thread', target, '--message', message],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    match = re.fullmatch(r'Queued message ([a-f0-9-]{36}) for thread ([a-f0-9-]{36})\.\s*', result.stdout)
    proof.update(exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr)
    if result.returncode or not match or match[2] != target:
        journal.write_text(json.dumps(proof, indent=2), encoding='utf-8')
        raise ValueError('Original desktop queue result is uncertain; do not resubmit.')
    proof.update(state='queued', desktop_message_id=match[1])
    journal.write_text(json.dumps(proof, indent=2), encoding='utf-8')
    jobs.update(request['id'], state='desktop_queued', desktop_message_id=match[1])


def server(config, jobs, draining):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def answer(self, code, value):
            body = encoded(value)
            self.send_response(code);self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)));self.end_headers();self.wfile.write(body)

        def authorized(self):
            return secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + config['token'])

        def do_GET(self):
            if not self.authorized():
                return self.answer(403, {'state': 'forbidden'})
            if self.path.startswith('/desktop-requests/'):
                try:
                    return self.answer(200, jobs.desktop_task(self.path.removeprefix('/desktop-requests/'),
                        config.get('desktop_thread_id')))
                except (ValueError, TypeError):
                    return self.answer(409, {'state': 'original_task_rejected'})
            if self.path != '/health':
                return self.answer(404, {'state': 'not_found'})
            return self.answer(200, {'backend': 'local-codex', 'ready': not draining.is_set(),
                'counts': jobs.counts(), 'pid': os.getpid(), 'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'desktop_thread_id': config.get('desktop_thread_id')})

        def do_POST(self):
            if not self.authorized():
                return self.answer(403, {'state': 'forbidden'})
            if self.path == '/drain':
                draining.set();return self.answer(200, {'state': 'draining'})
            if self.path not in ('/requests', '/desktop-completions'):
                return self.answer(404, {'state': 'not_found'})
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 20000000:
                    raise ValueError('Bounded request required.')
                value = json.loads(self.rfile.read(size))
                if self.path == '/desktop-completions':
                    return self.answer(200, jobs.complete_desktop(value, config.get('desktop_thread_id')))
                row = jobs.accept(value)
                state = row['state']
                self.answer(202 if state in ('queued', 'starting', 'running', 'desktop_submitting', 'desktop_queued') else 200,
                    {'state': state, **({'text': row['result']} if state == 'completed' else {})})
            except (ValueError, TypeError, KeyError):
                self.answer(409, {'state': 'original_input_rejected'})
    return ThreadingHTTPServer(('127.0.0.1', config['port']), Handler)


@contextmanager
def singleton(path):
    with Path(path).open('a+b') as stream:
        stream.write(b'0');stream.flush();stream.seek(0)
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    if not Path(config['codex']).is_file() or not re.fullmatch('[a-f0-9]{64}', config['token']):
        raise ValueError('Existing local Codex and private transport token required.')
    state = Path(config['state']);state.mkdir(mode=0o700, parents=True, exist_ok=True)
    with singleton(state / 'worker.lock'):
        jobs = Jobs(state);jobs.review_interrupted();draining = threading.Event()
        http = server(config, jobs, draining)
        threading.Thread(target=http.serve_forever, daemon=True).start()
        def consume(mode):
            while not draining.is_set():
                row = jobs.claim(mode)
                if not row:
                    time.sleep(.3);continue
                try:
                    if mode == 'engineering' and config.get('desktop_thread_id'):
                        notify_desktop(config, jobs, row)
                    else:
                        run_codex(config, jobs, row)
                except BlockingIOError:
                    jobs.update(row['id'], state='queued');time.sleep(30)
                except Exception:
                    old = jobs.get(row['id'])
                    if old['state'] != 'completed':
                        jobs.update(row['id'], state='review', error=traceback.format_exc())
        for mode in ('chat', 'engineering'):
            threading.Thread(target=consume, args=(mode,), daemon=True).start()
        tunnel = None
        with (state / 'ssh.stderr.log').open('a', encoding='utf-8') as stderr:
            try:
                while True:
                    if draining.is_set() and not any(jobs.counts().get(k, 0) for k in ('starting', 'running', 'desktop_submitting')):
                        break
                    if tunnel is None or tunnel.poll() is not None:
                        tunnel = subprocess.Popen(['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                            '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=12', '-o', 'ServerAliveInterval=15',
                            '-o', 'ServerAliveCountMax=3', '-i', config['identity_file'], '-R',
                            '127.0.0.1:' + str(config['remote_port']) + ':127.0.0.1:' + str(config['port']), config['ssh']],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    time.sleep(3)
            finally:
                http.shutdown()
                if tunnel is not None and tunnel.poll() is None:
                    tunnel.terminate();tunnel.wait(timeout=20)  # Only this worker's own forwarding process.


if __name__ == '__main__':
    main()
