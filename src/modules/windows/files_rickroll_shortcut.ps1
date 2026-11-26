$s=(New-Object -ComObject WScript.Shell).CreateShortcut("$env:USERPROFILE\Desktop\YouTube.lnk");$s.TargetPath='https://www.youtube.com/watch?v=dQw4w9WgXcQ';$s.Save()
