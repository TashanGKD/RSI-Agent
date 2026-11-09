"""Current display identity from the same commissioned role's own normal files.
Never changes routing, permissions, threads, account or employee count.
"""
import sys as _package_sys
from pathlib import Path as _PackagePath
_package_sys.path.insert(0, str(_PackagePath(__file__).resolve().parents[2] / 'host'))
import installation_config as _install
import json, re
from live_core import checked_path, stable_note

def entry_identity(role):
    if role.get('id') != 'secretary' or role.get('threadId') != _install.identity('monitor.employee_identity.identity_4344f0fd'):
        return None
    root = role['root']
    path = role.get('entry')
    if path != root / 'docs/工作接续.md':
        return None
    try:
        checked_path(path, [root])
        (raw, _) = stable_note(path)
        if not re.search('^当前主秘书对话' + re.escape(role['threadId']) + '[，,。\\s]', raw, re.M):
            return None
        sections = re.findall('^## [^\\n]*：现称[^\\n]+\\n(.*?)(?=^## |\\Z)', raw, re.M | re.S)
        if len(sections) != 1:
            return None
        match = re.search('^本人将原“([^”\\n]{1,40})”更名为\\*\\*([^*\\n]{1,40})\\*\\*，同一原岗位、对话、工作区及client=secretary继续。', sections[0], re.M)
        if not match or match[1] != role['name'] or re.search('[<>]|password|token|口令|密码', match[2], re.I):
            return None
        return {'name': match[2], 'aliases': [match[1]], 'threadId': role['threadId'], 'sourcePath': str(path), 'evidenceText': match[0]}
    except (OSError, ValueError, TypeError):
        return None

def read_identity(role):
    current = entry_identity(role)
    if current:
        return current
    root = role['root']
    path = root / 'STATE.json'
    role_path = root / 'ROLE.md'
    try:
        checked_path(path, [root])
        checked_path(role_path, [root])
        state = json.loads(stable_note(path)[0])
        raw = stable_note(role_path)[0]
        identity = state.get('identity', {})
        name = identity.get('name')
        owner = identity.get('thread_id')
        if role.get('id') == 'research-secretary':
            from research_secretary_scope import THREAD, ROOT
            if owner != THREAD or root != ROOT or identity.get('project_root') != str(ROOT):
                return None
            name = identity.get('role_name')
            identity = dict(identity, work_root=str(ROOT))
        if owner != role['threadId'] or identity.get('work_root') != str(root) or (not isinstance(name, str)) or (not 1 <= len(name) <= 40) or re.search('[\\n\\r<>]|password|token|口令|密码', name, re.I):
            return None
        if not (re.search('^称呼[：:]\\s*' + re.escape(name) + '(?:[。；;\\s]|$)', raw, re.M) or re.search('^#\\s*' + re.escape(name) + '(?:[（(\\s]|$)', raw, re.M)):
            return None
        aliases = list(dict.fromkeys([role['name']] + [v for v in identity.get('previous_names', []) if isinstance(v, str) and 1 <= len(v) <= 40]))
        return {'name': name, 'aliases': [v for v in aliases if v != name], 'threadId': owner, 'sourcePath': str(path)}
    except (OSError, ValueError, TypeError):
        return None
