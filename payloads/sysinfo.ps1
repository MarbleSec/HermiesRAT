# lang: PowerShell | file: sysinfo.ps1 | target: Windows 10/11
# tag: recon | shell: powershell

$out = [ordered]@{
    hostname    = $env:COMPUTERNAME
    user        = $env:USERNAME
    domain      = $env:USERDOMAIN
    os          = (Get-CimInstance Win32_OperatingSystem).Caption
    arch        = $env:PROCESSOR_ARCHITECTURE
    uptime_hrs  = [math]::Round(((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalHours, 2)
    ram_gb      = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
    public_ip   = (Invoke-RestMethod -Uri "https://api.ipify.org")
    local_ips   = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" }).IPAddress
    av_products = (Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntiVirusProduct).displayName
    ps_version  = $PSVersionTable.PSVersion.ToString()
}
$out | ConvertTo-Json -Depth 3
