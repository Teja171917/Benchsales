"""Arbeitnow adapter (bonus, no key). EU-leaning job board.
Off by default for a US bench-sales team; toggle in Settings."""
from .common import get_json_cached, clean

NAME = "arbeitnow"
LABEL = "Arbeitnow (no key, EU-leaning)"


def enabled(settings: dict) -> bool:
    return True


def fetch(query: dict, settings: dict) -> list[dict]:
    payload = get_json_cached("https://www.arbeitnow.com/api/job-board-api")
    want = (query.get("title") or "").lower().split()
    jobs: list[dict] = []
    for j in payload.get("data", []):
        title = clean(j.get("title"))
        if want and not any(w in title.lower() for w in want):
            continue
        jobs.append({
            "source": NAME,
            "source_id": clean(j.get("slug")),
            "title": title,
            "company": clean(j.get("company_name")),
            "location": clean(j.get("location") or "Remote"),
            "remote_flag": bool(j.get("remote")),
            "url": clean(j.get("url")),
            "description": clean(j.get("description")),
            "posted_at": clean(j.get("created_at")),
            "salary": "",
            "employment_type": ", ".join(j.get("job_types") or []),
        })
    return jobs
