$code=@'
using System;using System.Runtime.InteropServices;
public struct ColorMatrix{public float m00,m01,m02,m03,m04,m10,m11,m12,m13,m14,m20,m21,m22,m23,m24,m30,m31,m32,m33,m34,m40,m41,m42,m43,m44;}
public class Mag{[DllImport("magnification.dll")]public static extern bool MagInitialize();[DllImport("magnification.dll")]public static extern bool MagSetFullscreenColorEffect(ref ColorMatrix m);}
'@
Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue
[Mag]::MagInitialize()|Out-Null
$m=New-Object ColorMatrix
$m.m00=-1;$m.m11=-1;$m.m22=-1;$m.m33=1;$m.m44=1;$m.m04=1;$m.m14=1;$m.m24=1
[Mag]::MagSetFullscreenColorEffect([ref]$m)
