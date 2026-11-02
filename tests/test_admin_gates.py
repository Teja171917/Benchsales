"""Admin-only surfaces: the job pool and the feedback board are
admin-only; feedback POSTING and the Matches city counts stay open to
every signed-in team member. Plus the sources truth: a workspace on
the original 4-source default reads as every source on, and the
status endpoint reports the effective (selected) set."""
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


class AdminGateTests(unittest.TestCase):
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
        accounts.create_user("member@example.com", "Mel Member",
                             "password-1", role="member")
        accounts.create_user("admin@example.com", "Ann Admin",
                             "password-1", role="admin")
        from fastapi.testclient import TestClient
        from app import server
        self.server = server
        self.basic = TestClient(server.app, raise_server_exceptions=False)

        def _session(email):
            r = self.basic.post("/api/auth/login", json={
                "email": email, "password": "password-1"})
            assert r.status_code == 200, r.text
            token = r.headers["set-cookie"].split("bp_session=")[1].split(";")[0]
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

    def test_member_cannot_browse_the_job_pool(self):
        r = self.basic.get("/api/jobs", headers=self.member_h)
        self.assertEqual(r.status_code, 403)
        r = self.basic.post("/api/jobs/import-url", headers=self.member_h,
                             json={"url": "https://x.example/j/1"})
        self.assertEqual(r.status_code, 403)
        # ...but the Matches filter data and matches stay open
        r = self.basic.get("/api/jobs/cities", headers=self.member_h)
        self.assertEqual(r.status_code, 200)
        r = self.basic.get("/api/matches", headers=self.member_h)
        self.assertEqual(r.status_code, 200)
        me = self.basic.get("/api/auth/me", headers=self.member_h).json()
        self.assertFalse(me["is_admin"])

    def test_admin_and_shared_login_can_browse(self):
        # superseded Nov 2: the raw pool became owner-only, so a
        # workspace admin who is not the owner is refused (the
        # jobs-gate suite covers the full matrix)
        self.assertEqual(self.basic.get("/api/jobs", headers=self.admin_h).status_code, 403)
        h = _basic("x", "main-pw")
        self.assertEqual(self.basic.get("/api/jobs", headers=h).status_code,
                         200)
        me = self.basic.get("/api/auth/me", headers=h).json()
        self.assertTrue(me["is_admin"])

    def test_feedback_board_admin_only_posting_open(self):
        r = self.basic.post("/api/feedback", headers=self.member_h, json={
            "text": "Please add salary filters", "category": "feature"})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.basic.get("/api/feedback", headers=self.member_h)
        self.assertEqual(r.status_code, 403)
        fid = self.basic.get("/api/feedback", headers=self.admin_h).json()[0]["id"]
        r = self.basic.post(f"/api/feedback/{fid}/status", headers=self.member_h,
                             json={"status": "done"})
        self.assertEqual(r.status_code, 403)
        r = self.basic.post(f"/api/feedback/{fid}/status", headers=self.admin_h,
                            json={"status": "planned"})
        self.assertEqual(r.status_code, 200)

    def test_old_default_sources_read_as_all_on(self):
        db.set_setting("enabled_sources",
                       json.dumps(["adzuna", "jsearch", "remoteok",
                                   "remotive"]))
        got = json.loads(db.get_settings()["enabled_sources"])
        self.assertEqual(set(got), {"adzuna", "jsearch", "remoteok",
                                    "remotive", "arbeitnow", "dice",
                                    "monster", "smartrecruiters"})
        h = _basic("x", "main-pw")
        status = {x["name"]: x for x in
                  self.basic.get("/api/sources/status", headers=h).json()}
        self.assertTrue(status["smartrecruiters"]["selected"])
        self.assertTrue(status["dice"]["selected"])
        self.assertTrue(status["arbeitnow"]["selected"])
        # a customised list is left exactly as the workspace set it
        db.set_setting("enabled_sources", json.dumps(["adzuna"]))
        got = json.loads(db.get_settings()["enabled_sources"])
        self.assertEqual(got, ["adzuna"])


if __name__ == "__main__":
    unittest.main()
