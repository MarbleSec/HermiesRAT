# lang: PowerShell | file: screenshot.ps1 | target: Windows 10/11
# tag: surveillance | shell: powershell

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$screen = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp    = New-Object System.Drawing.Bitmap($screen.Width, $screen.Height)
$gfx    = [System.Drawing.Graphics]::FromImage($bmp)
$gfx.CopyFromScreen($screen.Location, [System.Drawing.Point]::Empty, $screen.Size)

$out = "$env:TEMP\ss_$(Get-Date -Format 'yyyyMMdd_HHmmss').png"
$bmp.Save($out)
$gfx.Dispose(); $bmp.Dispose()
Write-Output "[+] saved: $out"
