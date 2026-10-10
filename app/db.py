"""SQLite data layer for BenchPilot. stdlib sqlite3 only, no ORM."""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from . import emptype

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
    # USA market: drop jobs that clearly name a non-US location
    "usa_only": "1",
    # which employment types the recruiter wants (steers Adzuna/JSearch queries)
    "collect_emp_types": "fulltime,c2c,w2",
    "collect_interval_minutes": "60",
    # fully automatic mode: search for what the consultants' resumes say, and
    # learn new skill names from resumes (see app/autolearn.py)
    "auto_queries": "1",
    "max_queries": "8",
    "auto_learn_skills": "1",
    # Adzuna's default key allows 250 calls/day and 2,500/month; stay under it
    "adzuna_daily_budget": "80",
    # Agent Office / Tailor: draft a tailored resume for matches at/above
    # this score (drafts only; a person confirms any added skill)
    "tailor_cutoff": "65",
    # resume folder import (Google Drive): see app/resume_import.py
    "resume_folder_url": "",
    "google_api_key": "",
    "resume_import_minutes": "60",
    "tailor_max_per_run": "10",
    "search_queries": json.dumps(DEFAULT_SEARCH_QUERIES),
    "office_autopilot": "1",
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
    emp_pref TEXT DEFAULT '',
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
    emp_tags TEXT,
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
CREATE TABLE IF NOT EXISTS outreach_drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL UNIQUE,
    subject TEXT DEFAULT '',
    body TEXT DEFAULT '',
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
CREATE TABLE IF NOT EXISTS learned_skills (
    skill TEXT PRIMARY KEY,
    source TEXT DEFAULT '',
    learned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imported_files (
    file_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    version TEXT DEFAULT '',
    status TEXT DEFAULT 'ok',
    consultant_id INTEGER,
    error TEXT DEFAULT '',
    imported_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_usage (
    day TEXT NOT NULL,
    source TEXT NOT NULL,
    hits INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, source)
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


def _columns(conn, table: str) -> set:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        # --- migrations for databases created by older versions ---
        if "emp_tags" not in _columns(conn, "jobs"):
            conn.execute("ALTER TABLE jobs ADD COLUMN emp_tags TEXT")
        if "emp_pref" not in _columns(conn, "consultants"):
            conn.execute("ALTER TABLE consultants ADD COLUMN emp_pref TEXT DEFAULT ''")
        if "user_confirmed_skills_json" not in _columns(conn, "tailored_resumes"):
            conn.execute("ALTER TABLE tailored_resumes "
                         "ADD COLUMN user_confirmed_skills_json TEXT DEFAULT '[]'")
        if "needs_check" not in _columns(conn, "consultants"):
            conn.execute("ALTER TABLE consultants ADD COLUMN needs_check INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE consultants ADD COLUMN check_notes TEXT DEFAULT ''")
        if "compliance_flag" not in _columns(conn, "matches"):
            conn.execute('ALTER TABLE "matches" ADD COLUMN compliance_flag INTEGER DEFAULT 0')
        # backfill employment tags for jobs saved before tagging existed
        for r in conn.execute("SELECT id, employment_type, title, description "
                              "FROM jobs WHERE emp_tags IS NULL").fetchall():
            tags = emptype.classify(r["employment_type"], r["title"], r["description"])
            conn.execute("UPDATE jobs SET emp_tags=? WHERE id=?",
                         (emptype.to_db(tags), r["id"]))
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v)
            )
        # when the tagging rules change (emptype.VERSION), re-tag every saved job once
        row = conn.execute("SELECT value FROM settings WHERE key='emp_tags_version'").fetchone()
        if not row or row["value"] != str(emptype.VERSION):
            for r in conn.execute("SELECT id, employment_type, title, description "
                                  "FROM jobs").fetchall():
                tags = emptype.classify(r["employment_type"], r["title"], r["description"])
                conn.execute("UPDATE jobs SET emp_tags=? WHERE id=?",
                             (emptype.to_db(tags), r["id"]))
            conn.execute("INSERT INTO settings(key, value) VALUES ('emp_tags_version', ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (str(emptype.VERSION),))
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
               linkedin_url, notes, emp_pref, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("name", "").strip(),
                data.get("email", ""),
                data.get("phone", ""),
                data.get("location", ""),
                data.get("visa_status", ""),
                data.get("linkedin_url", ""),
                data.get("notes", ""),
                _clean_pref(data.get("emp_pref", "")),
                now_iso(),
            ),
        )
        conn.commit()
        return get_consultant(cur.lastrowid)


def set_consultant_check(cid: int, needs_check: bool, notes=None) -> None:
    """Mark a consultant created from a resume as 'needs a quick check' (or clear it)."""
    text = "; ".join(notes) if isinstance(notes, list) else (notes or "")
    with get_conn() as conn:
        conn.execute("UPDATE consultants SET needs_check=?, check_notes=? WHERE id=?",
                     (1 if needs_check else 0, text[:500], cid))
        conn.commit()


def _clean_pref(v) -> str:
    """Normalise a consultant's engagement preference to 'c2c,w2,fulltime'."""
    if isinstance(v, list):
        v = ",".join(v)
    return ",".join(emptype.parse_wanted(v or ""))


def update_consultant(cid: int, data: dict) -> dict | None:
    fields = ["name", "email", "phone", "location", "visa_status",
              "linkedin_url", "notes", "emp_pref"]
    sets, vals = [], []
    for f in fields:
        if f in data:
            sets.append(f"{f}=?")
            vals.append(_clean_pref(data[f]) if f == "emp_pref" else data[f])
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


def update_resume_skills(consultant_id: int, skills: list) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE resumes SET skills_json=? WHERE consultant_id=?",
                     (json.dumps(skills), consultant_id))
        conn.commit()


# ---- learned skills (vocabulary that grows from the resumes we hold) ----
def list_learned_skills() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT skill, source, learned_at FROM learned_skills "
            "ORDER BY learned_at DESC, skill")]


def add_learned_skills(skills: list, source: str = "") -> list:
    """Insert new skills; returns the ones that were actually new."""
    new = []
    with get_conn() as conn:
        for sk in skills:
            cur = conn.execute(
                "INSERT OR IGNORE INTO learned_skills(skill, source, learned_at) "
                "VALUES (?, ?, ?)", (sk, source, now_iso()))
            if cur.rowcount:
                new.append(sk)
        conn.commit()
    return new


def delete_learned_skill(skill: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM learned_skills WHERE skill=?", (skill,))
        conn.commit()
        return cur.rowcount > 0


# ---- daily API call budget (protects free-tier keys) ----
def usage_today(source: str) -> int:
    day = now_iso()[:10]
    with get_conn() as conn:
        r = conn.execute("SELECT hits FROM api_usage WHERE day=? AND source=?",
                         (day, source)).fetchone()
        return r["hits"] if r else 0


def usage_add(source: str, hits: int) -> None:
    day = now_iso()[:10]
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO api_usage(day, source, hits) VALUES (?, ?, ?) "
            "ON CONFLICT(day, source) DO UPDATE SET hits = hits + excluded.hits",
            (day, source, hits))
        conn.commit()


# ---- jobs ----
def insert_job(job: dict) -> int | None:
    """Insert a job dict. Returns new id, or None if duplicate."""
    tags = emptype.to_db(emptype.classify(
        job.get("employment_type", ""), job.get("title", ""),
        job.get("description", "")))
    with get_conn() as conn:
        # fuzzy dedupe: same title + company + location already present from
        # any source. (Location is part of the key: staffing vendors post the
        # same title in many cities and each is a separate opening.)
        dup = conn.execute(
            "SELECT id FROM jobs WHERE lower(title)=lower(?) AND "
            "lower(company)=lower(?) AND lower(location)=lower(?)",
            (job.get("title", ""), job.get("company", ""),
             job.get("location", "")),
        ).fetchone()
        if dup:
            return None
        try:
            cur = conn.execute(
                """INSERT INTO jobs(source, source_id, title, company, location,
                   remote_flag, url, description, posted_at, salary,
                   employment_type, emp_tags, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    tags,
                    now_iso(),
                ),
            )
            conn.commit()
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


def _with_tags(row: dict) -> dict:
    row["emp_tags"] = emptype.from_db(row.get("emp_tags") or "")
    return row


def list_jobs(source: str = "", q: str = "", limit: int = 50,
              emp: list | None = None, include_unspecified: bool = False) -> list:
    """emp: employment tags to keep (OR). Jobs with no detectable type are kept
    only when include_unspecified is true."""
    sql = "SELECT * FROM jobs WHERE 1=1"
    vals: list = []
    if source:
        sql += " AND source=?"
        vals.append(source)
    if q:
        sql += " AND (title LIKE ? OR company LIKE ? OR description LIKE ?)"
        vals += [f"%{q}%"] * 3
    if emp:
        conds = ["emp_tags LIKE ?"] * len(emp)
        vals += [f"%,{t},%" for t in emp]
        if include_unspecified:
            conds.append("COALESCE(emp_tags,'')=''")
        sql += " AND (" + " OR ".join(conds) + ")"
    sql += " ORDER BY fetched_at DESC, id DESC LIMIT ?"
    vals.append(max(1, min(limit, 1000)))
    with get_conn() as conn:
        return [_with_tags(dict(r)) for r in conn.execute(sql, vals)]


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


def update_match(mid: int, score: float, breakdown: dict, missing: list) -> None:
    with get_conn() as conn:
        conn.execute(
            'UPDATE "matches" SET score=?, score_breakdown_json=?, '
            'missing_skills_json=? WHERE id=?',
            (score, json.dumps(breakdown), json.dumps(missing), mid))
        conn.commit()


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
           'j.source, j.posted_at, j.salary, j.employment_type, j.emp_tags, '
           'j.remote_flag, c.name AS consultant_name '
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
        _with_tags(r)
    return rows


def get_match(mid: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute(
            'SELECT m.*, j.title AS job_title, j.company, j.location, j.url, '
            'j.source, j.posted_at, j.salary, j.employment_type, j.emp_tags, '
            'j.description AS job_description, c.name AS consultant_name '
            'FROM "matches" m JOIN jobs j ON j.id=m.job_id '
            'JOIN consultants c ON c.id=m.consultant_id WHERE m.id=?',
            (mid,),
        ).fetchone()
        if not r:
            return None
        d = _with_tags(dict(r))
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
        d["user_confirmed_skills"] = json.loads(
            d.pop("user_confirmed_skills_json", None) or "[]")
        return d


def update_tailored(tid: int, text: str, confirmed: list) -> dict | None:
    """Replace the tailored text and merge newly user-confirmed skills.

    Confirmed skills are the recruiter's explicit attestation that the
    candidate has them, so they are removed from `added_skills_flagged`.
    Returns the updated tailored-resume dict, or None if not found.
    """
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM tailored_resumes WHERE id=?", (tid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        prev = set(json.loads(d.get("user_confirmed_skills_json") or "[]"))
        merged = sorted(prev | set(confirmed))
        flagged = [s for s in json.loads(d.get("added_skills_flagged_json") or "[]")
                   if s not in merged]
        conn.execute(
            "UPDATE tailored_resumes SET tailored_text=?, "
            "added_skills_flagged_json=?, user_confirmed_skills_json=? WHERE id=?",
            (text, json.dumps(flagged), json.dumps(merged), tid),
        )
        conn.commit()
    return get_tailored(tid)


# ---- outreach drafts ----
def insert_outreach_draft(match_id: int, subject: str, body: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO outreach_drafts(match_id, subject, body, created_at)"
            " VALUES (?, ?, ?, ?)",
            (match_id, subject, body, now_iso()),
        )
        conn.commit()
        if cur.lastrowid:
            return cur.lastrowid
        r = conn.execute("SELECT id FROM outreach_drafts WHERE match_id=?",
                         (match_id,)).fetchone()
        return r["id"] if r else 0


def has_outreach_draft(match_id: int) -> bool:
    with get_conn() as conn:
        r = conn.execute("SELECT id FROM outreach_drafts WHERE match_id=? LIMIT 1",
                         (match_id,)).fetchone()
        return r is not None


def list_outreach_drafts(limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT d.*, j.title AS job_title, j.company, c.name AS consultant_name '
            'FROM outreach_drafts d JOIN "matches" m ON m.id=d.match_id '
            'JOIN jobs j ON j.id=m.job_id JOIN consultants c ON c.id=m.consultant_id '
            'ORDER BY d.id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(r) for r in rows]


# ---- compliance quarantine ----
def set_compliance_flag(mid: int, flag: int) -> None:
    with get_conn() as conn:
        conn.execute('UPDATE "matches" SET compliance_flag=? WHERE id=?',
                     (1 if flag else 0, mid))
        conn.commit()


def list_quarantined(limit: int = 50) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT m.*, j.title AS job_title, j.company, j.location, '
            'c.name AS consultant_name FROM "matches" m '
            'JOIN jobs j ON j.id=m.job_id JOIN consultants c ON c.id=m.consultant_id '
            'WHERE m.compliance_flag=1 ORDER BY m.score DESC LIMIT ?',
            (limit,)).fetchall()
        return [dict(r) for r in rows]


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
