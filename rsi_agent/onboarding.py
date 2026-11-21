"""Prepare a new installation and report each readiness stage without sending input."""
import csv
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

from .config import WECHAT_LINUX, load
from .wechat import doctor, private_file


def capture_module():
    spec = importlib.util.spec_from_file_location('rsi_setup_capture', WECHAT_LINUX / 'capture.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_capture(installation, binary='/opt/wechat/wechat'):
    if sys.platform != 'linux':
        raise ValueError('Prepare account authorization inside the client Linux environment.')
    if not private_file(installation):
        raise ValueError('An explicit private installation owned by the account user is required.')
    config = load(installation)
    module = capture_module()
    script = module.prepare(binary=binary, root=config['wechat']['runtime_root'])
    return {'state': 'prepared', 'capture_script': str(script),
            'client_version': module.release()['version'], 'gdb_present': shutil.which('gdb') is not None,
            'client_restarted': False, 'authorization_captured': False,
            'next': 'Use the prepared own-child script only in an authorized client restart window.'}


def private_directory(path):
    path.mkdir(mode=0o700)
    if sys.platform == 'win32':
        system = Path(os.environ['WINDIR']) / 'System32'
        try:
            result = subprocess.run([str(system / 'whoami.exe'), '/user', '/fo', 'csv', '/nh'],
                capture_output=True, text=True, check=True, timeout=10)
            sid = next(csv.reader(result.stdout.splitlines()))[-1]
            if not re.fullmatch(r'S-1-[0-9-]+', sid):
                raise ValueError('Could not determine the current Windows account SID.')
            subprocess.run([str(system / 'icacls.exe'), str(path), '/inheritance:r',
                '/grant:r', '*' + sid + ':(OI)(CI)F'], check=True, capture_output=True, timeout=10)
        except (OSError, subprocess.SubprocessError, StopIteration, IndexError):
            raise ValueError('Could not restrict the new pairing directory to the current Windows account.') from None


def native_file(value, label):
    path = Path(value)
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError(label + ' must be an existing absolute regular file.')
    return str(path)


def linux_path(value):
    if (not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value)
            or '..' in PurePosixPath(value).parts or len(PurePosixPath(value).parts) < 2):
        raise ValueError('Explicit absolute Linux installation paths are required.')
    return value.rstrip('/')


def write_private(path, text):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        stream.write(text)


def stage_pairing(output, codex, thread, ssh, identity_file, port=8765, remote_port=8766,
                  remote_root='/var/lib/rsi-agent', runtime_root='/var/lib/rsi-agent/wechat'):
    codex = native_file(codex, 'Codex executable')
    identity_file = native_file(identity_file, 'SSH identity')
    try:
        valid_thread = str(uuid.UUID(thread)) == thread
    except (ValueError, AttributeError):
        valid_thread = False
    if not valid_thread or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', ssh):
        raise ValueError('An actual dedicated conversation UUID and explicit SSH alias are required.')
    if (type(port) is not int or type(remote_port) is not int
            or not 1024 <= port <= 65535 or not 1024 <= remote_port <= 65535 or port == remote_port):
        raise ValueError('Use distinct unprivileged local and remote loopback ports.')
    remote_root, runtime_root = linux_path(remote_root), linux_path(runtime_root)
    runtime_path = PurePosixPath(runtime_root)
    coordinator = PurePosixPath(remote_root) / 'codex'
    if (runtime_path == PurePosixPath(remote_root) or runtime_path in PurePosixPath(remote_root).parents
            or runtime_path == coordinator or coordinator in runtime_path.parents):
        raise ValueError('Account runtime and coordinator files must keep distinct ownership directories.')
    output = Path(output).absolute()
    if output.exists() or any(part.is_symlink() for part in (output, *output.parents)):
        raise ValueError('Stage pairing only into a NEW directory; existing configurations and queues are preserved.')
    if not output.parent.is_dir():
        raise ValueError('The pairing directory parent must already exist.')
    private_directory(output)
    for relative in ('receiver-state', 'linux', 'linux/codex', 'linux/codex/state'):
        (output / relative).mkdir(mode=0o700)
    token = secrets.token_hex(32)
    receiver = {'codex': codex, 'token': token, 'state': str(output / 'receiver-state'),
        'port': port, 'desktop_thread_id': thread, 'desktop_all_requests': True,
        'ssh': ssh, 'identity_file': identity_file, 'remote_port': remote_port}
    backend = {'backend': 'local-codex', 'endpoint': 'http://127.0.0.1:' + str(remote_port),
        'token_file': remote_root + '/codex/token.txt', 'state': remote_root + '/codex/state',
        'model': 'local-codex', 'preferences_file': remote_root + '/codex/preferences.json',
        'engineering': False}
    installation = load()
    installation['wechat'].update(display=':92', xauthority='/run/wechat-gui/Xauthority',
                                  runtime_root=runtime_root)
    receiver_check = {name: receiver[name] for name in
                      ('token', 'port', 'remote_port', 'desktop_thread_id', 'desktop_all_requests')}
    files = {'local-codex.json': receiver, 'linux/receiver-check.json': receiver_check, 'linux/codex/model.json': backend,
             'linux/codex/preferences.json': {}, 'linux/installation.json': installation}
    for name, value in files.items():
        write_private(output / name, json.dumps(value, ensure_ascii=False, indent=2))
    write_private(output / 'linux/codex/token.txt', token)
    plan = {'schema_version': 1, 'state': 'staged', 'activated': False, 'paired': False,
        'receiver_config': str(output / 'local-codex.json'),
        'linux_files': {'codex': {'destination': remote_root + '/codex', 'owner': 'root'},
                        'receiver-check.json': {'destination': runtime_root + '/receiver-check.json', 'owner': 'wechat-gui'},
                        'installation.json': {'destination': runtime_root + '/installation.json', 'owner': 'wechat-gui'}},
        'account_authorized': False, 'operations_enabled': False,
        'next': 'Install the staged Linux files with their declared owners, configure the SSH tunnel, then run setup check --probe.'}
    write_private(output / 'plan.json', json.dumps(plan, indent=2))
    return plan


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


def receiver_stage(path, probe=False, remote=False):
    if not path:
        return {'state': 'blocked', 'code': 'RECEIVER_CONFIG_REQUIRED'}
    try:
        source = Path(path)
        if (not source.is_file() or source.is_symlink() or source.stat().st_size > 64000
                or sys.platform == 'linux' and not private_file(source)):
            return {'state': 'blocked', 'code': 'RECEIVER_CONFIG_NOT_PRIVATE_OR_MISSING'}
        config = json.loads(source.read_text(encoding='utf-8-sig'))
        if (not isinstance(config, dict) or not re.fullmatch('[a-f0-9]{64}', config.get('token', ''))
                or config.get('desktop_all_requests') is not True
                or str(uuid.UUID(config['desktop_thread_id'])) != config['desktop_thread_id']):
            raise ValueError('Receiver configuration is incomplete.')
        port = config['remote_port' if remote else 'port']
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Explicit loopback port required.')
        if not probe:
            return {'state': 'configured', 'connected': False}
        request = Request('http://127.0.0.1:' + str(port) + '/health',
                          headers={'Authorization': 'Bearer ' + config['token']})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=5) as response:
            body = response.read(65537)
            if len(body) > 65536:
                raise ValueError('Health response exceeded budget.')
            health = json.loads(body)
        if (health.get('backend') != 'local-codex' or health.get('ready') is not True
                or health.get('desktop_all_requests') is not True
                or health.get('desktop_thread_id') != config['desktop_thread_id']):
            return {'state': 'blocked', 'code': 'RECEIVER_NOT_READY_OR_TARGET_MISMATCH'}
        return {'state': 'ready', 'connected': True}
    except HTTPError as error:
        return {'state': 'blocked', 'code': 'RECEIVER_AUTH_REJECTED' if error.code == 403 else 'RECEIVER_HTTP_ERROR'}
    except (URLError, TimeoutError, OSError):
        return {'state': 'blocked', 'code': 'RECEIVER_UNREACHABLE'}
    except (ValueError, KeyError, TypeError, AttributeError):
        return {'state': 'blocked', 'code': 'RECEIVER_CONFIG_OR_HEALTH_INVALID'}


def check(installation=None, receiver_config=None, probe=False, remote=False, binary='/opt/wechat/wechat'):
    receiver = receiver_stage(receiver_config, probe, remote)
    stages = {'receiver': receiver}
    if sys.platform != 'linux':
        stages['wechat'] = {'state': 'not_checked', 'code': 'RUN_LINUX_CHECK_IN_CLIENT_DISTRO'}
        return {'state': 'incomplete', 'stages': stages, 'ready_for_acceptance': False,
                'live_delivery': 'not_verified', 'next': 'Run setup check as the Linux account-data owner inside the client distro.'}
    config = load(installation)
    status = doctor(config)
    runtime = Path(config['wechat']['runtime_root'])
    try:
        runtime_owned = (runtime.is_dir() and not runtime.is_symlink()
                         and runtime.stat().st_uid == os.getuid() and not runtime.stat().st_mode & 0o077)
    except OSError:
        runtime_owned = False
    module = capture_module()
    try:
        module.verify_binary(binary)
        client = {'state': 'ready', 'version': module.release()['version']}
    except (OSError, ValueError):
        client = {'state': 'blocked', 'code': 'REVIEWED_CLIENT_REQUIRED'}
    dependencies = {name: available for name, available in {
        'crypto': status['read']['checks']['crypto_installed'],
        'pillow': status['desktop']['checks']['pillow_installed'],
        'gtk': status['desktop']['checks']['gtk_installed'],
        **{name: shutil.which(name) is not None for name in ('xauth', 'xdpyinfo', 'xwininfo', 'xprop', 'tesseract', 'Xephyr', 'openbox', 'nc')},
        'sshd': (Path('/usr/sbin/sshd').is_file() or shutil.which('sshd') is not None),
    }.items()}
    missing = [name for name, present in dependencies.items() if not present]
    gdb_present = shutil.which('gdb') is not None
    stages.update(client=client,
        runtime_owner={'state': 'ready' if runtime_owned else 'blocked',
                       'code': 'ACCOUNT_RUNTIME_OWNED' if runtime_owned else 'RUN_AS_ACCOUNT_RUNTIME_OWNER'},
        dependencies={'state': 'blocked' if missing else 'ready', 'missing': missing},
        authorization_preparation={'state': 'not_required' if status['read']['ready'] else
            'ready' if gdb_present and client['state'] == 'ready' else 'blocked',
            'gdb_present': gdb_present, 'client_restart_automatic': False},
        account={'state': 'configured' if status['read']['ready'] else 'blocked',
                 'checks': status['read']['checks'], 'native_read_verified': False},
        display={'state': 'configured' if status['desktop']['dependencies_ready'] else 'blocked',
                 'checks': status['desktop']['checks'], 'login_verified': False},
        sender={'state': 'configured' if status['operations']['ready'] else 'blocked',
                'checks': status['operations']['checks']})
    complete = (runtime_owned and client['state'] == 'ready' and not missing and status['operations']['ready']
                and receiver['state'] == 'ready')
    if not runtime_owned:
        next_step = 'Create a private runtime owned by the account user and run the Linux check as that user; coordinator files keep their own owner.'
    elif client['state'] != 'ready':
        next_step = 'Install the reviewed client; preserve the hash check when the download URL changes.'
    elif missing:
        next_step = 'Install the listed runtime dependencies inside the client distro.'
    elif not status['read']['ready']:
        next_step = ('Prepare account authorization before first login; existing logins need a separately authorized own-child restart.'
            if gdb_present else 'Install the reviewed GDB authorization dependency before first login, then run setup prepare-capture; no restart is automatic.')
    elif not status['operations']['ready']:
        next_step = 'Verify the actual account, display and recipient binding, then configure the original V2 sender.'
    elif receiver['state'] != 'ready':
        next_step = 'Check the original receiver configuration and SSH loopback with --probe --remote.'
    else:
        next_step = 'Run native read/layout checks and one authorized fresh-message acceptance; configuration readiness is not delivery.'
    return {'state': 'configured' if complete else 'incomplete', 'stages': stages,
            'ready_for_acceptance': complete, 'live_delivery': 'not_verified', 'next': next_step}
