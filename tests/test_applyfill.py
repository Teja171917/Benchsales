"""Apply-assist fill plans: liveness classification, form parsing, and
the field-mapping rules — answered from data, blocked on anything the
data can't answer, dead postings reported. Fetching is stubbed."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, applyfill, db

FORM_HTML = """
<html><body>
<form action="/apply" method="post">
  <label for="fn">First Name</label><input id="fn" name="first_name" required>
  <label for="ln">Last Name</label><input id="ln" name="last_name" required>
  <label for="em">Email</label><input id="em" name="email" type="email" required>
  <label for="ph">Phone</label><input id="ph" name="phone" type="tel">
  <label for="rs">Resume</label><input id="rs" name="resume" type="file" required>
  <label for="cl">Cover Letter</label><input id="cl" name="cover" type="file">
  <label for="wa">Are you authorized to work in the US?</label>
  <select id="wa" name="work_auth" required><option>Yes</option><option>No</option></select>
  <label for="sal">Desired salary</label><input id="sal" name="salary">
  <input type="submit" value="Apply">
</form></body></html>
"""

DEAD_HTML = "<html><body><p>This job is no longer accepting applications.</p></body></html>"


def _page(html, http=200):
    return {"http": http, "final_url": "https://jobs.example/apply",
            "html": html, "error": ""}


class ApplyFillUnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()
        self.consultant = db.create_consultant({
            "name": "Pat Dev", "email": "pat@x.io", "phone": "555-0100",
            "location": "Dallas, TX"})
        db.upsert_resume(self.consultant["id"], "pat.docx",
                         "Pat Dev\nJava developer", ["java"])
        jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Java Dev",
            "company": "Acme", "location": "Remote", "remote_flag": 1,
            "url": "https://jobs.example/apply",
            "description": "Java role", "posted_at": "", "salary": "",
            "employment_type": ""})
        with db.get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 90.0, '{}', '[]', '2026-11-01T00:00:00Z')",
                (self.consultant["id"], jid))
            self.mid = cur.lastrowid
        self._orig_fetch = applyfill._fetch

    def tearDown(self):
        applyfill._fetch = self._orig_fetch
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def _plan(self, html, http=200):
        applyfill._fetch = lambda url: _page(html, http)
        return applyfill.build_fill_plan(db.get_match(self.mid))

    def test_live_form_blocks_on_unanswered_required(self):
        plan = self._plan(FORM_HTML)
        self.assertEqual(plan["liveness"], "live")
        self.assertEqual(plan["verdict"], "blocked")
        self.assertIn("Are you authorized to work in the US?",
                      plan["blockers"])
        by_field = {f["field"]: f for f in plan["fields"]}
        self.assertEqual(by_field["First Name"]["value"], "Pat")
        self.assertEqual(by_field["Last Name"]["value"], "Dev")
        self.assertEqual(by_field["Email"]["value"], "pat@x.io")
        self.assertEqual(by_field["Phone"]["value"], "555-0100")
        self.assertEqual(by_field["Resume"]["status"], "upload")
        # optional salary question: skipped, NOT a blocker
        self.assertNotIn("Desired salary", plan["blockers"])

    def test_visa_status_on_file_answers_work_auth(self):
        with db.get_conn() as conn:
            conn.execute("UPDATE consultants SET visa_status='US Citizen' "
                         "WHERE id=?", (self.consultant["id"],))
        plan = self._plan(FORM_HTML)
        self.assertEqual(plan["verdict"], "ready")
        by_field = {f["field"]: f for f in plan["fields"]}
        self.assertEqual(
            by_field["Are you authorized to work in the US?"]["value"],
            "US Citizen")

    def test_dead_posting_stops_the_plan(self):
        plan = self._plan(DEAD_HTML)
        self.assertEqual(plan["liveness"], "dead")
        self.assertEqual(plan["verdict"], "dead")
        self.assertEqual(plan["fields"], [])
        plan = self._plan("", http=404)
        self.assertEqual(plan["liveness"], "dead")

    def test_no_form_is_unknown_not_live(self):
        plan = self._plan("<html><body><p>Sign in to apply</p></body></html>")
        self.assertEqual(plan["liveness"], "unknown")
        self.assertEqual(plan["verdict"], "unknown")

    def test_search_box_is_not_an_application_form(self):
        page = ("<html><body><form action='/search'>"
                "<input name='q' placeholder='Search jobs'>"
                "<input type='submit' value='Search'></form>"
                "<p>Great role, apply on the employer's site.</p>"
                "</body></html>")
        plan = self._plan(page)
        self.assertEqual(plan["liveness"], "unknown")
        self.assertEqual(plan["verdict"], "unknown")


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class ApplyPlanHttpTests(unittest.TestCase):
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
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io"})
        db.upsert_resume(c["id"], "pat.docx", "Pat Dev\nJava", ["java"])
        jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Java Dev",
            "company": "Acme", "location": "Remote", "remote_flag": 1,
            "url": "https://jobs.example/apply", "description": "Java",
            "posted_at": "", "salary": "", "employment_type": ""})
        with db.get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 90.0, '{}', '[]', '2026-11-01T00:00:00Z')",
                (c["id"], jid))
            self.mid = cur.lastrowid
        self._orig_fetch = applyfill._fetch
        applyfill._fetch = lambda url: _page(DEAD_HTML)
        from fastapi.testclient import TestClient
        from app import server
        self.client = TestClient(server.app, raise_server_exceptions=False)

    def tearDown(self):
        applyfill._fetch = self._orig_fetch
        db.DB_PATH, accounts.ACCOUNTS_PATH = self._old_db, self._old_acc
        accounts._ready = False
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_plan_endpoint(self):
        h = _basic("x", "main-pw")
        r = self.client.post(f"/api/matches/{self.mid}/apply-plan",
                             headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["verdict"], "dead")
        r = self.client.post("/api/matches/9999/apply-plan", headers=h)
        self.assertEqual(r.status_code, 404)
        r = self.client.post(f"/api/matches/{self.mid}/apply-plan")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
