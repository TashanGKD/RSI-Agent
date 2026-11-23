"""Reconcile the evidence for one original WeChat request without writing state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

from receiver.codex_worker import completion_text, encoded
from receiver.desktop_reply import delivery, exchange


SHA256 = re.compile('[a-f0-9]{64}')
UUID = re.compile('[a-f0-9-]{36}')


def read_record(path):
    try:
        return json.loads(path.read_bytes())
    except FileNotFoundError:
        return None


def observed_turn(rollout, thread, message_sha):
    """Match the full queued text in a user item within an observed Codex turn."""
    matches = set()
    ended_bad = set()
    active = None
    with rollout.open('rb') as stream:
        meta = json.loads(next(stream, b''))
        if meta.get('type') != 'session_meta' or meta['payload'].get('id') != thread:
            raise ValueError('The supplied Codex history belongs to a different conversation.')
        for line in stream:
            if not line.endswith(b'\n'):
                break  # A live writer may not have finished the last record.
            record = json.loads(line)
            payload = record['payload']
            if record['type'] == 'event_msg':
                if payload.get('type') == 'task_started':
                    active = payload.get('turn_id')
                elif payload.get('type') == 'turn_aborted':
                    ended_bad.add(payload.get('turn_id'))
                    if payload.get('turn_id') == active:
                        active = None
                elif payload.get('type') == 'task_complete' and payload.get('turn_id') == active:
                    if payload.get('error'):
                        ended_bad.add(active)
                    active = None
            if (not UUID.fullmatch(active or '') or record['type'] != 'response_item'
                    or payload.get('type') != 'message' or payload.get('role') != 'user'):
                continue
            parts = payload['content']
            if parts and all(part.get('type') == 'input_text' for part in parts):
                text = ''.join(part['text'] for part in parts)
                if hashlib.sha256(text.encode()).hexdigest() == message_sha:
                    matches.add(active)
    # A turn that was interrupted or failed before reading the request is followed by
    # one requeue of the same text; only the turn that can actually carry it counts.
    matches -= ended_bad
    if len(matches) > 1:
        raise ValueError('The original queued text occurs in multiple Codex turns.')
    return next(iter(matches), None)


def reconcile(config, identity, rollout=None):
    original = exchange(config, '/desktop-requests/' + identity)
    digest = hashlib.sha256(encoded(original['body'])).hexdigest()
    thread = original['thread_id']
    if (original['id'] != identity or original['body']['id'] != identity
            or original['input_sha256'] != digest or not UUID.fullmatch(thread or '')):
        raise ValueError('Original request, digest and conversation must match.')
    folder = Path(config['state']) / identity
    binding = {'id': identity, 'input_sha256': digest, 'thread_id': thread}
    queue_id = original['desktop_message_id']
    journal = read_record(folder / 'desktop-notification.json') or {}
    message_sha = journal.get('message_sha256') or ''
    queue_acknowledged = bool(UUID.fullmatch(queue_id or '') and SHA256.fullmatch(message_sha)
        and all(journal.get(key) == value for key, value in binding.items())
        and journal.get('state') == 'queued' and journal.get('desktop_message_id') == queue_id
        and journal.get('exit_code') == 0
        and (journal.get('stdout') or '').strip() == f'Queued message {queue_id} for thread {thread}.')

    observed = None
    turn_evidence = 'unchecked'
    if rollout and queue_acknowledged:
        observed = observed_turn(rollout, thread, message_sha)
        turn_evidence = 'observed' if observed else 'not_observed'
    checkpoint = read_record(folder / 'desktop-execution.json')
    frozen = read_record(folder / 'desktop-completion.json')
    recorded_turn = original['turn_id']
    for record in (checkpoint, frozen):
        if record is not None and (any(record.get(key) != value for key, value in binding.items())
                                   or not UUID.fullmatch(record.get('turn_id') or '')):
            raise ValueError('Saved evidence does not match the original request.')
    turns = {turn for turn in (observed, recorded_turn, (checkpoint or {}).get('turn_id'),
                               (frozen or {}).get('turn_id')) if turn}
    if len(turns) > 1:
        raise ValueError('The original evidence names different Codex turns.')

    accepted = original['state'] == 'completed' and bool(UUID.fullmatch(recorded_turn or ''))
    if frozen is not None:
        text = frozen.get('text')
        if not isinstance(text, str) or not text.strip() or '\0' in text:
            raise ValueError('The saved completion does not contain a valid reply.')
        completion_text(original['body'], text)
        if accepted and text != original['text']:
            raise ValueError('The frozen reply differs from the accepted result.')
    receipt = {'state': 'unverified'}
    if accepted:
        native = delivery(config, identity, thread, recorded_turn, wait=False)
        if native.get('id') != identity:
            raise ValueError('The delivery receipt names a different original request.')
        receipt = {key: native[key] for key in ('state', 'code', 'native_request_id') if key in native}
        if receipt.get('code') == 'DELIVERY_STATUS_UNAVAILABLE':
            receipt['state'] = 'unverified'

    return {
        'id': identity, 'input_sha256': digest, 'thread_id': thread, 'receiver_state': original['state'],
        'queue_acknowledged': queue_acknowledged,
        'turn_evidence': turn_evidence,
        'observed_turn_id': observed, 'checkpoint_turn_id': (checkpoint or {}).get('turn_id'),
        'completion': 'accepted' if accepted else 'frozen' if frozen is not None else 'unverified',
        'completion_turn_id': recorded_turn if accepted else (frozen or {}).get('turn_id'),
        'v2': receipt,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('id')
    parser.add_argument('--rollout', type=Path, help='Local Codex session history for the original target.')
    args = parser.parse_args()
    if not SHA256.fullmatch(args.id):
        parser.error('Full original request ID required.')
    try:
        config = json.loads(args.config.read_bytes())
        report = reconcile(config, args.id, args.rollout)
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    sys.stdout.buffer.write(encoded(report) + b'\n')


if __name__ == '__main__':
    main()
