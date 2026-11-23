param(
    [ValidateSet('Check','Install','Status','WaitForLogin')][string]$Action = 'Check',
    [ValidatePattern('^RSI-WeChat(?:-[A-Za-z0-9]+)?$')][string]$Distro = 'RSI-WeChat',
    [string]$UbuntuArchive,
    [string]$WeChatPackage,
    [switch]$PrepareOnly,
    [ValidateRange(1,600)][int]$WaitSeconds = 120
)
$ErrorActionPreference = 'Stop'
$wsl = Join-Path $env:WINDIR 'System32/wsl.exe'
if (!(Test-Path -LiteralPath $wsl) -or [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64' -or [Environment]::OSVersion.Version.Build -lt 22000) {
    throw 'Windows 11 x64 with WSL 2 and WSLg is required.'
}
function Invoke-Wsl([string[]]$CommandLine) {
    & $wsl @CommandLine
    if ($LASTEXITCODE -ne 0) { throw "WSL command exited with $LASTEXITCODE." }
}
function Linux-Path([string]$File) {
    $absolute = (Resolve-Path -LiteralPath $File).Path
    if ($absolute -notmatch '^([A-Za-z]):[\\/](.*)$') { throw 'Use a local drive with default WSL mount paths.' }
    '/mnt/' + $Matches[1].ToLowerInvariant() + '/' + ($Matches[2] -replace '\\', '/')
}
function Get-Verified([string]$File, [string]$Url, [string]$Hash, [string]$Provided) {
    # A reviewed copy from an earlier install of any distro is reused by its SHA-256.
    $cache = Join-Path $env:LOCALAPPDATA "RSI-WeChat-Setup/packages/$($Hash.ToLowerInvariant())"
    if ($Provided) { $File = (Resolve-Path -LiteralPath $Provided).Path }
    elseif (!(Test-Path -LiteralPath $File) -and (Test-Path -LiteralPath $cache)) { $File = $cache }
    elseif (!(Test-Path -LiteralPath $File)) {
        $part = "$File.part"
        curl.exe --proto '=https' --fail --silent --show-error --location --connect-timeout 20 --max-time 600 --output $part $Url
        if ($LASTEXITCODE -ne 0) { throw 'Download failed. Check the network or supply a reviewed offline file with -UbuntuArchive or -WeChatPackage.' }
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $part).Hash -ne $Hash) {
            throw "The file at $Url is not the reviewed build (SHA-256 $Hash). The publisher may have replaced it with a newer, uncalibrated version. Keep verification enabled; supply the reviewed file with -UbuntuArchive or -WeChatPackage, or place it at $cache."
        }
        Move-Item -LiteralPath $part -Destination $File
    }
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash -ne $Hash) { throw 'Input did not match the reviewed SHA-256.' }
    if (!(Test-Path -LiteralPath $cache)) {
        New-Item -ItemType Directory -Path (Split-Path $cache) -Force | Out-Null
        Copy-Item -LiteralPath $File -Destination $cache
    }
    $File
}
$version = @(Invoke-Wsl @('--version') | ForEach-Object { $_ -replace [char]0, '' })
if (!($version -match 'WSLg')) { throw 'WSLg is unavailable. Update WSL before installation.' }
if ($Action -eq 'Check') {
    $drive = (Get-Item -LiteralPath $env:LOCALAPPDATA).PSDrive
    if ($drive.Free -lt 4GB) { throw 'Need at least 4 GiB free for installation and setup.' }
    'Platform check passed (WSL, WSLg and disk). Runtime dependencies, authorization and pairing still require setup check inside the client distro.'
    return
}
$data = Join-Path $env:LOCALAPPDATA "RSI-WeChat-Setup/$Distro"
$guest = @('-d',$Distro,'-u','root','--exec')
$distroList = @(& $wsl --list --quiet 2>$null | ForEach-Object { ($_ -replace [char]0, '').Trim() })
if ($distroList -notcontains $Distro) {
    if ($Action -in 'Status','WaitForLogin') { 'login=not_installed'; return }
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    $base = Get-Verified (Join-Path $data 'ubuntu-base-24.04.5-base-amd64.tar.gz') 'https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.5-base-amd64.tar.gz' 'e77b6f10c2590cef872b33ee9f635a0e3fd1f57fb074c0e52b5c7f56147a0c86' $UbuntuArchive
    Invoke-Wsl @('--import',$Distro,(Join-Path $data 'linux'),$base,'--version','2')
    Invoke-Wsl ($guest + @('/usr/bin/install','-d','-m','0700','/opt/rsi-wechat-setup'))
    Invoke-Wsl ($guest + @('/usr/bin/touch','/opt/rsi-wechat-setup/owned'))
}
Invoke-Wsl ($guest + @('/usr/bin/test','-f','/opt/rsi-wechat-setup/owned'))
if ($Action -in 'Status','WaitForLogin') {
    $seconds = if ($Action -eq 'WaitForLogin') { $WaitSeconds } else { 0 }
    Invoke-Wsl ($guest + @('/bin/bash',(Linux-Path (Join-Path $PSScriptRoot 'status.sh')),[string]$seconds))
    return
}
& $wsl @guest /usr/bin/test -x /usr/bin/wechat
$deb = '/dev/null'
if ($LASTEXITCODE -ne 0) {
    $localDeb = Get-Verified (Join-Path $data 'WeChatLinux_x86_64.deb') 'https://dldir1.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb' 'a0db8caeee8d1e6cfe0aa5ce58710270f8d74a90ff4920f53a3fc22aa0956fe9' $WeChatPackage
    $deb = Linux-Path $localDeb
}
Invoke-Wsl ($guest + @('/bin/bash',(Linux-Path (Join-Path $PSScriptRoot 'install-first.sh')),$deb))
if ($PrepareOnly) { 'Official WeChat verified. Prepare runtime dependencies, pairing and own-child authorization before first login.'; return }
& $wsl @guest /usr/bin/pgrep -u wechat-gui -x wechat | Out-Null
if ($LASTEXITCODE -ne 0) {
    $argsList = @('-d',$Distro,'-u','wechat-gui','--exec','/usr/bin/env','DISPLAY=:0','XDG_RUNTIME_DIR=/run/rsi-wechat-setup','QT_QPA_PLATFORM=xcb','/usr/bin/dbus-run-session','--','/usr/bin/wechat')
    Start-Process -FilePath $wsl -ArgumentList $argsList -WindowStyle Hidden | Out-Null
}
'Open WeChat. Scan the QR code, or click Log In and confirm on your phone. Use -Action WaitForLogin to verify.'
