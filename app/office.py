"""BenchPilot Agent Office.

An orchestrator that runs specialized agents on a schedule, so the
recruiting pipeline keeps moving while the team is away:

  - Scout:   finds new high-quality matches since the last run
  - Tailor:  pre-drafts tailored resumes for top matches (drafts only —
              flagged skills still need a human acknowledgment before
              anything is queued for apply)
  - Watchdog: flags pipeline items going cold (queued/applied with no
              movement)

run_office() executes all agents and returns a briefing dict. The server
scheduler runs it once a day and stores the briefing; the Office tab
displays it.
"""
import json
from datetime import datetime, timedelta, timezone

from app import db
from app import tailor as tailor_mod

TAILOR_SCORE_CUTOFF = 85  # auto-draft tailors for matches at/above this
MAX_DRAFTS_PER_RUN = 10   # safety cap per office run
STALE_QUEUED_DAYS = 3     # queued with no movement
STALE_APPLIED_DAYS = 14   # applied with no update


def _now():
    return datetime.now(timezone.utc)


def _parse_iso(s):
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _scout(settings, since):
    """New matches above the threshold since the last run."""
    threshold = int(settings.get("match_threshold") or 60)
    fresh = []
    for m in db.list_matches(min_score=threshold):
        created = _parse_iso(m.get("created_at"))
        if created and created >= since:
            fresh.append({
                "match_id": m["id"],
                "score": m["score"],
                "job_title": m["job_title"],
                "company": m["company"],
                "location": m["location"],
                "source": m["source"],
                "url": m["url"],
                "consultant_name": m["consultant_name"],
            })
    by_consultant = {}
    for f in fresh:
        by_consultant.setdefault(f["consultant_name"], []).append(f)
    return {"new_matches": len(fresh), "by_consultant": by_consultant}


def _has_draft(match_id):
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT id FROM tailored_resumes WHERE match_id=? LIMIT 1",
            (match_id,)).fetchone()
        return r is not None


def _is_queued(match_id):
    with db.get_conn() as conn:
        r = conn.execute(
            "SELECT id FROM applications WHERE match_id=? LIMIT 1",
            (match_id,)).fetchone()
        return r is not None


def _tailor(settings):
    """Draft tailored resumes for top matches that lack one. Drafts only."""
    drafted = []
    candidates = [m for m in db.list_matches(min_score=TAILOR_SCORE_CUTOFF)
                  if not _has_draft(m["id"]) and not _is_queued(m["id"])]
    for m in candidates[:MAX_DRAFTS_PER_RUN]:
        full = db.get_match(m["id"])
        if not full or not full.get("resume_text"):
            continue
        try:
            result = tailor_mod.tailor_match(full, settings)
        except Exception:
            continue  # one bad tailor shouldn't stop the office
        tid = db.insert_tailored(m["id"], result["text"],
                                 result["tailored_by"],
                                 result["added_skills_flagged"])
        drafted.append({
            "tailored_id": tid,
            "match_id": m["id"],
            "consultant_name": m["consultant_name"],
            "job_title": m["job_title"],
            "company": m["company"],
            "score": m["score"],
            "tailored_by": result["tailored_by"],
            "flagged": result["added_skills_flagged"],
        })
    return {"drafted": len(drafted), "drafts": drafted,
            "cutoff": TAILOR_SCORE_CUTOFF}


def _watchdog():
    """Pipeline items going cold."""
    now = _now()
    stale = []

    def days_old(iso):
        d = _parse_iso(iso)
        return (now - d).days if d else 999

    for a in db.list_applications(status="queued"):
        if days_old(a.get("updated_at")) >= STALE_QUEUED_DAYS:
            stale.append({
                "app_id": a["id"], "consultant_name": a["consultant_name"],
                "job_title": a["job_title"], "company": a["company"],
                "status": "queued",
                "days_stale": days_old(a.get("updated_at")),
                "note": f"queued {days_old(a.get('updated_at'))} days, no action yet",
            })
    for a in db.list_applications(status="applied"):
        if days_old(a.get("updated_at")) >= STALE_APPLIED_DAYS:
            stale.append({
                "app_id": a["id"], "consultant_name": a["consultant_name"],
                "job_title": a["job_title"], "company": a["company"],
                "status": "applied",
                "days_stale": days_old(a.get("updated_at")),
                "note": f"applied {days_old(a.get('updated_at'))} days ago, no update",
            })
    return {"stale": len(stale), "items": stale}


def run_office() -> dict:
    """Run every agent and return the morning briefing."""
    settings = db.get_settings()
    now = _now()
    since = now - timedelta(hours=24)
    briefing = {
        "run_at": now.isoformat(),
        "agents": {
            "scout": _scout(settings, since),
            "tailor": _tailor(settings),
            "watchdog": _watchdog(),
        },
    }
    return briefing
