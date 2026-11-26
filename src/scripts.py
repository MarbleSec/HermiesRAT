# lang: Python 3, file: scripts.py, target: all platforms
# script folder scanner — .ps1 / .sh / .bat — windows + linux subfolders

import os

_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")
_EXT_SHELL = {".ps1": "powershell", ".sh": "bash", ".bat": "cmd"}

PLATFORM_DIRS = {
    "windows": os.path.join(_BASE, "windows"),
    "linux":   os.path.join(_BASE, "linux"),
}


def scan_scripts() -> dict:
    result = {}
    for platform, dirpath in PLATFORM_DIRS.items():
        if not os.path.isdir(dirpath):
            print(f"[scripts] dir not found: {dirpath}")
            continue
        scripts = []
        try:
            for f in sorted(os.scandir(dirpath), key=lambda e: e.name.lower()):
                if not f.is_file():
                    continue
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in _EXT_SHELL:
                    continue
                scripts.append({
                    "name":     f.name,
                    "path":     f.path,
                    "shell":    _EXT_SHELL[ext],
                    "size":     f.stat().st_size,
                    "platform": platform,
                })
        except OSError as e:
            print(f"[scripts] scan error in {dirpath}: {e}")
        if scripts:
            result[platform] = scripts
            print(f"[scripts] {platform}: {len(scripts)} script(s)")
    return result
