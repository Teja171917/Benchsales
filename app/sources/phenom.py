"""Staffing-firms adapter, Phenom cohort: the watchlist firms whose
career sites run on Phenom (TEKsystems, Aerotek, Conduent, PwC, ICF,
BAE Systems, CAI verified live Nov 4 2026; the rest fail soft until
their page shape is confirmed).

Phenom sites server-render the first page of search results into the
page itself (the phApp data carries a "jobs" array), so fetch() reads
{site}/search-results?keywords=<title>, extracts that array, and maps
it onto the shared job shape. There is no full-feed endpoint, so each
firm keeps a small in-process union of the jobs its keyword pages
returned during the cache window, capped at a few page loads per firm
per window; every later query in the run is served from that union.
Descriptions are the posting's own teaser plus its parsed skills —
enough for the matcher to score honestly without downloading each
(very heavy) job page.

Like the SmartRecruiters feed this is gated by the staffing_enabled
setting, and it is deliberately NOT in the live-search source list:
page loads are far heavier than the JSON feeds.
"""
import json
import re
import time
from urllib.parse import quote_plus, urlparse

from .common import clean, get_text_cached
from .smartrecruiters import firms as _all_firms

NAME = "phenom"
LABEL = "Staffing Firms (Phenom)"
_PAGES_PER_FIRM = 3       # keyword page loads per firm per cache window
_WINDOW_SECONDS = 900

# firm name -> {"at": window start, "pages": loads used, "jobs": {id: job}}
_STATE: dict = {}


def phenom_firms() -> list[dict]:
    """Watchlist firms on Phenom career sites."""
    return [f for f in _all_firms()
            if (f.get("ats") or "").strip().lower() == "phenom"]


def enabled(settings: dict) -> bool:
    # Same kill switch as the SmartRecruiters staffing feed.
    return settings.get("staffing_enabled", "1") == "1"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _search_base(firm: dict) -> str:
    """The firm's job-search page: the careers URL itself when it already
    points at search results, otherwise the locale root + /search-results."""
    url = (firm.get("careers_url") or "").split("?")[0].rstrip("/")
    if "search-results" in url:
        return url
    path = urlparse(url).path
    if re.search(r"/(us|global|[a-z]{2})/[a-z]{2}(-[a-z]{2})?$", path, re.I) \
            or path in ("", "/"):
        return url + "/search-results"
    return url


def _job_url(firm: dict, raw: dict) -> str:
    base = _search_base(firm)
    seq = clean(raw.get("jobSeqNo"))
    if not seq:
        return base
    prefix = base[: -len("search-results")].rstrip("/") \
        if base.endswith("search-results") else base
    return f"{prefix}/job/{seq}"


def _extract_jobs(html: str) -> list[dict]:
    """The embedded "jobs":[...] array from a Phenom search page."""
    m = re.search(r'"jobs"\s*:\s*\[', html or "")
    if not m:
        return []
    start = m.end() - 1
    depth = 0
    for j in range(start, min(start + 400000, len(html))):
        c = html[j]
        if c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(html[start:j + 1])
                except ValueError:
                    return []
                return [x for x in data if isinstance(x, dict)]
    return []


def _normalize(firm: dict, raw: dict) -> dict | None:
    country = clean(raw.get("country")).upper()
    if country and country not in ("USA", "US", "UNITED STATES"):
        return None
    rid = clean(raw.get("reqId") or raw.get("jobId"))
    title = clean(raw.get("title"))
    if not rid or not title:
        return None
    locs = raw.get("multi_location") or []
    place = clean(raw.get("cityStateCountry")) \
        or (clean(locs[0]) if locs else "") \
        or ", ".join(x for x in [clean(raw.get("city")),
                                 clean(raw.get("state"))] if x) \
        or "United States"
    teaser = clean(raw.get("descriptionTeaser"))
    skills = [clean(s) for s in (raw.get("ml_skills") or []) if clean(s)]
    description = teaser
    if skills:
        description = (description + "\n\nSkills: " + ", ".join(skills)).strip()
    return {
        "source": NAME,
        "source_id": f"{_slug(firm['company'])}:{rid}",
        "title": title,
        "company": firm["company"],
        "location": place,
        "remote_flag": "remote" in (place + " " + title).lower(),
        "url": _job_url(firm, raw),
        "description": description,
        "posted_at": clean(raw.get("postedDate") or raw.get("dateCreated")),
        "salary": "",
        "employment_type": clean(raw.get("type")),
    }


def _firm_jobs(firm: dict, query_title: str) -> list[dict]:
    """The firm's accumulated jobs this window, loading at most
    _PAGES_PER_FIRM keyword pages per window."""
    now = time.time()
    st = _STATE.get(firm["company"])
    if st is None or now - st["at"] > _WINDOW_SECONDS:
        st = {"at": now, "pages": 0, "jobs": {}}
        _STATE[firm["company"]] = st
    if st["pages"] < _PAGES_PER_FIRM:
        st["pages"] += 1
        url = _search_base(firm)
        if query_title:
            url += "?keywords=" + quote_plus(query_title)
        try:
            html = get_text_cached(url, ttl=_WINDOW_SECONDS, timeout=30)
        except Exception:  # noqa: BLE001 - one firm's outage must not kill the feed
            html = ""
        for raw in _extract_jobs(html):
            job = _normalize(firm, raw)
            if job is not None:
                st["jobs"][job["source_id"]] = job
    return list(st["jobs"].values())


def fetch(query: dict, settings: dict) -> list[dict]:
    want = (query.get("title") or "").lower().split()
    jobs: list[dict] = []
    for firm in phenom_firms():
        try:
            found = _firm_jobs(firm, query.get("title") or "")
        except Exception:  # noqa: BLE001 - fail soft per firm
            continue
        for job in found:
            if want and not any(w in job["title"].lower() for w in want):
                continue
            jobs.append(job)
    return jobs
