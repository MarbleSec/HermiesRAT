# lang: Python 3, file: auth.py, target: all platforms
# HMAC-based client authentication

import hmac, hashlib, secrets, base64


def verify_client(conn, secret: bytes, timeout: int = 10) -> bool:
    try:
        conn.settimeout(timeout)
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