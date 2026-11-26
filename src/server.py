# lang: Python 3, file: server.py, target: all platforms
# accept loop, client registration, shared state

import threading, time
from auth      import verify_client
from messaging import send_msg, recv_msg
from database  import db_upsert
import config  as cfg

clients           = {}
client_id_counter = 0
_lock             = threading.Lock()
_map_geo_cache    = {}   # ip -> {lat, lon, city, country, org}


def accept_loop(server_sock, gui):
    while True:
        try:
            conn, addr = server_sock.accept()
        except Exception:
            break
        threading.Thread(
            target=_auth_and_register,
            args=(conn, addr, gui),
            daemon=True
        ).start()


def _auth_and_register(conn, addr, gui):
    global client_id_counter
    if not verify_client(conn, cfg.get_active_secret()):
        gui.log(f"[-] auth failed  {addr[0]}:{addr[1]}")
        try:
            conn.close()
        except Exception:
            pass
        return
    try:
        msg  = recv_msg(conn)
        info = msg.get("data", {}) if msg and msg.get("cmd") == "sysinfo" else {}
    except Exception:
        info = {}
    user   = info.get("user", "")
    os_str = info.get("os",   "")
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
    db_upsert(addr[0], f"{addr[0]}:{addr[1]}", user, os_str)
    gui.log(f"[+] authenticated  {addr[0]}:{addr[1]}  id={cid}  {os_str}  {user}")
    gui.refresh_clients()