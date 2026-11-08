"""Jobs list cache (Nov 8 2026): the Jobs table's pool scan is cached
per workspace + parameters and warmed at startup / after collections,
mirroring the match list. While a collection runs, the uncached scan
took ~30s — long enough to read as "not loading"."""
import base64
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, db


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class JobsCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_db, self._old_acc = db.DB_PATH, accounts.ACCOUNTS_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        accounts.ACCOUNTS_PATH = Path(self.tmp.name) / "accounts.db"
        accounts._ready = False
        accounts.init_accounts()
        self._old_env = {k: os.environ.get(k) for k in
                         ("BENCHPILOT_COMPANIES", "BENCHPILOT_PASSWORD")}
        os.environ.pop("BENCHPILOT_COMPANIES", None)
        os.environ["BENCHPILOT_PASSWORD"] = "main-pw"
        from fastapi.testclient import TestClient
        from app import server
        self.server = server
        server._jobs_cache.clear()
        self.client = TestClient(server.app, raise_server_exceptions=False)
        self.main = _basic("boss", "main-pw")
        db.insert_job({"source": "dice", "source_id": "j1",
                       "title": "Java Developer", "company": "Acme",
                       "location": "Houston, TX", "description": "x",
                       "url": ""})

    def tearDown(self):
        self.server._jobs_cache.clear()
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_second_call_served_from_cache_and_warm_rebuilds(self):
        calls = {"n": 0}
        orig = db.list_jobs

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        db.list_jobs = counting
        try:
            r1 = self.client.get("/api/jobs?limit=1000&light=1",
                                 headers=self.main)
            r2 = self.client.get("/api/jobs?limit=1000&light=1",
                                 headers=self.main)
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(len(r1.json()), 1)
            self.assertEqual(r2.json(), r1.json())
            self.assertEqual(calls["n"], 1)   # second call was a cache hit
            # a different parameter set is a different entry
            r3 = self.client.get("/api/jobs?limit=5&light=1",
                                 headers=self.main)
            self.assertEqual(r3.status_code, 200)
            self.assertEqual(calls["n"], 2)
        finally:
            db.list_jobs = orig
        # after a "collection" adds a job, the warm rebuilds the entry
        db.insert_job({"source": "dice", "source_id": "j2",
                       "title": "Data Engineer", "company": "Beta",
                       "location": "Austin, TX", "description": "x",
                       "url": ""})
        self.server._warm_jobs_cache()
        r4 = self.client.get("/api/jobs?limit=1000&light=1",
                             headers=self.main)
        self.assertEqual(len(r4.json()), 2)


if __name__ == "__main__":
    unittest.main()
