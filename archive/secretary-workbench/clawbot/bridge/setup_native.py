"""Prepare the shared Desktop entry; only explicit --apply mutates launch configuration.

The setup lock serializes installers. All inputs are checked before a transaction,
which snapshots bytes/modes and launchctl state and rolls back ordinary failures.
A failed rollback is reported explicitly; the recovery backup is retained.
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import os
from pathlib import Path
import plistlib
import shlex
import stat
import subprocess
import tempfile

from .native_runner import NODE as LEGACY_NODE, THREAD

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'cn.tashan.weixin-desktop-entry'
CLI = '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'
# Desktop native pipes validate the signing identity of process ancestors too.
# A Node.js Foundation runtime here makes OpenAI-signed MCP children fail auth.
NODE = '/Applications/ChatGPT.app/Contents/Resources/cua_node/bin/node'
ENV = 'CODEX_CLI_PATH'


@dataclass(frozen=True)
class FileState:
    data: bytes
    mode: int


@dataclass(frozen=True)
class SetupPlan:
    root: Path
    launchagents_dir: Path
    restore: bool
    files: dict
    desktop_exists: bool
    override: str
    override_present: bool
    loaded: bool
    script: bytes
    agent: bytes
    config: dict
    backup: dict | None

    @property
    def desktop(self): return self.root / 'desktop'
    @property
    def wrapper(self): return self.desktop / 'codex-shared-entry'
    @property
    def target(self): return self.launchagents_dir / (LABEL + '.plist')
    @property
    def backup_path(self): return self.root / 'desktop-entry-backup.json'
    @property
    def config_path(self): return self.root / 'native-context.json'


def _path(path):
    p = Path(os.path.abspath(path))
    if any(q.is_symlink() for q in (p, *p.parents)):
        raise ValueError('symlink path refused')
    return p


def _directory(path, *, private=True, optional=False):
    p = _path(path)
    if not p.exists() and optional:
        return False
    s = p.stat()
    forbidden = 0o077 if private else 0o022
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & forbidden:
        raise ValueError('unsafe directory ownership or permissions')
    return True


def _snapshot(path):
    p = _path(path)
    if not p.exists(): return None
    limit = 1048576 if p.name == 'desktop-entry-backup.json' else 65536
    with os.fdopen(os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as f:
        s = os.fstat(f.fileno())
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or
                s.st_nlink != 1 or s.st_mode & 0o077 or s.st_size > limit):
            raise ValueError('unsafe setup file ownership, permissions, type, or size')
        data = f.read(limit + 1)
        if len(data) > limit: raise ValueError('setup file exceeded size limit')
        return FileState(data, stat.S_IMODE(s.st_mode))


def _object(state, name):
    if state is None: return None
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj: raise ValueError('duplicate JSON key')
            obj[key] = value
        return obj
    try:
        value = json.loads(state.data, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ValueError('invalid ' + name) from error
    if not isinstance(value, dict): raise ValueError('invalid ' + name)
    return value


def _run(execute, *args, check=True):
    result = execute(['launchctl', *args], capture_output=True, text=True, check=False)
    if check and result.returncode:
        raise subprocess.CalledProcessError(result.returncode, ['launchctl', *args],
                                            output=result.stdout, stderr=result.stderr)
    return result


def _control(execute):
    result = _run(execute, 'getenv', ENV, check=False)
    if result.returncode not in (0, 1):
        raise ValueError('cannot read current CLI override')
    # launchctl appends one line terminator; do not strip meaningful whitespace.
    current = result.stdout.removesuffix('\n')
    if '\n' in current or '\x00' in current or (current and not Path(current).is_absolute()):
        raise ValueError('invalid CLI override')
    status = _run(execute, 'print', f'gui/{os.getuid()}/{LABEL}', check=False)
    if status.returncode not in (0, 113):
        raise ValueError('cannot determine LaunchAgent state')
    return current, status.returncode == 0, result.returncode == 0


def plan_setup(workspace, *, launchagents_dir=None, execute=subprocess.run, restore=False):
    """Validate ownership and contents, then read control state; never write."""
    root = _path(workspace)
    agents = _path(launchagents_dir or Path.home() / 'Library/LaunchAgents')
    _directory(root)
    _directory(agents, private=False)
    desktop = root / 'desktop'
    desktop_exists = _directory(desktop, optional=True)
    wrapper = desktop / 'codex-shared-entry'
    target = agents / (LABEL + '.plist')
    backup_path, config_path = root / 'desktop-entry-backup.json', root / 'native-context.json'
    files = {p: _snapshot(p) for p in (wrapper, target, backup_path, config_path)}
    _snapshot(agents / ('.' + LABEL + '.lock'))
    command = 'exec ' + shlex.quote(NODE) + ' ' + shlex.quote(str(ROOT / 'bridge/desktop_launcher.mjs')) + ' "$@"\n'
    prefix = '#!/bin/sh\nexport TASHAN_DESKTOP_SOCKET_ROOT=' + shlex.quote(str(desktop)) + '\n'
    script = (prefix + 'if [ -x ' + shlex.quote(NODE) + ' ] && [ -f ' + shlex.quote(str(ROOT / 'bridge/desktop_launcher.mjs')) + ' ] && ' + shlex.quote(NODE) + ' --check ' + shlex.quote(str(ROOT / 'bridge/desktop_launcher.mjs')) + ' >/dev/null 2>&1; then\n' + command + 'fi\n' +
              "printf '%s\\n' 'WeChat startup adapter unavailable; using official native startup.' >&2\n" +
              'exec ' + shlex.quote(CLI) + ' "$@"\n').encode()
    checked_preflight = script
    pause_code = """import os,sys,stat,tempfile,json
root=sys.argv[1]
s=os.lstat(root)
assert stat.S_ISDIR(s.st_mode) and not stat.S_ISLNK(s.st_mode) and s.st_uid==os.getuid() and not s.st_mode&0o077
filename=os.path.join(root,'bridge-state.json')
try:
 s=os.lstat(filename)
 assert stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and s.st_nlink==1 and not s.st_mode&0o077
except FileNotFoundError:
 pass
fd,tmp=tempfile.mkstemp(prefix='.bridge-state-',dir=root)
try:
 with os.fdopen(fd,'w') as f:
  json.dump({'version':1,'enabled':False,'reason':'shell_preflight_failed'},f)
  f.flush();os.fsync(f.fileno())
 os.replace(tmp,filename)
finally:
 if os.path.exists(tmp):os.unlink(tmp)
"""
    pause = '/usr/bin/python3 -c ' + shlex.quote(pause_code) + ' "$TASHAN_DESKTOP_SOCKET_ROOT" >/dev/null 2>&1 || true\n'
    script = checked_preflight.replace(b'fi\n', ('fi\n' + pause).encode(), 1)
    legacy_command = 'exec ' + shlex.quote(LEGACY_NODE) + ' ' + shlex.quote(str(ROOT / 'bridge/desktop_launcher.mjs')) + ' "$@"\n'
    previous_preflight = (prefix + 'if [ -x ' + shlex.quote(NODE) + ' ] && [ -f ' + shlex.quote(str(ROOT / 'bridge/desktop_launcher.mjs')) + ' ]; then\n' + command + 'fi\n' +
              "printf '%s\\n' 'WeChat startup adapter unavailable; using official native startup.' >&2\n" + 'exec ' + shlex.quote(CLI) + ' "$@"\n').encode()
    allowed_scripts = {script, checked_preflight, previous_preflight, (prefix + command).encode(), ('#!/bin/sh\n' + command).encode(),
                       ('#!/bin/sh\n' + legacy_command).encode(),
                       ('#!/bin/sh\nexport TASHAN_DESKTOP_SOCKET_ROOT=' + shlex.quote(str(desktop)) + '\n' + legacy_command).encode()}
    if files[wrapper] and files[wrapper].data not in allowed_scripts:
        raise ValueError('existing wrapper differs')
    agent = {'Label': LABEL, 'ProgramArguments': ['/bin/launchctl', 'setenv', ENV, str(wrapper)], 'RunAtLoad': True}
    if files[target]:
        try: existing = plistlib.loads(files[target].data)
        except Exception as error: raise ValueError('invalid LaunchAgent') from error
        if existing != agent: raise ValueError('foreign or mismatched LaunchAgent')
    config = _object(files[config_path], 'native context') or {}
    if config.get('thread_id', THREAD) != THREAD:
        raise ValueError('foreign native context thread')
    if config.get('socket_path', str(desktop / 'control.sock')) != str(desktop / 'control.sock'):
        raise ValueError('foreign native context socket')
    if 'enabled' in config and not isinstance(config['enabled'], bool):
        raise ValueError('invalid native enabled state')
    backup = _object(files[backup_path], 'Desktop entry backup')
    if backup is not None:
        previous = backup.get('previous_override')
        if not isinstance(previous, str) or '\n' in previous or '\x00' in previous or (previous and not Path(previous).is_absolute()):
            raise ValueError('invalid backup override')
        if 'previous_override_present' in backup and not isinstance(backup['previous_override_present'], bool):
            raise ValueError('invalid backup override presence')
        if backup.get('workspace', str(root)) != str(root):
            raise ValueError('backup belongs to another workspace')
        if previous == str(wrapper): raise ValueError('backup points back to managed wrapper')
    if restore and (backup is None or files[config_path] is None):
        raise ValueError('restore requires a valid backup and native context')
    current, loaded, present = _control(execute)
    allowed = {'', str(wrapper)}
    if backup is not None: allowed.add(backup['previous_override'])
    else: allowed.add(CLI)
    if current not in allowed: raise ValueError('unrelated CLI override is active')
    if backup is None and current == str(wrapper):
        raise ValueError('managed CLI override has no recovery backup')
    if loaded and files[target] is None:
        raise ValueError('loaded LaunchAgent has no matching owned plist')
    return SetupPlan(root, agents, restore, files, desktop_exists, current, present, loaded,
                     script, plistlib.dumps(agent), config, backup)


def _atomic(path, state):
    """Write private bytes and mode atomically; no shell or config rewriting."""
    _snapshot(path)
    limit = 1048576 if path.name == 'desktop-entry-backup.json' else 65536
    if len(state.data) > limit: raise ValueError('setup file exceeds size limit')
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            os.fchmod(f.fileno(), state.mode)
            f.write(state.data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        parent_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(parent_fd)
        finally: os.close(parent_fd)
    finally:
        if os.path.exists(name): os.unlink(name)


def _json(value):
    return FileState((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode(), 0o600)


@contextmanager
def _lock(agents):
    _directory(agents, private=False)
    path = agents / ('.' + LABEL + '.lock')
    _snapshot(path)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        s = os.fstat(fd)
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid() or
                s.st_nlink != 1 or s.st_mode & 0o077):
            raise ValueError('unsafe setup lock')
        try: fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error: raise ValueError('another native setup is running') from error
        yield
    finally:
        os.close(fd)
    # Keep the inode: unlinking a flock file allows concurrent lock holders.


def _set_override(execute, value, *, present=None):
    if present is None: present = bool(value)
    if present: _run(execute, 'setenv', ENV, value)
    else: _run(execute, 'unsetenv', ENV)


def _restore_file(path, state):
    if _snapshot(path) == state: return
    if state is None: path.unlink(missing_ok=True)
    else: _atomic(path, state)


def apply_plan(plan, *, execute=subprocess.run):
    """Revalidate under a shared setup lock, then apply or restore transactionally."""
    with _lock(plan.launchagents_dir):
        fresh = plan_setup(plan.root, launchagents_dir=plan.launchagents_dir,
                           execute=execute, restore=plan.restore)
        if fresh != plan: raise ValueError('setup state changed; create a fresh plan')
        domain = f'gui/{os.getuid()}'
        env_attempted = False
        service_attempted = False
        created_desktop = False
        try:
            if plan.backup is None:
                snapshots = {str(p.relative_to(plan.root)) if p.is_relative_to(plan.root) else 'launchagent':
                             None if s is None else {'base64': base64.b64encode(s.data).decode(), 'mode': s.mode}
                             for p, s in plan.files.items() if p != plan.backup_path}
                _atomic(plan.backup_path, _json({'version': 1, 'workspace': str(plan.root),
                    'previous_override': plan.override, 'previous_override_present': plan.override_present,
                    'previous_loaded': plan.loaded, 'files': snapshots}))
            config = dict(plan.config)
            config.update(enabled=not plan.restore, thread_id=THREAD, socket_path=str(plan.desktop / 'control.sock'))
            if plan.restore:
                # Preserve a disabled native context so the worker cannot fall back.
                _atomic(plan.config_path, _json(config))
                if plan.loaded:
                    service_attempted = True
                    _run(execute, 'bootout', domain, str(plan.target))
                env_attempted = True
                _set_override(execute, plan.backup['previous_override'],
                              present=plan.backup.get('previous_override_present'))
                plan.target.unlink(missing_ok=True)
            else:
                if not plan.desktop_exists:
                    plan.desktop.mkdir(mode=0o700)
                    created_desktop = True
                _atomic(plan.wrapper, FileState(plan.script, 0o700))
                _atomic(plan.config_path, _json(config))
                _atomic(plan.target, FileState(plan.agent, 0o600))
                env_attempted = True
                _set_override(execute, str(plan.wrapper))
                if not plan.loaded:
                    service_attempted = True
                    _run(execute, 'bootstrap', domain, str(plan.target))
        except BaseException as cause:
            errors = []
            def recover(action):
                try: action()
                except BaseException as error: errors.append(error)
            # Stop a possibly partially bootstrapped job before removing its plist.
            if service_attempted and not plan.loaded:
                def stop_added():
                    _, loaded, _ = _control(execute)
                    if loaded: _run(execute, 'bootout', domain, str(plan.target))
                recover(stop_added)
            for path, state in plan.files.items():
                if path != plan.backup_path:
                    recover(lambda p=path, s=state: _restore_file(p, s))
            if service_attempted and plan.loaded:
                def reload_original():
                    _, loaded, _ = _control(execute)
                    if not loaded: _run(execute, 'bootstrap', domain, str(plan.target))
                recover(reload_original)
            if env_attempted or service_attempted:
                recover(lambda: _set_override(execute, plan.override, present=plan.override_present))
            if created_desktop: recover(plan.desktop.rmdir)
            if not errors:
                recover(lambda: _restore_file(plan.backup_path, plan.files[plan.backup_path]))
            if errors:
                raise RuntimeError('native setup failed; rollback incomplete; retain recovery backup at ' + str(plan.backup_path)) from cause
            raise
    return plan


def main(argv=None, *, execute=subprocess.run, launchagents_dir=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args(argv)
    if not args.workspace:
        parser.print_help()
        return
    if not args.apply:
        print('Dry run: explicit --apply required; no files or launch configuration changed.')
        print('Original conversation:', THREAD)
        return
    plan = plan_setup(args.workspace, launchagents_dir=launchagents_dir, execute=execute, restore=args.restore)
    apply_plan(plan, execute=execute)
    if args.restore:
        print('Original Desktop entry restored; native forwarding suspended. Reopen the app to apply.')
    else:
        print('Shared Desktop entry configured. Current app is not restarted; native verification remains pending.')


if __name__ == '__main__': main()
