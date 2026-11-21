# lang: PowerShell | file: clipboard_grab.ps1 | target: Windows 10/11
# tag: surveillance | shell: powershell

Add-Type -AssemblyName System.Windows.Forms
$clip = [System.Windows.Forms.Clipboard]::GetText()
if ($clip) {
    Write-Output "[+] clipboard contents:"
    Write-Output $clip
} else {
    Write-Output "[-] clipboard empty or non-text"
}
