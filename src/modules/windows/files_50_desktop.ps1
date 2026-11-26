1..50|%{New-Item "$env:USERPROFILE\Desktop\file$_.txt" -Force|Out-Null}
