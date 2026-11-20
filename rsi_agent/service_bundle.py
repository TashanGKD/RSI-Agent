"""Stage reviewable Horyzon units; never install, enable or start a service."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from .config import ROOT


def stage(release, output, profile='server'):
    if profile not in ('server', 'wsl'):
        raise ValueError('Unknown desktop service profile.')
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
    output.mkdir(mode=0o700)
    for name, text in units.items():
        (output / name).write_text(text, encoding='utf-8', newline='\n')
    plan = {
        'schema_version': 1, 'release': release, 'profile': profile, 'activated': False,
        'unit_sha256': {name: hashlib.sha256(text.encode()).hexdigest() for name, text in units.items()},
        'verify_argv': ['systemd-analyze', 'verify', '--man=no', *[str(output / name) for name in units]],
    }
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    return plan
