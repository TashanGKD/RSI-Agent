"""Build and install the private fixture plugin through supported Codex commands.

The public source has no capability URL. Connection JSON and generated packages
must stay in a private, ignored directory; no desktop UI automation is used.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tomllib
from urllib.parse import urlsplit
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--connection', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    state = args.state.resolve()
    state.mkdir(parents=True, exist_ok=False)
    connection = json.loads(args.connection.read_text(encoding='utf-8'))
    url = connection['mcp_server_url']
    if urlsplit(url).scheme != 'https':
        raise ValueError('verified HTTPS connection required')
    source = Path(__file__).with_name('codex-plugin')
    bundle = state / 'plugins/rsi-trigger-lab'
    bundle.mkdir(parents=True)
    shutil.copyfile(source / 'plugin.json', bundle / 'plugin.json')
    mcp = json.loads((source / 'mcp.json.template').read_text(encoding='utf-8'))
    mcp['mcpServers']['rsi-trigger-lab']['url'] = url
    (bundle / 'mcp.json').write_text(json.dumps(mcp, ensure_ascii=False, indent=2), encoding='utf-8')
    catalog = state / '.agents/plugins/marketplace.json'
    catalog.parent.mkdir(parents=True)
    catalog.write_text(json.dumps({'name': 'rsi-trigger-experiments', 'plugins': [{
        'name': 'rsi-trigger-lab', 'source': {'source': 'local', 'path': './plugins/rsi-trigger-lab'},
        'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'},
        'category': 'Developer Tools'}]}, indent=2), encoding='utf-8')
    with zipfile.ZipFile(state / 'rsi-trigger-lab.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in bundle.iterdir():
            archive.write(path, path.name)
    config = Path.home() / '.codex/config.toml'
    before = config.read_bytes()
    (state / 'config.before.toml').write_bytes(before)
    def cli(arguments, name):
        result = subprocess.run([args.codex] + arguments, text=True, encoding='utf-8', capture_output=True)
        (state / (name + '.stdout.json')).write_text(result.stdout, encoding='utf-8')
        (state / (name + '.stderr.log')).write_text(result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('supported Codex command failed; inspect private ' + name + '.stderr.log')
        return json.loads(result.stdout)
    cli(['plugin', 'marketplace', 'add', str(state), '--json'], 'marketplace-add')
    installed = cli(['plugin', 'add', 'rsi-trigger-lab@rsi-trigger-experiments', '--json'], 'plugin-add')
    listed = cli(['plugin', 'list', '--json'], 'plugin-list')
    entry = next(x for x in listed['installed'] if x['name'] == 'rsi-trigger-lab'
                 and x['marketplaceName'] == 'rsi-trigger-experiments')
    old = tomllib.loads(before.decode('utf-8-sig'))
    new = tomllib.loads(config.read_text(encoding='utf-8-sig'))
    changed = [key for key in set(old) | set(new) if old.get(key) != new.get(key)]
    receipt = {'installed': True, 'plugin_id': entry['pluginId'], 'enabled': entry['enabled'],
               'installed_path': installed['installedPath'], 'changed_config_sections': sorted(changed),
               'dot_subscription_proven': False, 'desktop_restarted': False, 'wechat_transport': False}
    (state / 'acceptance.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
