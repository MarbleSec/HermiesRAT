while($true){$w=(Get-ChildItem 'C:\Windows\Media\*.wav'|Get-Random).FullName;(New-Object Media.SoundPlayer $w).PlaySync();Start-Sleep 5}
