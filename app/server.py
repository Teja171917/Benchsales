"""BenchPilot v1 API server. FastAPI + vanilla JS frontend."""
import base64
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import autolearn, contact as contact_mod, db, emptype, market, portals, usa
from app import matcher as matcher_mod
from app import office as office_mod
from app import resume as resume_mod
from app import tailor as tailor_mod
from app.skills import display_name, extract_skills
from app.sources import adzuna, jsearch, remoteok, remotive, arbeitnow, dice, urlimport

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

SOURCES = [adzuna, jsearch, remoteok, remotive, arbeitnow, dice]

app = FastAPI(title="BenchPilot", version="1.0")


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    pwd = os.environ.get("BENCHPILOT_PASSWORD")
    if pwd:
        ok = False
        auth = request.headers.get("authorization", "")
        if auth.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8", "ignore")
                _, _, given = decoded.partition(":")
                ok = secrets.compare_digest(given, pwd)
            except Exception:
                ok = False
        if not ok:
            return JSONResponse({"detail": "authentication required"},
                                status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="BenchPilot"'})
    return await call_next(request)


@app.on_event("startup")
def _startup():
    db.init_db()
    autolearn.sync_vocabulary()  # learned skills back into memory after a restart
    t = threading.Thread(target=_auto_collect_loop, daemon=True,
                         name="benchpilot-auto-collect")
    t.start()


# ---------- auto-refresh scheduler ----------
_collect_lock = threading.Lock()
_collect_status = {
    "last_run_at": None,      # ISO timestamp of last finished run
    "last_result": None,      # {"jobs_new": n, "matches_new": n, ...}
    "next_run_at": None,      # ISO timestamp of next scheduled run
    "running": False,
}


def _do_collect() -> dict:
    """Run one collection cycle (manual or scheduled). Thread-safe."""
    from collector import run
    with _collect_lock:
        _collect_status["running"] = True
        try:
            summary = run()
        finally:
            _collect_status["running"] = False
            # stored in the database so a restart does not reset the schedule
            db.set_setting("last_collect_at", datetime.now(timezone.utc).isoformat())
    _collect_status["last_run_at"] = datetime.now(timezone.utc).isoformat()
    _collect_status["last_result"] = {
        "jobs_new": summary.get("jobs_new", 0),
        "matches_new": summary.get("matches_new", 0),
        "errors": summary.get("errors", []),
        "learned_skills": summary.get("learned_skills", []),
        "rescored": summary.get("rescored", 0),
        "queries": summary.get("queries", []),
    }
    return summary


def _next_due(interval: int):
    """When the next automatic refresh is due: `interval` minutes after the
    last finished one. The last-finished time is stored in the database, so a
    restart (free hosting restarts often) does not reset the clock."""
    last = db.get_setting("last_collect_at", "") or ""
    try:
        d = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
    except ValueError:
        d = None
    if d is None:
        return datetime.now(timezone.utc)  # never ran: run now
    return d + timedelta(minutes=interval)


def _auto_collect_loop():
    """Background loop: refresh jobs on the schedule (the interval is the
    setting, slowed down when needed to respect the job API's daily limit),
    then let the Agent Office work on the fresh jobs."""
    while True:
        try:
            interval = autolearn.effective_interval_minutes()
            if interval <= 0:
                _collect_status["next_run_at"] = None
            else:
                due = _next_due(interval)
                _collect_status["next_run_at"] = due.isoformat()
                if datetime.now(timezone.utc) >= due and not _collect_status["running"]:
                    _do_collect()
        except Exception:
            pass  # collector records per-source errors; keep the loop alive
        _maybe_run_office()  # after the refresh, so it sees today's jobs
        time.sleep(30)


def _maybe_run_office():
    """Run the Agent Office once per UTC day."""
    today = datetime.now(timezone.utc).date().isoformat()
    if db.get_setting("office_last_run_date") == today:
        return
    try:
        office_mod.run_and_store()
    except Exception:
        pass  # never let the office break the scheduler loop


@app.post("/api/office/run")
def api_office_run():
    return office_mod.run_and_store()


@app.get("/api/office/briefing")
def api_office_briefing():
    raw = db.get_setting("office_briefing_json")
    if not raw:
        return {"run_at": None, "agents": {}}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"run_at": None, "agents": {}}


@app.get("/api/office/drafts")
def api_office_drafts(limit: int = 50):
    """Persisted outreach email drafts (newest first). Drafts only - the app
    never sends email itself."""
    return db.list_outreach_drafts(max(1, min(limit, 200)))


@app.post("/api/office/autopilot")
def api_office_autopilot(payload: dict):
    """Toggle autopilot: agents fix safe issues themselves (on) or only
    report them (off)."""
    enabled = bool(payload.get("enabled", True))
    db.set_setting("office_autopilot", "1" if enabled else "0")
    return {"autopilot": enabled}


@app.post("/api/matches/{mid}/unquarantine")
def api_unquarantine(mid: int):
    """Restore a match quarantined by the Compliance agent."""
    db.set_compliance_flag(mid, 0)
    return {"ok": True}

def _kick_collect():
    """Start a collection in the background unless one is already running
    (used right after a resume upload so new jobs for that person arrive
    without anyone pressing a button)."""
    if _collect_status["running"]:
        return False
    threading.Thread(target=lambda: _safe_collect(), daemon=True,
                     name="benchpilot-kick").start()
    return True


def _safe_collect():
    try:
        _do_collect()
    except Exception:
        pass


@app.get("/api/collect/status")
def api_collect_status():
    settings = db.get_settings()
    try:
        wanted = int(settings.get("collect_interval_minutes") or 0)
    except (ValueError, TypeError):
        wanted = 0
    interval = autolearn.effective_interval_minutes(settings)
    queries = autolearn.queries_for_run(settings)
    return {
        "interval_minutes": interval,
        "interval_wanted": wanted,
        "running": _collect_status["running"],
        "last_run_at": _collect_status["last_run_at"] or (
            settings.get("last_collect_at") or None),
        "next_run_at": _collect_status["next_run_at"] if interval > 0 else None,
        "last_result": _collect_status["last_result"],
        "queries": queries,
        "auto_queries": settings.get("auto_queries", "1") == "1",
        "adzuna_used_today": db.usage_today("adzuna"),
        "adzuna_daily_budget": autolearn.adzuna_budget(settings),
        "learned_skills": len(db.list_learned_skills()),
    }


@app.get("/api/learned-skills")
def api_learned_skills():
    return db.list_learned_skills()


@app.delete("/api/learned-skills/{skill}")
def api_delete_learned_skill(skill: str):
    if not db.delete_learned_skill(skill.lower()):
        raise HTTPException(404, "skill not found")
    autolearn.block_skill(skill)  # do not learn it again from the same resumes
    autolearn.maintain()  # refresh resumes + rescore without that skill
    return {"ok": True}


# ---------- consultants ----------
@app.get("/api/consultants")
def api_list_consultants():
    out = []
    for c in db.list_consultants():
        r = db.get_resume(c["id"])
        c["has_resume"] = r is not None
        c["skills"] = json.loads(r["skills_json"]) if r else []
        c["resume_filename"] = r["filename"] if r else ""
        out.append(c)
    return out


@app.post("/api/consultants")
def api_create_consultant(data: dict):
    if not (data.get("name") or "").strip():
        raise HTTPException(400, "name is required")
    return db.create_consultant(data)


@app.get("/api/consultants/{cid}")
def api_get_consultant(cid: int):
    c = db.get_consultant(cid)
    if not c:
        raise HTTPException(404, "consultant not found")
    r = db.get_resume(cid)
    c["skills"] = json.loads(r["skills_json"]) if r else []
    c["resume_filename"] = r["filename"] if r else ""
    c["resume_text"] = r["raw_text"] if r else ""
    return c


@app.put("/api/consultants/{cid}")
def api_update_consultant(cid: int, data: dict):
    c = db.update_consultant(cid, data)
    if not c:
        raise HTTPException(404, "consultant not found")
    return c


@app.delete("/api/consultants/{cid}")
def api_delete_consultant(cid: int):
    if not db.delete_consultant(cid):
        raise HTTPException(404, "consultant not found")
    return {"ok": True}


def _parse_resume(filename: str, data: bytes) -> str:
    try:
        return resume_mod.parse(filename, data)
    except ValueError as e:  # unsupported extension
        raise HTTPException(400, str(e))


def _ingest_resume(cid: int, filename: str, data: bytes, kick: bool = True) -> dict:
    """Read a resume file and attach it to consultant `cid`: learn new skills,
    store the skills, rescore, match, and (optionally) start a job search."""
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "file too large (10 MB max)")
    if not data:
        raise HTTPException(400, "the file is empty")
    try:
        text = _parse_resume(filename or "resume", data).strip()
    except HTTPException:
        raise
    except Exception:  # damaged / password-protected / not really a .docx or .pdf
        raise HTTPException(
            400, "could not read this file (it may be damaged or "
                 "password-protected); try saving it again as .docx or .pdf")
    if not text:
        raise HTTPException(400, "could not extract text from file")
    # learn any skill names we have never seen, then read this resume with
    # the enlarged vocabulary
    learned: list = []
    if db.get_setting("auto_learn_skills", "1") == "1":
        try:
            learned = db.add_learned_skills(
                autolearn.candidate_skills(text), source=filename or "")
            autolearn.sync_vocabulary()
        except Exception:
            learned = []
    skills = extract_skills(text)
    row = db.upsert_resume(cid, filename or "resume", text, skills)
    # bring everything else in step (other resumes, old scores), then score
    # this consultant against the jobs already collected, so the Matches tab
    # is filled right away instead of after the next collection
    try:
        autolearn.maintain()
        matcher_mod.rescore_existing(consultant_id=cid)
        new_matches = matcher_mod.run_all(consultant_id=cid)
    except Exception:  # never fail an upload because matching hiccuped
        new_matches = 0
    # and go and look for jobs for this person's role right now
    searching = False
    if kick:
        try:
            searching = _kick_collect()
        except Exception:
            pass
    return {"filename": row["filename"], "skills": skills,
            "chars": len(text), "new_matches": new_matches,
            "learned_skills": learned, "searching_jobs": searching,
            "text": text}


@app.post("/api/consultants/{cid}/resume")
async def api_upload_resume(cid: int, file: UploadFile = File(...)):
    if not db.get_consultant(cid):
        raise HTTPException(404, "consultant not found")
    data = await file.read()
    r = _ingest_resume(cid, file.filename or "resume", data)
    r.pop("text", None)
    return r


@app.post("/api/resumes/auto")
async def api_resume_auto(file: UploadFile = File(...), kick: int = 1):
    """One resume file in -> consultant created (or found) from the name /
    email in the resume, resume attached, skills + searches + matches done."""
    data = await file.read()
    filename = file.filename or "resume"
    if not data:
        raise HTTPException(400, "the file is empty")
    try:
        text = _parse_resume(filename, data).strip()
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            400, "could not read this file (it may be damaged or "
                 "password-protected); try saving it again as .docx or .pdf")
    if not text:
        raise HTTPException(400, "could not extract text from file")
    info = contact_mod.parse_contact(text, filename)
    existing = None
    for c in db.list_consultants():
        if info["email"] and (c.get("email") or "").lower() == info["email"].lower():
            existing = c
            break
        if (c.get("name") or "").strip().lower() == info["name"].strip().lower():
            existing = c
            break
    created = existing is None
    if created:
        c = db.create_consultant(info)
    else:
        c = existing
        fill = {k: v for k, v in info.items()
                if k != "name" and v and not (c.get(k) or "").strip()}
        if fill:
            c = db.update_consultant(c["id"], fill)
    r = _ingest_resume(c["id"], filename, data, kick=bool(kick))
    r.pop("text", None)
    r.update(consultant_id=c["id"], name=c["name"], created=created,
             email=c.get("email", ""), location=c.get("location", ""))
    return r


@app.post("/api/collect/kick")
def api_collect_kick():
    return {"started": _kick_collect()}


# ---------- jobs ----------
@app.get("/api/jobs")
def api_list_jobs(source: str = "", q: str = "", limit: int = 50,
                  emp: str = "", include_unspecified: bool = False):
    """emp = comma list of full-time/c2c/w2/... tags (OR). Jobs whose type
    could not be detected are hidden when emp is set, unless
    include_unspecified=true."""
    return db.list_jobs(source=source, q=q, limit=limit,
                        emp=emptype.parse_wanted(emp),
                        include_unspecified=include_unspecified)


@app.get("/api/emp-types")
def api_emp_types():
    return [{"tag": t, "label": emptype.TAG_LABELS[t]} for t in emptype.TAGS]


@app.get("/api/portals")
def api_portals(title: str = "", location: str = "", emp: str = "",
                days: int = 7):
    """Pre-filled search links for Dice, Indeed, LinkedIn, ZipRecruiter..."""
    if not title.strip():
        raise HTTPException(400, "title is required")
    return portals.build_links(title, location, emptype.parse_wanted(emp),
                               max(1, min(days, 30)))


@app.get("/api/portals/check")
def api_portals_check():
    """Can the server reach each portal? (Runs ~8 quick HTTP requests.)"""
    return portals.check_reachability()


@app.post("/api/jobs/import-url")
def api_import_url(data: dict):
    url = (data.get("url") or "").strip()
    if not url:
        raise HTTPException(400, "url is required")
    try:
        job = urlimport.import_url(url)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"could not import URL: {e}")
    jid = db.insert_job(job)
    job["id"] = jid
    job["duplicate"] = jid is None
    if jid:
        matcher_mod.run_all()  # score consultants against the new posting
    return job


@app.post("/api/collect")
def api_collect():
    return _do_collect()


LIVE_SOURCES = [adzuna, jsearch, remoteok, remotive, arbeitnow]  # dice: no public API


@app.post("/api/jobs/live-search")
def api_live_search(data: dict):
    """Search the boards right now for a job title (+ optional location).

    Returns listings without saving them; the frontend saves explicitly
    via /api/jobs/save-live.
    """
    title = (data.get("title") or "").strip()
    if not title:
        raise HTTPException(400, "title is required")
    location = (data.get("location") or "").strip()
    settings = db.get_settings()
    try:
        enabled_sources = set(json.loads(settings.get("enabled_sources") or "[]"))
    except json.JSONDecodeError:
        enabled_sources = set(db.DEFAULT_ENABLED_SOURCES)
    query = {"title": title, "location": location}
    emp_wanted = emptype.parse_wanted(",".join(data.get("emp") or [])
                                      if isinstance(data.get("emp"), list)
                                      else (data.get("emp") or ""))
    include_unspecified = bool(data.get("include_unspecified"))
    usa_only = (settings.get("usa_only", "1") == "1") and data.get("usa_only", True)
    # let the live search steer the per-source filters the same way collection does
    if emp_wanted:
        settings = {**settings, "collect_emp_types": ",".join(emp_wanted)}
    jobs: list[dict] = []
    sources: dict = {}
    for mod in LIVE_SOURCES:
        name = mod.NAME
        label = getattr(mod, "LABEL", name)
        if name not in enabled_sources:
            sources[name] = {"label": label, "status": "disabled in Settings", "count": 0}
            continue
        if not mod.enabled(settings):
            sources[name] = {"label": label, "status": "needs API key — add it in Settings", "count": 0}
            continue
        try:
            fetched = mod.fetch(query, settings)
            if usa_only:
                fetched = usa.filter_us(fetched)
            for j in fetched:
                j["temp_id"] = f"{name}:{j.get('source_id')}"
                j["emp_tags"] = emptype.classify(
                    j.get("employment_type", ""), j.get("title", ""),
                    j.get("description", ""))
            if emp_wanted:
                fetched = [j for j in fetched if emptype.matches_filter(
                    j["emp_tags"], emp_wanted, include_unspecified)]
            fetched = fetched[:30]
            jobs.extend(fetched)
            sources[name] = {"label": label, "status": "ok", "count": len(fetched)}
        except Exception as e:  # noqa: BLE001 - one bad source shouldn't kill the search
            sources[name] = {"label": label, "status": f"error: {e}", "count": 0}
    # rank: jobs whose title covers more of the query words come first
    words = title.lower().split()

    def _relevance(job: dict):
        t = (job.get("title") or "").lower()
        c = (job.get("company") or "").lower()
        hit_title = sum(1 for w in words if w in t)
        hit_all = sum(1 for w in words if w in t or w in c)
        return (hit_title / len(words), hit_all / len(words))

    jobs.sort(key=_relevance, reverse=True)
    return {"jobs": jobs, "sources": sources}


@app.post("/api/jobs/save-live")
def api_save_live(data: dict):
    """Save live-search listings into the job board (dedupes) and re-run matching."""
    jobs = data.get("jobs") or []
    if not isinstance(jobs, list) or not jobs:
        raise HTTPException(400, "jobs list is required")
    saved, dupes = 0, 0
    for j in jobs:
        j.pop("temp_id", None)
        j.pop("emp_tags", None)  # recomputed on insert
        if db.insert_job(j):
            saved += 1
        else:
            dupes += 1
    matches_new = matcher_mod.run_all()
    return {"saved": saved, "duplicates": dupes, "matches_new": matches_new}


# ---------- matches ----------
@app.get("/api/matches")
def api_list_matches(consultant_id: int = 0, min_score: float = 0):
    return db.list_matches(consultant_id or None, min_score)


@app.get("/api/matches/{mid}")
def api_get_match(mid: int):
    m = db.get_match(mid)
    if not m:
        raise HTTPException(404, "match not found")
    return m


@app.post("/api/matches/{mid}/tailor")
def api_tailor(mid: int):
    m = db.get_match(mid)
    if not m:
        raise HTTPException(404, "match not found")
    settings = db.get_settings()
    result = tailor_mod.tailor_match(m, settings)
    tid = db.insert_tailored(mid, result["text"], result["tailored_by"],
                             result["added_skills_flagged"])
    demand = market.demand_map()
    missing = [{"skill": s, "in_demand": s in demand,
                "demand_jobs": demand.get(s, 0)}
               for s in (m.get("missing_skills") or [])]
    return {"id": tid, "tailored_by": result["tailored_by"],
            "added_skills_flagged": result["added_skills_flagged"],
            "missing_skills": missing, "score": m.get("score")}


@app.post("/api/tailored/{tid}/add-skills")
def api_tailored_add_skills(tid: int, data: dict):
    """Add recruiter-confirmed missing skills to a tailored resume.

    Body: {"skills": [...], "confirmed": true}. Only skills listed as
    missing for this match can be added - this is the honesty gate: the
    recruiter explicitly attests the candidate has them.
    """
    t = db.get_tailored(tid)
    if not t:
        raise HTTPException(404, "not found")
    if not (data or {}).get("confirmed"):
        raise HTTPException(400, "confirm the candidate has these skills first")
    skills = (data or {}).get("skills") or []
    if not isinstance(skills, list) or not skills:
        raise HTTPException(400, "no skills given")
    m = db.get_match(t["match_id"])
    allowed = set((m.get("missing_skills") or []) if m else [])
    allowed |= set(t.get("user_confirmed_skills") or [])
    clean = []
    for s in skills:
        s = (s or "").strip()
        if s and s in allowed and s not in clean:
            clean.append(s)
    if not clean:
        raise HTTPException(400, "none of these skills are missing for this match")
    new_text = tailor_mod.add_skills_to_text(
        t["tailored_text"], [display_name(s) for s in clean])
    updated = db.update_tailored(tid, new_text, clean)
    return {"id": tid, "added": clean,
            "user_confirmed_skills": updated["user_confirmed_skills"],
            "added_skills_flagged": updated["added_skills_flagged"]}


@app.get("/api/market/skills")
def api_market_skills(days: int = 30, limit: int = 50):
    """Current market demand: top skills across recent job postings."""
    days = max(1, min(days, 180))
    limit = max(1, min(limit, 200))
    return {"days": days, "skills": market.demand(days, limit)}


@app.get("/api/tailored/{tid}")
def api_get_tailored(tid: int):
    t = db.get_tailored(tid)
    if not t:
        raise HTTPException(404, "not found")
    m = db.get_match(t["match_id"])
    if m:
        t["original_text"] = m.get("resume_text", "")
    return t


@app.post("/api/matches/{mid}/queue")
def api_queue(mid: int, data: dict | None = None):
    if not db.get_match(mid):
        raise HTTPException(404, "match not found")
    tid = (data or {}).get("tailored_resume_id")
    return db.queue_application(mid, tid)


# ---------- applications ----------
@app.get("/api/applications")
def api_list_applications(status: str = ""):
    return db.list_applications(status)


@app.patch("/api/applications/{aid}")
def api_update_application(aid: int, data: dict):
    try:
        a = db.update_application(aid, data.get("status"), data.get("notes"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not a:
        raise HTTPException(404, "application not found")
    return a


# ---------- settings / sources ----------
MASKED_KEYS = {"adzuna_app_key", "rapidapi_key", "llm_api_key"}


def _mask(key: str, value: str) -> str:
    if key in MASKED_KEYS and value:
        return (value[:3] + "***" + value[-2:]) if len(value) > 6 else "***"
    return value


@app.get("/api/settings")
def api_get_settings():
    return {k: _mask(k, v) for k, v in db.get_settings().items()}


@app.put("/api/settings")
def api_put_settings(data: dict):
    allowed = {"match_threshold", "search_queries", "enabled_sources",
               "adzuna_app_id", "adzuna_app_key", "rapidapi_key",
               "llm_base_url", "llm_api_key", "llm_model",
               "collect_interval_minutes", "usa_only", "collect_emp_types",
               "auto_queries", "max_queries", "auto_learn_skills",
               "adzuna_daily_budget", "tailor_cutoff", "tailor_max_per_run"}
    for k, v in data.items():
        if k not in allowed:
            raise HTTPException(400, f"unknown setting: {k}")
        if k in MASKED_KEYS and isinstance(v, str) and "***" in v:
            continue  # masked value echoed back -> keep existing
        db.set_setting(k, v if isinstance(v, str) else json.dumps(v))
    return api_get_settings()


@app.get("/api/sources/status")
def api_sources_status():
    settings = db.get_settings()
    try:
        enabled_sources = set(json.loads(settings.get("enabled_sources") or "[]"))
    except json.JSONDecodeError:
        enabled_sources = set(db.DEFAULT_ENABLED_SOURCES)
    out = []
    for mod in SOURCES:
        name = mod.NAME
        last = {}
        try:
            last = json.loads(settings.get(f"last_run_{name}") or "{}")
        except json.JSONDecodeError:
            pass
        configured = mod.enabled(settings)
        state = "disabled"
        if name == "dice":
            state = "link-out only (no public API) — use Portal search links, Adzuna or URL import"
        elif name in enabled_sources:
            state = "ready" if configured else "needs credentials"
        out.append({
            "name": name,
            "label": getattr(mod, "LABEL", name),
            "enabled": name in enabled_sources and configured,
            "configured": configured,
            "state": state,
            "last_run": last,
        })
    out.append({"name": "urlimport", "label": urlimport.LABEL,
                "enabled": True, "configured": True,
                "state": "manual (Import URL box)", "last_run": {}})
    return out


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True),
              name="frontend")
