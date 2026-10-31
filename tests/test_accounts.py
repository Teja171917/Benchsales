"""Individual account tests: hashing, sessions, workspace routing and
the admin authorization rules (stdlib unittest; TestClient for the HTTP
layer, no network).

Run from the project root:   python -m unittest discover -s tests -v
"""
import base64
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import accounts, db  # noqa: E402


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_db, self._old_acc = db.DB_PATH, accounts.ACCOUNTS_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
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

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_password_hash_roundtrip(self):
        h = accounts.hash_password("correct horse")
        self.assertTrue(accounts.verify_password("correct horse", h))
        self.assertFalse(accounts.verify_password("wrong horse", h))
        self.assertFalse(accounts.verify_password("correct horse", "junk"))

    def test_create_and_authenticate(self):
        u = accounts.create_user("Admin@Example.com", "Ann Admin",
                                 "password-1", role="admin")
        self.assertEqual(u["email"], "admin@example.com")
        self.assertIsNotNone(accounts.authenticate("admin@example.com",
                                                   "password-1"))
        self.assertIsNone(accounts.authenticate("admin@example.com", "nope"))
        self.assertIsNone(accounts.authenticate("ghost@example.com", "x"))
        with self.assertRaises(ValueError):
            accounts.create_user("admin@example.com", "Dup", "password-2")
        with self.assertRaises(ValueError):
            accounts.create_user("not-an-email", "Bad", "password-2")
        with self.assertRaises(ValueError):
            accounts.create_user("ok@example.com", "Short", "short")

    def test_company_user_routes_to_company_db(self):
        u = accounts.create_user("rec@acme.com", "Rec Ruiter", "password-1",
                                 company_slug="acme_staffing")
        target = accounts.target_path_for(u)
        self.assertEqual(Path(target).name, "company_acme_staffing.db")
        main_user = accounts.create_user("boss@example.com", "Boss",
                                         "password-1", role="admin")
        self.assertIsNone(accounts.target_path_for(main_user))

    def test_session_lifecycle(self):
        u = accounts.create_user("sam@example.com", "Sam", "password-1")
        token = accounts.create_session(u["id"])
        who = accounts.resolve_session(token)
        self.assertEqual(who["email"], "sam@example.com")
        accounts.delete_session(token)
        self.assertIsNone(accounts.resolve_session(token))
        # expired sessions resolve to None
        token = accounts.create_session(u["id"])
        import sqlite3
        with sqlite3.connect(accounts.ACCOUNTS_PATH) as conn:
            conn.execute("UPDATE sessions SET expires_at = ?",
                         (time.time() - 1,))
        self.assertIsNone(accounts.resolve_session(token))

    def test_deactivation_blocks_login_and_sessions(self):
        u = accounts.create_user("pat@example.com", "Pat", "password-1")
        token = accounts.create_session(u["id"])
        accounts.set_active(u["id"], False)
        self.assertIsNone(accounts.authenticate("pat@example.com",
                                                "password-1"))
        self.assertIsNone(accounts.resolve_session(token))

    def test_password_reset_kills_sessions(self):
        u = accounts.create_user("kim@example.com", "Kim", "password-1")
        token = accounts.create_session(u["id"])
        accounts.set_password(u["id"], "password-2")
        self.assertIsNone(accounts.resolve_session(token))
        self.assertIsNotNone(accounts.authenticate("kim@example.com",
                                                   "password-2"))


class AccountHttpTests(unittest.TestCase):
    """The HTTP layer: login page, session login, admin rules, and the
    legacy Basic fallback staying alive during migration."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_db, self._old_acc = db.DB_PATH, accounts.ACCOUNTS_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
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

    @staticmethod
    def _basic(user, pw):
        return {"Authorization": "Basic " + base64.b64encode(
            f"{user}:{pw}".encode()).decode()}

    def test_gate_redirects_pages_and_401s_api(self):
        r = self.client.get("/", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.headers["location"], "/login")
        r = self.client.get("/api/settings")
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)

    def test_basic_fallback_still_works(self):
        r = self.client.get("/api/auth/me", headers=self._basic("x", "main-pw"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["basic_workspace"], "main")

    def test_admin_bootstrap_and_session_login(self):
        # the legacy company login creates its workspace's first admin
        r = self.client.post("/api/admin/users", headers=self._basic("acme", "acme-pw"),
                             json={"email": "lead@acme.com", "name": "Lead",
                                   "password": "password-1", "role": "admin",
                                   "workspace": "acme_staffing"})
        self.assertEqual(r.status_code, 200, r.text)
        # ...but cannot create users for the main workspace
        r = self.client.post("/api/admin/users", headers=self._basic("acme", "acme-pw"),
                             json={"email": "sneak@example.com", "name": "S",
                                   "password": "password-1", "role": "admin",
                                   "workspace": "main"})
        self.assertEqual(r.status_code, 403)
        # the new admin signs in with email + password and gets a session
        r = self.client.post("/api/auth/login",
                             json={"email": "lead@acme.com",
                                   "password": "password-1"})
        self.assertEqual(r.status_code, 200, r.text)
        cookie = r.headers.get("set-cookie", "")
        self.assertIn("bp_session=", cookie)
        token = cookie.split("bp_session=")[1].split(";")[0]
        r = self.client.get("/api/auth/me",
                            headers={"Cookie": f"bp_session={token}"})
        self.assertEqual(r.json()["user"]["email"], "lead@acme.com")
        self.assertEqual(r.json()["user"]["workspace"], "acme_staffing")
        # a member of that workspace cannot use the admin endpoints
        accounts.create_user("mem@acme.com", "Mem", "password-1",
                             company_slug="acme_staffing")
        r = self.client.post("/api/auth/login",
                             json={"email": "mem@acme.com",
                                   "password": "password-1"})
        token = r.headers["set-cookie"].split("bp_session=")[1].split(";")[0]
        r = self.client.get("/api/admin/users",
                            headers={"Cookie": f"bp_session={token}"})
        self.assertEqual(r.status_code, 403)
        # wrong password is refused
        r = self.client.post("/api/auth/login",
                             json={"email": "lead@acme.com",
                                   "password": "wrong-password"})
        self.assertEqual(r.status_code, 401)

    def test_login_page_is_one_unified_form(self):
        r = self.client.get("/login")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Email or company username", r.text)
        self.assertIn("/api/auth/basic-login", r.text)
        self.assertIn("/api/auth/login", r.text)
        self.assertEqual(r.headers.get("cache-control"), "no-store")

    def test_shared_login_cookie_flow_for_browsers(self):
        # the shared company login signs in through the form endpoint...
        r = self.client.post("/api/auth/basic-login",
                             json={"username": "acme", "password": "acme-pw"})
        self.assertEqual(r.status_code, 200, r.text)
        cookie = r.headers.get("set-cookie", "")
        self.assertIn("bp_basic=", cookie)
        token = cookie.split("bp_basic=")[1].split(";")[0]
        # ...and its cookie opens pages and APIs in a browser (no popup)
        r = self.client.get("/", headers={"Cookie": f"bp_basic={token}"})
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/auth/me",
                            headers={"Cookie": f"bp_basic={token}"})
        self.assertEqual(r.json()["basic_workspace"], "acme_staffing")
        # ...including the Team page bootstrap for that workspace
        r = self.client.post("/api/admin/users",
                             headers={"Cookie": f"bp_basic={token}"},
                             json={"email": "first@acme.com", "name": "First",
                                   "password": "password-1", "role": "admin",
                                   "workspace": "acme_staffing"})
        self.assertEqual(r.status_code, 200, r.text)
        # bad shared-login password and a tampered cookie are both refused
        r = self.client.post("/api/auth/basic-login",
                             json={"username": "acme", "password": "nope"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/auth/me",
                            headers={"Cookie": "bp_basic=AAAA.deadbeef"})
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
