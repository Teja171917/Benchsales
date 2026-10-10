"""Keep the database when the website is rebuilt or goes to sleep.

A published Replit site runs on a disk that is wiped on every Republish and
when the site sleeps, so the consultants, resumes and keys saved in the local
SQLite file vanish. This module keeps a copy of that file in Replit
"App Storage" (permanent) and puts it back when the site starts.

- backup: every 20 seconds, if the database changed, a consistent snapshot is
  uploaded (one object, `benchpilot/benchpilot.db`).
- restore: at start-up, before the database is opened. The backup replaces the
  local file only when it is newer (each backup is stamped inside the file),
  so a newer local database is never overwritten.
- Nothing here can break the website: every failure is caught and shown in
  Settings ("Data backup: OFF / ON").

Without App Storage (for example on a laptop) everything is a no-op.
"""
import os
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from . import db

OBJECT = "benchpilot/benchpilot.db"
INTERVAL = 20  # seconds between "did it change?" checks

_state = {"enabled": False, "reason": "not started", "last_backup_at": None,
          "last_error": "", "restored": False, "size": 0}
_store = None
_lock = threading.Lock()
_last_sig = None


class _ReplitStore:
    """Thin adapter over replit.object_storage.Client (default bucket)."""
    def __init__(self):
        from replit.object_storage import Client  # may be missing: caller catches
        self.c = Client()

    def exists(self, name):
        return bool(self.c.exists(name))

    def put(self, name, path):
        self.c.upload_from_filename(name, str(path))

    def get(self, name, path):
        self.c.download_to_filename(name, str(path))


def _get_store():
    global _store
    if _store is not None:
        return _store
    try:
        _store = _ReplitStore()
        _state.update(enabled=True, reason="")
    except Exception as e:
        _state.update(enabled=False, reason=_why(e))
    return _store


def _why(e: Exception) -> str:
    if isinstance(e, ImportError):
        return "the package 'replit-object-storage' is not installed"
    msg = str(e)[:160]
    if "bucket" in msg.lower():
        return "no App Storage bucket is set up for this app"
    return f"App Storage is not available ({e.__class__.__name__}: {msg})"


def _stamp_of(path: Path) -> str:
    try:
        c = sqlite3.connect(path)
        try:
            r = c.execute("SELECT value FROM settings WHERE key='backup_stamp'").fetchone()
        finally:
            c.close()
        return r[0] if r else ""
    except Exception:
        return ""


def _sig(path: Path):
    try:
        st = path.stat()
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def restore(store=None) -> bool:
    """Run once at start-up, BEFORE db.init_db(). True when the local file was
    replaced by the backup."""
    global _last_sig
    store = store or _get_store()
    if store is None:
        return False
    try:
        if not store.exists(OBJECT):
            return False
        tmp = Path(tempfile.mkdtemp()) / "restore.db"
        store.get(OBJECT, tmp)
        remote = _stamp_of(tmp)
        local_path = Path(db.DB_PATH)
        local = _stamp_of(local_path) if local_path.exists() else ""
        if not local_path.exists() or (remote and remote > local):
            local_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(tmp, local_path)
            _state.update(restored=True)
            _last_sig = _sig(local_path)
            return True
        return False
    except Exception as e:
        _state.update(last_error=f"restore failed: {e.__class__.__name__}: {str(e)[:120]}")
        return False


def backup(store=None, force: bool = False) -> bool:
    """Upload a snapshot if the database changed. Never raises."""
    global _last_sig
    store = store or _get_store()
    if store is None:
        return False
    with _lock:
        try:
            path = Path(db.DB_PATH)
            sig = _sig(path)
            if sig is None or (sig == _last_sig and not force):
                return False
            db.set_setting("backup_stamp", datetime.now(timezone.utc).isoformat())
            snap = Path(tempfile.mkdtemp()) / "snapshot.db"
            src = sqlite3.connect(path)
            dst = sqlite3.connect(snap)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            store.put(OBJECT, snap)
            _state.update(last_backup_at=datetime.now(timezone.utc).isoformat(),
                          last_error="", size=snap.stat().st_size)
            _last_sig = _sig(path)   # after our own stamp write
            return True
        except Exception as e:
            _state.update(last_error=f"backup failed: {e.__class__.__name__}: {str(e)[:120]}")
            return False


def _loop():
    while True:
        time.sleep(INTERVAL)
        try:
            backup()
        except Exception:
            pass


def start_background():
    """Start the backup loop (only when App Storage is available)."""
    if _get_store() is None:
        return False
    threading.Thread(target=_loop, daemon=True, name="benchpilot-backup").start()
    return True


def status() -> dict:
    s = dict(_state)
    if _store is None and not s["enabled"] and s["reason"] == "not started":
        _get_store()
        s = dict(_state)
    return s
