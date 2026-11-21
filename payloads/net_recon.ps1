# lang: PowerShell | file: net_recon.ps1 | target: Windows 10/11
# tag: recon | shell: powershell

$listeners   = Get-NetTCPConnection -State Listen    | Select-Object LocalAddress, LocalPort, OwningProcess
$established = Get-NetTCPConnection -State Established | Select-Object LocalAddress, LocalPort, RemoteAddress, RemotePort, OwningProcess
$arp         = arp -a
$dns_cache   = Get-DnsClientCache | Select-Object Entry, RecordName, Data

[ordered]@{
    listeners   = $listeners
    established = $established
    arp_table   = $arp
    dns_cache   = $dns_cache
} | ConvertTo-Json -Depth 4
