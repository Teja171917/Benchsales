"""BenchPilot job collector.

For each enabled source x each search query: fetch -> normalize -> dedupe
(on (source, source_id) and fuzzy title+company) -> insert new jobs ->
run matcher for all consultants. Idempotent: safe to re-run.
"""
import json
import sys
import traceback
from datetime import datetime, timezone

from app import db
from app import matcher
from app.sources import adzuna, jsearch, remoteok, remotive, arbeitnow, dice

SOURCES = [adzuna, jsearch, remoteok, remotive, arbeitnow, dice]


def run() -> dict:
    settings = db.get_settings()
    try:
        queries = json.loads(settings.get("search_queries") or "[]")
    except json.JSONDecodeError:
        queries = []
    if not queries:
        queries = db.DEFAULT_SEARCH_QUERIES
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
                for q in queries:
                    for job in mod.fetch(q, settings):
                        fetched += 1
                        if db.insert_job(job):
                            new += 1
                st.update(status="ok", jobs=fetched, new=new)
                summary["jobs_fetched"] += fetched
                summary["jobs_new"] += new
            except Exception as e:  # noqa: BLE001 - keep collecting other sources
                st["status"] = f"error: {e}"
                summary["errors"].append(f"{name}: {e}")
        summary["sources"][name] = st
        db.set_setting(f"last_run_{name}", json.dumps({
            "status": st["status"], "jobs": st["jobs"], "new": st["new"],
            "at": summary["started"],
        }))

    try:
        summary["matches_new"] = matcher.run_all()
    except Exception as e:  # noqa: BLE001
        summary["errors"].append(f"matcher: {e}")

    summary["finished"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    db.init_db()
    try:
        run()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
