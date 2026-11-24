# lang: Python 3, file: messaging.py, target: all platforms
# send_msg / recv_msg / _recvall wire protocol helpers

import json, struct


def send_msg(sock, cmd: str, data=None):
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


def _recvall(sock, n: int) -> bytes | None:
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