"""Activity log: actions and errors are recorded per workspace, the
assistant can answer 'what happened / any errors?' from the log even
with no AI configured, and one workspace's log never leaks into
another's."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, assistant, db


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class ActivityLogTests(unittest.TestCase):
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
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io"})
        self.cid = c["id"]
        db.upsert_resume(self.cid, "pat.docx",
                         "Java Spring SQL developer",
                         ["java", "spring", "sql"])
        jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Java Dev",
            "company": "Co", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": "Java Spring role",
            "posted_at": "", "salary": "", "employment_type": ""})
        with db.get_conn() as conn:
            conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 90.0, '{}', '[]', '2026-11-02T00:00:00Z')",
                (self.cid, jid))
            self.mid = conn.execute(
                'SELECT id FROM "matches"').fetchone()["id"]
        from fastapi.testclient import TestClient
        from app import server
        self.server = server
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

    def test_tailor_and_queue_are_logged(self):
        r = self.client.post(f"/api/matches/{self.mid}/tailor",
                             headers=self.main)
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post(f"/api/matches/{self.mid}/queue",
                             headers=self.main, json={})
        self.assertEqual(r.status_code, 200, r.text)
        events = db.list_activity(10)
        summaries = [e["summary"] for e in events]
        self.assertTrue(any("Tailored Pat Dev" in x for x in summaries))
        self.assertTrue(any("Queued Pat Dev" in x for x in summaries))
        self.assertTrue(all(e["actor"] == "shared login (main)"
                            for e in events))

    def test_tailor_failure_is_logged_as_error(self):
        def boom(match, settings):
            raise RuntimeError("provider exploded")
        old = self.server.tailor_mod.tailor_match
        self.server.tailor_mod.tailor_match = boom
        try:
            r = self.client.post(f"/api/matches/{self.mid}/tailor",
                                 headers=self.main)
        finally:
            self.server.tailor_mod.tailor_match = old
        self.assertEqual(r.status_code, 500)
        errors = db.list_activity(5, kind="error")
        self.assertEqual(len(errors), 1)
        self.assertIn("Tailor failed for Pat Dev", errors[0]["summary"])
        self.assertIn("provider exploded", errors[0]["detail"])

    def test_activity_endpoint_is_admin_only(self):
        db.log_activity("action", "Something happened", actor="tester")
        r = self.client.get("/api/activity", headers=self.main)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["events"][0]["summary"],
                         "Something happened")
        r = self.client.get("/api/activity")
        self.assertEqual(r.status_code, 401)

    def test_assistant_answers_from_the_log_without_ai(self):
        db.log_activity("error", "Tailor failed for Pat Dev — Java Dev "
                                 "at Co", actor="shared login (main)",
                        detail="RuntimeError: provider exploded")
        db.log_activity("action", "Queued Pat Dev for Java Dev at Co",
                        actor="shared login (main)")
        out = assistant.chat("any errors today?")
        self.assertFalse(out["ai"])
        self.assertIn("Tailor failed for Pat Dev", out["reply"])
        out = assistant.chat("what happened recently?")
        self.assertIn("Queued Pat Dev", out["reply"])

    def test_snapshot_carries_recent_activity(self):
        db.log_activity("action", "Collected 12 new jobs", actor="system")
        snap = assistant.build_snapshot()
        self.assertIn("RECENT ACTIVITY", snap)
        self.assertIn("Collected 12 new jobs", snap)

    def test_logs_are_per_workspace(self):
        other = Path(self.tmp.name) / "other.db"
        db.log_activity("action", "Main event", actor="tester")
        with db.use(other):
            db.init_db()
            self.assertEqual(db.list_activity(5), [])
            db.log_activity("action", "Other event", actor="tester")
            self.assertEqual(len(db.list_activity(5)), 1)
        self.assertEqual([e["summary"] for e in db.list_activity(5)],
                         ["Main event"])

    def test_logging_never_breaks_the_caller(self):
        # a database without the table (not initialised): silent no-op
        broken = Path(self.tmp.name) / "broken.db"
        broken.write_bytes(b"")
        with db.use(broken):
            db.log_activity("action", "into the void")  # must not raise
            self.assertEqual(db.list_activity(5), [])


if __name__ == "__main__":
    unittest.main()
