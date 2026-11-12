"""BenchPilot job collector.

For each enabled source x each search query: fetch -> normalize -> dedupe
(on (source, source_id) and fuzzy title+company) -> insert new jobs ->
run matcher for all consultants. Idempotent: safe to re-run.
"""
import json
import sys
import time
import traceback
from datetime import datetime, timezone

from app import autolearn, db, usa
from app import matcher
from app.sources import (adzuna, jsearch, dice, monster, phenom,
                         smartrecruiters)

# US-based sources only (owner decision, Nov 4 2026): the global/EU boards
# (RemoteOK, Remotive, Arbeitnow) are no longer wired in — their adapter
# modules stay in app/sources/ but nothing collects from them.
SOURCES = [adzuna, jsearch, dice, monster, smartrecruiters, phenom]

# One slow or dying source must not stretch a run without bound: every
# fetch has its own timeout, and each source gets this much wall-clock
# for ALL its searches combined before the run moves on without it
# (Nov 4 2026: an unbounded run wedged the scheduler for 9+ hours —
# no collections finished and, because the office rode the same loop,
# no office runs either).
SOURCE_BUDGET_SECONDS = 240

# The fetch loop is not the whole run: the phases before and after it
# (learning/rescoring searches in prepare; vocabulary sync, misfit
# pruning and matching in match) loop over every consultant x job pair
# and every stored match, and on Nov 4 2026 a run sat in that tail for
# 40+ minutes after every source had reported — status showed nothing
# but "running". Each phase now gets its own wall-clock budget too: a
# phase that spends it is cut, NAMED in the run summary (summary
# ["phases"]), and the run still finishes and reports.
PHASE_BUDGET_SECONDS = {"prepare": 240, "match": 600}

# Live progress for /api/collect/status: which phase is running and
# since when, so a slow run shows WHERE it is instead of just "running".
PROGRESS = {"phase": None, "phase_started": None, "run_started": None}


def _begin_phase(phases: dict, name: str) -> float:
    PROGRESS["phase"] = name
    PROGRESS["phase_started"] = datetime.now(timezone.utc).isoformat()
    if PROGRESS["run_started"] is None:
        PROGRESS["run_started"] = PROGRESS["phase_started"]
    return time.monotonic()


def _end_phase(phases: dict, name: str, started: float,
               status: str = "ok") -> None:
    phases[name] = {
        "seconds": round(time.monotonic() - started, 1), "status": status}
    PROGRESS["phase"] = None
    PROGRESS["phase_started"] = None


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


def _prepare_all(deadline: float | None = None) -> tuple[list, dict]:
    """Learn from every database's resumes and collect the searches they need.
    Returns (all searches, {database: its own part}). Maintenance is capped
    by the phase deadline: a database whose upkeep spends the budget is
    noted and skipped, but its searches are still collected — stale skills
    must never block job collection."""
    queries, per_db = [], {}
    for path in db.all_paths():
        with db.use(path):
            if not path.exists():
                db.init_db()
            try:
                maintained = autolearn.maintain(deadline=deadline)
            except matcher.PhaseTimeout:
                maintained = {"partial": "stopped at the "
                              f"{PHASE_BUDGET_SECONDS['prepare'] // 60}-minute "
                              "prepare phase budget"}
            except Exception as e:  # noqa: BLE001 - never block job collection
                maintained = {"error": str(e)}
            # stored-pool sweep (Nov 5 2026): the fetch filter only
            # guards the door — jobs already inside (Arbeitnow-era rows,
            # bare foreign cities the filter once let through) are
            # deleted here, per workspace, when its usa_only is on.
            purged = {"jobs": 0, "matches": 0}
            if db.get_settings().get("usa_only", "1") == "1":
                try:
                    if deadline is not None:
                        matcher.check_deadline(deadline)
                    purged = db.purge_non_us_jobs()
                except matcher.PhaseTimeout:
                    maintained["partial"] = (
                        "stopped at the "
                        f"{PHASE_BUDGET_SECONDS['prepare'] // 60}-minute "
                        "prepare phase budget")
                except Exception as e:  # noqa: BLE001 - never block collection
                    purged = {"jobs": 0, "matches": 0, "error": str(e)}
            own = autolearn.queries_for_run(db.get_settings())
            has_people = bool(db.consultants_with_resumes())
        per_db[str(path)] = {"queries": own if has_people else [],
                             "learned_skills": maintained.get("learned", []),
                             "rescored": maintained.get("rescored", 0),
                             "purged_non_us": purged,
                             "matches_new": 0}
        if maintained.get("partial"):
            per_db[str(path)]["maintain_partial"] = maintained["partial"]
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


def _job_keys(job: dict) -> list[tuple]:
    """Identity keys for run-scoped dedupe, mirroring db.insert_job's
    own dedupe: the source's id, plus the fuzzy title+company+location
    key insert_job checks across sources. insert_job is insert-only —
    a repeat sighting can never change the stored row — so a repeat is
    pure cost: three text classifiers plus a fuzzy table scan, paid
    once per database the job is copied into."""
    keys = []
    sid = (job.get("source_id") or "").strip()
    if sid:
        keys.append(("id", job.get("source", ""), sid))
    keys.append(("fuzzy", (job.get("title") or "").strip().lower(),
                 (job.get("company") or "").strip().lower(),
                 (job.get("location") or "").strip().lower()))
    return keys


def _seen_before(seen: set, job: dict) -> bool:
    """True when this run has already processed this job (under either
    identity key); records the job's keys either way."""
    keys = _job_keys(job)
    if any(k in seen for k in keys):
        return True
    seen.update(keys)
    return False


def run() -> dict:
    """One collection for everyone: the searches are done once (one set of API
    calls), the jobs are copied into each company's database, and each
    company's own consultants are matched inside their own database."""
    with db.use(None):
        return _run()


def _run() -> dict:
    phases: dict = {}
    t = _begin_phase(phases, "prepare")
    prepare_deadline = time.monotonic() + PHASE_BUDGET_SECONDS["prepare"]
    queries, per_db = _prepare_all(deadline=prepare_deadline)
    prepare_status = "ok"
    if any(p.get("maintain_partial") for p in per_db.values()):
        prepare_status = ("partial: maintenance stopped at the "
                          f"{PHASE_BUDGET_SECONDS['prepare'] // 60}-minute "
                          "phase budget in at least one workspace")
    _end_phase(phases, "prepare", t, prepare_status)
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
        "phases": phases,
    }

    t = _begin_phase(phases, "fetch")
    # run-scoped dedupe (Nov 9 2026): whole-feed sources hand back the
    # same jobs for many queries, and every repeat sighting used to pay
    # a full insert_job (classifiers + fuzzy scan) in every database —
    # the three feed sources burned their whole 4-minute budgets on
    # re-saving known jobs. Each job is now processed once per run.
    seen_jobs: set = set()
    for mod in SOURCES:
        name = mod.NAME
        st = {"label": getattr(mod, "LABEL", name), "status": "skipped",
              "jobs": 0, "new": 0}
        src_t0 = None
        if name == "monster" and mod.enabled(settings):
            enabled_sources.add("monster")    # an Apify token means "use Monster"
        if name == "dice" and mod.enabled(settings):
            enabled_sources.add("dice")       # free official connector: on by default
        if name == "smartrecruiters" and mod.enabled(settings):
            enabled_sources.add("smartrecruiters")   # no-key public feed: on by default
        if name == "phenom" and mod.enabled(settings):
            enabled_sources.add("phenom")   # staffing watchlist, Phenom cohort: on by default
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
                cut_short = 0
                t_start = datetime.now(timezone.utc)
                src_t0 = time.monotonic()
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
                for qi, q in enumerate(run_queries):
                    if (datetime.now(timezone.utc) - t_start).total_seconds() \
                            >= SOURCE_BUDGET_SECONDS:
                        cut_short = len(run_queries) - qi
                        break
                    if name == "adzuna":  # count before calling: a failed call can still use quota
                        db.usage_add("adzuna", autolearn.ADZUNA_CALLS_PER_QUERY)
                    if name == "jsearch":
                        db.usage_add("jsearch", 1)
                    batch = mod.fetch(q, settings)
                    if usa_only:
                        batch = usa.filter_us(batch)
                    for job in batch:
                        fetched += 1
                        if _seen_before(seen_jobs, job):
                            continue   # repeat sighting this run:
                            # insert_job would only re-confirm the dup
                        if _save_job(job):
                            new += 1
                if name == "monster" and not cut_short:   # only a run that WORKED starts the 12-hour wait
                    db.set_setting("monster_last_run_at", datetime.now(timezone.utc).isoformat())
                if cut_short:
                    st.update(status=(f"partial: stopped at the "
                                      f"{SOURCE_BUDGET_SECONDS // 60}-minute source "
                                      f"budget ({cut_short} searches left)"),
                              jobs=fetched, new=new)
                else:
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
        # per-source wall-clock seconds (Nov 9 2026): the fetch phase
        # total alone could not show WHICH source eats the time — the
        # Nov 9 dedupe fix left fetch at 2583s with the split unknown.
        # Stored on the Settings status so the next check reads it
        # verbatim instead of guessing.
        stored_status = st["status"]
        secs = None
        if src_t0 is not None:
            secs = round(time.monotonic() - src_t0, 1)
            stored_status += f" · took {secs:.0f}s"
        db.set_setting(f"last_run_{name}", json.dumps({
            "status": stored_status, "jobs": st["jobs"], "new": st["new"],
            "at": summary["started"], "seconds": secs,
        }))

    fetch_status = "ok"
    if any(str(s.get("status", "")).startswith("partial")
           for s in summary["sources"].values()):
        fetch_status = "partial: at least one source hit its budget"
    _end_phase(phases, "fetch", t, fetch_status)

    t = _begin_phase(phases, "match")
    match_deadline = time.monotonic() + PHASE_BUDGET_SECONDS["match"]
    match_status = "ok"
    summary["matches_removed"] = 0
    for path in db.all_paths():   # each company is matched in its own file
        with db.use(path):
            try:
                autolearn.sync_vocabulary()
                summary["matches_removed"] += matcher.prune_misfits(
                    deadline=match_deadline)
                n = matcher.run_all(deadline=match_deadline)
                per_db[str(path)]["matches_new"] = n
                summary["matches_new"] += n
            except matcher.PhaseTimeout:
                match_status = ("partial: stopped at the "
                                f"{PHASE_BUDGET_SECONDS['match'] // 60}-minute "
                                "phase budget")
                summary["errors"].append(
                    f"matcher: stopped at the "
                    f"{PHASE_BUDGET_SECONDS['match'] // 60}-minute match "
                    f"phase budget in {path.name}")
                break   # the budget is spent; later workspaces wait a run
            except Exception as e:  # noqa: BLE001
                summary["errors"].append(f"matcher: {e}")
    with db.use(None):
        autolearn.sync_vocabulary()
    _end_phase(phases, "match", t, match_status)
    PROGRESS["run_started"] = None

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
