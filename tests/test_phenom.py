"""Phenom staffing-firms adapter + US-only source wiring (Nov 4 2026).

The owner asked for US-based sources only (RemoteOK / Remotive /
Arbeitnow unwired) and for more of the staffing watchlist to actually
feed jobs: the Phenom cohort (TEKsystems, Aerotek, ...) gets an adapter
that reads the job array Phenom server-renders into its search pages.
"""
import json

import pytest

from app.sources import phenom


FIRMS = [
    {"company": "TEKsystems", "careers_url": "https://careers.teksystems.com/us/en",
     "ats": "Phenom", "identifier": "", "verified": True, "notes": ""},
    {"company": "Acme Staffing", "careers_url": "https://careers.acme.example/us/en/search-results",
     "ats": "phenom", "identifier": "", "verified": True, "notes": ""},
]


def _page(jobs):
    return ('<html><script>phApp.ddo = {"searchResults": {"jobs": '
            + json.dumps(jobs) + '}}</script></html>')


def _raw(**kw):
    base = {
        "reqId": "JP-001", "jobId": "JP-001", "jobSeqNo": "TESYUSJP001ENUS",
        "title": "Java Developer", "country": "USA",
        "city": "Austin", "state": "Texas",
        "cityStateCountry": "Austin, Texas, USA",
        "multi_location": ["Austin,TX,73301,USA"],
        "descriptionTeaser": "Build Java services.",
        "ml_skills": ["java", "spring"],
        "type": "Contractor", "postedDate": "2026-11-03T10:00:00.000+0000",
    }
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _reset_state():
    phenom._STATE.clear()
    yield
    phenom._STATE.clear()


def test_search_base_shapes():
    assert phenom._search_base(FIRMS[0]) == \
        "https://careers.teksystems.com/us/en/search-results"
    assert phenom._search_base(FIRMS[1]) == \
        "https://careers.acme.example/us/en/search-results"
    bare = {"company": "X", "careers_url": "https://careers.x.example"}
    assert phenom._search_base(bare) == \
        "https://careers.x.example/search-results"


def test_extract_jobs_and_missing():
    assert phenom._extract_jobs(_page([_raw()]))[0]["reqId"] == "JP-001"
    assert phenom._extract_jobs("<html>no data</html>") == []
    assert phenom._extract_jobs("") == []


def test_normalize_us_only_and_fields():
    job = phenom._normalize(FIRMS[0], _raw())
    assert job["source"] == "phenom"
    assert job["source_id"] == "teksystems:JP-001"
    assert job["company"] == "TEKsystems"
    assert job["location"] == "Austin, Texas, USA"
    assert job["employment_type"] == "Contractor"
    assert job["url"] == \
        "https://careers.teksystems.com/us/en/job/TESYUSJP001ENUS"
    assert "java" in job["description"]
    assert phenom._normalize(FIRMS[0], _raw(country="India")) is None
    assert phenom._normalize(FIRMS[0], _raw(reqId="", jobId="")) is None
    assert phenom._normalize(FIRMS[0], _raw(title="")) is None


def test_fetch_filters_by_title_and_caps_pages(monkeypatch):
    calls = []

    def fake_get_text(url, ttl=900, timeout=30):
        calls.append(url)
        if "teksystems" in url:
            return _page([_raw(),
                          _raw(reqId="JP-002", jobSeqNo="TESYUSJP002ENUS",
                               title="Accountant")])
        return _page([_raw(reqId="AC-1", jobSeqNo="ACMEAC1ENUS",
                           title="Java Architect",
                           cityStateCountry="Dallas, Texas, USA")])

    monkeypatch.setattr(phenom, "phenom_firms", lambda: FIRMS)
    monkeypatch.setattr(phenom, "get_text_cached", fake_get_text)

    jobs = phenom.fetch({"title": "Java Developer"}, {})
    titles = {(j["company"], j["title"]) for j in jobs}
    assert ("TEKsystems", "Java Developer") in titles
    assert ("Acme Staffing", "Java Architect") in titles
    # the shared any-token rule (same as SmartRecruiters) keeps titles
    # sharing a query token; a title with no shared token is excluded
    assert ("TEKsystems", "Accountant") not in titles
    assert len(calls) == 2                     # one page per firm
    phenom.fetch({"title": "Data Engineer"}, {})
    phenom.fetch({"title": "DevOps Engineer"}, {})
    assert len(calls) == 6                     # pages 2 and 3 per firm
    phenom.fetch({"title": "QA Engineer"}, {})
    assert len(calls) == 6                     # cap reached: union only


def test_enabled_uses_staffing_switch():
    assert phenom.enabled({}) is True
    assert phenom.enabled({"staffing_enabled": "0"}) is False


def test_us_only_wiring():
    import collector
    from app import db, server
    names = [m.NAME for m in collector.SOURCES]
    assert names == ["adzuna", "jsearch", "dice", "monster",
                     "smartrecruiters", "phenom"]
    assert [m.NAME for m in server.SOURCES] == names
    assert [m.NAME for m in server.LIVE_SOURCES] == \
        ["adzuna", "jsearch", "dice", "smartrecruiters"]
    assert set(db.DEFAULT_ENABLED_SOURCES) == \
        {"adzuna", "jsearch", "dice", "monster", "smartrecruiters"}
    for gone in ("remoteok", "remotive", "arbeitnow"):
        assert gone not in names
