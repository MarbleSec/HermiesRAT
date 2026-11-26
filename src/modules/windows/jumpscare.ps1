$sig = '[DllImport("user32.dll")]public static extern void keybd_event(byte k,byte s,int f,int e);'
Add-Type -MemberDefinition $sig -Name V -Namespace W -ErrorAction SilentlyContinue
1..50 | % { [W.V]::keybd_event(0xAF,0,0,0); [W.V]::keybd_event(0xAF,0,2,0); Start-Sleep -Milliseconds 20 }

Start-Process "https://youtu.be/UZw7y0-txpI"
