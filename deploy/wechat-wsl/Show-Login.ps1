param(
    [ValidatePattern('^RSI-WeChat(?:-[A-Za-z0-9]+)?$')][string]$Distro = 'RSI-WeChat',
    [ValidateRange(1, 30)][int]$Minutes = 10
)
# Show the private WeChat display in a browser page that refreshes every 2 s, so the
# login QR code or "Log In" screen is reachable after a restart even when WSLg does not
# show the Xephyr window. Read-only: it only captures the screen; nothing is clicked.
$ErrorActionPreference = 'Stop'
$wsl = Join-Path $env:WINDIR 'System32/wsl.exe'
$dir = Join-Path $env:LOCALAPPDATA "RSI-WeChat-Setup/$Distro/login-view"
New-Item -ItemType Directory -Force -Path $dir | Out-Null
$capture = Join-Path $dir 'capture.py'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText($capture, @'
import gi, os, sys, time
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk
target, end = sys.argv[1], time.time() + float(sys.argv[2])
while time.time() < end:
    root = Gdk.get_default_root_window()
    image = Gdk.pixbuf_get_from_window(root, 0, 0, root.get_width(), root.get_height())
    image.savev(target + '.tmp', 'png', [], [])
    os.replace(target + '.tmp', target)
    time.sleep(2)
'@.Replace("`r", ''), $utf8)
[IO.File]::WriteAllText((Join-Path $dir 'index.html'), @'
<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<title>WeChat login</title></head><body style="margin:0;background:#111;text-align:center">
<img src="screen.png" style="max-width:100%"></body></html>
'@, $utf8)
$linux = (& $wsl -d $Distro -u root --exec wslpath -a ($dir -replace '\\', '/')).Trim()
& $wsl -d $Distro -u root --exec /bin/sh -c 'systemctl stop rsi-login-view.service 2>/dev/null; true'
& $wsl -d $Distro -u root --exec systemd-run --unit=rsi-login-view --collect --uid=wechat-gui --gid=wechat-gui `
    -E DISPLAY=:92 -E XAUTHORITY=/run/wechat-gui/Xauthority /usr/bin/python3 "$linux/capture.py" "$linux/screen.png" ($Minutes * 60)
if ($LASTEXITCODE -ne 0) { throw 'The private WeChat display could not be captured. Start the distribution first.' }
Start-Sleep -Seconds 3
Start-Process (Join-Path $dir 'index.html')
Write-Output "Opened the live WeChat screen for $Minutes minutes. Scan the code with the bot account's phone."
