"""Current-market skill demand, computed from the app's own job data.

"Market" here means what employers are actually asking for right now: we
count skill mentions across job descriptions collected in the last N days
and rank them. No external API, no guessing - the demand list is derived
from postings the app has already pulled.
"""
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import db
from .skills import extract_skills

# demand() scans every recent job description — on a few thousand jobs
# that takes seconds, and tailor/consultant views ask for it on every
# click. Cache it per workspace DB for a few minutes; market demand
# does not change minute to minute.
_DEMAND_TTL = 600
_demand_cache: dict = {}


def _demand_cached(days: int, limit: int) -> list[dict]:
    key = (str(db.current_path()), days, limit)
    hit = _demand_cache.get(key)
    if hit and time.time() - hit[0] < _DEMAND_TTL:
        return hit[1]
    out = _demand_compute(days, limit)
    _demand_cache[key] = (time.time(), out)
    return out


def demand(days: int = 30, limit: int = 50) -> list[dict]:
    """Top in-demand skills across jobs first seen in the last `days`
    days (cached per workspace for a few minutes — see _demand_cached).

    Returns [{"skill": str, "jobs": int}] sorted by posting count, desc.
    """
    return _demand_cached(days, limit)


def _demand_compute(days: int = 30, limit: int = 50) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    counter: Counter[str] = Counter()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT description FROM jobs WHERE fetched_at >= ? AND description != ''",
            (since,),
        ).fetchall()
    for (desc,) in rows:
        if desc:
            counter.update(set(extract_skills(desc)))
    return [{"skill": s, "jobs": n} for s, n in counter.most_common(limit)]


def demand_map(days: int = 30, limit: int = 50) -> dict[str, int]:
    """skill -> number of recent postings mentioning it."""
    return {d["skill"]: d["jobs"] for d in demand(days, limit)}
