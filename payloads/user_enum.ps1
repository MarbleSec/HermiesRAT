# lang: PowerShell | file: user_enum.ps1 | target: Windows 10/11
# tag: recon | shell: powershell

$local_users  = Get-LocalUser | Select-Object Name, Enabled, LastLogon, PasswordRequired
$local_groups = Get-LocalGroup | ForEach-Object {
    $g = $_
    $members = Get-LocalGroupMember $g.Name -ErrorAction SilentlyContinue | Select-Object Name, ObjectClass
    [PSCustomObject]@{ Group = $g.Name; Members = $members }
}
$whoami_priv = whoami /priv

[ordered]@{
    users  = $local_users
    groups = $local_groups
    privs  = $whoami_priv
} | ConvertTo-Json -Depth 4
