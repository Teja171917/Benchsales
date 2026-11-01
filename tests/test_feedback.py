"""Feedback board: team members leave points (feature / problem / idea)
in their own workspace; the list and status flow over HTTP."""
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


class FeedbackDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_create_list_status_roundtrip(self):
        f = db.create_feedback("sam@acme.com", "feature",
                               "Filter matches by salary range")
        self.assertEqual(f["status"], "new")
        self.assertEqual(f["category"], "feature")
        items = db.list_feedback()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["text"], "Filter matches by salary range")
        self.assertTrue(db.set_feedback_status(f["id"], "done"))
        self.assertEqual(db.list_feedback()[0]["status"], "done")
        self.assertFalse(db.set_feedback_status(9999, "done"))


class FeedbackHttpTests(unittest.TestCase):
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

    def tearDown(self):
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_feedback_flow(self):
        h = _basic("acme", "acme-pw")
        r = self.client.post("/api/feedback", headers=h, json={
            "text": "Matches page should remember my filters",
            "category": "nonsense", "name": "Sam"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["category"], "idea")   # coerced
        self.assertEqual(r.json()["author"], "Sam")
        r = self.client.get("/api/feedback", headers=h)
        self.assertEqual(len(r.json()), 1)
        fid = r.json()[0]["id"]
        r = self.client.post(f"/api/feedback/{fid}/status", headers=h,
                             json={"status": "planned"})
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/api/feedback", headers=h)
        self.assertEqual(r.json()[0]["status"], "planned")

    def test_empty_text_rejected_and_auth_required(self):
        r = self.client.post("/api/feedback", headers=_basic("x", "main-pw"),
                             json={"text": "   "})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/feedback", json={"text": "hi"})
        self.assertEqual(r.status_code, 401)
        r = self.client.get("/api/feedback")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
