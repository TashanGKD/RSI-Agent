param([ValidateRange(1, 30)][int]$Minutes = 10)
# Show the Xiaohongshu login QR code from the hidden browser in a page that refreshes every 2 s.
# It reloads an expired code and stops once the account is logged in. Nothing is typed or submitted.
$ErrorActionPreference = 'Stop'
$dir = Join-Path $env:LOCALAPPDATA 'RSI-WeChat-Setup/xiaohongshu-login'
New-Item -ItemType Directory -Force -Path $dir | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'capture_login.py') (Join-Path $dir 'capture.py') -Force
$utf8 = New-Object System.Text.UTF8Encoding($false)
[IO.File]::WriteAllText((Join-Path $dir 'index.html'), @'
<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<title>星语小红书登录二维码</title></head><body style="margin:0;background:#111;text-align:center">
<img src="screen.png" style="max-width:100%"></body></html>
'@, $utf8)
Remove-Item (Join-Path $dir 'status.txt'), (Join-Path $dir 'screen.png') -ErrorAction SilentlyContinue
Start-Process -WindowStyle Hidden python -ArgumentList '-X', 'utf8', (Join-Path $dir 'capture.py'), $dir, $Minutes
Start-Sleep -Seconds 5
Start-Process (Join-Path $dir 'index.html')
Write-Output "Status: $(Get-Content (Join-Path $dir 'status.txt') -ErrorAction SilentlyContinue)"
