"""Read and complete an authenticated ordinary WeChat chat from its desktop turn."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from receiver.codex_worker import completion_text, encoded


def save_once(path, value):
    """Publish a complete checkpoint without replacing a concurrent or prior value."""
    temp = NamedTemporaryFile(dir=path.parent, delete=False)
    staged = Path(temp.name)
    try:
        with temp:
            temp.write(encoded(value))
            temp.flush()
            os.fsync(temp.fileno())
        os.link(staged, path)
    except FileExistsError:
        if json.loads(path.read_bytes()) != value:
            raise ValueError('An existing checkpoint differs. Reconcile the original.')
    finally:
        staged.unlink()


def chat_binding(record, identity, thread, turn):
    body = record['body']
    digest = hashlib.sha256(encoded(body)).hexdigest()
    if (body['id'] != identity or body['mode'] != 'chat'
            or record['input_sha256'] != digest or record['thread_id'] != thread):
        raise ValueError('Original chat, input digest and current thread must match.')
    return {'id': identity, 'input_sha256': digest, 'thread_id': thread, 'turn_id': turn}


def exchange(config, path, value=None, *, timeout=8):
    request = Request(f"http://127.0.0.1:{int(config['port'])}{path}",
                      data=encoded(value) if value is not None else None,
                      headers={'Authorization': 'Bearer ' + config['token']})
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)


def delivery(config, identity, thread, turn, wait):
    deadline = time.monotonic() + (18 if wait else 0)
    route = f'/desktop-deliveries/{identity}/{thread}/{turn}'
    while True:
        try:
            timeout = max(0.1, min(2, deadline - time.monotonic())) if wait else 2
            result = exchange(config, route, timeout=timeout)
        except HTTPError as error:
            if error.code != 404:
                raise
            return {'id': identity, 'state': 'pending', 'code': 'DELIVERY_STATUS_UNAVAILABLE'}
        except OSError:
            return {'id': identity, 'state': 'pending', 'code': 'DELIVERY_STATUS_UNAVAILABLE'}
        remaining = deadline - time.monotonic()
        if result['state'] != 'pending' or remaining <= 0:
            return result
        time.sleep(min(1, remaining))


def chat_reply(config, identity, thread, turn, reply=None):
    folder = Path(config['state']) / identity
    checkpoint = folder / 'desktop-execution.json'
    if reply is None:
        original = exchange(config, '/desktop-requests/' + identity)
        binding = chat_binding(original, identity, thread, turn)
        if original['state'] != 'desktop_queued':
            return {'id': identity, 'state': original['state']}
        save_once(checkpoint, dict(binding, phase='running', workspace=None, artifacts=[]))
        for message in original['body']['messages']:
            if isinstance(message['content'], list):
                message['content'] = [part if part['type'] == 'text' else {'type': part['type']}
                                      for part in message['content']]
        return original

    original = json.loads((folder / 'original.json').read_bytes())
    binding = chat_binding(original, identity, thread, turn)
    if json.loads(checkpoint.read_bytes()) != dict(binding, phase='running', workspace=None, artifacts=[]):
        raise ValueError('Use the checkpoint from this actual chat turn.')
    completion_path = folder / 'desktop-completion.json'
    completion = dict(binding, text=reply)
    if not completion_path.exists() or json.loads(completion_path.read_bytes()) != completion:
        # Windows pipelines add CRLF framing. Keep an exact legacy retry intact.
        reply = reply.replace('\r\n', '\n').removesuffix('\n')
        completion['text'] = reply
    if not reply.strip() or '\0' in reply or len(reply.encode()) > 65536:
        raise ValueError('Bounded original chat reply required.')
    completion_text(original['body'], reply)
    save_once(completion_path, completion)
    return exchange(config, '/desktop-completions', completion)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('read', 'complete', 'status'))
    parser.add_argument('config', type=Path)
    parser.add_argument('id')
    parser.add_argument('thread_id')
    parser.add_argument('turn_id')
    parser.add_argument('--wait', action='store_true', help='Wait briefly for the original WeChat delivery receipt.')
    args = parser.parse_args()
    if (not re.fullmatch('[a-f0-9]{64}', args.id)
            or any(not re.fullmatch('[a-f0-9-]{36}', value) for value in (args.thread_id, args.turn_id))):
        parser.error('Full request ID and actual desktop thread and turn IDs required.')
    try:
        config = json.loads(args.config.read_bytes())
        target = (config, args.id, args.thread_id, args.turn_id)
        if args.action != 'status':
            reply = sys.stdin.buffer.read(65537).decode() if args.action == 'complete' else None
            result = chat_reply(*target, reply)
        if args.action == 'status' or args.action == 'complete' and args.wait:
            result = delivery(*target, args.wait)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    sys.stdout.buffer.write(encoded(result) + b'\n')


if __name__ == '__main__':
    main()
