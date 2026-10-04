"""Adzuna aggregator adapter. Needs free key from developer.adzuna.com."""
from .common import get, clean

NAME = "adzuna"
LABEL = "Adzuna (aggregator)"


def enabled(settings: dict) -> bool:
    return bool(settings.get("adzuna_app_id") and settings.get("adzuna_app_key"))


def fetch(query: dict, settings: dict) -> list[dict]:
    app_id = settings["adzuna_app_id"]
    app_key = settings["adzuna_app_key"]
    jobs: list[dict] = []
    for page in (1, 2):
        r = get(
            f"https://api.adzuna.com/v1/api/jobs/us/search/{page}",
            params={"app_id": app_id, "app_key": app_key,
                    "what": query.get("title", ""),
                    "where": query.get("location", ""),
                    "results_per_page": 50, "content-type": "application/json"},
        )
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
                "remote_flag": "remote" in (loc.get("display_name") or "").lower(),
                "url": clean(j.get("redirect_url")),
                "description": desc,
                "posted_at": clean(j.get("created")),
                "salary": salary,
                "employment_type": clean(j.get("contract_time") or ""),
            })
        if page * 50 >= (data.get("count") or 0):
            break
    return jobs
