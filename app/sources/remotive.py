"""Remotive adapter. No key needed. Remote jobs."""
from .common import get, clean, strip_html

NAME = "remotive"
LABEL = "Remotive (no key)"


def enabled(settings: dict) -> bool:
    return True


def fetch(query: dict, settings: dict) -> list[dict]:
    r = get("https://remotive.com/api/remote-jobs",
            params={"search": query.get("title", ""), "limit": 50})
    r.raise_for_status()
    jobs: list[dict] = []
    for j in r.json().get("jobs", []):
        salary = ""
        if j.get("salary"):
            salary = clean(j["salary"])
        jobs.append({
            "source": NAME,
            "source_id": str(j.get("id", "")),
            "title": clean(j.get("title")),
            "company": clean(j.get("company_name")),
            "location": clean(j.get("candidate_required_location") or "Remote"),
            "remote_flag": True,
            "url": clean(j.get("url")),
            "description": strip_html(clean(j.get("description"))),
            "posted_at": clean(j.get("publication_date")),
            "salary": salary,
            "employment_type": clean(j.get("job_type") or ""),
        })
    return jobs
