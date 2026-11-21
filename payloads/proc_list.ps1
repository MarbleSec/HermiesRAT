# lang: PowerShell | file: proc_list.ps1 | target: Windows 10/11
# tag: recon | shell: powershell

Get-Process | Select-Object Name, Id, CPU, WorkingSet, Path |
    Sort-Object CPU -Descending |
    ConvertTo-Json -Depth 2
