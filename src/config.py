import os, json, base64

CONFIG_FILE    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermies_config.json")
DB_PATH_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermies_clients.db")

HOST = "0.0.0.0"
PORT = 4444
CHUNK = 65536
AUTH_TIMEOUT = 10

SHARED_SECRET  = b""
_active_secret = b""
_config        = {}


def load_config():
    global SHARED_SECRET, _config, _active_secret
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                _config = json.load(fh)
            secret_b64 = _config.get("hmac_secret", "")
            if secret_b64:
                SHARED_SECRET  = secret_b64.encode()
                _active_secret = SHARED_SECRET
                print(f"[config] loaded HMAC secret from {CONFIG_FILE}")
        except Exception as e:
            print(f"[config] load error: {e}")
    else:
        print(f"[config] no config file found at {CONFIG_FILE}")


def save_config():
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(_config, fh, indent=2)
        print(f"[config] saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"[config] save error: {e}")


def get_active_secret():
    return _active_secret


def set_active_secret(secret_bytes: bytes):
    global _active_secret, SHARED_SECRET
    _active_secret = SHARED_SECRET = secret_bytes