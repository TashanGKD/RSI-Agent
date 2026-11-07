"""The adapter configures one existing client and delegates to the original SDK."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config import WORKBENCH

READ_ACTIONS = {'resolve', 'messages', 'voice', 'attachments', 'attachment'}


def private_file(path):
    p = Path(path)
    return (p.is_file() and not p.is_symlink() and not p.stat().st_mode & 0o077
            and hasattr(os, 'getuid') and p.stat().st_uid == os.getuid())


def gtk_available():
    try:
        gi = importlib.import_module('gi')
        gi.require_version('Gtk', '3.0')
        importlib.import_module('gi.repository.Gtk')
        return True
    except (ImportError, ValueError):
        return False


def doctor(config):
    wx = config['wechat']
    root = Path(wx['runtime_root'])
    linux = sys.platform == 'linux'
    read = {
        'linux': linux, 'account_configured': bool(wx['account']),
        'profile_configured': bool(wx['profile']) and (Path(wx['profile']) / 'db_storage').is_dir(),
        'private_keys_present': private_file(root / 'db-keys.json'),
        'crypto_installed': importlib.util.find_spec('Crypto') is not None,
    }
    desktop = {'linux': linux, 'xauthority_present': private_file(wx['xauthority']),
               'pillow_installed': importlib.util.find_spec('PIL') is not None,
               'gtk_installed': gtk_available(),
               'xwininfo_installed': shutil.which('xwininfo') is not None,
               'xprop_installed': shutil.which('xprop') is not None}
    operations = {
        'enabled': wx['operations_enabled'], 'read_ready': all(read.values()),
        'desktop_dependencies_ready': all(desktop.values()), 'ocr_installed': shutil.which('tesseract') is not None,
        'ui_binding_present': private_file(root / 'native-ui.json'),
        'operation_config_present': private_file(root / 'operations-state/config.json'),
    }
    return {
        'display': wx['display'], 'inspection': 'prerequisites only; no GUI or message read',
        'read': {'ready': all(read.values()), 'checks': read},
        'desktop': {'dependencies_ready': all(desktop.values()), 'checks': desktop},
        'operations': {'ready': all(operations.values()), 'checks': operations},
        'live_acceptance': 'not verified by this command',
    }


def environment(config):
    wx = config['wechat']
    source = WORKBENCH / 'wechat'
    env = dict(os.environ,
               WECHAT_DISPLAY=wx['display'], WECHAT_XAUTHORITY=wx['xauthority'],
               WECHAT_TOOL_ROOT=wx['runtime_root'], WECHAT_NATIVE_CODE=str(source),
               WECHAT_HOST_SUPPORT_CODE=str(source / 'host_support'),
               WECHAT_OCR_ROOT='/usr/share/tesseract-ocr/5', WECHAT_OCR_RUNTIME='/')
    if wx['profile']:
        env['WECHAT_PROFILE'] = wx['profile']
    if wx['account']:
        env['WECHAT_ACCOUNT_ID'] = wx['account']
    return env


def call(config, mode, request):
    if not isinstance(request, dict):
        raise ValueError('A JSON object is required.')
    if mode == 'read' and request.get('action') not in READ_ACTIONS:
        raise ValueError('The read entry accepts only resolve/messages/voice/attachments/attachment.')
    if mode == 'operations' and request.get('op') == 'get':
        state = Path(config['wechat']['runtime_root']) / 'operations-state'
        if not (sys.platform == 'linux' and private_file(state / 'config.json')
                and private_file(state / 'queue.sqlite')):
            raise ValueError('Existing private operations configuration and queue required for receipt lookup.')
    else:
        status = doctor(config)
        if not status['read' if mode == 'read' else 'operations']['ready']:
            raise ValueError('WeChat prerequisites are incomplete; run doctor before reading or writing.')
    source = WORKBENCH / 'wechat'
    command = [sys.executable, '-B', str(source / 'linux_tool.py'), '--execute']
    if mode == 'operations':
        state = Path(config['wechat']['runtime_root']) / 'operations-state'
        command = [sys.executable, '-B', '-m', 'operations.cli', 'request', '--execute',
                   '--root', str(state), '--config', str(state / 'config.json')]
    result = subprocess.run(command, cwd=source, env=environment(config),
                            input=json.dumps(request, ensure_ascii=False), text=True)
    return result.returncode
