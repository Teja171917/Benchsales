"""BenchPilot "runs by itself" helpers.

What this module does without any human:
  * learns new skill names from the Skills section of every resume we hold
    (so a tool the built-in list never heard of still counts in matching);
  * keeps each resume's stored skills in step with the current vocabulary;
  * builds the job-search queries from the consultants' resumes (their headline
    role + location), instead of a fixed list someone typed once;
  * works out how often it may refresh without breaking a free API key's limit.

Everything here is conservative on purpose: it only reads the Skills section,
it never invents skills for a consultant, and learned skills can be removed
from the Settings page.
"""
import json
import math
import re

from . import db, matcher, skills as skills_mod
from .skills import extract_skills

# ---------------------------------------------------------------- learning
_HEADING = re.compile(
    r"^\s*(technical\s+skills|core\s+skills|key\s+skills|skills(\s+summary)?|"
    r"technologies|tech\s+stack|tools(\s*(&|and)\s*technologies)?|"
    r"technical\s+(summary|proficiency|expertise))\b\s*:?\s*$", re.I)
_OTHER_HEADING = re.compile(
    r"^\s*(professional\s+|work\s+|employment\s+)?(experience|history|summary|"
    r"profile|objective|education|projects?|certifications?|achievements|"
    r"awards|publications|references|personal\s+details|declaration|"
    r"academic\s+(background|qualifications?))(\s+(history|summary))?\s*:?\s*$",
    re.I)
_LABEL = re.compile(r"^\s*([^:,]{2,40}):\s*(\S.*)$")
_ITEM_OK = re.compile(r"^[a-z0-9][a-z0-9 .+#/&\-]{1,29}$")

# words that appear in skills sections but are not a named skill
_NOT_SKILLS = {
    "and", "or", "etc", "others", "other", "various", "basic", "advanced",
    "good", "strong", "excellent", "knowledge", "experience", "years",
    "proficient", "familiar", "working", "hands-on", "hands on", "expert",
    "intermediate", "beginner", "tools", "tool", "skills", "technologies",
    "languages", "language", "frameworks", "framework", "databases",
    "database", "cloud", "testing", "methodologies", "methodology",
    "operating systems", "operating system", "platforms", "platform",
    "libraries", "environment", "environments", "concepts", "others",
    "communication", "teamwork", "leadership", "problem solving",
    "analytical", "management", "team player", "english", "telugu", "hindi",
    "present", "current", "summary", "technical", "software", "applications",
    "application", "web", "mobile", "data", "reporting", "version control",
    "bug tracking", "defect tracking", "build tools", "ci tools", "ide",
    "ides", "os", "n/a", "na", "none",
}
_MAX_PER_RESUME = 60


def _skills_section_lines(text: str) -> list[str]:
    lines = (text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if not _HEADING.match(lines[i]):
            i += 1
            continue
        j = i + 1
        got = 0
        while j < len(lines):
            ln = lines[j]
            if not ln.strip():
                if got:
                    break  # blank line after the section's content ends it
                j += 1
                continue
            if _HEADING.match(ln) or _OTHER_HEADING.match(ln):
                break
            out.append(ln)
            got += 1
            j += 1
        i = j
    return out


def _blocked() -> set:
    try:
        return set(json.loads(db.get_setting("blocked_skills", "[]") or "[]"))
    except (json.JSONDecodeError, TypeError):
        return set()


def block_skill(skill: str) -> None:
    """A person removed this learned skill: never learn it again."""
    b = _blocked()
    b.add(skill.strip().lower())
    db.set_setting("blocked_skills", json.dumps(sorted(b)))


def candidate_skills(text: str) -> list[str]:
    """New-looking skill names from the Skills section of one resume. Items
    that are already known (or that contain a known skill) are skipped."""
    found: list[str] = []
    blocked = _blocked()
    for ln in _skills_section_lines(text):
        m = _LABEL.match(ln)
        body = m.group(2) if m else ln
        body = re.sub(r"[()]", ",", body)
        for raw in re.split(r"[,;|•·]", body):
            item = raw.strip(" \t.:-–—*").lower()
            if not item or not _ITEM_OK.match(item):
                continue
            if item in _NOT_SKILLS or item in blocked or len(item.split()) > 3:
                continue
            if re.fullmatch(r"[\d .+\-/]+", item):
                continue
            if skills_mod.is_known(item) or extract_skills(item):
                continue
            if item not in found:
                found.append(item)
            if len(found) >= _MAX_PER_RESUME:
                return found
    return found


def sync_vocabulary() -> bool:
    """Load the learned skills from the database into memory. If the list
    changed, forget cached job-skill results. Returns True if it changed."""
    changed = skills_mod.set_learned([r["skill"] for r in db.list_learned_skills()])
    if changed:
        matcher._jd_skills.cache_clear()
    return changed


def maintain() -> dict:
    """The whole "keep everything up to date" step. Safe to call any time.
    Learns new skills, refreshes stored resume skills, and rescores existing
    matches when something changed. Never deletes a match."""
    out = {"learned": [], "resumes_refreshed": 0, "rescored": 0}
    # a skill learned earlier that has since become an alias ("jenkin" ->
    # "jenkins") is a spelling of a known skill, not a skill of its own
    for row in db.list_learned_skills():
        if (row.get("skill") or "").lower() in skills_mod.ALIASES:
            db.delete_learned_skill(row["skill"])
    sync_vocabulary()
    consultants = db.consultants_with_resumes()
    if db.get_setting("auto_learn_skills", "1") == "1":
        new: list[str] = []
        for c in consultants:
            new += db.add_learned_skills(
                candidate_skills(c.get("raw_text") or ""),
                source=c.get("filename") or "")
        if new:
            out["learned"] = sorted(set(new))
            sync_vocabulary()
    for c in consultants:
        fresh = extract_skills(c.get("raw_text") or "")
        if fresh != sorted(c.get("skills") or []):
            db.update_resume_skills(c["id"], fresh)
            out["resumes_refreshed"] += 1
    if out["learned"] or out["resumes_refreshed"]:
        out["rescored"] = matcher.rescore_existing()
    return out


# ------------------------------------------------------------- job queries
_TITLE_JUNK = re.compile(
    r"\(.*?\)|\b\d+\+?\s*(years?|yrs?)\b.*|\b(resume|curriculum vitae|cv)\b", re.I)


def headline_title(raw_text: str, skills: list | None = None) -> str:
    """The role a resume is for ("QA Automation Engineer"), cleaned up. Falls
    back to the consultant's top skills when no sensible title is found."""
    t = matcher.consultant_title(raw_text or "")
    t = _TITLE_JUNK.sub("", t)
    t = re.sub(r"\s+", " ", t).strip(" -–—,:;|")
    words = t.split()
    ok = (3 <= len(t) <= 60 and 1 <= len(words) <= 6 and "@" not in t
          and not re.search(r"\d{3}", t) and re.search(r"[A-Za-z]{3}", t)
          and re.search(r"engineer|developer|analyst|architect|tester|"
                        r"administrator|consultant|manager|specialist|"
                        r"scientist|lead|programmer|sdet|qa|devops|sre|admin",
                        t, re.I))
    if ok:
        return t
    # no title line: use the role named in the summary ("Teamcenter PLM")
    r = matcher.role_from_summary(raw_text or "")
    if r and 1 <= len(r.split()) <= 5 and re.search(r"[A-Za-z]{3}", r):
        return r
    sk = [s for s in (skills or []) if len(s) > 2][:2]
    return " ".join(sk)


def _loc_query(location: str) -> str:
    loc = (location or "").strip()
    if not loc or len(loc) > 60:
        return ""
    return loc


def build_queries(consultants: list, manual: list, max_queries: int = 8) -> list:
    """Search queries for the collector: for each consultant with a resume,
    their headline role in their own area and as Remote. Consultants take
    turns so a long list of people can't push anyone out. Whatever room is
    left is filled from the manually typed queries."""
    max_queries = max(1, min(int(max_queries or 8), 12))  # 12 x 2 = 24 < Adzuna 25/min
    per: list[list[dict]] = []
    for c in consultants:
        title = headline_title(c.get("raw_text") or "", c.get("skills") or [])
        if not title:
            continue
        qs = []
        loc = _loc_query(c.get("location"))
        if loc:
            qs.append({"title": title, "location": loc})
        qs.append({"title": title, "location": "Remote"})
        per.append(qs)
    out: list[dict] = []
    seen: set = set()

    def add(q: dict) -> bool:
        key = (q["title"].lower(), (q.get("location") or "").lower())
        if key in seen or len(out) >= max_queries:
            return False
        seen.add(key)
        out.append(q)
        return True

    depth = 0
    while len(out) < max_queries and any(depth < len(p) for p in per):
        for p in per:
            if depth < len(p):
                add(p[depth])
        depth += 1
    for q in manual or []:
        if isinstance(q, dict) and q.get("title"):
            add({"title": q["title"], "location": q.get("location", "")})
    return out


def queries_for_run(settings: dict) -> list:
    try:
        manual = json.loads(settings.get("search_queries") or "[]")
    except json.JSONDecodeError:
        manual = []
    if not manual:
        manual = db.DEFAULT_SEARCH_QUERIES
    if settings.get("auto_queries", "1") != "1":
        return manual
    try:
        mx = int(settings.get("max_queries") or 8)
    except ValueError:
        mx = 8
    # the untouched built-in example queries are only a starting point: once
    # real resumes exist they would just waste searches on unrelated roles
    extra = [] if manual == db.DEFAULT_SEARCH_QUERIES else manual
    # searches the Market Analyst added for hot skills the bench lacks: keep
    # room for the newest two so they are not squeezed out by the resumes
    try:
        added = json.loads(settings.get("office_expanded_queries") or "[]")
    except json.JSONDecodeError:
        added = []
    added = [q for q in added if isinstance(q, dict) and q.get("title")][-2:]
    auto = build_queries(db.consultants_with_resumes(), extra,
                         max(1, min(mx, 12) - len(added)))
    seen = {((q["title"]).lower(), (q.get("location") or "").lower()) for q in auto}
    for q in added:
        key = (q["title"].lower(), (q.get("location") or "").lower())
        if key not in seen:
            auto.append({"title": q["title"], "location": q.get("location", "")})
            seen.add(key)
    return auto or manual


# ------------------------------------------------------ quota-aware schedule
ADZUNA_CALLS_PER_QUERY = 2  # the adapter reads 2 pages per query


def adzuna_budget(settings: dict) -> int:
    try:
        return max(0, min(int(settings.get("adzuna_daily_budget") or 80), 240))
    except ValueError:
        return 80


def effective_interval_minutes(settings: dict | None = None) -> int:
    """How often to refresh. Never faster than the setting, and slowed down if
    Adzuna's daily allowance would otherwise run out before midnight. 0 = off."""
    settings = settings or db.get_settings()
    try:
        wanted = int(settings.get("collect_interval_minutes") or 0)
    except ValueError:
        wanted = 0
    if wanted <= 0:
        return 0
    try:
        enabled = set(json.loads(settings.get("enabled_sources") or "[]"))
    except json.JSONDecodeError:
        enabled = set()
    if "adzuna" in enabled and settings.get("adzuna_app_id") and settings.get("adzuna_app_key"):
        n = len(queries_for_run(settings))
        cost = max(1, n * ADZUNA_CALLS_PER_QUERY)
        runs_per_day = max(1, adzuna_budget(settings) // cost)
        wanted = max(wanted, math.ceil(1440 / runs_per_day))
    return wanted
