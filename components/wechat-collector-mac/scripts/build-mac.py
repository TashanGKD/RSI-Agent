#!/usr/bin/env python3
"""Build a fresh local .app with explicit --output-app/--worker/--helper-payload; never captures private data or modifies the installed WeChat."""
from pathlib import Path
import os
import plistlib
import shutil
import subprocess
import sys
import argparse
from importlib.util import spec_from_file_location, module_from_spec

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output-app', required=True, type=Path, help='Fresh absolute .app path; existing output is refused.')
parser.add_argument('--worker', required=True, type=Path, help='Accepted frozen worker.')
parser.add_argument('--helper-payload', required=True, type=Path, help='Same opaque helper pack sealed into the worker.')
arguments = parser.parse_args()
# No arguments/help exit above, before any filesystem mutation.
app = arguments.output_app
worker = arguments.worker
payload = arguments.helper_payload
for path in (app, worker, payload):
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        parser.error('Use absolute paths without symlink ancestors.')
if app.exists() or app.suffix != '.app' or not app.parent.is_dir():
    parser.error('Output must be a fresh .app below an existing directory.')
if not worker.is_file() or not payload.is_file(): parser.error('Worker and helper payload must exist.')
sys.path.insert(0, str(root / 'src/MacWorker/foundation'))
import helper_payload
from PyInstaller.archive.readers import CArchiveReader
sealed = payload.read_bytes()
digest, image = helper_payload.decode(sealed)
archive = CArchiveReader(str(worker))
if archive.extract('vendor/oneshot-helper.pack') != sealed:
    parser.error('Worker and compiled Native helper payload differ.')
dotnet = Path(os.environ.get('WECHAT_COLLECTOR_DOTNET','dotnet'))
env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_GENERATE_ASPNET_CERTIFICATE='false', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1')
contents = app / 'Contents'
resources = contents / 'Resources'
app.mkdir(mode=0o700)
(contents / 'MacOS').mkdir(parents=True, exist_ok=False)
resources.mkdir(parents=True, exist_ok=True)
subprocess.run([str(dotnet), 'publish', str(root / 'src/MacHost/MacHost.csproj'), '-c', 'Release', '-r', 'osx-arm64', '--self-contained', 'true', '-o', str(resources / 'backend'), '--nologo'], check=True, env=env)
subprocess.run([str(dotnet), 'publish', str(root / 'src/MacCLI/MacCLI.csproj'), '-c', 'Release', '-r', 'osx-arm64', '--self-contained', 'true', '-o', str(resources / 'cli'), '--nologo'], check=True, env=env)
# Compile pins into signed Native code, never load privileged execution pins from resources at runtime.
pins = app.parent / (app.name + '.helper-pins.swift')
with pins.open('x') as stream: stream.write('enum MacConnectionBuildPins { static let helperSHA256 = "' + digest + '"; static let helperBytes = ' + str(len(image)) + ' }\n')
subprocess.run(['/usr/bin/swiftc', str(root / 'src/MacNative/main.swift'), str(root / 'src/MacNative/BackendIdentity.swift'), str(root / 'src/MacNative/MacShadowSession.swift'), str(root / 'src/MacNative/MacConnectionSession.swift'), str(root / 'src/MacNative/MacOriginalHandover.swift'), str(root / 'src/MacNative/MacConnectionBootstrap.swift'), str(pins), str(root / 'src/MacNative/MacLocalMediaPlayback.swift'), str(root / 'src/MacNative/MacPlaybackActivitySender.swift'), str(root / 'src/MacNative/MacForwardView.swift'), str(root / 'src/MacNative/MacSavedArticleView.swift'), str(root / 'src/MacNative/MacFileLocationView.swift'), str(root / 'src/MacNative/MacScreenReaderClient.swift'), str(root / 'src/MacNative/MacScreenReaderSetup.swift'), str(root / 'src/MacNative/MacWindowInspector.swift'), str(root / 'src/MacShared/PipeIO.swift'), '-O', '-framework', 'AppKit', '-framework', 'WebKit', '-framework', 'AVKit', '-o', str(contents / 'MacOS/WechatCollectorMac')], check=True)
subprocess.run([sys.executable, str(root / 'scripts/build-screen-reader.py'), str(resources / 'helpers/微信窗口读取.app')], check=True)
if not worker.is_file(): raise RuntimeError('Build the Mac worker before packaging the app.')
(resources / 'worker').mkdir(exist_ok=True)
shutil.copy2(worker, resources / 'worker/mac-worker')
spec = spec_from_file_location('bundle_native', root / 'scripts/bundle-native.py')
module = module_from_spec(spec); spec.loader.exec_module(module)
module.bundle_native(resources / 'native')
subprocess.run(['/usr/bin/swiftc', '-parse-as-library', str(root / 'src/MacNative/sticker_probe.swift'), '-O', '-framework', 'Foundation', '-framework', 'CoreGraphics', '-framework', 'ImageIO', '-o', str(resources / 'native/sticker-probe')], check=True)
vault = resources / 'native/mac-vault'
if not vault.exists() or vault.stat().st_mtime < (root / 'src/MacNative/vault.swift').stat().st_mtime:
    subprocess.run(['/usr/bin/swiftc',str(root / 'src/MacNative/vault.swift'),'-O','-framework','Security','-o',str(vault)],check=True)
for source, destination in [(root / 'reference-web', resources / 'Project/reference-web'), (root / 'reference-licenses', resources / 'Project/reference-licenses'), (root / 'src/MacHost/Web', resources / 'Project/src/MacHost/Web')]:
    shutil.copytree(source, destination, dirs_exist_ok=True)
with (contents / 'Info.plist').open('wb') as stream:
    plistlib.dump({'CFBundleIdentifier': 'local.wechat.collector.mac', 'CFBundleExecutable': 'WechatCollectorMac', 'CFBundleName': '微信记录', 'CFBundleDisplayName': '微信记录', 'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': '0.2.5', 'CFBundleVersion': '1', 'LSMinimumSystemVersion': '13.0', 'NSHighResolutionCapable': True, 'NSHumanReadableCopyright': 'Windows UI resources preserved from the supplied 0.2.5 release.'}, stream)
signing_spec = spec_from_file_location('local_signing', root / 'scripts/local-signing.py')
signing_module = module_from_spec(signing_spec); signing_spec.loader.exec_module(signing_module)
subprocess.run(['/usr/bin/codesign', '--force', '--deep', '--sign', signing_module.local_signing_identity(), str(app)], check=True)
print(app)
