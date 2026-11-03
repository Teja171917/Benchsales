"""Source adapters must survive odd field types from live feeds."""

from app.sources import arbeitnow
from app.sources.common import clean


def test_clean_coerces_numbers():
    assert clean(1699999999) == "1699999999"
    assert clean(None) == ""
    assert clean("  x ") == "x"


def test_arbeitnow_unix_created_at(monkeypatch):
    import app.sources.arbeitnow as ab
    monkeypatch.setattr(ab, "get_json_cached", lambda url: {"data": [{
        "slug": "dev-1", "title": ".NET Developer", "company_name": "Acme",
        "location": "Remote", "remote": True, "url": "https://x.example/1",
        "description": "Build .NET services", "created_at": 1762000000,
        "job_types": ["full-time"],
    }]})
    jobs = ab.fetch({"title": ".NET Developer"}, {})
    assert len(jobs) == 1
    assert jobs[0]["posted_at"].startswith("2025-")   # ISO, not the raw int
    assert jobs[0]["source"] == "arbeitnow"
