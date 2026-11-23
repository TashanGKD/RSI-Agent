param(
    [Parameter(Mandatory)][ValidateSet('Status','Pause','Resume')][string]$Action,
    [ValidatePattern('^RSI-WeChat(?:-[A-Za-z0-9]+)?$')][string]$Distro = 'RSI-WeChat'
)
$ErrorActionPreference = 'Stop'
$wsl = Join-Path $env:WINDIR 'System32/wsl.exe'
$units = @('wechat-gui-x.service', 'wechat-gui-desktop.service', 'rsi-owner-replies.service')

function Invoke-Distro {
    param([string[]]$Command)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { $output = & $wsl -d $Distro -u root --exec @Command 2>&1 }
    finally { $ErrorActionPreference = $previous }
    return @{ Code = $LASTEXITCODE; Text = ($output | Out-String).Trim() }
}

if ($Action -eq 'Status') {
    foreach ($unit in $units) {
        $result = Invoke-Distro @('/usr/bin/systemctl', 'is-active', $unit)
        Write-Output ("{0} {1}" -f $unit, $result.Text)
    }
    return
}

$verb = if ($Action -eq 'Pause') { 'stop' } else { 'start' }
$result = Invoke-Distro @('/usr/bin/systemctl', $verb, 'wechat-gui.target')
if ($result.Code -ne 0) { throw "The WSL desktop target did not $verb cleanly: $($result.Text)" }
if ($Action -eq 'Pause') {
    Write-Output 'Desktop paused. Resume with -Action Resume; the client may need a phone-confirmed login afterwards.'
} else {
    Write-Output 'Desktop resumed.'
}
