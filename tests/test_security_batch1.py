"""Security batch 1 (Nov 7 2026) regression tests.

From the Nov 7 security audit:
- D-1: the middleware Authorization: Basic door had NO rate limiting
  while the login endpoints did — the shared workspace passwords were
  brute-forceable straight at the API. Now the same 10-fails/10-min
  limiter guards that branch.
- D-2: office/autopilot, office/run, matches unquarantine,
  learned-skills DELETE, backup status/now and resume-import
  status/run skipped the role checks their siblings have — any member
  could call them. Now _require_admin guards each.
- Malformed JSON to the auth endpoints used to 500; now a clean 400.
"""
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


class SecurityBatch1Tests(unittest.TestCase):
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
        # dedicated usernames per concern so the in-memory limiter's
        # buckets never collide with other test files
        os.environ["BENCHPILOT_COMPANIES"] = json.dumps({
            "Acme Staffing": {"username": "acme", "password": "acme-pw"},
            "Globex": {"username": "globex", "password": "globex-pw"},
            "Umbrella": {"username": "umbrella", "password": "umbrella-pw"},
        })
        os.environ["BENCHPILOT_PASSWORD"] = "main-pw"
        os.environ.pop("BENCHPILOT_USERNAME", None)
        accounts.create_user("member@example.com", "Mel Member",
                             "password-1", role="member")
        accounts.create_user("admin@example.com", "Ann Admin",
                             "password-1", role="admin")
        from fastapi.testclient import TestClient
        from app import server
        self.client = TestClient(server.app, raise_server_exceptions=False)

        def _session(email):
            r = self.client.post("/api/auth/login", json={
                "email": email, "password": "password-1"})
            assert r.status_code == 200, r.text
            token = r.cookies.get("bp_session")
            return {"Cookie": f"bp_session={token}"}

        self.member_h = _session("member@example.com")
        self.admin_h = _session("admin@example.com")

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    # ---- D-1: Basic-header door is rate limited ----

    def test_basic_door_locks_after_ten_failures(self):
        for i in range(10):
            r = self.client.get("/api/jobs/count",
                                headers=_basic("umbrella", "wrong"))
            self.assertEqual(r.status_code, 401, f"attempt {i + 1}")
        r = self.client.get("/api/jobs/count",
                            headers=_basic("umbrella", "wrong"))
        self.assertEqual(r.status_code, 429)
        # even the CORRECT password is refused while limited
        r = self.client.get("/api/jobs/count",
                            headers=_basic("umbrella", "umbrella-pw"))
        self.assertEqual(r.status_code, 429)

    def test_basic_door_still_works_below_the_limit(self):
        for _ in range(3):
            r = self.client.get("/api/jobs/count",
                                headers=_basic("globex", "wrong"))
            self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/jobs/count",
                            headers=_basic("globex", "globex-pw"))
        self.assertEqual(r.status_code, 200)

    # ---- D-2: admin role checks ----

    def test_member_gets_403_on_admin_surfaces(self):
        checks = [
            ("post", "/api/office/run", None),
            ("post", "/api/office/autopilot", {"enabled": False}),
            ("post", "/api/matches/1/unquarantine", None),
            ("delete", "/api/learned-skills/python", None),
            ("get", "/api/backup/status", None),
            ("post", "/api/backup/now", None),
            ("get", "/api/resume-import/status", None),
            ("post", "/api/resume-import/run", None),
        ]
        for method, path, payload in checks:
            fn = getattr(self.client, method)
            kwargs = {"headers": self.member_h}
            if payload is not None:
                kwargs["json"] = payload
            r = fn(path, **kwargs)
            self.assertEqual(r.status_code, 403, f"{method} {path}")

    def test_admin_passes_the_new_checks(self):
        r = self.client.post("/api/office/autopilot",
                             headers=self.admin_h, json={"enabled": True})
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/backup/status", headers=self.admin_h)
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/resume-import/status",
                            headers=self.admin_h)
        self.assertEqual(r.status_code, 200)

    def test_shared_company_login_keeps_admin_surfaces(self):
        # the legacy shared login is the workspace's bootstrap admin
        # authority — role checks must not lock it out
        r = self.client.get("/api/backup/status",
                            headers=_basic("acme", "acme-pw"))
        self.assertEqual(r.status_code, 200)

    # ---- malformed JSON: 400, never 500 ----

    def test_malformed_json_is_400_on_auth_endpoints(self):
        for path in ("/api/auth/basic-login", "/api/auth/login",
                     "/api/auth/signup"):
            r = self.client.post(
                path, content="{bad json",
                headers={"Content-Type": "application/json"})
            self.assertEqual(r.status_code, 400, path)


if __name__ == "__main__":
    unittest.main()
