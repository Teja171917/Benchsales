"""Settings are owner-only: only the owner's own account
(Saiteja.ks222@gmail.com) and the legacy main shared login may read
or change them. Company logins, company admins, and ordinary members
— in every workspace — get 403 and never see the tab."""
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


class SettingsGateTests(unittest.TestCase):
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

    def test_company_shared_login_is_locked_out(self):
        r = self.client.get("/api/settings", headers=self.rsa)
        self.assertEqual(r.status_code, 403)
        r = self.client.put("/api/settings", headers=self.rsa,
                            json={"match_threshold": "50"})
        self.assertEqual(r.status_code, 403)
        me = self.client.get("/api/auth/me", headers=self.rsa).json()
        self.assertFalse(me["can_settings"])

    def test_main_shared_login_keeps_access(self):
        r = self.client.get("/api/settings", headers=self.main)
        self.assertEqual(r.status_code, 200)
        me = self.client.get("/api/auth/me", headers=self.main).json()
        self.assertTrue(me["can_settings"])

    def test_owner_account_has_access_from_any_role(self):
        accounts.create_user("saiteja.ks222@gmail.com", "Teja",
                             "password-1", role="admin")
        h = self._session("saiteja.ks222@gmail.com")
        r = self.client.get("/api/settings", headers=h)
        self.assertEqual(r.status_code, 200)
        me = self.client.get("/api/auth/me", headers=h).json()
        self.assertTrue(me["can_settings"])

    def test_company_admin_and_main_member_are_locked_out(self):
        accounts.create_user("lead@rsatech.com", "Lead", "password-1",
                             role="admin", company_slug="rsatech")
        accounts.create_user("helper@gmail.com", "Helper", "password-1",
                             role="member")
        for email in ("lead@rsatech.com", "helper@gmail.com"):
            h = self._session(email)
            r = self.client.get("/api/settings", headers=h)
            self.assertEqual(r.status_code, 403, email)
            me = self.client.get("/api/auth/me", headers=h).json()
            self.assertFalse(me["can_settings"], email)


if __name__ == "__main__":
    unittest.main()
