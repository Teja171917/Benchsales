"""RemoteOK adapter. No key needed. Remote tech jobs."""
from .common import get_json_cached, clean, strip_html

NAME = "remoteok"
LABEL = "RemoteOK (no key)"


def enabled(settings: dict) -> bool:
    return True


def fetch(query: dict, settings: dict) -> list[dict]:
    data = get_json_cached("https://remoteok.com/api")
    if isinstance(data, dict):  # API sometimes wraps in {"jobs": [...]}
        data = data.get("jobs", [])
    want = (query.get("title") or "").lower().split()
    jobs: list[dict] = []
    for j in data:
        if not isinstance(j, dict) or not j.get("slug"):
            continue
        title = clean(j.get("position"))
        hay = (title + " " + " ".join(j.get("tags") or [])).lower()
        if want and not any(w in hay for w in want):
            continue
        jobs.append({
            "source": NAME,
            "source_id": clean(j.get("slug") or j.get("id")),
            "title": title,
            "company": clean(j.get("company")),
            "location": clean(j.get("location") or "Remote"),
            "remote_flag": True,
            "url": clean(j.get("url")),
            "description": strip_html(j.get("description") or ""),
            "posted_at": clean(j.get("date")),
            "salary": "",
            "employment_type": "",
        })
    return jobs
