"""Stage reviewable Horyzon units; never install, enable or start a service."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .config import ROOT


def stage(release, output, profile='server', owner_config=None, python='/usr/bin/python3'):
    if profile not in ('server', 'wsl'):
        raise ValueError('Unknown desktop service profile.')
    if not isinstance(python, str):
        raise ValueError('Explicit Linux interpreter required.')
    for value in (python, owner_config):
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value)
                                  or '..' in PurePosixPath(value).parts or len(PurePosixPath(value).parts) < 2):
            raise ValueError('Explicit Linux interpreter/configuration paths required.')
    if owner_config and profile != 'wsl':
        raise ValueError('Owner startup binding is for the local WSL profile.')
    if (not isinstance(release, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', release)
            or '..' in PurePosixPath(release).parts or len(PurePosixPath(release).parts) < 2):
        raise ValueError('An absolute Linux release path without expansion characters is required.')
    output = Path(output).expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ValueError('Stage into a new directory; existing bundles are preserved.')
    source = ROOT / 'deploy/wechat-gui/systemd'
    # Read everything before creating output, so invalid source cannot leave a partial plan.
    units = {p.name: p.read_text(encoding='utf-8').replace('@RELEASE@', release.rstrip('/'))
             for p in sorted(source.iterdir()) if p.is_file()}
    if len(units) != 6 or any('@RELEASE@' in text for text in units.values()):
        raise ValueError('The complete six-unit template set is required.')
    if profile == 'wsl':
        source = ROOT / 'deploy/wechat-wsl/systemd'
        units = {'wechat-gui-desktop.service': units['wechat-gui-desktop.service'], **{
            p.name: p.read_text(encoding='utf-8').replace('@RELEASE@', release.rstrip('/'))
            for p in sorted(source.iterdir()) if p.is_file()}}
        if len(units) != 3 or any('@RELEASE@' in text for text in units.values()):
            raise ValueError('The complete WSL desktop template set is required.')
        if owner_config:
            owner = (ROOT / 'deploy/owner-replies/rsi-owner-replies.service').read_text(encoding='utf-8')
            owner = owner.replace('@RELEASE@', release.rstrip('/')).replace('/usr/bin/python3', python)
            owner = owner.replace('/var/lib/rsi-agent/owner-replies/config.json', owner_config)
            units['rsi-owner-replies.service'] = owner.replace('[Unit]\n', '[Unit]\nPartOf=wechat-gui.target\n', 1)
            units['wechat-gui.target'] = units['wechat-gui.target'].replace('[Unit]\n',
                '[Unit]\nRequires=rsi-owner-replies.service\nAfter=rsi-owner-replies.service\n', 1)
    output.mkdir(mode=0o700)
    for name, text in units.items():
        (output / name).write_text(text, encoding='utf-8', newline='\n')
    plan = {
        'schema_version': 1, 'release': release, 'profile': profile, 'activated': False,
        'owner_replies_included': owner_config is not None,
        'unit_sha256': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in units.items()},
        'verify_argv': ['systemd-analyze', 'verify', '--man=no', *[str(output / name) for name in units]],
    }
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan
