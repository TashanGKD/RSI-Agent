import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WECHAT_LINUX = ROOT / 'components/wechat-linux'
DEFAULT = {
    'version': 1,
    'wechat': {
        'display': ':92', 'xauthority': '/run/wechat-gui/Xauthority',
        'runtime_root': '/var/lib/rsi-agent/wechat', 'profile': None, 'account': None,
        'operations_enabled': False,
    },
}


def load(path=None):
    value = json.loads(json.dumps(DEFAULT))
    if path is None:
        return value
    path = Path(path).expanduser().absolute()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or set(data) != {'version', 'wechat'} or data['version'] != 1:
        raise ValueError('Configuration must contain version=1 and wechat.')
    fields = data['wechat']
    if not isinstance(fields, dict) or set(fields) - set(DEFAULT['wechat']):
        raise ValueError('Unknown WeChat configuration fields.')
    value['wechat'].update(fields)
    wx = value['wechat']
    if not isinstance(wx['display'], str) or not re.fullmatch(r':\d+(?:\.\d+)?', wx['display']):
        raise ValueError('An explicit local X11 display is required.')
    if type(wx['operations_enabled']) is not bool:
        raise ValueError('operations_enabled must be true or false.')
    if wx['account'] is not None and (not isinstance(wx['account'], str) or not re.fullmatch(r'[A-Za-z0-9_@.-]{1,200}', wx['account'])):
        raise ValueError('account must be an exact account identifier or null.')
    for field in ('xauthority', 'runtime_root', 'profile'):
        if wx[field] is None and field == 'profile':
            continue
        if not isinstance(wx[field], str) or not wx[field]:
            raise ValueError(field + ' must be a path.')
        p = Path(wx[field]).expanduser()
        wx[field] = str(p if p.is_absolute() else path.parent / p)
    return value
