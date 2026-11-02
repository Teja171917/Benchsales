"""Signup routing: a company ID sends the approval to that company's
admin; NO company ID means a personal signup that lands with the main
workspace's admin. Rehearses the owner's own journey: blank signup ->
shared login approves him as Admin -> later blank signups come to
him."""
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


class SignupRoutingTests(unittest.TestCase):
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
        self.client = TestClient(server.app, raise_server_exceptions=False)
        self.main = _basic("boss", "main-pw")

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def _signup(self, email, company_id, name="Person"):
        return self.client.post("/api/auth/signup", json={
            "name": name, "email": email, "password": "password-1",
            "company_id": company_id})

    def _session(self, email):
        r = self.client.post("/api/auth/login", json={
            "email": email, "password": "password-1"})
        assert r.status_code == 200, r.text
        token = r.headers["set-cookie"].split("bp_session=")[1].split(";")[0]
        return {"Cookie": f"bp_session={token}"}

    def test_blank_company_lands_with_main_admin(self):
        r = self._signup("owner@gmail.com", "", name="Owner")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["workspace"], "main")
        # waits for approval
        r = self.client.post("/api/auth/login", json={
            "email": "owner@gmail.com", "password": "password-1"})
        self.assertEqual(r.status_code, 403)
        # the shared main login sees it and makes him Admin
        users = self.client.get("/api/admin/users",
                                headers=self.main).json()["users"]
        owner = [u for u in users if u["email"] == "owner@gmail.com"][0]
        self.assertTrue(owner["pending"])
        r = self.client.post(f"/api/admin/users/{owner['id']}/approve",
                             headers=self.main, json={"role": "admin"})
        self.assertEqual(r.status_code, 200, r.text)
        owner_h = self._session("owner@gmail.com")
        me = self.client.get("/api/auth/me", headers=owner_h).json()
        self.assertTrue(me["is_admin"])
        # the next blank signup comes to HIM (and to the shared login)
        r = self._signup("friend@gmail.com", "   ", name="Friend")
        self.assertEqual(r.status_code, 200, r.text)
        me = self.client.get("/api/auth/me", headers=owner_h).json()
        self.assertEqual(me["pending_approvals"], 1)
        users = self.client.get("/api/admin/users",
                                headers=owner_h).json()["users"]
        friend = [u for u in users
                  if u["email"] == "friend@gmail.com"][0]
        r = self.client.post(f"/api/admin/users/{friend['id']}/approve",
                             headers=owner_h, json={"role": "member"})
        self.assertEqual(r.status_code, 200, r.text)

    def test_company_signup_stays_with_company_admin(self):
        r = self._signup("rec@acme.com", "acme_staffing")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["workspace"], "acme_staffing")
        # the owner-admin of main does not hold acme's approvals: once
        # he exists, his user list shows main only
        accounts.create_user("owner@gmail.com", "Owner", "password-1",
                             role="admin")
        owner_h = self._session("owner@gmail.com")
        users = self.client.get("/api/admin/users",
                                headers=owner_h).json()["users"]
        self.assertNotIn("rec@acme.com", [u["email"] for u in users])
        # acme's own admin login does see it
        users = self.client.get(
            "/api/admin/users",
            headers=_basic("acme", "acme-pw")).json()["users"]
        self.assertIn("rec@acme.com", [u["email"] for u in users])

    def test_bad_company_still_rejected(self):
        r = self._signup("x@gmail.com", "no-such-co")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not recognised", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
