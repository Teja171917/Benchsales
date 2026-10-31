"""Individual user accounts for BenchPilot.

One central accounts database (data/accounts.db, next to the main bench
database) holds every user of the deployment. A user belongs to exactly
one workspace: the main bench (company_slug NULL) or one company from
db.companies(). Admins create and manage the users of their own
workspace; members just sign in.

Sign-in is by email + password (PBKDF2-HMAC-SHA256, stdlib only) or,
when Google OAuth is configured, by a Google identity whose email
matches an existing account. Sessions are random tokens; only their
SHA-256 hash is stored.

This layer replaces the shared company password over time: the server
accepts session logins first and falls back to the legacy Basic logins
while a workspace migrates.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path

from . import db

ACCOUNTS_PATH = Path(db.DB_PATH).parent / "accounts.db"

_PBKDF2_ROUNDS = 240_000
_SESSION_DAYS = 14
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_ready = False


def _conn():
    ACCOUNTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ACCOUNTS_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_accounts() -> None:
    """Create the accounts tables if they do not exist yet."""
    global _ready
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL DEFAULT '',
                password_hash TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'member',
                company_slug TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )""")
        # The backup layer (persist.py) stamps every database file it
        # keeps through a settings table; accounts.db carries one too so
        # backups and restores treat it exactly like a bench database.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )""")
    _ready = True


def _ensure():
    if not _ready:
        init_accounts()


def slugify(name: str) -> str:
    """Same slug rule as db.companies(): a company's workspace key."""
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


def workspace_slugs() -> list:
    """['main'] plus one slug per configured company."""
    return ["main"] + [slugify(c["name"]) for c in db.companies()]


def _slug_for_path(path) -> str:
    if path is None:
        return "main"
    for c in db.companies():
        if Path(c["path"]) == Path(path):
            return slugify(c["name"])
    return "main"


def target_path_for(user: dict):
    """The database file a user's workspace opens (None = main bench),
    or False when the workspace no longer exists."""
    slug = user.get("company_slug")
    if not slug:
        return None
    for c in db.companies():
        if slugify(c["name"]) == slug:
            return c["path"]
    return False


# ---------- passwords ----------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", (password or "").encode(),
                                 salt, _PBKDF2_ROUNDS)
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ROUNDS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, rounds, salt_b64, digest_b64 = (stored or "").split("$")
        if kind != "pbkdf2":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", (password or "").encode(),
                                     salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ---------- users ----------

def _row_user(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"],
            "role": row["role"], "company_slug": row["company_slug"],
            "active": bool(row["active"]), "created_at": row["created_at"]}


def any_users() -> bool:
    _ensure()
    with _conn() as conn:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0


def count_users(company_slug=None) -> int:
    _ensure()
    with _conn() as conn:
        if company_slug is None:
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE company_slug IS NULL"
            ).fetchone()[0]
        return conn.execute(
            "SELECT COUNT(*) FROM users WHERE company_slug = ?",
            (company_slug,)).fetchone()[0]


def get_user_by_email(email: str):
    _ensure()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?",
                           ((email or "").strip().lower(),)).fetchone()
    return _row_user(row) if row else None


def get_user(user_id: int):
    _ensure()
    with _conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?",
                           (user_id,)).fetchone()
    return _row_user(row) if row else None


def create_user(email: str, name: str, password: str, role: str = "member",
                company_slug: str = None) -> dict:
    """Create one user. Raises ValueError with a plain message on bad input."""
    _ensure()
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("that email address does not look right")
    if role not in ("admin", "member"):
        raise ValueError("role must be admin or member")
    if company_slug == "main":
        company_slug = None
    if company_slug is not None and company_slug not in workspace_slugs():
        raise ValueError("unknown workspace")
    if password and len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    if get_user_by_email(email):
        raise ValueError("an account with that email already exists")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, name, password_hash, role,"
            " company_slug, active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            (email, (name or "").strip(),
             hash_password(password) if password else "",
             role, company_slug, time.time()))
        user_id = cur.lastrowid
    return get_user(user_id)


def list_users(company_slug="__all__") -> list:
    _ensure()
    with _conn() as conn:
        if company_slug == "__all__":
            rows = conn.execute("SELECT * FROM users ORDER BY email").fetchall()
        elif company_slug is None:
            rows = conn.execute(
                "SELECT * FROM users WHERE company_slug IS NULL"
                " ORDER BY email").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM users WHERE company_slug = ? ORDER BY email",
                (company_slug,)).fetchall()
    return [_row_user(r) for r in rows]


def set_password(user_id: int, password: str) -> None:
    if not password or len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    _ensure()
    with _conn() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?",
                     (hash_password(password), user_id))
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def set_active(user_id: int, active: bool) -> None:
    _ensure()
    with _conn() as conn:
        conn.execute("UPDATE users SET active = ? WHERE id = ?",
                     (1 if active else 0, user_id))
        if not active:
            conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))


def authenticate(email: str, password: str):
    """The active user for these credentials, or None."""
    user = get_user_by_email(email)
    if not user or not user["active"] or not user.get("id"):
        return None
    _ensure()
    with _conn() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?",
                           (user["id"],)).fetchone()
    if not row or not row["password_hash"]:
        return None
    return user if verify_password(password, row["password_hash"]) else None


# ---------- sessions ----------

def _token_hash(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def create_session(user_id: int) -> str:
    _ensure()
    token = secrets.token_urlsafe(32)
    now = time.time()
    with _conn() as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at, created_at)"
            " VALUES (?, ?, ?, ?)",
            (_token_hash(token), user_id, now + _SESSION_DAYS * 86400, now))
    return token


def resolve_session(token: str):
    """The active user behind a session token, or None."""
    if not token:
        return None
    _ensure()
    with _conn() as conn:
        row = conn.execute(
            "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?",
            (_token_hash(token),)).fetchone()
        if not row:
            return None
        if row["expires_at"] < time.time():
            conn.execute("DELETE FROM sessions WHERE token_hash = ?",
                         (_token_hash(token),))
            return None
    user = get_user(row["user_id"])
    return user if user and user["active"] else None


def delete_session(token: str) -> None:
    if not token:
        return
    _ensure()
    with _conn() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?",
                     (_token_hash(token),))


# ---------- Google sign-in (active only when OAuth secrets are set) ----------

def google_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID")
                and os.environ.get("GOOGLE_CLIENT_SECRET"))


def google_user_for_email(email: str):
    """Google sign-in never creates accounts: the admin adds the user
    first, then that person can sign in with Google instead of a
    password."""
    user = get_user_by_email(email)
    return user if user and user["active"] else None
