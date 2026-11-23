param(
    [Parameter(Mandatory)][string]$Release,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$Python,
    [ValidatePattern('^RSI-WeChat(?:-[A-Za-z0-9]+)?$')][string]$Distro = 'RSI-WeChat'
)
$ErrorActionPreference = 'Stop'
foreach ($file in @($Config, $Python, (Join-Path $Release 'receiver/codex_worker.py'))) {
    if (!(Test-Path -LiteralPath $file -PathType Leaf)) { throw "Required local file is missing: $file" }
}
$wsl = Join-Path $env:WINDIR 'System32/wsl.exe'
& $wsl -d $Distro -u root --exec /usr/bin/systemctl start wechat-gui.target
if ($LASTEXITCODE -ne 0) { throw 'The WSL desktop target did not start. Check systemd and the installed WSL service bundle.' }
& $wsl -d $Distro -u root --exec /usr/bin/systemctl is-active --quiet rsi-owner-replies.service
if ($LASTEXITCODE -ne 0) { throw 'The confirmed owner reply service is not active. Stage/install the WSL bundle with --owner-config; preserve its original private state.' }
# WSL stops a distribution after instanceIdleTimeout (15 s by default) without a wsl.exe client,
# which would log WeChat out. Keep one idle client for this distribution only, independent of the receiver.
$keepalive = Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
    Where-Object { $_.CommandLine -like "*-d $Distro *--exec /bin/sleep infinity*" }
if (-not $keepalive) {
    Start-Process -FilePath $wsl -ArgumentList @('-d', $Distro, '-u', 'root', '--exec', '/bin/sleep', 'infinity') -WindowStyle Hidden
}
# A receiver that died leaves its windowless ssh forward running; it keeps the WSL return port and
# makes every new tunnel fail. Stop only forwards for this configured port whose receiver is gone.
$remotePort = (Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json).remote_port
if ($remotePort) {
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
        Where-Object { $_.CommandLine -like "* -R 127.0.0.1:$($remotePort):*" -and
            -not (Get-Process -Id $_.ParentProcessId -ErrorAction SilentlyContinue) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
# A queued WeChat original starts its turn only when the local app-server daemon is
# running. Start it on every launch so a reboot needs no manual step; the command is
# idempotent and a failure only warns, because the queue and the receiver still work.
$codex = (Get-Content -Raw -LiteralPath $Config | ConvertFrom-Json).codex
if ($codex -and (Test-Path -LiteralPath $codex -PathType Leaf)) {
    $ErrorActionPreference = 'Continue'
    try { & $codex app-server daemon start *> $null } catch { Write-Warning "Codex daemon did not start: $_" }
    $ErrorActionPreference = 'Stop'
}
Push-Location -LiteralPath $Release
try {
    & $Python -B -m receiver.codex_worker --config $Config
    $receiverExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $receiverExit
