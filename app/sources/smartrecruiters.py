"""Staffing-firms adapter: the careers boards of US tech recruiting firms.

Phase 1 covers the firms whose ATS is SmartRecruiters, via its public
postings API (no key): GET /v1/companies/{identifier}/postings. The firm
watchlist (202 companies from the user's CSV) lives in
app/data/staffing_firms.json; firms on other ATSs are directory-only
until their adapters land. These firms post mostly contract/C2C work,
which is exactly what a bench-sales pool wants.

Like the other whole-feed adapters, fetch() is called once per search
query: each firm's feed is cached, postings are filtered to US locations
whose title matches the query, and the full job-ad text is fetched only
for the survivors so the matcher has a real description to score.
"""
import json
from pathlib import Path

from .common import clean, get_json_cached, strip_html

NAME = "smartrecruiters"
LABEL = "Staffing Firms (SmartRecruiters)"
API = "https://api.smartrecruiters.com/v1/companies"
_FIRMS_FILE = Path(__file__).resolve().parent.parent / "data" / "staffing_firms.json"
_MAX_PAGES = 3          # up to 300 postings per firm per run
_DETAIL_CAP = 40        # job-ad detail fetches per fetch() call


def firms() -> list[dict]:
    """The full staffing-firm watchlist (all ATSs)."""
    try:
        return json.loads(_FIRMS_FILE.read_text())
    except (OSError, ValueError):
        return []


def sr_firms() -> list[dict]:
    """Firms this adapter can pull today: SmartRecruiters + identifier."""
    return [f for f in firms() if f.get("identifier")]


def enabled(settings: dict) -> bool:
    # Public API, no key — on by default like Dice's connector; a company
    # turns it off with the staffing_enabled setting.
    return settings.get("staffing_enabled", "1") == "1"


def _postings(identifier: str) -> list[dict]:
    out: list[dict] = []
    for page in range(_MAX_PAGES):
        payload = get_json_cached(
            f"{API}/{identifier}/postings?limit=100&offset={page * 100}",
            ttl=900)
        content = payload.get("content") or []
        out.extend(content)
        if len(out) >= int(payload.get("totalFound") or 0) or not content:
            break
    return out


def _description(identifier: str, posting_id: str) -> str:
    try:
        payload = get_json_cached(
            f"{API}/{identifier}/postings/{posting_id}", ttl=3600)
    except Exception:  # noqa: BLE001 - a missing ad body must not kill the feed
        return ""
    sections = ((payload.get("jobAd") or {}).get("sections") or {})
    parts = []
    for key in ("jobDescription", "qualifications", "additionalInformation"):
        text = ((sections.get(key) or {}).get("text") or "")
        if text:
            parts.append(strip_html(text))
    return "\n\n".join(parts)


def _normalize(firm: dict, p: dict) -> dict | None:
    loc = p.get("location") or {}
    if (loc.get("country") or "").lower() != "us":
        return None
    identifier = firm["identifier"]
    pid = clean(str(p.get("id") or ""))
    if not pid:
        return None
    title = clean(p.get("name"))
    place = clean(loc.get("fullLocation")) or ", ".join(
        x for x in [clean(loc.get("city")), clean(loc.get("region"))] if x) or "United States"
    emp = (p.get("typeOfEmployment") or {}).get("label") or ""
    return {
        "source": NAME,
        "source_id": f"{identifier}:{pid}",
        "title": title,
        "company": firm["company"],
        "location": place,
        "remote_flag": bool(loc.get("remote")),
        "url": f"https://careers.smartrecruiters.com/{identifier}/{pid}",
        "description": "",
        "posted_at": clean(p.get("releasedDate")),
        "salary": "",
        "employment_type": clean(emp),
        "_sr": (identifier, pid),
    }


def fetch(query: dict, settings: dict) -> list[dict]:
    want = (query.get("title") or "").lower().split()
    jobs: list[dict] = []
    for firm in sr_firms():
        try:
            postings = _postings(firm["identifier"])
        except Exception:  # noqa: BLE001 - one firm's outage must not kill the feed
            continue
        for p in postings:
            job = _normalize(firm, p)
            if job is None:
                continue
            if want and not any(w in job["title"].lower() for w in want):
                continue
            jobs.append(job)
    for job in jobs[:_DETAIL_CAP]:
        ident, pid = job.pop("_sr")
        job["description"] = _description(ident, pid)
    for job in jobs[_DETAIL_CAP:]:
        job.pop("_sr", None)
    return jobs
