"""Read-only, allowlisted observations for the DSH WeChat status tool."""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import time

from .wechat import private_file


def read_object(path):
    if not private_file(path):
        raise ValueError('Private state required.')
    with Path(path).open(encoding='utf-8') as stream:
        value = json.loads(stream.read(65537))
    if not isinstance(value, dict):
        raise ValueError('Object required.')
    return value


def service_state(name, current):
    """Inspect fixed service names; never start, stop or signal a process."""
    result = subprocess.run(['systemctl', 'show', name, '--no-pager',
        '--property=ActiveState,MainPID,WorkingDirectory'], capture_output=True,
        text=True, timeout=3, check=True)
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    active = fields.get('ActiveState') == 'active' and int(fields.get('MainPID', '0')) > 0
    same = (active and Path('/proc', fields['MainPID'], 'cwd').resolve(strict=True) == current
            and Path(fields['WorkingDirectory']).resolve(strict=True) == current)
    return {'process_active': active, 'current_code': bool(same)}


def worker(path, channel, service, current, now):
    result = {'channel': channel, 'observation': 'unavailable'}
    try:
        result.update(service_state(service, current))
    except (OSError, ValueError, subprocess.SubprocessError):
        result.update(process_active=None, current_code=None)
    try:
        config = read_object(path)
        state = Path(config['state'])
        status = read_object(state / 'status.json')
        timestamp = status['checked_at']
        result['fresh'] = (type(timestamp) in (int, float) and 0 <= now - timestamp <= 90)
        allowed = {'idle', 'sent', 'pending', 'attention', 'media_pending',
                   'model_unavailable', 'transport_attention', 'quiet', 'stopped', 'waiting_codex'}
        result['observation'] = status['state'] if status.get('state') in allowed else 'unknown'
        result['enabled'] = config.get('enabled') is True
        backend = status.get('model_backend')
        result['model_backend'] = backend if backend in ('deepseek-harness', 'direct-scnet') else 'unknown'
        # Read only state/count, never message text, generated replies or native IDs.
        database = state / 'inbox.sqlite'
        if not private_file(database):
            raise ValueError('Private inbox required.')
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=1) as db:
            counts = dict(db.execute('SELECT state,count(*) FROM inbox GROUP BY state'))
        result['queue'] = {key: counts.get(key, 0) for key in ('new', 'pending', 'attention', 'local_codex')}
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        result['observation'] = 'unavailable'
    return result


def engineering(model_path):
    result = {'state': 'unavailable', 'retry_allowed': False}
    try:
        model = read_object(model_path)
        workspace = model.get('engineering_workspace')
        if not workspace:
            return dict(result, state='not_configured')
        marker = Path(workspace).parent / 'engineering-current.json'
        if not marker.exists():
            return dict(result, state='clear')
        # Presence alone blocks a second execution. A saved "running" record
        # does not establish whether a tool process is still alive.
        result['state'] = 'needs_review'
        request = read_object(marker)['request']
        if not isinstance(request, str) or not re.fullmatch('[a-f0-9]{64}', request):
            raise ValueError('Invalid original request.')
        receipt = read_object(Path(model['state']) / 'calls' / (request + '.json'))
        result['recorded_state'] = receipt['state'] if receipt.get('state') in ('running', 'sdk_completed', 'completed') else 'unknown'
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return result


def snapshot(owner_config, groups_config, release, current):
    now = time.time()
    current = Path(current).resolve()
    value = {'schema_version': 1, 'release': 'unknown', 'workers': [],
             'engineering': {'state': 'unavailable', 'retry_allowed': False},
             'scope': 'observations_only_not_delivery_acceptance'}
    try:
        # Release metadata is public code provenance, not an account file.
        metadata = json.loads(Path(release).read_text(encoding='utf-8'))
        commit = metadata.get('commit')
        if isinstance(commit, str) and re.fullmatch('[a-f0-9]{40}', commit):
            value['release'] = commit
    except (OSError, ValueError, AttributeError):
        pass
    value['workers'].append(worker(owner_config, 'owner', 'rsi-owner-replies.service', current, now))
    try:
        value['engineering'] = engineering(read_object(owner_config)['model'])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        groups = read_object(groups_config)['groups']
        if not isinstance(groups, list) or len(groups) > 100:
            raise ValueError('Bounded group registry required.')
        for index, path in enumerate(groups):
            value['workers'].append(worker(path, 'group-' + str(index + 1),
                'rsi-group-replies.service', current, now))
        value['group_registry'] = 'read'
    except (OSError, ValueError, KeyError, TypeError):
        value['group_registry'] = 'unavailable'
    admission_path = Path(groups_config).with_name('admission-status.json')
    if admission_path.exists():
        try:
            admission = read_object(admission_path)
            value['group_admission'] = {
                'state': admission['state'] if admission.get('state') in ('enabled', 'unavailable') else 'unknown',
                'fresh': 0 <= now - admission['checked_at'] <= 90,
                **{key: admission.get(key, 0) if type(admission.get(key, 0)) is int
                   and 0 <= admission.get(key, 0) <= 100 else None
                   for key in ('waiting_owner', 'unaddressable')}}
        except (OSError, ValueError, KeyError, TypeError):
            value['group_admission'] = {'state': 'unavailable'}
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('owner-config', 'groups-config', 'release', 'current'):
        parser.add_argument('--' + field, required=True)
    args = parser.parse_args()
    print(json.dumps(snapshot(args.owner_config, args.groups_config, args.release, args.current)))


if __name__ == '__main__':
    main()
