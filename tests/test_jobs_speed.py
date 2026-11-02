"""Jobs list speed: the list endpoint can return light rows (no job
descriptions — the bulk of the payload), the table renders from
those, and the full posting is fetched per job for the drawer."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, db


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class JobsSpeedTests(unittest.TestCase):
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
        os.environ["BENCHPILOT_COMPANIES"] = json.dumps(
            {"RSATECH": {"username": "rsatech", "password": "rsa-pw"}})
        os.environ["BENCHPILOT_PASSWORD"] = "main-pw"
        self.jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Java Dev",
            "company": "Co", "location": "Houston, TX", "remote_flag": 0,
            "url": "https://x.io/1",
            "description": "A very long description. " * 200,
            "posted_at": "2026-11-01", "salary": "$50/hr",
            "employment_type": "contract"})
        from fastapi.testclient import TestClient
        from app import server
        self.client = TestClient(server.app, raise_server_exceptions=False)
        self.main = _basic("boss", "main-pw")
        self.rsa = _basic("rsatech", "rsa-pw")

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_light_rows_skip_descriptions(self):
        rows = db.list_jobs(light=True)
        self.assertEqual(len(rows), 1)
        self.assertNotIn("description", rows[0])
        self.assertEqual(rows[0]["title"], "Java Dev")
        self.assertIn("emp_tags", rows[0])
        full = db.list_jobs()
        self.assertIn("description", full[0])

    def test_light_endpoint_and_single_job(self):
        r = self.client.get("/api/jobs?limit=10&light=1", headers=self.main)
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("description", r.json()[0])
        r = self.client.get(f"/api/jobs/{self.jid}", headers=self.main)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["description"].startswith(
            "A very long description."))
        r = self.client.get(f"/api/jobs/{self.jid}", headers=self.rsa)
        self.assertEqual(r.status_code, 403)
        r = self.client.get("/api/jobs/999999", headers=self.main)
        self.assertEqual(r.status_code, 404)

    def test_named_routes_still_win_over_job_id(self):
        # /api/jobs/cities and /api/jobs/count must not be swallowed
        # by the /api/jobs/{jid} route
        r = self.client.get("/api/jobs/cities", headers=self.main)
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/jobs/count", headers=self.main)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 1)


if __name__ == "__main__":
    unittest.main()
