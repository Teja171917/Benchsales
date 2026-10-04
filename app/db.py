"""SQLite data layer for BenchPilot. stdlib sqlite3 only, no ORM."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("BENCHPILOT_DB", BASE_DIR / "data" / "benchpilot.db"))

DEFAULT_SEARCH_QUERIES = [
    {"title": "Java Developer", "location": "Houston, TX"},
    {"title": "QA Automation Engineer", "location": "Remote"},
    {"title": "Python Developer", "location": "Remote"},
    {"title": "DevOps Engineer", "location": "Houston, TX"},
]
DEFAULT_ENABLED_SOURCES = ["adzuna", "jsearch", "remoteok", "remotive"]
# arbeidnow exists as a bonus adapter but is OFF by default (EU-leaning source).

DEFAULT_SETTINGS = {
    "match_threshold": "60",
    "collect_interval_minutes": "60",
    "search_queries": json.dumps(DEFAULT_SEARCH_QUERIES),
    "enabled_sources": json.dumps(DEFAULT_ENABLED_SOURCES),
    "adzuna_app_id": "",
    "adzuna_app_key": "",
    "rapidapi_key": "",
    "llm_base_url": "",
    "llm_api_key": "",
    "llm_model": "",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS consultants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT DEFAULT '',
    phone TEXT DEFAULT '',
    location TEXT DEFAULT '',
    visa_status TEXT DEFAULT '',
    linkedin_url TEXT DEFAULT '',
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consultant_id INTEGER NOT NULL UNIQUE,
    filename TEXT DEFAULT '',
    raw_text TEXT DEFAULT '',
    skills_json TEXT DEFAULT '[]',
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY (consultant_id) REFERENCES consultants(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    source_id TEXT NOT NULL,
    title TEXT DEFAULT '',
    company TEXT DEFAULT '',
    location TEXT DEFAULT '',
    remote_flag INTEGER DEFAULT 0,
    url TEXT DEFAULT '',
    description TEXT DEFAULT '',
    posted_at TEXT DEFAULT '',
    salary TEXT DEFAULT '',
    employment_type TEXT DEFAULT '',
    fetched_at TEXT NOT NULL,
    UNIQUE(source, source_id)
);
CREATE TABLE IF NOT EXISTS "matches" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    consultant_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    score REAL NOT NULL,
    score_breakdown_json TEXT DEFAULT '{}',
    missing_skills_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE(consultant_id, job_id),
    FOREIGN KEY (consultant_id) REFERENCES consultants(id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS tailored_resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    tailored_text TEXT DEFAULT '',
    tailored_by TEXT DEFAULT '',
    added_skills_flagged_json TEXT DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES "matches"(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    tailored_resume_id INTEGER,
    applied_at TEXT,
    notes TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES "matches"(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
        conn.commit()


# ---- settings ----
def get_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}


def get_setting(key: str, default: str = "") -> str:
    s = get_settings()
    return s.get(key, default)


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()


# ---- consultants ----
def list_consultants() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM consultants ORDER BY id")]


def get_consultant(cid: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM consultants WHERE id=?", (cid,)).fetchone()
        return dict(r) if r else None


def create_consultant(data: dict) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO consultants(name, email, phone, location, visa_status,
               linkedin_url, notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("name", "").strip(),
                data.get("email", ""),
                data.get("phone", ""),
                data.get("location", ""),
                data.get("visa_status", ""),
                data.get("linkedin_url", ""),
                data.get("notes", ""),
                now_iso(),
            ),
        )
        conn.commit()
        return get_consultant(cur.lastrowid)


def update_consultant(cid: int, data: dict) -> dict | None:
    fields = ["name", "email", "phone", "location", "visa_status",
              "linkedin_url", "notes"]
    sets, vals = [], []
    for f in fields:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(data[f])
    if sets:
        vals.append(cid)
        with get_conn() as conn:
            conn.execute(f"UPDATE consultants SET {', '.join(sets)} WHERE id=?", vals)
            conn.commit()
    return get_consultant(cid)


def delete_consultant(cid: int) -> bool:
    with get_conn() as conn:
        # cascade manually for safety
        conn.execute("DELETE FROM applications WHERE match_id IN "
                     "(SELECT id FROM \"matches\" WHERE consultant_id=?)", (cid,))
        conn.execute("DELETE FROM tailored_resumes WHERE match_id IN "
                     "(SELECT id FROM \"matches\" WHERE consultant_id=?)", (cid,))
        conn.execute("DELETE FROM \"matches\" WHERE consultant_id=?", (cid,))
        conn.execute("DELETE FROM resumes WHERE consultant_id=?", (cid,))
        cur = conn.execute("DELETE FROM consultants WHERE id=?", (cid,))
        conn.commit()
        return cur.rowcount > 0


# ---- resumes ----
def upsert_resume(consultant_id: int, filename: str, raw_text: str,
                  skills: list) -> dict:
    with get_conn() as conn:
        conn.execute("DELETE FROM resumes WHERE consultant_id=?", (consultant_id,))
        cur = conn.execute(
            """INSERT INTO resumes(consultant_id, filename, raw_text, skills_json,
               uploaded_at) VALUES (?, ?, ?, ?, ?)""",
            (consultant_id, filename, raw_text, json.dumps(skills), now_iso()),
        )
        conn.commit()
        r = conn.execute("SELECT * FROM resumes WHERE id=?",
                         (cur.lastrowid,)).fetchone()
        return dict(r)


def get_resume(consultant_id: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM resumes WHERE consultant_id=?",
                         (consultant_id,)).fetchone()
        return dict(r) if r else None


def consultants_with_resumes() -> list:
    """Consultants that have a parsed resume, with skills list attached."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, r.raw_text, r.skills_json, r.filename
               FROM consultants c JOIN resumes r
               ON r.consultant_id = c.id ORDER BY c.id"""
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["skills"] = json.loads(d.pop("skills_json") or "[]")
        out.append(d)
    return out


# ---- jobs ----
def insert_job(job: dict) -> int | None:
    """Insert a job dict. Returns new id, or None if duplicate."""
    with get_conn() as conn:
        # fuzzy dedupe: same title+company already present from any source
        dup = conn.execute(
            "SELECT id FROM jobs WHERE lower(title)=lower(?) AND lower(company)=lower(?)",
            (job.get("title", ""), job.get("company", "")),
        ).fetchone()
        if dup:
            return None
        try:
            cur = conn.execute(
                """INSERT INTO jobs(source, source_id, title, company, location,
                   remote_flag, url, description, posted_at, salary,
                   employment_type, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    job.get("source", ""),
                    job.get("source_id", ""),
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    1 if job.get("remote_flag") else 0,
                    job.get("url", ""),
                    job.get("description", ""),
                    job.get("posted_at", ""),
                    job.get("salary", ""),
                    job.get("employment_type", ""),
                    now_iso(),
                ),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def list_jobs(source: str = "", q: str = "", limit: int = 50) -> list:
    sql = "SELECT * FROM jobs WHERE 1=1"
    vals: list = []
    if source:
        sql += " AND source=?"
        vals.append(source)
    if q:
        sql += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
        vals += [f"%{q}%"] * 3
    sql += " ORDER BY fetched_at DESC, id DESC LIMIT ?"
    vals.append(max(1, min(limit, 500)))
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, vals)]


def get_job(jid: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        return dict(r) if r else None


def count_jobs() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]


# ---- matches ----
def insert_match(consultant_id: int, job_id: int, score: float,
                 breakdown: dict, missing: list) -> int | None:
    with get_conn() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO "matches"(consultant_id, job_id, score,
                   score_breakdown_json, missing_skills_json, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (consultant_id, job_id, score, json.dumps(breakdown),
                 json.dumps(missing), now_iso()),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def match_exists(consultant_id: int, job_id: int) -> bool:
    with get_conn() as conn:
        r = conn.execute(
            'SELECT id FROM "matches" WHERE consultant_id=? AND job_id=?',
            (consultant_id, job_id),
        ).fetchone()
        return r is not None


def list_matches(consultant_id: int | None = None,
                 min_score: float = 0) -> list:
    sql = ('SELECT m.*, j.title AS job_title, j.company, j.location, j.url, '
           'j.source, j.posted_at, j.salary, c.name AS consultant_name '
           'FROM "matches" m JOIN jobs j ON j.id=m.job_id '
           'JOIN consultants c ON c.id=m.consultant_id WHERE m.score >= ?')
    vals: list = [min_score]
    if consultant_id:
        sql += " AND m.consultant_id=?"
        vals.append(consultant_id)
    sql += " ORDER BY m.score DESC, m.id DESC"
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(sql, vals)]
    for r in rows:
        r["score_breakdown"] = json.loads(r.pop("score_breakdown_json") or "{}")
        r["missing_skills"] = json.loads(r.pop("missing_skills_json") or "[]")
    return rows


def get_match(mid: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute(
            'SELECT m.*, j.title AS job_title, j.company, j.location, j.url, '
            'j.source, j.posted_at, j.salary, j.description AS job_description, '
            'c.name AS consultant_name '
            'FROM "matches" m JOIN jobs j ON j.id=m.job_id '
            'JOIN consultants c ON c.id=m.consultant_id WHERE m.id=?',
            (mid,),
        ).fetchone()
        if not r:
            return None
        d = dict(r)
        d["score_breakdown"] = json.loads(d.pop("score_breakdown_json") or "{}")
        d["missing_skills"] = json.loads(d.pop("missing_skills_json") or "[]")
        res = conn.execute("SELECT raw_text, skills_json FROM resumes "
                           "WHERE consultant_id=?", (d["consultant_id"],)).fetchone()
        if res:
            d["resume_text"] = res["raw_text"]
            d["resume_skills"] = json.loads(res["skills_json"] or "[]")
        else:
            d["resume_text"] = ""
            d["resume_skills"] = []
        return d


# ---- tailored resumes ----
def insert_tailored(match_id: int, text: str, tailored_by: str,
                    flagged: list) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO tailored_resumes(match_id, tailored_text, tailored_by,
               added_skills_flagged_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (match_id, text, tailored_by, json.dumps(flagged), now_iso()),
        )
        conn.commit()
        return cur.lastrowid


def get_tailored(tid: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM tailored_resumes WHERE id=?", (tid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["added_skills_flagged"] = json.loads(
            d.pop("added_skills_flagged_json") or "[]")
        return d


# ---- applications ----
APPLICATION_STATUSES = ["queued", "applied", "screening", "interview",
                        "offered", "placed", "rejected", "withdrawn"]


def queue_application(match_id: int, tailored_resume_id: int | None = None) -> dict:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO applications(match_id, status, tailored_resume_id,
               updated_at) VALUES (?, 'queued', ?, ?)
               ON CONFLICT(match_id) DO UPDATE SET updated_at=excluded.updated_at""",
            (match_id, tailored_resume_id, now_iso()),
        )
        conn.commit()
        r = conn.execute("SELECT * FROM applications WHERE match_id=?",
                         (match_id,)).fetchone()
        return dict(r)


def list_applications(status: str = "") -> list:
    sql = ('SELECT a.*, c.name AS consultant_name, j.title AS job_title, '
           'j.company, j.url, j.location, m.score '
           'FROM applications a JOIN "matches" m ON m.id=a.match_id '
           'JOIN consultants c ON c.id=m.consultant_id '
           'JOIN jobs j ON j.id=m.job_id')
    vals: list = []
    if status:
        sql += " WHERE a.status=?"
        vals.append(status)
    sql += " ORDER BY a.updated_at DESC"
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, vals)]


def update_application(aid: int, status: str | None, notes: str | None) -> dict | None:
    if status and status not in APPLICATION_STATUSES:
        raise ValueError(f"invalid status: {status}")
    sets, vals = ["updated_at=?"], [now_iso()]
    if status:
        sets.append("status=?")
        vals.append(status)
    if notes is not None:
        sets.append("notes=?")
        vals.append(notes)
    vals.append(aid)
    with get_conn() as conn:
        conn.execute(f"UPDATE applications SET {', '.join(sets)} WHERE id=?", vals)
        if status == "applied":
            conn.execute("UPDATE applications SET applied_at=? WHERE id=? AND "
                         "applied_at IS NULL", (now_iso(), aid))
        conn.commit()
        r = conn.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
        return dict(r) if r else None
