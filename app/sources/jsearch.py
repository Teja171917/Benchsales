"""JSearch (RapidAPI) adapter — aggregates LinkedIn/Indeed/Glassdoor/ZipRecruiter.
Working endpoint as of 2026: /search-v2 (old /search 404s).
Needs a RapidAPI key (rapidapi.com, JSearch API)."""
from .common import get, clean, wanted_emp, CONTRACT_TAGS

NAME = "jsearch"
LABEL = "JSearch (LinkedIn/Indeed via RapidAPI)"
BASE = "https://jsearch.p.rapidapi.com/search-v2"


def enabled(settings: dict) -> bool:
    return bool(settings.get("rapidapi_key"))


def fetch(query: dict, settings: dict) -> list[dict]:
    headers = {"X-RapidAPI-Key": settings["rapidapi_key"],
               "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    q = query.get("title", "")
    if query.get("location"):
        q += f" in {query['location']}"
    # num_pages=1: JSearch counts extra pages as extra requests, and the free
    # plan only has 200 a month
    params = {"query": q, "page": "1", "num_pages": "1",
              "country": "us", "date_posted": "month"}
    # JSearch employment_types: FULLTIME, CONTRACTOR, PARTTIME, INTERN
    # (comma-separated = OR). C2C / W2 / 1099 / C2H roles are all CONTRACTOR.
    want = wanted_emp(settings)
    types = []
    if "fulltime" in want:
        types.append("FULLTIME")
    if set(want) & CONTRACT_TAGS:
        types.append("CONTRACTOR")
    if types:
        params["employment_types"] = ",".join(types)
    jobs: list[dict] = []
    # One request = one page (about 10 jobs) = one call of the monthly quota.
    r = get(BASE, params=params, headers=headers)
    r.raise_for_status()
    for j in job_rows(r.json()):
        jobs.append(to_job(j))
    return [j for j in jobs if j["title"]]


def job_rows(payload) -> list:
    """JSearch v5 can return {"data": [...]} or {"data": {"jobs": [...], ...}}
    (older code assumed the first, which gave "'str' object has no attribute
    'get'"). Find the list of job records wherever it is."""
    if isinstance(payload, list):
        rows = [x for x in payload if isinstance(x, dict)]
        if rows:
            return rows
        return []
    if isinstance(payload, dict):
        for key in ("data", "jobs", "results", "items"):
            if key in payload:
                got = job_rows(payload[key])
                if got:
                    return got
    return []


PUBLISHERS = {"linkedin": "linkedin", "indeed": "indeed", "glassdoor": "glassdoor",
              "ziprecruiter": "ziprecruiter", "dice": "dice", "monster": "monster"}


def _g(j: dict, *keys):
    for k in keys:
        v = j.get(k)
        if v not in (None, "", [], {}):
            return v
    return None


def to_job(j: dict) -> dict:
    smin = _g(j, "job_min_salary", "min_salary", "salary_min")
    smax = _g(j, "job_max_salary", "max_salary", "salary_max")
    salary = f"${smin or '?'} - ${smax or '?'}" if (smin or smax) else ""
    loc = _g(j, "job_location", "location")
    if not loc:
        loc = ", ".join(x for x in (clean(_g(j, "job_city", "city") or ""),
                                    clean(_g(j, "job_state", "state") or "")) if x)
    if isinstance(loc, dict):
        loc = loc.get("name") or loc.get("display_name") or ""
    publisher = clean(str(_g(j, "job_publisher", "publisher", "source") or "")).lower()
    # show WHERE the job was posted (LinkedIn, Indeed...) instead of "jsearch"
    src = next((v for k, v in PUBLISHERS.items() if k in publisher.replace(" ", "")), "")
    if not src and publisher:   # any other site (Jooble, USAJobs, Talent.com...): its own name
        import re
        src = re.sub(r"[^a-z0-9.]+", "", publisher)[:20]
    src = src or NAME
    company = _g(j, "employer_name", "company_name", "company")
    if isinstance(company, dict):
        company = company.get("name") or ""
    return {
        "source": src,
        "source_id": clean(str(_g(j, "job_id", "id") or "")),
        "title": clean(str(_g(j, "job_title", "title") or "")),
        "company": clean(str(company or "")),
        "location": clean(str(loc or "")),
        "remote_flag": bool(_g(j, "job_is_remote", "is_remote", "remote")),
        "url": clean(str(_g(j, "job_apply_link", "apply_link", "job_google_link", "url") or "")),
        "description": clean(str(_g(j, "job_description", "description") or "")),
        "posted_at": clean(str(_g(j, "job_posted_at_datetime_utc", "posted_at",
                                  "date_posted") or "")),
        "salary": salary,
        "employment_type": clean(str(_g(j, "job_employment_type", "employment_type") or "")),
    }
