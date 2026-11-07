#!/usr/bin/env python3
"""Build only the window-specific helper; never request permissions or read screens."""
from pathlib import Path
import hashlib
import plistlib
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
destination = Path(sys.argv[1]) if len(sys.argv) == 2 else root / 'build/微信记录.app/Contents/Resources/helpers/微信窗口读取.app'
sources = sorted((root / 'src/MacScreenReader').glob('*.swift')) + sorted((root / 'src/MacShared').glob('*.swift'))
info = {'CFBundleIdentifier':'local.wechat.collector.screen-reader', 'CFBundleExecutable':'WechatScreenReader', 'CFBundleName':'微信窗口读取', 'CFBundleDisplayName':'微信窗口读取', 'CFBundlePackageType':'APPL', 'CFBundleShortVersionString':'0.2.5', 'CFBundleVersion':'1', 'LSUIElement':True, 'LSMinimumSystemVersion':'14.2'}
digest = hashlib.sha256(plistlib.dumps(info) + b''.join(path.read_bytes() for path in sources)).hexdigest()
stamp = destination / 'Contents/Resources/source.sha256'
executable = destination / 'Contents/MacOS/WechatScreenReader'
if not (executable.is_file() and stamp.is_file() and stamp.read_text() == digest):
    executable.parent.mkdir(parents=True, exist_ok=True)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    with (destination / 'Contents/Info.plist').open('wb') as stream: plistlib.dump(info, stream)
    subprocess.run(['/usr/bin/swiftc','-parse-as-library','-target','arm64-apple-macosx14.2',*[str(path) for path in sources],'-O',*[argument for framework in ['AppKit','CoreGraphics','CoreVideo','ApplicationServices','ScreenCaptureKit','Vision','CryptoKit','Security','ImageIO'] for argument in ['-framework',framework]],'-o',str(executable)],check=True)
    stamp.write_text(digest)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(destination)],check=True)
else:
    subprocess.run(['/usr/bin/codesign','--verify','--strict',str(destination)],check=True)
print('Window-only screen reader helper built; no screen or permissions accessed.')
