"""Adzuna aggregator adapter. Needs free key from developer.adzuna.com."""
from .common import get, clean, wanted_emp, CONTRACT_TAGS

NAME = "adzuna"
LABEL = "Adzuna (aggregator)"


def enabled(settings: dict) -> bool:
    return bool(settings.get("adzuna_app_id") and settings.get("adzuna_app_key"))


REMOTE_WORDS = {"remote", "anywhere", "worldwide", "usa", "us", "united states",
                "work from home", "wfh"}


def is_remote_query(query: dict) -> bool:
    return (query.get("location") or "").strip().lower() in REMOTE_WORDS


def fetch(query: dict, settings: dict) -> list[dict]:
    """Adzuna's "where" is a place name, so "Remote" finds nothing. A remote
    search therefore leaves "where" out and asks for postings that mention
    remote / work from home. If that finds nothing, it retries once without
    that extra word and keeps only the postings that say remote."""
    remote = is_remote_query(query)
    jobs, failed = [], None
    try:
        jobs = _fetch(query, settings, remote_hint=remote)
    except Exception as e:  # noqa: BLE001 - e.g. a temporary 503 on the extra filter
        if not remote:
            raise
        failed = e
    if not jobs and remote:
        from .. import db
        db.usage_add("adzuna", 2)   # the retry costs calls the collector does not count
        # the retry is broader, so keep only the postings that say remote
        jobs = [j for j in _fetch(query, settings, remote_hint=False) if j["remote_flag"]]
    return jobs


def _fetch(query: dict, settings: dict, remote_hint: bool) -> list[dict]:
    app_id = settings["adzuna_app_id"]
    app_key = settings["adzuna_app_key"]
    jobs: list[dict] = []
    remote_q = is_remote_query(query)
    params = {"app_id": app_id, "app_key": app_key,
              "what": query.get("title", ""),
              "results_per_page": 50, "content-type": "application/json"}
    if not remote_q:
        params["where"] = query.get("location", "")
    if remote_hint:
        params["what_or"] = "remote telecommute work-from-home"
    # Adzuna can't OR filters: narrow to contract roles only when the
    # recruiter asked for contract types and NOT full-time.
    want = wanted_emp(settings)
    if want and "fulltime" not in want and set(want) <= CONTRACT_TAGS:
        params["contract"] = "1"
    elif want == ["fulltime"]:
        params["full_time"] = "1"
    for page in (1, 2):
        r = get(f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
                params=params)
        r.raise_for_status()
        data = r.json()
        for j in data.get("results", []):
            comp = j.get("company") or {}
            loc = j.get("location") or {}
            sal_min, sal_max = j.get("salary_min"), j.get("salary_max")
            salary = ""
            if sal_min or sal_max:
                salary = f"${sal_min or '?'} - ${sal_max or '?'}"
            desc = clean(j.get("description"))
            jobs.append({
                "source": NAME,
                "source_id": str(j.get("id", "")),
                "title": clean(j.get("title")),
                "company": clean(comp.get("display_name")),
                "location": clean(loc.get("display_name")),
                "remote_flag": "remote" in (loc.get("display_name") or "").lower()
                or ("remote" in (clean(j.get("title")) + " " + desc[:600]).lower()),
                "url": clean(j.get("redirect_url")),
                "description": desc,
                "posted_at": clean(j.get("created")),
                "salary": salary,
                # contract_time = full_time/part_time, contract_type = permanent/contract
                "employment_type": " ".join(filter(None, [
                    clean(j.get("contract_time")), clean(j.get("contract_type"))])),
            })
        if page * 50 >= (data.get("count") or 0):
            break
    return jobs
