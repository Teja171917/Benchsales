"""Current-market skill demand, computed from the app's own job data.

"Market" here means what employers are actually asking for right now: we
count skill mentions across job descriptions collected in the last N days
and rank them. No external API, no guessing - the demand list is derived
from postings the app has already pulled.
"""
from collections import Counter
from datetime import datetime, timedelta, timezone

from . import db
from .skills import extract_skills


def demand(days: int = 30, limit: int = 50) -> list[dict]:
    """Top in-demand skills across jobs first seen in the last `days` days.

    Returns [{"skill": str, "jobs": int}] sorted by posting count, desc.
    """
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
