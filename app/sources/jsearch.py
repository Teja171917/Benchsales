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
    for j in r.json().get("data", []):
        salary = ""
        smin, smax = j.get("job_min_salary"), j.get("job_max_salary")
        if smin or smax:
            salary = f"${smin or '?'} - ${smax or '?'}"
        jobs.append({
            "source": NAME,
            "source_id": clean(j.get("job_id")),
            "title": clean(j.get("job_title")),
            "company": clean(j.get("employer_name")),
            "location": clean(j.get("job_location")),
            "remote_flag": bool(j.get("job_is_remote")),
            "url": clean(j.get("job_apply_link") or j.get("job_google_link")),
            "description": clean(j.get("job_description")),
            "posted_at": clean(j.get("job_posted_at_datetime_utc")),
            "salary": salary,
            "employment_type": clean(j.get("job_employment_type")),
        })
    return jobs
