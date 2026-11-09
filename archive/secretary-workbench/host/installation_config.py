"""Package-only installation slots. Empty by default; no operator data bundled.

Relative configuration filenames use the current working directory. All path
values inside a configuration use the operator-selected configuration filename's
parent directory, before following a configuration-file symlink. Tilde expands
normally; OS readability is authoritative.
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _config_file(file=None):
    value = file or os.environ.get('SECRETARY_INSTALLATION_CONFIG')
    return Path(value).expanduser().absolute() if value else None


def read(file=None):
    p = _config_file(file)
    if p is None:
        return {'version': 1, 'modules': {}, 'identities': {}, 'paths': {}}

    def pairs(rows):
        out = {}
        for key, value in rows:
            if key in out:
                raise ValueError('duplicate installation key')
            out[key] = value
        return out

    with p.open(encoding='utf-8-sig') as stream:
        result = json.load(stream, object_pairs_hook=pairs)
    if not isinstance(result, dict) or set(result) - {'version', 'modules', 'identities', 'paths'} or type(result.get('version')) is not int or result.get('version') != 1:
        raise ValueError('installation schema')
    for key in ['modules', 'identities', 'paths']:
        result.setdefault(key, {})
        if not isinstance(result[key], dict):
            raise ValueError('installation section')
    return result


def setting(module, name, default=None):
    section = read()['modules'].get(module, {})
    if not isinstance(section, dict):
        raise ValueError('installation module must be an object')
    return section.get(name, default)


def identity(name):
    value = read()['identities'].get(name)
    if value is not None and not isinstance(value, str):
        raise ValueError('installation identity must be text or absent')
    return value


def _path(value):
    if not isinstance(value, str):
        raise ValueError('installation path must be text')
    p = Path(value).expanduser()
    config = _config_file()
    base = config.parent if config else Path.cwd()
    return p if p.is_absolute() else base / p


def path(name):
    value = read()['paths'].get(name)
    if value is None:
        return REPO / 'var/unconfigured' / name.replace('.', '/')
    return _path(value)


def path_list(module, name):
    values = setting(module, name, [])
    if not isinstance(values, list):
        raise ValueError('installation path list')
    return [_path(value) for value in values]


def path_map(module, name, lists=False):
    rows = setting(module, name, {})
    if not isinstance(rows, dict):
        raise ValueError('installation path map')
    out = {}
    for key, value in rows.items():
        if lists:
            if not isinstance(value, list):
                raise ValueError('installation path list')
            out[key] = [_path(v) for v in value]
        else:
            out[key] = _path(value)
    return out


def role_map(module, name):
    rows = setting(module, name, {})
    if not isinstance(rows, dict):
        raise ValueError('installation role map')
    out = {}
    for thread, row in rows.items():
        if not isinstance(thread, str) or not isinstance(row, list) or len(row) != 4 or any(not isinstance(v, str) for v in row):
            raise ValueError('role mapping requires thread -> [id,name,root,entry]')
        out[thread] = (row[0], row[1], _path(row[2]), _path(row[3]))
    return out
