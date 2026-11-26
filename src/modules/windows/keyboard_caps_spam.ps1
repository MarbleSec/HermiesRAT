$w=(New-Object -ComObject WScript.Shell);1..20|%{$w.SendKeys('{CAPSLOCK}');Start-Sleep -Milliseconds 300}
