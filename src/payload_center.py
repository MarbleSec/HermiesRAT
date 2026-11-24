# lang: Python 3, file: payload_center.py, target: all platforms
# payload library — load/save hermies_payloads.json

import os, json

PAYLOADS_FILE   = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "hermies_payloads.json")
_payload_library: list = []


def pc_load():
    global _payload_library
    if os.path.exists(PAYLOADS_FILE):
        try:
            with open(PAYLOADS_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                _payload_library = data
                print(f"[payloads] loaded {len(_payload_library)} payload(s)")
                return
        except Exception as e:
            print(f"[payloads] load error: {e}")
    _payload_library = []


def pc_save():
    try:
        with open(PAYLOADS_FILE, "w", encoding="utf-8") as fh:
            json.dump(_payload_library, fh, indent=2)
    except Exception as e:
        print(f"[payloads] save error: {e}")


def get_library() -> list:
    return _payload_library