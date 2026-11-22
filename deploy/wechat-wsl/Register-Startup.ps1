param(
    [ValidateSet('Check','Register','Remove')][string]$Action = 'Check',
    [Parameter(Mandatory)][string]$Release,
    [Parameter(Mandatory)][string]$Config,
    [Parameter(Mandatory)][string]$Python,
    [ValidatePattern('^RSI-WeChat(?:-[A-Za-z0-9]+)?$')][string]$Distro = 'RSI-WeChat'
)
$ErrorActionPreference = 'Stop'
$taskName = "$Distro-Receiver"
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($Action -eq 'Remove') {
    if ($existing) {
        if ($existing.State -eq 'Running') { throw 'Drain and stop the original receiver task before removing its registration.' }
        if ($existing.Description -ne 'RSI Agent local WSL receiver startup') { throw 'This task is not an RSI Agent startup registration.' }
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    }
    return
}
$launcher = Join-Path $Release 'deploy/wechat-wsl/Start-Local.ps1'
foreach ($file in @($Config, $Python, $launcher, (Join-Path $Release 'receiver/codex_worker.py'))) {
    if (![IO.Path]::IsPathRooted($file) -or !(Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "An existing absolute local file is required: $file"
    }
    if ($file -match '["\r\n]') { throw 'Startup paths cannot contain quotes or line breaks.' }
}
if ($Action -eq 'Check') {
    [PSCustomObject]@{ Task = $taskName; Registered = [bool]$existing; User = $user; Activated = $false }
    return
}
if ($existing) { throw 'An existing task is preserved. Review it and explicitly remove the stopped registration before replacing it.' }
$powershell = Join-Path $env:WINDIR 'System32/WindowsPowerShell/v1.0/powershell.exe'
# A plain console task is handed to the default terminal (often Windows Terminal); closing that
# window sends Ctrl+C and stops the receiver. A headless conhost keeps it off any terminal window.
$conhost = Join-Path $env:WINDIR 'System32/conhost.exe'
$arguments = "-NoProfile -NonInteractive -WindowStyle Hidden -File `"$launcher`" -Release `"$Release`" -Config `"$Config`" -Python `"$Python`" -Distro $Distro"
$taskAction = New-ScheduledTaskAction -Execute $conhost -Argument "--headless `"$powershell`" $arguments" -WorkingDirectory $Release
# RestartCount covers only launch failures. The five-minute timer starts the task again after the
# receiver exits for any reason; IgnoreNew skips it while the receiver is running.
$trigger = @((New-ScheduledTaskTrigger -AtLogOn -User $user),
    (New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 5)))
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $taskAction -Trigger $trigger -Principal $principal -Settings $settings -Description 'RSI Agent local WSL receiver startup' | Out-Null
Write-Output "Registered $taskName for the current user's next logon. The task has not been started."
