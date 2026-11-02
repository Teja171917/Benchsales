"""Owner's signup policy (Nov 2026): personal accounts are Gmail-only
and approved by the main admin; company accounts must use the company
email domain (@rsatech.com) and are approved by that company's admin;
every other domain is blocked. Plus the privacy rule: the RSATECH
admin must never see the main workspace's (Saiteja) accounts."""
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


class SignupPolicyTests(unittest.TestCase):
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
            {"RSATECH": {"username": "rsatech", "password": "rsa-pw"}})
        os.environ["BENCHPILOT_PASSWORD"] = "main-pw"
        os.environ.pop("BENCHPILOT_USERNAME", None)
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

    def _signup(self, email, company_id, name="Person"):
        return self.client.post("/api/auth/signup", json={
            "name": name, "email": email, "password": "password-1",
            "company_id": company_id})

    def test_gmail_blank_goes_to_main_admin(self):
        r = self._signup("friend@gmail.com", "")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["workspace"], "main")

    def test_gmail_with_company_id_rejected(self):
        r = self._signup("friend@gmail.com", "rsatech")
        self.assertEqual(r.status_code, 400)
        self.assertIn("personal signup", r.json()["detail"])

    def test_rsatech_email_blank_routes_to_rsatech(self):
        r = self._signup("recruiter@rsatech.com", "")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["workspace"], "rsatech")

    def test_rsatech_email_with_company_id(self):
        r = self._signup("recruiter@rsatech.com", "rsatech")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["workspace"], "rsatech")

    def test_rsatech_email_cannot_join_main(self):
        r = self._signup("recruiter@rsatech.com", "main")
        self.assertEqual(r.status_code, 400)
        self.assertIn("company email", r.json()["detail"])

    def test_other_domains_blocked(self):
        for email, cid in (("a@outlook.com", ""), ("a@outlook.com", "rsatech"),
                           ("a@acme.com", ""), ("a@acme.com", "rsatech")):
            r = self._signup(email, cid)
            self.assertEqual(r.status_code, 400, (email, cid, r.text))

    def test_unknown_company_still_rejected_first(self):
        r = self._signup("a@gmail.com", "no-such-co")
        self.assertEqual(r.status_code, 400)
        self.assertIn("not recognised", r.json()["detail"])

    def test_rsatech_admin_cannot_see_main_accounts(self):
        # the owner's own personal admin + a pending personal signup
        accounts.create_user("saiteja.ks222@gmail.com", "Teja",
                             "password-1", role="admin")
        self._signup("pal@gmail.com", "")
        self._signup("recruiter@rsatech.com", "rsatech")
        # RSATECH's shared login: only RSATECH accounts, only its count
        users = self.client.get("/api/admin/users",
                                headers=self.rsa).json()["users"]
        emails = [u["email"] for u in users]
        self.assertEqual(emails, ["recruiter@rsatech.com"])
        me = self.client.get("/api/auth/me", headers=self.rsa).json()
        self.assertEqual(me["pending_approvals"], 1)
        # a personal admin inside RSATECH sees the same walled view
        accounts.create_user("lead@rsatech.com", "Lead", "password-1",
                             role="admin", company_slug="rsatech")
        r = self.client.post("/api/auth/login", json={
            "email": "lead@rsatech.com", "password": "password-1"})
        self.assertEqual(r.status_code, 200, r.text)
        token = r.headers["set-cookie"].split("bp_session=")[1].split(";")[0]
        users = self.client.get(
            "/api/admin/users",
            headers={"Cookie": f"bp_session={token}"}).json()["users"]
        self.assertNotIn("saiteja.ks222@gmail.com",
                         [u["email"] for u in users])
        self.assertNotIn("pal@gmail.com", [u["email"] for u in users])
        # and the main side never sees RSATECH's people either
        users = self.client.get("/api/admin/users",
                                headers=self.main).json()["users"]
        self.assertIn("pal@gmail.com", [u["email"] for u in users])


class GzipTests(unittest.TestCase):
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

    def test_large_responses_are_gzipped(self):
        r = self.client.get("/", headers={**self.main,
                                          "Accept-Encoding": "gzip"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("content-encoding"), "gzip")


if __name__ == "__main__":
    unittest.main()
