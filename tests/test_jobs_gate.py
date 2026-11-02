"""The raw job pool (all-USA postings) is owner-only on the front
end: only the owner's account and the legacy main shared login may
list/import/live-search/save pool jobs or kick a manual collection.
Collection keeps running in the backend for every workspace, and
the Matches helpers (cities, counts) stay open to everyone."""
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


class JobsGateTests(unittest.TestCase):
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

    def _session(self, email, password="password-1"):
        r = self.client.post("/api/auth/login", json={
            "email": email, "password": password})
        assert r.status_code == 200, r.text
        token = r.headers["set-cookie"].split("bp_session=")[1].split(";")[0]
        return {"Cookie": f"bp_session={token}"}

    def test_company_login_locked_out_of_the_pool(self):
        for method, path, kwargs in (
                ("GET", "/api/jobs", {}),
                ("POST", "/api/jobs/import-url", {"json": {"url": "https://x.io/j"}}),
                ("POST", "/api/jobs/live-search", {"json": {"title": "Java"}}),
                ("POST", "/api/jobs/save-live", {"json": {"job": {}}}),
                ("POST", "/api/collect", {}),
                ("POST", "/api/collect/kick", {})):
            r = self.client.request(method, path, headers=self.rsa, **kwargs)
            self.assertEqual(r.status_code, 403, f"{method} {path}")
        me = self.client.get("/api/auth/me", headers=self.rsa).json()
        self.assertFalse(me["can_jobs"])

    def test_matches_helpers_stay_open(self):
        r = self.client.get("/api/jobs/cities", headers=self.rsa)
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/jobs/count", headers=self.rsa)
        self.assertEqual(r.status_code, 200)

    def test_main_login_and_owner_keep_the_pool(self):
        r = self.client.get("/api/jobs", headers=self.main)
        self.assertEqual(r.status_code, 200)
        me = self.client.get("/api/auth/me", headers=self.main).json()
        self.assertTrue(me["can_jobs"])
        accounts.create_user("saiteja.ks222@gmail.com", "Teja",
                             "password-1", role="admin")
        h = self._session("saiteja.ks222@gmail.com")
        r = self.client.get("/api/jobs", headers=h)
        self.assertEqual(r.status_code, 200)
        me = self.client.get("/api/auth/me", headers=h).json()
        self.assertTrue(me["can_jobs"])

    def test_company_admin_and_member_locked_out(self):
        accounts.create_user("lead@rsatech.com", "Lead", "password-1",
                             role="admin", company_slug="rsatech")
        accounts.create_user("helper@gmail.com", "Helper", "password-1",
                             role="member")
        for email in ("lead@rsatech.com", "helper@gmail.com"):
            h = self._session(email)
            r = self.client.get("/api/jobs", headers=h)
            self.assertEqual(r.status_code, 403, email)
            me = self.client.get("/api/auth/me", headers=h).json()
            self.assertFalse(me["can_jobs"], email)


if __name__ == "__main__":
    unittest.main()
