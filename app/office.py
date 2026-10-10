"""BenchPilot Agent Office.

An orchestrator that runs specialized agents on a schedule, so the
recruiting pipeline keeps moving while the team is away:

  - Scout:       finds new high-quality matches since the last run
  - Tailor:      pre-drafts tailored resumes for top matches (drafts only —
                  flagged skills still need a human acknowledgment before
                  anything is queued for apply)
  - Watchdog:    flags pipeline items going cold (queued/applied with no
                  movement)
  - Market Analyst: per-consultant demand briefing - which of their skills
                  are hot right now, and which in-demand skills they're
                  missing (computed from live posting data, no guessing)
  - Outreach:    drafts submission emails for top matches (drafts only -
                  a human always sends)
  - Compliance:  flags employment-type / authorization conflicts before
                  anyone applies (e.g. C2C consultant vs "W2 only" posting)

run_office() executes all agents and returns a briefing dict. The server
scheduler runs it once a day and stores the briefing; the Office tab
displays it.

Autopilot (on by default, toggleable): agents don't just report - they fix
safe issues themselves. Compliance quarantines mismatched matches,
Market Analyst expands search queries for hot uncovered skills, and
Watchdog leaves follow-up reminders on stale applications. Every action is
logged in the briefing and reversible. The app never sends email, never
queues applications, and never acknowledges resume skills on its own.
"""
import json
from datetime import datetime, timedelta, timezone

from app import db
from app import tailor as tailor_mod
from app import market as market_mod
from app import emptype
from app.skills import display_name, extract_skills

TAILOR_SCORE_CUTOFF = 85  # auto-draft tailors for matches at/above this
OUTREACH_SCORE_CUTOFF = 80  # draft outreach emails for matches at/above this
MAX_DRAFTS_PER_RUN = 10   # safety cap per office run (each drafting agent)
STALE_QUEUED_DAYS = 3     # queued with no movement
STALE_APPLIED_DAYS = 14   # applied with no update
MARKET_WINDOW_DAYS = 30   # demand window for the Market Analyst
MAX_QUERY_EXPANSIONS = 2  # new search queries the analyst may add per run


def _autopilot_on(settings) -> bool:
    """Autopilot: agents fix safe issues themselves instead of only reporting."""
    return (settings.get("office_autopilot") or "1") == "1"


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
        if m.get("compliance_flag"):
            continue  # quarantined by Compliance - handled separately
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
    return {"new_matches": len(fresh), "by_consultant": by_consultant,
            "actions": []}


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
            "cutoff": TAILOR_SCORE_CUTOFF, "actions": []}


def _watchdog(settings=None):
    """Pipeline items going cold.

    Autopilot: leaves a Watchdog note on the application record (once per
    stale episode) so the follow-up isn't forgotten. Never sends anything
    externally.
    """
    settings = settings or {}
    autopilot = _autopilot_on(settings)
    actions = []
    now = _now()
    stale = []

    def days_old(iso):
        d = _parse_iso(iso)
        return (now - d).days if d else 999

    def check(a, status, limit, note):
        age = days_old(a.get("updated_at"))
        if age < limit:
            return
        stale.append({
            "app_id": a["id"], "consultant_name": a["consultant_name"],
            "job_title": a["job_title"], "company": a["company"],
            "status": status, "days_stale": age, "note": note.format(age),
        })
        if autopilot and "[Watchdog]" not in (a.get("notes") or ""):
            new_notes = ((a.get("notes") or "").strip() + "\n" if a.get("notes") else "")
            new_notes += (f"[Watchdog] No movement for {age} days "
                          f"({status}) — consider following up.")
            try:
                db.update_application(a["id"], None, new_notes.strip())
                actions.append({
                    "text": f"Left a follow-up reminder on {a['consultant_name']} → "
                            f"{a['job_title']} ({a['company']}) — stale {age} days.",
                })
            except Exception:
                pass

    for a in db.list_applications(status="queued"):
        check(a, "queued", STALE_QUEUED_DAYS, "queued {} days, no action yet")
    for a in db.list_applications(status="applied"):
        check(a, "applied", STALE_APPLIED_DAYS, "applied {} days ago, no update")
    return {"stale": len(stale), "items": stale, "actions": actions}


def _top_titles_for_skill(skill: str, since_iso: str, limit: int = 3) -> list[str]:
    """Most common job titles among recent postings mentioning a skill."""
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT title, COUNT(*) AS c FROM jobs WHERE fetched_at >= ? "
            "AND lower(description) LIKE ? GROUP BY lower(title) "
            "ORDER BY c DESC LIMIT ?",
            (since_iso, f"%{skill.lower()}%", limit)).fetchall()
        return [r["title"] for r in rows if r["title"]]


def _manual_queries(settings) -> list:
    try:
        qs = json.loads(settings.get("search_queries") or "[]")
        return [q for q in qs if isinstance(q, dict) and q.get("title")]
    except (json.JSONDecodeError, TypeError):
        return []


def _market_analyst(settings):
    """Per-consultant demand briefing from live posting data.

    For each consultant with a resume: which of their skills are currently
    in demand, and which top in-demand skills they're missing (learning
    targets). No guessing - demand comes from jobs the app actually pulled.

    Autopilot: for hot gap skills (in demand, but the bench lacks them),
    adds the most common posting title as a search query so the next
    collection pulls more of those roles.
    """
    autopilot = _autopilot_on(settings)
    actions = []
    try:
        demand = market_mod.demand(days=MARKET_WINDOW_DAYS, limit=50)
    except Exception:
        return {"consultants": [], "top_skills": [], "actions": actions,
                "window_days": MARKET_WINDOW_DAYS, "error": "no job data yet"}
    demand_map = {d["skill"]: d["jobs"] for d in demand}
    top_overall = demand[:10]
    per_consultant = []
    bench_skills: set = set()
    for c in db.list_consultants():
        try:
            r = db.get_resume(c["id"])
        except Exception:
            continue
        if not r:
            continue
        rskills = set(json.loads(r.get("skills_json") or "[]"))
        bench_skills |= rskills
        hot = [{"skill": s, "jobs": demand_map[s]} for s in rskills
               if s in demand_map]
        hot.sort(key=lambda x: -x["jobs"])
        gaps = [d for d in top_overall if d["skill"] not in rskills][:5]
        if hot or gaps:
            per_consultant.append({
                "consultant_name": c["name"],
                "hot_skills": hot[:8],
                "gaps": gaps,
            })
    if autopilot and bench_skills:
        since_iso = (_now() - timedelta(days=MARKET_WINDOW_DAYS)).isoformat()
        existing = {(q.get("title") or "").lower() for q in _manual_queries(settings)}
        try:
            expanded = set(json.loads(db.get_setting("office_expanded_skills") or "[]"))
        except (json.JSONDecodeError, TypeError):
            expanded = set()
        added = 0
        for d in top_overall:
            if added >= MAX_QUERY_EXPANSIONS:
                break
            if d["skill"] in bench_skills or d["skill"] in expanded:
                continue  # bench already covers it, or already expanded before
            for title in _top_titles_for_skill(d["skill"], since_iso):
                if title.lower() not in existing:
                    queries = _manual_queries(settings)
                    queries.append({"title": title, "location": ""})
                    db.set_setting("search_queries", json.dumps(queries))
                    expanded.add(d["skill"])
                    db.set_setting("office_expanded_skills", json.dumps(sorted(expanded)))
                    existing.add(title.lower())
                    added += 1
                    actions.append({
                        "text": f"Added search query \u201c{title}\u201d — "
                                f"\u201c{display_name(d['skill'])}\u201d is in demand "
                                f"({d['jobs']} postings) and the bench doesn't cover it.",
                    })
                    break
    return {"consultants": per_consultant, "top_skills": top_overall,
            "actions": actions, "window_days": MARKET_WINDOW_DAYS}


def _draft_outreach_body(full: dict) -> tuple[str, str]:
    """Draft a submission email from real match data only.

    Uses matched skills (JD ∩ resume), the job posting, and the consultant's
    employment preference. Never invents years of experience, rates, or
    claims. Returns (subject, body).
    """
    jd = full.get("job_description") or ""
    rskills = set(full.get("resume_skills") or [])
    matched = sorted(set(extract_skills(jd)) & rskills)
    shown = [display_name(s) for s in matched[:6]]
    name = full.get("consultant_name") or "our consultant"
    first = name.split()[0] if name else "our consultant"
    title = full.get("job_title") or "the role"
    company = full.get("company") or "your company"
    location = full.get("location") or ""
    score = full.get("score")

    subject = f"Submission: {name} — {title} ({company})"

    lines = [
        "Hi [Hiring Manager],",
        "",
        f"I'd like to submit {name} for the {title} position at {company}"
        + (f" ({location})" if location else "") + ".",
        "",
    ]
    if shown:
        lines.append(f"Why {first} fits — strong match on: " + ", ".join(shown) + ".")
        lines.append("")
    if score is not None:
        lines.append(f"Our internal match score against your posting: {score}%.")
        lines.append("")
    try:
        c = db.get_consultant(full.get("consultant_id"))
        tags = emptype.parse_wanted((c or {}).get("emp_pref") or "")
        if tags:
            lines.append("Open to " + "/".join(
                emptype.TAG_LABELS.get(t, t) for t in tags) + ".")
            lines.append("")
    except Exception:
        pass
    lines += [
        "Happy to share a tailored resume and set up a call at your convenience.",
        "",
        "Best regards,",
        "[Your Name]",
        "[Your Company] | [Phone]",
        "",
        "-- Drafted by BenchPilot Outreach. Edit before sending. --",
    ]
    return subject, "\n".join(lines)


def _outreach(settings):
    """Draft submission emails for top matches. Drafts only - never sent."""
    drafted = []
    candidates = [m for m in db.list_matches(min_score=OUTREACH_SCORE_CUTOFF)
                  if not _is_queued(m["id"]) and not db.has_outreach_draft(m["id"])]
    for m in candidates[:MAX_DRAFTS_PER_RUN]:
        full = db.get_match(m["id"])
        if not full or not full.get("resume_text"):
            continue
        try:
            subject, body = _draft_outreach_body(full)
        except Exception:
            continue  # one bad draft shouldn't stop the office
        did = db.insert_outreach_draft(m["id"], subject, body)
        drafted.append({
            "draft_id": did,
            "match_id": m["id"],
            "consultant_name": m["consultant_name"],
            "job_title": m["job_title"],
            "company": m["company"],
            "score": m["score"],
            "subject": subject,
        })
    return {"drafted": len(drafted), "drafts": drafted,
            "cutoff": OUTREACH_SCORE_CUTOFF, "actions": []}


def _compliance(settings):
    """Flag employment-type / authorization conflicts before anyone applies.

    Checks each above-threshold match: if the consultant has an employment
    preference (e.g. C2C) and the posting's detected type has zero overlap
    (e.g. Full-time only), that's a conflict worth a human look.

    Autopilot: quarantines the mismatched match (it drops out of Scout's
    "new matches" so it stops wasting attention). Fully reversible from
    the Office tab. Matches already in the pipeline are never quarantined.
    """
    threshold = int(settings.get("match_threshold") or 60)
    autopilot = _autopilot_on(settings)
    issues = []
    actions = []
    seen_consultants = {}
    for m in db.list_matches(min_score=threshold):
        cid = m.get("consultant_id")
        if cid not in seen_consultants:
            try:
                c = db.get_consultant(cid) or {}
            except Exception:
                c = {}
            seen_consultants[cid] = emptype.parse_wanted(c.get("emp_pref") or "")
        pref = seen_consultants[cid]
        job_tags = m.get("emp_tags") or []
        if not pref or not job_tags:
            continue  # can't judge without both sides
        if not set(pref) & set(job_tags):
            want = "/".join(emptype.TAG_LABELS.get(t, t) for t in pref)
            has = "/".join(emptype.TAG_LABELS.get(t, t) for t in job_tags)
            detail = (f"{m['consultant_name']} prefers {want}; "
                      f"posting looks like {has}.")
            quarantined = False
            if autopilot and not m.get("compliance_flag") and not _is_queued(m["id"]):
                try:
                    db.set_compliance_flag(m["id"], 1)
                    quarantined = True
                    actions.append({
                        "text": f"Quarantined {m['job_title']} ({m['company']}) for "
                                f"{m['consultant_name']} — {detail} "
                                f"Restore it from the Office tab if this is wrong.",
                    })
                except Exception:
                    pass
            issues.append({
                "match_id": m["id"],
                "consultant_name": m["consultant_name"],
                "job_title": m["job_title"],
                "company": m["company"],
                "score": m["score"],
                "issue": "Employment-type mismatch",
                "detail": detail,
                "quarantined": quarantined or bool(m.get("compliance_flag")),
            })
    return {"issues": len(issues), "items": issues, "actions": actions}


def run_office() -> dict:
    """Run every agent and return the morning briefing."""
    settings = db.get_settings()
    now = _now()
    since = now - timedelta(hours=24)
    briefing = {
        "run_at": now.isoformat(),
        "autopilot": _autopilot_on(settings),
        "agents": {
            "scout": _scout(settings, since),
            "tailor": _tailor(settings),
            "watchdog": _watchdog(settings),
            "market_analyst": _market_analyst(settings),
            "outreach": _outreach(settings),
            "compliance": _compliance(settings),
        },
    }
    return briefing
