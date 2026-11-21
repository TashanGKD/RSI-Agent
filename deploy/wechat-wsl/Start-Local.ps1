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
Push-Location -LiteralPath $Release
try {
    & $Python -B -m receiver.codex_worker --config $Config
    $receiverExit = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $receiverExit
