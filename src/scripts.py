# lang: Python 3, file: scripts.py, target: all platforms
# script folder scanner — .ps1 / .sh / .bat

import os

SCRIPT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "src", "modules")
_EXT_SHELL = {".ps1": "powershell", ".sh": "bash", ".bat": "cmd"}


def scan_scripts() -> dict:
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
                scripts.append({
                    "name":  f.name,
                    "path":  f.path,
                    "shell": _EXT_SHELL[ext],
                    "size":  f.stat().st_size,
                })
        except OSError as e:
            print(f"[scripts] scan error in {entry.path}: {e}")
        if scripts:
            result[entry.name] = scripts
    print(f"[scripts] found {len(result)} folder(s) in {SCRIPT_BASE_DIR}")
    return result