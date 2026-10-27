"""BenchPilot job collector.

For each enabled source x each search query: fetch -> normalize -> dedupe
(on (source, source_id) and fuzzy title+company) -> insert new jobs ->
run matcher for all consultants. Idempotent: safe to re-run.
"""
import json
import sys
import traceback
from datetime import datetime, timezone

from app import autolearn, db, usa
from app import matcher
from app.sources import (adzuna, jsearch, remoteok, remotive, arbeitnow,
                         dice, monster, smartrecruiters)

SOURCES = [adzuna, jsearch, remoteok, remotive, arbeitnow, dice, monster,
           smartrecruiters]


def jsearch_room(settings: dict) -> tuple[int, int]:
    """(calls left today for automatic runs, calls left this month)."""
    def num(k, d):
        try:
            return max(0, int(float(settings.get(k) or d)))
        except ValueError:
            return d
    month_left = max(0, num("jsearch_monthly_limit", 200) - 5 - db.usage_month("jsearch"))
    today_left = max(0, num("jsearch_daily_budget", 6) - db.usage_today("jsearch"))
    return min(today_left, month_left), month_left


def _within_budget(queries: list, summary: dict) -> list:
    """Adzuna's free key allows 250 calls a day (2,500 a month). Use at most
    the daily budget setting, and start from a different query each time so
    that, when the budget is short, every query gets its turn."""
    settings = db.get_settings()
    budget = autolearn.adzuna_budget(settings)
    used = db.usage_today("adzuna")
    room = max(0, (budget - used) // autolearn.ADZUNA_CALLS_PER_QUERY)
    if not queries:
        return []
    start = (used // autolearn.ADZUNA_CALLS_PER_QUERY) % len(queries)
    rotated = queries[start:] + queries[:start]
    chosen = rotated[:room]
    if len(chosen) < len(queries):
        summary["budget_skipped"]["adzuna"] = len(queries) - len(chosen)
    return chosen


def _merge(queries: list, more: list) -> None:
    seen = {((q.get("title") or "").lower(), (q.get("location") or "").lower())
            for q in queries}
    for q in more:
        k = ((q.get("title") or "").lower(), (q.get("location") or "").lower())
        if k not in seen:
            seen.add(k)
            queries.append(q)


def _prepare_all() -> tuple[list, dict]:
    """Learn from every database's resumes and collect the searches they need.
    Returns (all searches, {database: its own part})."""
    queries, per_db = [], {}
    for path in db.all_paths():
        with db.use(path):
            if not path.exists():
                db.init_db()
            try:
                maintained = autolearn.maintain()
            except Exception as e:  # noqa: BLE001 - never block job collection
                maintained = {"error": str(e)}
            own = autolearn.queries_for_run(db.get_settings())
            has_people = bool(db.consultants_with_resumes())
        per_db[str(path)] = {"queries": own if has_people else [],
                             "learned_skills": maintained.get("learned", []),
                             "rescored": maintained.get("rescored", 0),
                             "matches_new": 0}
        if has_people:
            _merge(queries, own)
    if not queries:   # nobody has a resume yet: the main database's searches
        with db.use(None):
            queries = autolearn.queries_for_run(db.get_settings())
    return queries, per_db


def _save_job(job: dict) -> bool:
    """Save a job in the main database and in every company's. True if new."""
    new = bool(db.insert_job(job))
    for c in db.companies():
        with db.use(c["path"]):
            db.insert_job(job)
    return new


def run() -> dict:
    """One collection for everyone: the searches are done once (one set of API
    calls), the jobs are copied into each company's database, and each
    company's own consultants are matched inside their own database."""
    with db.use(None):
        return _run()


def _run() -> dict:
    queries, per_db = _prepare_all()
    settings = db.get_settings()
    main_part = per_db.get(str(db.DB_PATH), {})
    try:
        enabled_sources = set(json.loads(settings.get("enabled_sources") or "[]"))
    except json.JSONDecodeError:
        enabled_sources = set(db.DEFAULT_ENABLED_SOURCES)

    summary = {
        "started": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "jobs_fetched": 0,
        "jobs_new": 0,
        "matches_new": 0,
        "errors": [],
        "queries": queries,
        "learned_skills": main_part.get("learned_skills", []),
        "rescored": main_part.get("rescored", 0),
        "budget_skipped": {},
        "per_db": per_db,
    }

    for mod in SOURCES:
        name = mod.NAME
        st = {"label": getattr(mod, "LABEL", name), "status": "skipped",
              "jobs": 0, "new": 0}
        if name == "monster" and mod.enabled(settings):
            enabled_sources.add("monster")    # an Apify token means "use Monster"
        if name == "dice" and mod.enabled(settings):
            enabled_sources.add("dice")       # free official connector: on by default
        if name not in enabled_sources:
            st["status"] = "disabled in settings"
        elif not mod.enabled(settings):
            st["status"] = "not configured (missing credentials)"
        elif name == "monster" and not mod.due(settings):
            st["status"] = f"waiting (Monster runs every {mod.every_hours(settings)} h to keep the cost low)"
        else:
            try:
                fetched = 0
                new = 0
                usa_only = settings.get("usa_only", "1") == "1"
                run_queries = queries
                if name == "adzuna":
                    run_queries = _within_budget(queries, summary)
                if name == "jsearch":   # free plan: 200 calls a month
                    room, _ = jsearch_room(settings)
                    start = db.usage_month("jsearch") % max(1, len(queries))
                    rotated = queries[start:] + queries[:start]   # every title gets turns
                    run_queries = rotated[:room]
                    if len(run_queries) < len(queries):
                        summary["budget_skipped"]["jsearch"] = len(queries) - len(run_queries)
                for q in run_queries:
                    if name == "adzuna":  # count before calling: a failed call can still use quota
                        db.usage_add("adzuna", autolearn.ADZUNA_CALLS_PER_QUERY)
                    if name == "jsearch":
                        db.usage_add("jsearch", 1)
                    batch = mod.fetch(q, settings)
                    if usa_only:
                        batch = usa.filter_us(batch)
                    for job in batch:
                        fetched += 1
                        if _save_job(job):
                            new += 1
                if name == "monster":   # only a run that WORKED starts the 12-hour wait
                    db.set_setting("monster_last_run_at", datetime.now(timezone.utc).isoformat())
                st.update(status="ok", jobs=fetched, new=new)
                summary["jobs_fetched"] += fetched
                summary["jobs_new"] += new
            except Exception as e:  # noqa: BLE001 - keep collecting other sources
                from app.sources.common import safe_error
                st["status"] = f"error: {safe_error(e)}"
                summary["errors"].append(f"{name}: {safe_error(e)}")
        summary["sources"][name] = st
        if st["status"].startswith("waiting"):
            continue   # keep the last REAL run visible in Settings (e.g. Monster's result)
        db.set_setting(f"last_run_{name}", json.dumps({
            "status": st["status"], "jobs": st["jobs"], "new": st["new"],
            "at": summary["started"],
        }))

    summary["matches_removed"] = 0
    for path in db.all_paths():   # each company is matched in its own file
        with db.use(path):
            try:
                autolearn.sync_vocabulary()
                summary["matches_removed"] += matcher.prune_misfits()
                n = matcher.run_all()
                per_db[str(path)]["matches_new"] = n
                summary["matches_new"] += n
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"matcher: {e}")
    with db.use(None):
        autolearn.sync_vocabulary()

    summary["finished"] = datetime.now(timezone.utc).isoformat()
    db.set_setting("last_collect_at", summary["finished"])
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    db.init_db()
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
