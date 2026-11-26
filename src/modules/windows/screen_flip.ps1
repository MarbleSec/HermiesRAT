$code=@'
using System;using System.Runtime.InteropServices;
public struct DEVMODE{[MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)]public string dmDeviceName;public short dmSpecVersion,dmDriverVersion,dmSize,dmDriverExtra;public int dmFields;public int dmPositionX,dmPositionY,dmDisplayOrientation;public int dmDisplayFixedOutput;public short dmColor,dmDuplex,dmYResolution,dmTTOption,dmCollate;[MarshalAs(UnmanagedType.ByValTStr,SizeConst=32)]public string dmFormName;public short dmLogPixels;public int dmBitsPerPel,dmPelsWidth,dmPelsHeight,dmDisplayFlags,dmDisplayFrequency;}
public class Disp{[DllImport("user32.dll")]public static extern bool EnumDisplaySettings(string d,int m,ref DEVMODE dm);[DllImport("user32.dll")]public static extern int ChangeDisplaySettings(ref DEVMODE dm,int f);}
'@
Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue
$dm=New-Object DEVMODE
$dm.dmSize=[System.Runtime.InteropServices.Marshal]::SizeOf($dm)
[Disp]::EnumDisplaySettings($null,-1,[ref]$dm)
$dm.dmFields=0x80;$dm.dmDisplayOrientation=2
[Disp]::ChangeDisplaySettings([ref]$dm,0)
