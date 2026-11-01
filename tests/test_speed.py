"""Speed release: versioned asset caching, plus the matches summary
endpoint that lets the overview and badges read counts/top matches from
the precomputed matches table instead of shipping every row."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, db  # noqa: E402


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class MatchesSummaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io"})
        self.cid = c["id"]
        for n, score in ((1, 55.0), (2, 91.5), (3, 72.25)):
            jid = db.insert_job({
                "source": "t", "source_id": f"s{n}", "title": f"Java Dev {n}",
                "company": f"Co{n}", "location": "Houston, TX",
                "remote_flag": 0, "url": "", "description": "Java",
                "posted_at": "", "salary": "", "employment_type": ""})
            with db.get_conn() as conn:
                conn.execute(
                    'INSERT INTO "matches"(consultant_id, job_id, score, '
                    'score_breakdown_json, missing_skills_json, created_at) '
                    "VALUES (?, ?, ?, '{}', '[]', '2026-11-01T00:00:00Z')",
                    (self.cid, jid, score))

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_summary_counts_and_orders_top(self):
        out = db.matches_summary()
        self.assertEqual(out["total"], 3)
        self.assertEqual([r["score"] for r in out["top"]], [91.5, 72.25, 55.0])
        top = out["top"][0]
        self.assertEqual(top["job_title"], "Java Dev 2")
        self.assertEqual(top["consultant_name"], "Pat Dev")
        self.assertEqual(top["score_breakdown"], {})

    def test_summary_is_small(self):
        # the whole point: the payload stays tiny regardless of row size
        out = db.matches_summary(top_n=2)
        self.assertEqual(len(out["top"]), 2)
        self.assertLess(len(json.dumps(out)), 2000)


class AssetCachingHttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_db, self._old_acc = db.DB_PATH, accounts.ACCOUNTS_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        accounts.ACCOUNTS_PATH = Path(self.tmp.name) / "accounts.db"
        accounts._ready = False
        accounts.init_accounts()
        self._old_env = {k: os.environ.get(k) for k in
                         ("BENCHPILOT_COMPANIES", "BENCHPILOT_PASSWORD",
                          "BENCHPILOT_USERNAME")}
        os.environ["BENCHPILOT_COMPANIES"] = json.dumps(
            {"Acme Staffing": {"username": "acme", "password": "acme-pw"}})
        os.environ["BENCHPILOT_PASSWORD"] = "main-pw"
        os.environ.pop("BENCHPILOT_USERNAME", None)
        from fastapi.testclient import TestClient
        from app import server
        self.server = server
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_index_references_versioned_assets(self):
        r = self.client.get("/", headers=_basic("x", "main-pw"))
        self.assertEqual(r.status_code, 200)
        v = self.server.ASSET_VERSION
        self.assertIn(f'app.js?v={v}', r.text)
        self.assertIn(f'styles.css?v={v}', r.text)
        self.assertEqual(r.headers["cache-control"], "no-cache")

    def test_versioned_asset_is_immutable_unversioned_is_not(self):
        v = self.server.ASSET_VERSION
        r = self.client.get(f"/app.js?v={v}", headers=_basic("x", "main-pw"))
        self.assertEqual(r.status_code, 200)
        self.assertIn("immutable", r.headers["cache-control"])
        r = self.client.get("/app.js", headers=_basic("x", "main-pw"))
        self.assertEqual(r.headers["cache-control"], "no-cache")
        r = self.client.get("/app.js?v=stale", headers=_basic("x", "main-pw"))
        self.assertEqual(r.headers["cache-control"], "no-cache")

    def test_matches_summary_endpoint(self):
        r = self.client.get("/api/matches/summary",
                            headers=_basic("x", "main-pw"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["total"], 0)
        self.assertEqual(body["top"], [])


if __name__ == "__main__":
    unittest.main()
