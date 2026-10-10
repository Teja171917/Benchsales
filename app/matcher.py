"""Consultant <-> job scoring for BenchPilot (0-100)."""
import json
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from . import db, emptype
from .usa import STATE_ABBR_TO_NAME
from .skills import extract_skills, requirements_skills

STOPWORDS = {"a", "an", "the", "and", "or", "of", "for", "to", "in", "on",
             "at", "with", "sr", "senior", "junior", "jr", "ii", "iii", "iv",
             "lead", "i", "software", "engineer", "developer"}


def _tokens(s: str) -> set[str]:
    toks = set(re.findall(r"[a-z0-9+#.\-]+", (s or "").lower()))
    return {t for t in toks if t not in STOPWORDS and len(t) > 1}


_LOC_NOISE = {"usa", "us", "united", "states", "america", "county"}


def _loc_tokens(s: str) -> set[str]:
    """Location words, with state abbreviations spelled out so that
    "Irvine, CA" and "California, USA" share the token 'california'."""
    s = s or ""
    toks = set(_tokens(s))
    for m in re.finditer(r"\b([A-Z]{2})\b", s):
        name = STATE_ABBR_TO_NAME.get(m.group(1))
        if name:
            toks.discard(m.group(1).lower())
            toks.update(name.split())
    return {t for t in toks if t not in _LOC_NOISE}


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


_ROLE_WORD = (r"Professional|Engineer|Developer|Administrator|Analyst|Architect|"
              r"Consultant|Specialist|Manager|Lead|Tester|Programmer|Admin")
_ROLE_RE = re.compile(r"((?:[A-Z][A-Za-z+/.&#\-]*[ \t]+){1,5}(?:" + _ROLE_WORD + r"))\b")
_FLUFF = re.compile(r"^(results?[- ]driven|experienced|dynamic|motivated|detail[- ]oriented|"
                    r"seasoned|highly|skilled|passionate|proven|dedicated|accomplished|"
                    r"resourceful|self[- ]motivated|versatile|talented|a|an|the)$", re.I)


def role_from_summary(raw_text: str) -> str:
    """For resumes with no title line: the role named in the summary, e.g.
    "Results-driven Teamcenter PLM Professional with 8+ years..." ->
    "Teamcenter PLM". Returns "" when nothing sensible is found."""
    head = (raw_text or "")[:2500]
    m = _ROLE_RE.search(head)
    if not m:
        return ""
    words = m.group(1).split()
    while words and _FLUFF.match(words[0]):
        words.pop(0)
    if words and words[-1].lower() == "professional":
        words.pop()                      # "PLM Professional" -> "PLM"
    return " ".join(words) if words else ""


def consultant_title(raw_text: str) -> str:
    """Best guess at the candidate's current title: the first line, unless it
    looks like a name (short, no tech terms) - then the second line. When that
    line is a contact line (phone / email) there is no title line, so the role
    is read from the summary instead."""
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    first = lines[0]
    if len(first.split()) <= 4 and not extract_skills(first) and len(lines) > 1:
        cand = lines[1].split("|")[0].strip()
    else:
        cand = first.split("|")[0].strip()
    if re.search(r"@|\d{3}", cand) or not re.search(r"[A-Za-z]{3}", cand):
        return role_from_summary(raw_text) or cand
    if len(cand.split()) <= 3 and not re.search(r"engineer|developer|analyst|architect|tester|"
                                                 r"administrator|consultant|manager|specialist|"
                                                 r"lead|programmer|admin|qa|devops|sdet", cand, re.I):
        # a heading such as "PROFESSIONAL SUMMARY", not a title
        if re.match(r"(?i)(professional |career |executive )?(summary|profile|objective)", cand):
            return role_from_summary(raw_text) or cand
    return cand


def consultant_titles(raw_text: str) -> list:
    """The main title plus the other titles on the same header line, e.g.
    "Senior QA Test Manager | Test Lead | Automation Engineer" gives all three,
    so a job for any of the person's own roles counts as a title match."""
    main = consultant_title(raw_text)
    out = [main] if main else []
    lines = [ln.strip() for ln in (raw_text or "").splitlines() if ln.strip()]
    for ln in lines[:3]:
        if "|" in ln and not re.search(r"@|\d{3}", ln) and main and main in ln:
            for part in ln.split("|"):
                part = part.strip()
                if part and part not in out and len(part.split()) <= 6:
                    out.append(part)
            break
    return out


@lru_cache(maxsize=4096)
def _jd_skills(jd_text: str) -> tuple[frozenset, frozenset]:
    """Skill extraction is the slow part and is identical for every consultant
    scored against the same job, so cache it by description text."""
    jd = frozenset(extract_skills(jd_text))
    return jd, frozenset(requirements_skills(jd_text)) & jd


def emp_compatible(consultant: dict, job_tags: list) -> bool:
    """A consultant who only takes e.g. W2 should not be matched to a job that
    explicitly says C2C only. Jobs with no detectable type always pass, and a
    consultant with no stated preference matches everything."""
    pref = emptype.parse_wanted(consultant.get("emp_pref") or "")
    if not pref or not job_tags:
        return True
    return bool(set(pref) & set(job_tags))


def score(consultant: dict, job: dict) -> dict:
    """consultant: dict with raw_text, skills(list), location.
    job: dict with title, location, remote_flag, description, posted_at.
    Returns {score, breakdown, missing_skills}."""
    resume_skills = set(consultant.get("skills") or [])
    jd_text = job.get("description") or ""
    jd_skills, req_skills = _jd_skills(jd_text)

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
    job_tokens = _tokens(job.get("title", ""))
    title_score = max((_jaccard(_tokens(t), job_tokens)
                       for t in consultant_titles(consultant.get("raw_text", ""))),
                      default=0.0)

    # 10% location/remote fit
    remote = bool(job.get("remote_flag")) or "remote" in (job.get("location") or "").lower()
    if remote:
        loc_score = 1.0
    elif consultant.get("location") and job.get("location"):
        loc_score = _jaccard(_loc_tokens(consultant["location"]),
                            _loc_tokens(job["location"]))
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
        "missing_skills": sorted(set(jd_skills) - resume_skills),
    }


STRONG_SKILL = 90.0   # a job whose title is unrelated needs a near-perfect skill fit


def fits_role(breakdown: dict) -> bool:
    """A job is shown to a consultant only when its title has something in
    common with the person's own role(s), or the skills match almost
    perfectly. Skill overlap alone is not enough: a Teamcenter administrator
    and a test engineer both list Jira and SQL."""
    return (breakdown.get("title", 0) > 0
            or breakdown.get("skill", 0) >= STRONG_SKILL)


def run_all(threshold: float | None = None,
            consultant_id: int | None = None) -> int:
    """Score every consultant with a resume against every job; insert new
    matches at/above threshold. Returns number of new matches. Pass
    consultant_id to score just that one consultant (used right after a
    resume upload)."""
    if threshold is None:
        try:
            threshold = float(db.get_setting("match_threshold", "60"))
        except ValueError:
            threshold = 60.0
    consultants = db.consultants_with_resumes()
    if consultant_id is not None:
        consultants = [c for c in consultants if c["id"] == consultant_id]
    with db.get_conn() as conn:
        jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs")]
        # one query instead of one connection per (consultant, job) pair
        existing = {(r["consultant_id"], r["job_id"]) for r in conn.execute(
            'SELECT consultant_id, job_id FROM "matches"')}
    new = 0
    for c in consultants:
        for j in jobs:
            if (c["id"], j["id"]) in existing:
                continue
            if not emp_compatible(c, emptype.from_db(j.get("emp_tags") or "")):
                continue
            r = score(c, j)
            if r["score"] >= threshold and fits_role(r["breakdown"]):
                if db.insert_match(c["id"], j["id"], r["score"],
                                   r["breakdown"], r["missing_skills"]):
                    new += 1
    return new


def rescore_existing(consultant_id: int | None = None) -> int:
    """Recompute the score of matches that already exist (the skill list or a
    resume changed). Only updates numbers - never deletes a match, because an
    application may depend on it. Returns how many scores changed."""
    consultants = {c["id"]: c for c in db.consultants_with_resumes()}
    with db.get_conn() as conn:
        jobs = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
        rows = [dict(r) for r in conn.execute(
            'SELECT id, consultant_id, job_id, score, score_breakdown_json, '
            'missing_skills_json FROM "matches"')]
    changed = 0
    for m in rows:
        if consultant_id is not None and m["consultant_id"] != consultant_id:
            continue
        c, j = consultants.get(m["consultant_id"]), jobs.get(m["job_id"])
        if not c or not j:
            continue
        r = score(c, j)
        old_missing = json.loads(m["missing_skills_json"] or "[]")
        if r["score"] != m["score"] or r["missing_skills"] != old_missing:
            db.update_match(m["id"], r["score"], r["breakdown"], r["missing_skills"])
            changed += 1
    return changed


def prune_misfits() -> int:
    """Remove matches that fail the role check (see fits_role) and that nobody
    has used: no application, tailored resume or outreach draft depends on
    them. Returns how many were removed."""
    consultants = {c["id"]: c for c in db.consultants_with_resumes()}
    with db.get_conn() as conn:
        jobs = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM jobs")}
        rows = [dict(r) for r in conn.execute(
            'SELECT m.id, m.consultant_id, m.job_id FROM "matches" m '
            'WHERE NOT EXISTS (SELECT 1 FROM applications a WHERE a.match_id=m.id) '
            'AND NOT EXISTS (SELECT 1 FROM tailored_resumes t WHERE t.match_id=m.id) '
            'AND NOT EXISTS (SELECT 1 FROM outreach_drafts o WHERE o.match_id=m.id)')]
    drop = []
    for m in rows:
        c, j = consultants.get(m["consultant_id"]), jobs.get(m["job_id"])
        if not c or not j:
            continue
        if not fits_role(score(c, j)["breakdown"]):
            drop.append(m["id"])
    if drop:
        with db.get_conn() as conn:
            conn.executemany('DELETE FROM "matches" WHERE id=?', [(i,) for i in drop])
            conn.commit()
    return len(drop)
