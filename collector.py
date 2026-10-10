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
from app.sources import adzuna, jsearch, remoteok, remotive, arbeitnow, dice

SOURCES = [adzuna, jsearch, remoteok, remotive, arbeitnow, dice]


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


def run() -> dict:
    # step 0: learn from the resumes we hold (new skills, refreshed skill
    # lists, rescored matches) so the searches below use up-to-date data
    maintained = {}
    try:
        maintained = autolearn.maintain()
    except Exception as e:  # noqa: BLE001 - never block job collection
        maintained = {"error": str(e)}
    settings = db.get_settings()
    queries = autolearn.queries_for_run(settings)
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
        "learned_skills": maintained.get("learned", []),
        "rescored": maintained.get("rescored", 0),
        "budget_skipped": {},
    }

    for mod in SOURCES:
        name = mod.NAME
        st = {"label": getattr(mod, "LABEL", name), "status": "skipped",
              "jobs": 0, "new": 0}
        if name not in enabled_sources:
            st["status"] = "disabled in settings"
        elif not mod.enabled(settings):
            st["status"] = "not configured (missing credentials)"
        else:
            try:
                fetched = 0
                new = 0
                usa_only = settings.get("usa_only", "1") == "1"
                run_queries = queries
                if name == "adzuna":
                    run_queries = _within_budget(queries, summary)
                for q in run_queries:
                    if name == "adzuna":  # count before calling: a failed call can still use quota
                        db.usage_add("adzuna", autolearn.ADZUNA_CALLS_PER_QUERY)
                    batch = mod.fetch(q, settings)
                    if usa_only:
                        batch = usa.filter_us(batch)
                    for job in batch:
                        fetched += 1
                        if db.insert_job(job):
                            new += 1
                st.update(status="ok", jobs=fetched, new=new)
                summary["jobs_fetched"] += fetched
                summary["jobs_new"] += new
            except Exception as e:  # noqa: BLE001 - keep collecting other sources
                from app.sources.common import safe_error
                st["status"] = f"error: {safe_error(e)}"
                summary["errors"].append(f"{name}: {safe_error(e)}")
        summary["sources"][name] = st
        db.set_setting(f"last_run_{name}", json.dumps({
            "status": st["status"], "jobs": st["jobs"], "new": st["new"],
            "at": summary["started"],
        }))

    try:
        summary["matches_removed"] = matcher.prune_misfits()
        summary["matches_new"] = matcher.run_all()
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"matcher: {e}")

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
