"""Read and complete an authenticated ordinary WeChat chat from its desktop turn."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
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


def chat_reply(config, identity, thread, turn, reply=None):
    folder = Path(config['state']) / identity
    checkpoint = folder / 'desktop-execution.json'
    http = build_opener(ProxyHandler({}))

    def exchange(path, value=None):
        request = Request(f"http://127.0.0.1:{int(config['port'])}{path}",
                          data=encoded(value) if value is not None else None,
                          headers={'Authorization': 'Bearer ' + config['token']})
        with http.open(request, timeout=8) as response:
            return json.load(response)

    if reply is None:
        original = exchange('/desktop-requests/' + identity)
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
    if not reply.strip() or '\0' in reply or len(reply.encode()) > 65536:
        raise ValueError('Bounded original chat reply required.')
    completion_text(original['body'], reply)
    completion = dict(binding, text=reply)
    save_once(folder / 'desktop-completion.json', completion)
    return exchange('/desktop-completions', completion)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('read', 'complete'))
    parser.add_argument('config', type=Path)
    parser.add_argument('id')
    parser.add_argument('thread_id')
    parser.add_argument('turn_id')
    args = parser.parse_args()
    if (not re.fullmatch('[a-f0-9]{64}', args.id)
            or any(not re.fullmatch('[a-f0-9-]{36}', value) for value in (args.thread_id, args.turn_id))):
        parser.error('Full request ID and actual desktop thread and turn IDs required.')
    try:
        config = json.loads(args.config.read_bytes())
        reply = sys.stdin.buffer.read(65537).decode() if args.action == 'complete' else None
        result = chat_reply(config, args.id, args.thread_id, args.turn_id, reply)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    sys.stdout.buffer.write(encoded(result) + b'\n')


if __name__ == '__main__':
    main()
