"""Per-consultant standing rules.

Standing rules say which jobs the Agent Office may act on for a
consultant: draft a tailored resume, file the match into the apply
queue. They never change matching or scores - they only gate agent
actions, so a recruiter can rule out whole categories of jobs once
("no clearance roles", "remote only", "nothing under $120k") instead
of rejecting them one by one forever.

Stored as JSON on the consultant row (consultants.rules_json):

    {"titles": [], "locations": [], "remote_only": false,
     "min_rate": 0, "exclude_keywords": [], "exclude_clients": []}
"""
import json
import re

_HOURLY_WORDS = ("/hr", "/hour", "per hour", "an hour", "hourly")
_HOURS_PER_YEAR = 2080


def empty_rules() -> dict:
    return {"titles": [], "locations": [], "remote_only": False,
            "min_rate": 0, "exclude_keywords": [], "exclude_clients": []}


def parse_rules(raw) -> dict:
    """Normalise whatever was stored or sent into the rules shape.

    Accepts a dict, a JSON string, or None; anything unreadable becomes
    the empty (allow-everything) shape.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "")
        except ValueError:
            raw = None
    if not isinstance(raw, dict):
        return empty_rules()

    def _list(key):
        v = raw.get(key) or []
        if isinstance(v, str):
            v = v.split(",")
        if not isinstance(v, (list, tuple)):
            return []
        return [str(x).strip() for x in v if str(x).strip()]

    try:
        rate = float(raw.get("min_rate") or 0)
    except (TypeError, ValueError):
        rate = 0
    return {"titles": _list("titles"),
            "locations": _list("locations"),
            "remote_only": bool(raw.get("remote_only")),
            "min_rate": int(rate) if rate == int(rate) else rate,
            "exclude_keywords": _list("exclude_keywords"),
            "exclude_clients": _list("exclude_clients")}


def _is_remote(job) -> bool:
    return bool(job.get("remote_flag")) or \
        "remote" in (job.get("location") or "").lower()


def _salary_annual(text):
    """Best annual figure in a salary string, or None if none is readable.

    A range resolves to its top (what the job can pay); hourly figures
    are annualised. Returns None for missing/unparseable text so callers
    never block on absent data.
    """
    if not text:
        return None
    t = str(text).lower()
    amounts = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", t):
        val = float(m.group(1).replace(",", ""))
        if m.group(2):
            val *= 1000
        amounts.append(val)
    if not amounts:
        return None
    top = max(amounts)
    if any(w in t for w in _HOURLY_WORDS):
        top *= _HOURS_PER_YEAR
    return top


def rules_allow(consultant, job) -> tuple[bool, str]:
    """May the agents act on this job for this consultant?

    Returns (allowed, reason). Exclusions always win. A rule blocks only
    on data that is actually present - a job with no readable salary is
    never blocked by min_rate.
    """
    consultant = consultant or {}
    job = job or {}
    raw = consultant.get("rules")
    if raw is None:
        raw = consultant.get("rules_json")
    rules = parse_rules(raw)

    title = job.get("title") or job.get("job_title") or ""
    company = job.get("company") or ""
    location = job.get("location") or ""
    haystack = " ".join([title, company,
                         job.get("description")
                         or job.get("job_description") or ""]).lower()

    for kw in rules["exclude_keywords"]:
        if kw.lower() in haystack:
            return False, f"excluded keyword: {kw}"
    for client in rules["exclude_clients"]:
        if client.lower() in company.lower():
            return False, f"excluded client: {client}"
    if rules["titles"] and not any(t.lower() in title.lower()
                                   for t in rules["titles"]):
        return False, "job title outside standing rules"
    remote = _is_remote(job)
    if rules["remote_only"] and not remote:
        return False, "standing rules: remote only"
    if rules["locations"] and not remote and not any(
            loc.lower() in location.lower() for loc in rules["locations"]):
        return False, "job location outside standing rules"
    if rules["min_rate"]:
        annual = _salary_annual(job.get("salary"))
        if annual is not None and annual < rules["min_rate"]:
            return False, f"salary below standing min rate ({rules['min_rate']})"
    return True, ""
