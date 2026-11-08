"""Private stdio entry to the pinned DeepSeek Harness runtime."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import traceback

from .config import ROOT
from .model import ModelClient
from .wechat import private_file


def config(path):
    if not private_file(path):
        raise ValueError('Private Harness configuration required.')
    value = json.loads(Path(path).read_text())
    required = {'backend', 'provider_config', 'python', 'state', 'workspace'}
    if (set(value) not in (required, required | {'engineering_workspace'})
            or value['backend'] != 'deepseek-harness'):
        raise ValueError('Invalid DeepSeek Harness configuration.')
    for name in ('state', 'workspace', *(['engineering_workspace'] if 'engineering_workspace' in value else [])):
        p = Path(value[name])
        if (not p.is_absolute() or p.is_symlink() or not p.is_dir()
                or p.stat().st_uid != os.getuid() or p.stat().st_mode & 0o077):
            raise ValueError('Private explicit Harness directories required.')
    return value


def blocks(messages):
    """Keep supplied system facts separate; image bytes must be inline data."""
    systems, data = [], []
    for message in messages:
        if message['role'] == 'system':
            if not isinstance(message['content'], str):
                raise ValueError('Text application facts required.')
            systems.append(message['content'])
        else:
            content = message['content']
            if isinstance(content, str):
                data.append({'type': 'text', 'text': message['role'] + ': ' + content})
                continue
            if message['role'] != 'user' or not isinstance(content, list):
                raise ValueError('User text/image blocks required.')
            for part in content:
                if part['type'] == 'text':
                    data.append({'type': 'text', 'text': part['text']})
                elif part['type'] == 'image_url':
                    match = re.fullmatch(r'data:(image/(?:png|jpeg|gif|webp));base64,([A-Za-z0-9+/=]+)',
                                         part['image_url']['url'])
                    if not match:
                        raise ValueError('Verified inline image required; no remote image fetch.')
                    base64.b64decode(match[2], validate=True)
                    data.append({'type': 'image', 'mimeType': match[1], 'data': match[2]})
                else:
                    raise ValueError('Unsupported Harness input block.')
    return '\n'.join(systems), data


def execute(value, request):
    if (set(request) != {'id', 'session', 'mode', 'messages'} or request['mode'] not in ('chat', 'engineering')
            or not re.fullmatch('[a-f0-9]{64}', request['id'])
            or not re.fullmatch('rsi-[a-z0-9-]{1,80}', request['session'])):
        raise ValueError('Exact private Harness request required.')
    system, content = blocks(request['messages'])
    state = Path(value['state'])
    workspace = value['workspace']
    if request['mode'] == 'engineering':
        workspace = value.get('engineering_workspace')
        if not workspace:
            raise ValueError('Explicit isolated owner engineering workspace required.')
    calls = state / 'calls'
    calls.mkdir(mode=0o700, exist_ok=True)
    if calls.is_symlink() or calls.stat().st_mode & 0o077:
        raise ValueError('Private Harness receipts required.')
    path = calls / (request['id'] + '.json')
    digest = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    import fcntl
    fd = os.open(calls / (request['id'] + '.lock'), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)

    def save(result):
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(dict(result, input_sha256=digest)) + '\n')
        temporary.chmod(0o600)
        os.replace(temporary, path)

    work_fd = None
    work_marker = None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            if not private_file(path):
                raise ValueError('Private original Harness receipt required.')
            old = json.loads(path.read_text())
            if old['input_sha256'] != digest:
                raise ValueError('Original Harness input changed; preserve its request.')
            if old['state'] == 'completed':
                return old
            raise ValueError('Original Harness result is uncertain; do not run tools again.')
        if request['mode'] == 'engineering':
            work_fd = os.open(Path(workspace).parent / 'engineering.lock',
                os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            fcntl.flock(work_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            work_marker = Path(workspace).parent / 'engineering-current.json'
            if work_marker.exists():
                raise ValueError('Earlier owner work is unresolved; inspect its original request.')
            from .engineering import prepare
            prepare(workspace)
        sessions = state / 'sessions'
        sessions.mkdir(mode=0o700, exist_ok=True)
        if sessions.is_symlink() or sessions.stat().st_mode & 0o077:
            raise ValueError('Private Harness session markers required.')
        marker = sessions / (request['session'] + '.json')
        binding = {'workspace': workspace, 'mode': request['mode']}
        if marker.exists() and (not private_file(marker) or json.loads(marker.read_text()) != binding):
            raise ValueError('Original Harness session scope changed.')
        save({'state': 'running'})
        if work_marker is not None:
            fd_work = os.open(work_marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd_work, 'w') as stream:
                stream.write(json.dumps({'request': request['id']}))
        from deepseek_harness import DeepSeekHarness
        provider = ModelClient(value['provider_config'])
        patches = [str(ROOT / 'harness/deepseek/scnet.patch.yml')]
        # Chat stays tool-free; owner engineering gets the structured tools.
        patches.append(str(ROOT / 'harness/deepseek' /
            ('chat.patch.yml' if request['mode'] == 'chat' else 'engineering.patch.yml')))
        role = (ROOT / 'harness/deepseek/ROLE.md').read_text(encoding='utf8')
        with DeepSeekHarness(provider='scnet', model=provider.model, max_tokens=4096,
                cwd=workspace, dsh_home=str(state / 'home'), profile='sdk-minimal',
                patches=tuple(patches), base_url=provider.base_url, api_key=provider._key,
                env={'DSH_SYSTEM_PROMPT': role + '\n' + system}, initialize_timeout_seconds=40,
                request_timeout_seconds=360 if request['mode'] == 'engineering' else 150) as harness:
            result = (harness.resume_session(request['session']).run(content) if marker.exists()
                      else harness.run(content, session_id=request['session']))
        if result.finish_reason != 'completed' or not result.final_response.strip():
            raise ValueError('Harness did not complete; inspect the original Session.')
        if '<｜｜DSML｜｜' in result.final_response or '<tool_call>' in result.final_response:
            raise ValueError('Unexecuted tool syntax is not a completed response.')
        receipt = {'state': 'completed', 'response': result.final_response,
                   'backend': 'deepseek-harness', 'mode': request['mode'], 'session': request['session']}
        if request['mode'] == 'engineering':
            from .engineering import publish
            receipt['change'] = publish(workspace)
            if receipt['change']:
                receipt['response'] += '\n' + receipt['change']['review_url']
        temporary = marker.with_suffix('.tmp')
        temporary.write_text(json.dumps(binding))
        temporary.chmod(0o600)
        os.replace(temporary, marker)
        save(receipt)
        if work_marker is not None:
            work_marker.unlink()
        return receipt
    finally:
        if work_fd is not None:
            os.close(work_fd)
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    os.umask(0o077)
    raw = sys.stdin.read(15000001)
    if len(raw.encode()) > 15000000:
        raise ValueError('Harness input exceeds the inline transport budget.')
    print(json.dumps(execute(config(args.config), json.loads(raw)), ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({'state': 'attention', 'code': type(error).__name__}))
        raise SystemExit(2)
