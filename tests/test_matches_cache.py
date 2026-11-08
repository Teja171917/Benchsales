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


class MatchesLimitTests(unittest.TestCase):
    """limit= on /api/matches (Nov 7 2026): the Matches page paints the
    newest 50 first, then loads the rest. The slice must be newest
    postings first (score tiebreak), same row shape, and the full
    list must be untouched."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        server._matches_cache.clear()
        db._cities_cache.clear()
        c = db.create_consultant({"name": "Limit Tester"})
        jobs = [
            ("j-old", "Old Role", "2026-10-01T09:00:00", 95),
            ("j-mid", "Mid Role", "2026-11-03T09:00:00", 70),
            ("j-new", "New Role", "2026-11-06T09:00:00", 80),
        ]
        for sid, title, posted, score in jobs:
            jid = db.insert_job({"source": "dice", "source_id": sid,
                                 "title": title, "company": "Acme",
                                 "location": "Houston, TX",
                                 "description": "x", "url": "",
                                 "posted_at": posted})
            db.insert_match(c["id"], jid, score, {}, [])

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_limit_returns_newest_first(self):
        rows = server.api_list_matches(0, 0, 2)
        self.assertEqual([r["job_title"] for r in rows],
                         ["New Role", "Mid Role"])

    def test_no_limit_returns_everything(self):
        self.assertEqual(len(server.api_list_matches(0, 0)), 3)
        self.assertEqual(len(server.api_list_matches(0, 0, 0)), 3)
        rows = server.api_list_matches(0, 0, 50)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["job_title"], "New Role")


class MatchesWarmTests(unittest.TestCase):
    """Cache warming (Nov 7 2026): _warm_matches_cache builds each
    workspace's list on a background thread at startup and after each
    collection, so the first Matches open is a memory hit. The warm
    must REPLACE a fresh-but-stale entry, not just fill an empty one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        server._matches_cache.clear()
        db._cities_cache.clear()
        self.c = db.create_consultant({"name": "Warm Tester"})
        jid = db.insert_job({"source": "dice", "source_id": "w1",
                             "title": "Java Developer", "company": "Acme",
                             "location": "Houston, TX",
                             "description": "Java.", "url": ""})
        db.insert_match(self.c["id"], jid, 90, {}, [])

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_warm_populates_cache_and_refresh_replaces(self):
        server._warm_matches_cache()
        calls = {"n": 0}
        orig = db.list_matches

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        db.list_matches = counting
        try:
            rows = server.api_list_matches(0, 0)
            self.assertEqual(calls["n"], 0)   # served from the warm cache
            self.assertEqual(len(rows), 1)
            # a collection lands a new match; warming again must
            # replace the entry even though its TTL has not expired
            jid2 = db.insert_job({"source": "dice", "source_id": "w2",
                                  "title": "Data Engineer", "company": "Beta",
                                  "location": "Austin, TX",
                                  "description": "x", "url": ""})
            db.insert_match(self.c["id"], jid2, 85, {}, [])
        finally:
            db.list_matches = orig
        server._warm_matches_cache()
        rows = server.api_list_matches(0, 0)
        self.assertEqual(len(rows), 2)


class MatchesBuildLockTests(unittest.TestCase):
    """Per-key build lock (Nov 7 2026): two callers racing a cold
    cache must share ONE build — before the lock, a click landing
    mid-warm started a duplicate build and both crawled."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        server._matches_cache.clear()
        db._cities_cache.clear()
        c = db.create_consultant({"name": "Lock Tester"})
        jid = db.insert_job({"source": "dice", "source_id": "l1",
                             "title": "Java Developer", "company": "Acme",
                             "location": "Houston, TX",
                             "description": "Java.", "url": ""})
        db.insert_match(c["id"], jid, 90, {}, [])

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_concurrent_callers_share_one_build(self):
        import threading
        import time as _time
        calls = {"n": 0}
        orig = db.list_matches

        def slow_counting(*a, **k):
            calls["n"] += 1
            _time.sleep(0.3)
            return orig(*a, **k)

        db.list_matches = slow_counting
        results = {}
        try:
            def worker(name):
                results[name] = server._matches_rows(0, 0)

            threads = [threading.Thread(target=worker, args=(n,))
                       for n in ("a", "b")]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            db.list_matches = orig
        self.assertEqual(calls["n"], 1)
        self.assertEqual(results["a"], results["b"])
        self.assertEqual(len(results["a"]), 1)
