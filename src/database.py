# lang: Python 3, file: database.py, target: all platforms
# SQLite client persistence layer

import os, sqlite3, time

_db_conn = None


def db_init(path: str) -> bool:
    global _db_conn
    try:
        _db_conn = sqlite3.connect(path, check_same_thread=False)
        _db_conn.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                ip         TEXT PRIMARY KEY,
                label      TEXT,
                user       TEXT,
                os         TEXT,
                first_seen TEXT,
                last_seen  TEXT,
                note       TEXT
            )
        """)
        _db_conn.commit()
        print(f"[db] initialized at {path}")
        return True
    except Exception as e:
        print(f"[db] init error: {e}")
        return False


def db_close():
    global _db_conn
    if _db_conn:
        try:
            _db_conn.close()
        except Exception:
            pass
        _db_conn = None


def db_upsert(ip: str, label: str, user: str = "", os_str: str = ""):
    if not _db_conn:
        return
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        _db_conn.execute("""
            INSERT INTO clients (ip, label, user, os, first_seen, last_seen, note)
            VALUES (?, ?, ?, ?, ?, ?, '')
            ON CONFLICT(ip) DO UPDATE SET
                label     = excluded.label,
                user      = excluded.user,
                os        = excluded.os,
                last_seen = excluded.last_seen
        """, (ip, label, user, os_str, now, now))
        _db_conn.commit()
    except Exception as e:
        print(f"[db] upsert error: {e}")


def db_fetch_all() -> list:
    if not _db_conn:
        return []
    try:
        cur = _db_conn.execute(
            "SELECT ip, label, user, os, first_seen, last_seen, note "
            "FROM clients ORDER BY last_seen DESC"
        )
        return cur.fetchall()
    except Exception as e:
        print(f"[db] fetch error: {e}")
        return []


def db_delete(ip: str):
    if not _db_conn:
        return
    try:
        _db_conn.execute("DELETE FROM clients WHERE ip=?", (ip,))
        _db_conn.commit()
    except Exception as e:
        print(f"[db] delete error: {e}")


def db_update_note(ip: str, note: str):
    if not _db_conn:
        return
    try:
        _db_conn.execute("UPDATE clients SET note=? WHERE ip=?", (note, ip))
        _db_conn.commit()
    except Exception as e:
        print(f"[db] note error: {e}")


def db_connected() -> bool:
    return _db_conn is not None