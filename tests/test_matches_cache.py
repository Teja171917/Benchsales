"""Matches endpoint + confirmed-cities caching (Nov 4 2026): the full
match list is the heaviest response; rebuilding it under collection /
office contention measured 7-39s in production."""
import tempfile
import unittest
from pathlib import Path

from app import db
from app import server


class MatchesCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        server._matches_cache.clear()
        db._cities_cache.clear()
        c = db.create_consultant({"name": "Cache Tester"})
        jid = db.insert_job({"source": "dice", "source_id": "c1",
                             "title": "Java Developer", "company": "Acme",
                             "location": "Houston, TX",
                             "description": "Java.", "url": ""})
        db.insert_match(c["id"], jid, 90, {}, [])

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_matches_endpoint_serves_second_call_from_cache(self):
        calls = {"n": 0}
        orig = db.list_matches

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        db.list_matches = counting
        try:
            first = server.api_list_matches(0, 0)
            second = server.api_list_matches(0, 0)
        finally:
            db.list_matches = orig
        assert calls["n"] == 1
        assert first == second and len(first) == 1
        assert first[0]["city"] == "Houston"

    def test_confirmed_cities_recomputes_only_when_pool_grows(self):
        assert db.confirmed_cities() == {"Houston"}
        assert db.confirmed_cities() == {"Houston"}   # cached
        db.insert_job({"source": "dice", "source_id": "c2",
                       "title": "Data Engineer", "company": "Beta",
                       "location": "Austin, TX", "description": "x",
                       "url": ""})
        assert db.confirmed_cities() == {"Houston", "Austin"}
