"""Consultant <-> job scoring for BenchPilot (0-100)."""
import re
from datetime import datetime, timedelta, timezone

from . import db
from .skills import extract_skills, requirements_skills

STOPWORDS = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on",
             "at", "with", "sr", "senior", "junior", "jr", "ii", "iii", "iv",
             "lead", "i", "software", "engineer", "developer"}


def _tokens(s: str) -> set[str]:
    toks = set(re.findall(r"[a-z0-9+#.\-]+", (s or "").lower()))
    return {t for t in toks if t not in STOPWORDS and len(t) > 1}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_date(s: str):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except Exception:
        return None


def consultant_title(raw_text: str) -> str:
    """Best guess at the candidate's current title: the first line, unless it
    looks like a name (short, no tech terms) — then the second line."""
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    first = lines[0]
    if len(first.split()) <= 4 and not extract_skills(first) and len(lines) > 1:
        return lines[1].split("|")[0].strip()
    return first.split("|")[0].strip()


def score(consultant: dict, job: dict) -> dict:
    """consultant: dict with raw_text, skills(list), location.
    job: dict with title, location, remote_flag, description, posted_at.
    Returns {score, breakdown, missing_skills}."""
    resume_skills = set(consultant.get("skills") or [])
    jd_text = job.get("description") or ""
    jd_skills = set(extract_skills(jd_text))
    req_skills = requirements_skills(jd_text) & jd_skills

    # 70% skill overlap (requirements-section skills count 2x)
    possible = 0
    matched_w = 0
    for s in jd_skills:
        w = 2 if s in req_skills else 1
        possible += w
        if s in resume_skills:
            matched_w += w
    skill_score = (matched_w / possible) if possible else 0.0
    # evidence guard: a JD yielding <3 recognizable skills is too thin for a
    # confident skill verdict — scale the component down instead of letting
    # 1 coincidental keyword drive the whole score.
    if possible:
        skill_score *= min(1.0, len(jd_skills) / 3.0)

    # 20% title similarity
    title_score = _jaccard(_tokens(consultant_title(consultant.get("raw_text", ""))),
                           _tokens(job.get("title", "")))

    # 10% location/remote fit
    remote = bool(job.get("remote_flag")) or "remote" in (job.get("location") or "").lower()
    if remote:
        loc_score = 1.0
    elif consultant.get("location") and job.get("location"):
        loc_score = _jaccard(_tokens(consultant["location"]), _tokens(job["location"]))
    else:
        loc_score = 0.5

    base = 0.70 * skill_score + 0.20 * title_score + 0.10 * loc_score
    score100 = round(base * 100, 1)

    # recency boost
    recency = 0
    posted = _parse_date(job.get("posted_at"))
    if posted and posted >= datetime.now(timezone.utc) - timedelta(days=7):
        recency = 5
    score100 = min(100.0, score100 + recency)

    breakdown = {
        "skill": round(skill_score * 100, 1),
        "title": round(title_score * 100, 1),
        "location": round(loc_score * 100, 1),
        "recency": recency,
    }
    return {
        "score": score100,
        "breakdown": breakdown,
        "missing_skills": sorted(jd_skills - resume_skills),
    }


def run_all(threshold: float | None = None) -> int:
    """Score every consultant with a resume against every job; insert new
    matches at/above threshold. Returns number of new matches."""
    if threshold is None:
        try:
            threshold = float(db.get_setting("match_threshold", "60"))
        except ValueError:
            threshold = 60.0
    consultants = db.consultants_with_resumes()
    with db.get_conn() as conn:
        jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs")]
    new = 0
    for c in consultants:
        for j in jobs:
            if db.match_exists(c["id"], j["id"]):
                continue
            r = score(c, j)
            if r["score"] >= threshold:
                if db.insert_match(c["id"], j["id"], r["score"],
                                   r["breakdown"], r["missing_skills"]):
                    new += 1
    return new
