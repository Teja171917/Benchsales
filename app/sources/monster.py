"""Monster jobs through Apify (paid per job, but Apify's free plan includes a
monthly credit that covers a few thousand jobs).

Monster has no public API. Apify's "Monster Job Scraper"
(blackfalcondata/monster-scraper) reads Monster's US job search and returns
JSON. It takes a minute or two per search, so Monster is used only by the
automatic job collection (not the instant live search), and only every
`monster_every_hours` hours (default 12), at most `monster_max_per_search`
jobs per title (default 30).

Needs an Apify API token: Replit Secret APIFY_TOKEN.
"""
from datetime import datetime, timedelta, timezone

import requests

from .common import clean

NAME = "monster"
LABEL = "Monster (via Apify)"
ACTOR = "blackfalcondata~monster-scraper"
API = "https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
REMOTE_WORDS = {"remote", "anywhere", "worldwide", "usa", "us", "united states",
                "work from home", "wfh"}


def enabled(settings: dict) -> bool:
    return bool((settings.get("apify_token") or "").strip())


def _int(settings: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(float(settings.get(key) or default))))
    except ValueError:
        return default


def every_hours(settings: dict) -> int:
    return _int(settings, "monster_every_hours", 12, 1, 168)


def due(settings: dict, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    last = settings.get("monster_last_run_at") or ""
    try:
        d = datetime.fromisoformat(last.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return now >= d + timedelta(hours=every_hours(settings))


def build_input(query: dict, settings: dict) -> dict:
    loc = (query.get("location") or "").strip()
    body = {"query": (query.get("title") or "").strip(),
            "country": "US",
            "maxResults": _int(settings, "monster_max_per_search", 30, 5, 200)}
    if loc.lower() in REMOTE_WORDS:
        if loc.lower() == "remote":
            body["location"] = "Remote"
    elif loc:
        body["location"] = loc
    return body


def to_job(d: dict) -> dict | None:
    if not isinstance(d, dict):
        return None
    title = clean(d.get("title"))
    url = clean(d.get("url") or d.get("applyUrl"))
    if not title or not url:
        return None
    loc = clean(d.get("location")) or ", ".join(
        x for x in (clean(d.get("city")), clean(d.get("state"))) if x)
    smin, smax = d.get("salaryMin"), d.get("salaryMax")
    salary = clean(d.get("salaryText")) or (
        f"${smin or '?'} - ${smax or '?'}" if (smin or smax) else "")
    return {
        "source": NAME,
        "source_id": clean(str(d.get("jobId") or url)),
        "title": title,
        "company": clean(d.get("company")),
        "location": loc or ("Remote" if d.get("isRemote") else ""),
        "remote_flag": bool(d.get("isRemote")) or "remote" in loc.lower(),
        "url": url,
        "description": clean(d.get("description") or d.get("descriptionMarkdown")),
        "posted_at": clean(d.get("postedDate")),
        "salary": salary,
        "employment_type": clean(d.get("employmentType")),
    }


def fetch(query: dict, settings: dict) -> list[dict]:
    """One Apify run for one search title (takes about 1-2 minutes)."""
    r = requests.post(API.format(actor=(settings.get("apify_monster_actor") or ACTOR)
                                 .strip().replace("/", "~")),
                      params={"token": settings["apify_token"].strip()},
                      json=build_input(query, settings), timeout=300)
    r.raise_for_status()
    data = r.json()
    jobs, seen = [], set()
    for d in data if isinstance(data, list) else []:
        j = to_job(d)
        if j and j["source_id"] not in seen:
            seen.add(j["source_id"])
            jobs.append(j)
    return jobs
