"""Owner-private action gateway for preconfigured, explicitly confirmed commands."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sqlite3
import subprocess
import threading
import time

from rsi_agent.wechat import private_file
from .owner_knowledge import owner_db

CONFIG_NAME = 'actions.json'
FORMAT_VERSION = 1
MAX_CONFIG_BYTES = 64 * 1024
MAX_ACTIONS = 32
MAX_PENDING = 8
MAX_RECORDS = 200
STAGE_SECONDS = 30 * 60
DEFAULT_TIMEOUT = 20
MAX_TIMEOUT = 60
MAX_OUTPUT_BYTES = 64 * 1024
MAX_EXCERPT_CHARS = 2000
MAX_REPLY_BYTES = 6000
ID_PATTERN = re.compile(r'^[0-9a-f]{16}$')

_TERMINAL = ('succeeded', 'failed', 'timeout', 'unknown', 'cancelled', 'expired', 'blocked')
_STATES = {
    'pending': '待确认', 'running': '执行中', 'succeeded': '成功', 'failed': '失败',
    'timeout': '超时', 'unknown': '状态未知', 'cancelled': '已取消',
    'expired': '已过期', 'blocked': '配置已变化，未执行',
}
_DANGEROUS_ENV = {
    'BASH_ENV', 'ENV', 'IFS', 'LD_LIBRARY_PATH', 'LD_PRELOAD', 'NODE_OPTIONS',
    'PERL5OPT', 'PYTHONPATH', 'PYTHONSTARTUP', 'RUBYOPT', 'SHELLOPTS',
}
_HELP = ('用法：\n'
         '动作 列表 — 查看已配置动作\n'
         '动作 准备 <名称> — 生成一次性确认编号\n'
         '动作 确认 <编号> — 执行一次\n'
         '动作 取消 <编号> — 取消待确认动作\n'
         '动作 查看 [编号] — 查看待确认与最近记录')


def _stamp(now=None):
    return int(time.time() if now is None else now)


def format_time(value):
    try:
        return datetime.fromtimestamp(int(value)).strftime('%Y-%m-%d %H:%M')
    except (OverflowError, OSError, ValueError):
        return '未知'


def _clip_bytes(value, limit=MAX_REPLY_BYTES):
    data = value.encode('utf-8')
    if len(data) <= limit:
        return value
    return data[:max(0, limit - 3)].decode('utf-8', 'ignore') + '…'


def _clean_output(value):
    value = value.replace('\r\n', '\n').replace('\r', '\n').replace('\0', '')
    value = ''.join(char for char in value if char in '\n\t' or ord(char) >= 32)
    return value.strip()


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate action configuration key.')
        value[key] = item
    return value


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _valid_name(value):
    return (isinstance(value, str) and bool(re.fullmatch(r'[^\s\[\]：:]{1,32}', value))
            and not any(ord(char) < 32 for char in value))


def _config(path):
    path = Path(path)
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file():
        raise ValueError('Private action configuration required.')
    if os.name == 'posix' and not private_file(path):
        raise ValueError('Private action configuration required.')
    if path.stat().st_size > MAX_CONFIG_BYTES:
        raise ValueError('Action configuration is too large.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeDecodeError, ValueError):
        raise ValueError('Action configuration is unreadable.') from None
    if (not isinstance(data, dict) or set(data) != {'version', 'actions'}
            or type(data['version']) is not int or data['version'] != FORMAT_VERSION
            or not isinstance(data['actions'], dict)
            or not 1 <= len(data['actions']) <= MAX_ACTIONS):
        raise ValueError('Invalid action configuration.')
    actions = {}
    for name, definition in data['actions'].items():
        if not _valid_name(name) or not isinstance(definition, dict):
            raise ValueError('Invalid action name or definition.')
        keys = set(definition)
        if not {'description', 'command'} <= keys <= {'description', 'command', 'cwd', 'timeout', 'env'}:
            raise ValueError('Invalid action definition.')
        description = definition['description']
        command = definition['command']
        if (not isinstance(description, str) or not description.strip()
                or len(description) > 200 or '\0' in description
                or not isinstance(command, list) or not 1 <= len(command) <= 32
                or any(not isinstance(item, str) or not item or '\0' in item
                       or len(item.encode()) > 4096 for item in command)
                or not Path(command[0]).is_absolute()):
            raise ValueError('Invalid action command.')
        cwd = definition.get('cwd')
        if cwd is not None and (not isinstance(cwd, str) or not Path(cwd).is_absolute()):
            raise ValueError('Action working directory must be absolute.')
        timeout = definition.get('timeout', DEFAULT_TIMEOUT)
        if type(timeout) is not int or not 1 <= timeout <= MAX_TIMEOUT:
            raise ValueError('Invalid action timeout.')
        env = definition.get('env', {})
        if not isinstance(env, dict) or len(env) > 16:
            raise ValueError('Invalid action environment.')
        for key, value in env.items():
            if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', key)
                    or key in _DANGEROUS_ENV or not isinstance(value, str) or '\0' in value
                    or len(value.encode()) > 4096):
                raise ValueError('Invalid action environment.')
        resolved = {
            'description': description, 'command': tuple(command),
            'cwd': cwd or str(path.absolute().parent), 'timeout': timeout, 'env': dict(env),
        }
        actions[name] = dict(resolved, sha256=hashlib.sha256(
            _canonical([name, resolved])).hexdigest())
    return actions


def _ready(action):
    executable = Path(action['command'][0])
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return '动作命令不可执行。'
    if not Path(action['cwd']).is_dir():
        return '动作工作目录不可用。'
    return None


def initialize(db):
    db.executescript(
        'CREATE TABLE IF NOT EXISTS owner_actions('
        'id TEXT PRIMARY KEY,action TEXT NOT NULL,definition_sha256 TEXT NOT NULL,'
        "state TEXT NOT NULL,source_id TEXT NOT NULL,approved_source_id TEXT,"
        'created INTEGER NOT NULL,expires_at INTEGER NOT NULL,approved_at INTEGER,'
        'started_at INTEGER,finished_at INTEGER,exit_code INTEGER,elapsed_ms INTEGER,'
        'stdout_sha256 TEXT,stderr_sha256 TEXT,stdout_excerpt TEXT,stderr_excerpt TEXT,'
        'truncated INTEGER NOT NULL DEFAULT 0,error TEXT);'
        'CREATE INDEX IF NOT EXISTS owner_actions_state ON owner_actions(state,created);')


def _expire(db, now):
    db.execute("UPDATE owner_actions SET state='expired',finished_at=?,"
               "error=COALESCE(error,'待确认时间已过期；未执行，也不会自动重试。') "
               "WHERE state='pending' AND expires_at<=?", (now, now))


def _prune(db):
    rows = db.execute("SELECT id FROM owner_actions WHERE state IN "
                      "('succeeded','failed','timeout','unknown','cancelled','expired','blocked') "
                      "ORDER BY created DESC LIMIT -1 OFFSET ?", (MAX_RECORDS,)).fetchall()
    for row in rows:
        db.execute('DELETE FROM owner_actions WHERE id=?', (row[0],))


def recover(db, now=None):
    """A process that died mid-action is unknown, never retried automatically."""
    stamp = _stamp(now)
    with db:
        db.execute("UPDATE owner_actions SET state='unknown',finished_at=?,"
                   "error=COALESCE(error,'执行过程在重启后无法确认；未自动重试。') "
                   "WHERE state='running'", (stamp,))
        _expire(db, stamp)
        _prune(db)


def _action_lines(actions):
    return ['{}：{}'.format(name, action['description']) for name, action in sorted(actions.items())]


def _pending(db):
    return db.execute("SELECT id,action,created,expires_at FROM owner_actions "
                      "WHERE state='pending' ORDER BY created,id").fetchall()


def _view(db, config_path, now, action_id=None):
    with db:
        _expire(db, now)
    try:
        actions = _config(config_path)
        config_error = None
    except ValueError:
        actions, config_error = {}, '动作配置不可用。'
    if action_id:
        row = db.execute('SELECT * FROM owner_actions WHERE id=?', (action_id,)).fetchone()
        if not row:
            return '没有找到这个动作记录。'
        lines = ['动作 {}（{}）：{}'.format(row['id'], row['action'], _STATES.get(row['state'], row['state']))]
        if row['state'] == 'pending':
            lines.append('确认截止：' + format_time(row['expires_at']))
        if row['started_at']:
            lines.append('开始：' + format_time(row['started_at']))
        if row['finished_at']:
            lines.append('结束：' + format_time(row['finished_at']))
        if row['exit_code'] is not None:
            lines.append('退出码：{}，用时 {:.1f} 秒。'.format(row['exit_code'], (row['elapsed_ms'] or 0) / 1000))
        if row['error']:
            lines.append('说明：' + row['error'])
        if row['stdout_excerpt']:
            lines.append('输出：\n' + row['stdout_excerpt'])
        if row['stderr_excerpt']:
            lines.append('错误输出：\n' + row['stderr_excerpt'])
        if row['truncated']:
            lines.append('输出过长，只保留了前一部分；完整日志请由动作自己写入私有位置。')
        return _clip_bytes('\n'.join(lines))
    lines = []
    if config_error:
        lines.append(config_error)
    elif not actions:
        lines.append('动作网关还没有配置。在私有状态目录放置 actions.json 后，再用「动作 列表」查看。')
    else:
        lines.append('已配置动作：')
        lines.extend(_action_lines(actions))
    pending = _pending(db)
    if pending:
        lines.append('待确认：')
        for row in pending:
            lines.append('{} {}（截止 {}）'.format(row['id'], row['action'], format_time(row['expires_at'])))
    else:
        lines.append('当前没有待确认动作。')
    recent = db.execute("SELECT id,action,state,created FROM owner_actions "
                        "WHERE state!='pending' ORDER BY created DESC LIMIT 5").fetchall()
    if recent:
        lines.append('最近记录：')
        for row in recent:
            lines.append('{} {}（{}，{}）'.format(row['id'], row['action'],
                                                _STATES.get(row['state'], row['state']),
                                                format_time(row['created'])))
    return _clip_bytes('\n'.join(lines))


def _stage(db, row, name, actions, now):
    action = actions.get(name)
    if action is None:
        return ('没有这个动作。可用：' + '、'.join(sorted(actions)) + '。'
                if actions else '动作网关还没有配置。')
    unavailable = _ready(action)
    if unavailable:
        return unavailable
    with db:
        _expire(db, now)
    pending = db.execute("SELECT id FROM owner_actions WHERE state='pending' AND action=? "
                         "ORDER BY created,id LIMIT 1", (name,)).fetchone()
    if pending:
        return '这个动作已有待确认记录 {}；先确认或取消，未重复准备。'.format(pending['id'])
    if len(_pending(db)) >= MAX_PENDING:
        return '待确认动作太多了。先确认或取消一些，再准备新的。'
    action_id = secrets.token_hex(8)
    with db:
        db.execute('INSERT INTO owner_actions(id,action,definition_sha256,state,source_id,'
                   'created,expires_at) VALUES(?,?,?,?,?,?,?)',
                   (action_id, name, action['sha256'], 'pending', row['id'],
                    now, now + STAGE_SECONDS))
        _prune(db)
    return ('已准备动作 {}：{}（{}）。回复「动作 确认 {}」执行一次，'
            '或「动作 取消 {}」取消；{} 分钟内有效。').format(
                action_id, name, action['description'], action_id, action_id, STAGE_SECONDS // 60)


def _environment(action):
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8'}
    for key in ('HOME', 'TZ'):
        if key in os.environ:
            env[key] = os.environ[key]
    env.update(action['env'])
    return env


def _drain(stream, chunks, state):
    size = 0
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            if size < MAX_OUTPUT_BYTES:
                keep = chunk[:MAX_OUTPUT_BYTES - size]
                chunks.append(keep)
                size += len(keep)
                if len(keep) < len(chunk):
                    state['truncated'] = True
            else:
                state['truncated'] = True
    except (OSError, ValueError):
        return


def _stop(process):
    if os.name == 'posix':
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            return
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass


def _execute(action):
    started = time.monotonic()
    kwargs = {'cwd': action['cwd'], 'env': _environment(action), 'stdin': subprocess.DEVNULL,
              'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE}
    if os.name == 'posix':
        kwargs['start_new_session'] = True
    try:
        process = subprocess.Popen(list(action['command']), **kwargs)
    except OSError as error:
        return {'state': 'failed', 'exit_code': None, 'elapsed_ms': 0, 'stdout': b'',
                'stderr': b'', 'truncated': False, 'error': str(error)}
    out, err, state = [], [], {'truncated': False}
    threads = [threading.Thread(target=_drain, args=(process.stdout, out, state), daemon=True),
               threading.Thread(target=_drain, args=(process.stderr, err, state), daemon=True)]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=action['timeout'])
    except subprocess.TimeoutExpired:
        timed_out = True
        _stop(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
    for thread in threads:
        thread.join(timeout=2)
    for stream in (process.stdout, process.stderr):
        try:
            stream.close()
        except OSError:
            pass
    stdout, stderr = b''.join(out), b''.join(err)
    elapsed = int((time.monotonic() - started) * 1000)
    if timed_out:
        result = {'state': 'timeout', 'exit_code': process.returncode,
                  'error': '超过 {} 秒，已终止；未自动重试。'.format(action['timeout'])}
    elif process.returncode:
        result = {'state': 'failed', 'exit_code': process.returncode,
                  'error': '命令返回非零退出码。'}
    else:
        result = {'state': 'succeeded', 'exit_code': 0, 'error': None}
    return dict(result, elapsed_ms=elapsed, stdout=stdout, stderr=stderr,
                truncated=state['truncated'])


def _result_reply(row, action, result):
    label = _STATES.get(result['state'], result['state'])
    lines = ['动作 {}（{}）：{}。'.format(row['id'], row['action'], label)]
    if result.get('exit_code') is not None:
        lines.append('退出码 {}，用时 {:.1f} 秒。'.format(result['exit_code'],
                                                       (result['elapsed_ms'] or 0) / 1000))
    if result.get('error'):
        lines.append(result['error'])
    stdout = _clean_output(result['stdout'].decode('utf-8', 'replace'))
    stderr = _clean_output(result['stderr'].decode('utf-8', 'replace'))
    if stdout:
        lines.append('输出：\n' + stdout[:MAX_EXCERPT_CHARS])
    if stderr:
        lines.append('错误输出：\n' + stderr[:MAX_EXCERPT_CHARS])
    if not stdout and not stderr and result['state'] == 'succeeded':
        lines.append('执行完成，没有输出。')
    if result.get('truncated'):
        lines.append('输出过长，只保留了前一部分；完整日志请由动作自己写入私有位置。')
    return _clip_bytes('\n'.join(lines))


def _approve(db, row, action_id, actions, now):
    record = db.execute('SELECT * FROM owner_actions WHERE id=?', (action_id,)).fetchone()
    if not record:
        return '没有找到这个动作，可能编号不对或记录已清理。'
    if record['state'] != 'pending':
        return '动作 {} 当前为{}，未重复执行。'.format(action_id, _STATES.get(record['state'], record['state']))
    if record['expires_at'] <= now:
        with db:
            _expire(db, now)
        return '动作 {} 已过期，未执行；请重新准备。'.format(action_id)
    action = actions.get(record['action'])
    if action is None or action['sha256'] != record['definition_sha256']:
        with db:
            db.execute("UPDATE owner_actions SET state='blocked',finished_at=?,"
                       "error='动作定义已变化，未执行；请重新准备。' WHERE id=? AND state='pending'",
                       (now, action_id))
        return '动作定义已变化，未执行；请重新准备并确认。'
    unavailable = _ready(action)
    if unavailable:
        with db:
            db.execute("UPDATE owner_actions SET state='blocked',finished_at=?,"
                       "error=? WHERE id=? AND state='pending'", (now, unavailable, action_id))
        return unavailable
    with db:
        changed = db.execute("UPDATE owner_actions SET state='running',approved_source_id=?,"
                             "approved_at=?,started_at=?,error=NULL "
                             "WHERE id=? AND state='pending'",
                             (row['id'], now, now, action_id)).rowcount
    if changed != 1:
        return '动作 {} 已被处理，未重复执行。'.format(action_id)
    try:
        result = _execute(action)
    except Exception as error:  # The action already started; report, never retry.
        result = {'state': 'failed', 'exit_code': None, 'elapsed_ms': 0, 'stdout': b'',
                  'stderr': b'', 'truncated': False, 'error': str(error)}
    stdout = result['stdout']
    stderr = result['stderr']
    with db:
        db.execute('UPDATE owner_actions SET state=?,finished_at=?,exit_code=?,elapsed_ms=?,'
                   'stdout_sha256=?,stderr_sha256=?,stdout_excerpt=?,stderr_excerpt=?,'
                   'truncated=?,error=? WHERE id=?',
                   (result['state'], _stamp(), result.get('exit_code'), result.get('elapsed_ms'),
                    hashlib.sha256(stdout).hexdigest(), hashlib.sha256(stderr).hexdigest(),
                    _clean_output(stdout.decode('utf-8', 'replace'))[:MAX_EXCERPT_CHARS] or None,
                    _clean_output(stderr.decode('utf-8', 'replace'))[:MAX_EXCERPT_CHARS] or None,
                    1 if result.get('truncated') else 0, result.get('error'), action_id))
        _prune(db)
    return _result_reply(record, action, result)


def command(db, row, config_path, now=None):
    """Handle one explicit owner action command; never invoked from model text."""
    text = (row['text'] or '').strip()
    if not text.startswith('动作'):
        return None
    known = re.match(r'^动作[ ：:]*(?:列表|清单|准备|新建|确认|执行|取消|查看|查询|帮助)', text)
    if text not in ('动作', '动作帮助') and not known:
        return None
    stamp = _stamp(now)
    if text in ('动作', '动作帮助') or re.fullmatch(r'动作[ ：:]*帮助', text):
        return _HELP
    if re.fullmatch(r'动作[ ：:]*(?:列表|清单)', text):
        return _view(db, config_path, stamp)
    match = re.fullmatch(r'动作[ ：:]*(?:准备|新建)(?:[ ：:]+([^\s]{1,32}))?', text)
    if match:
        try:
            actions = _config(config_path)
        except ValueError:
            return '动作配置不可用，未执行；请检查私有 actions.json。'
        if not match[1]:
            return '用法：动作 准备 <名称>' + ('\n可用：' + '、'.join(sorted(actions)) if actions else '')
        return _stage(db, row, match[1], actions, stamp)
    match = re.fullmatch(r'动作[ ：:]*(?:确认|执行)(?:[ ：:]+([0-9a-fA-F]{16}))?', text)
    if match:
        try:
            actions = _config(config_path)
        except ValueError:
            return '动作配置不可用，未执行；请检查私有 actions.json。'
        if not match[1]:
            with db:
                _expire(db, stamp)
            pending = _pending(db)
            return '用法：动作 确认 <编号>' + (
                '\n待确认：' + '、'.join(row['id'] for row in pending) if pending else '\n当前没有待确认动作。')
        return _approve(db, row, match[1].lower(), actions, stamp)
    match = re.fullmatch(r'动作[ ：:]*(?:取消)(?:[ ：:]+([0-9a-fA-F]{16}))?', text)
    if match:
        if not match[1]:
            with db:
                _expire(db, stamp)
            pending = _pending(db)
            return '用法：动作 取消 <编号>' + (
                '\n待确认：' + '、'.join(row['id'] for row in pending) if pending else '\n当前没有待确认动作。')
        action_id = match[1].lower()
        with db:
            _expire(db, stamp)
            changed = db.execute("UPDATE owner_actions SET state='cancelled',finished_at=?,"
                                 "error=COALESCE(error,'本人取消；未执行。') "
                                 "WHERE id=? AND state='pending'", (stamp, action_id)).rowcount
            _prune(db)
        return ('已取消动作 {}，未执行。'.format(action_id) if changed
                else '没有待确认动作 {}。'.format(action_id))
    match = re.fullmatch(r'动作[ ：:]*(?:查看|查询)(?:[ ：:]+([0-9a-fA-F]{16}))?', text)
    if match:
        return _view(db, config_path, stamp, match[1].lower() if match[1] else None)
    return _HELP


def review(db_path, show_output=False, now=None):
    path = owner_db(db_path)
    stamp = _stamp(now)
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        table = bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='owner_actions'").fetchone())
        rows = []
        if table:
            rows = db.execute('SELECT * FROM owner_actions ORDER BY created DESC,id LIMIT 20').fetchall()
        try:
            actions = _config(path.parent / CONFIG_NAME)
            config_error = None
        except ValueError:
            actions, config_error = {}, '动作配置不可用。'
        records = []
        for row in rows:
            state = row['state']
            if state == 'pending' and row['expires_at'] <= stamp:
                state = 'expired'
            item = {'id': row['id'], 'action': row['action'], 'state': state,
                    'created': format_time(row['created']), 'expires_at': format_time(row['expires_at']),
                    'approved_at': format_time(row['approved_at']) if row['approved_at'] else None,
                    'finished_at': format_time(row['finished_at']) if row['finished_at'] else None,
                    'exit_code': row['exit_code'], 'elapsed_ms': row['elapsed_ms'],
                    'truncated': bool(row['truncated']), 'source_id': row['source_id'],
                    'error': row['error']}
            if show_output:
                item['stdout'] = row['stdout_excerpt']
                item['stderr'] = row['stderr_excerpt']
            records.append(item)
        return {'state': 'ok', 'db': str(path), 'read_only': True, 'table': table,
                'configured': [{'name': name, 'description': action['description']}
                               for name, action in sorted(actions.items())],
                'configuration_error': config_error,
                'pending': sum(1 for item in records if item['state'] == 'pending'),
                'actions': records,
                'note': 'Read-only; prepare and confirm only from the native owner private chat.'}
    finally:
        db.close()