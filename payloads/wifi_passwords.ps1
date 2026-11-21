# lang: PowerShell | file: wifi_passwords.ps1 | target: Windows 10/11
# tag: credential | shell: powershell

$profiles = (netsh wlan show profiles) -match "All User Profile" |
    ForEach-Object { ($_ -split ":")[1].Trim() }

$results = foreach ($p in $profiles) {
    $raw  = netsh wlan show profile name="$p" key=clear
    $pass = ($raw -match "Key Content") | ForEach-Object { ($_ -split ":")[1].Trim() }
    [PSCustomObject]@{ SSID = $p; Password = if ($pass) { $pass } else { "<none/open>" } }
}

$results | ConvertTo-Json
