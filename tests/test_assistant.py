"""In-app assistant: the workspace snapshot, the no-AI fallback, the
prompt assembly with a stubbed model, and the HTTP endpoint."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, assistant, db  # noqa: E402


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


class AssistantDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io",
                                  "location": "Dallas, TX"})
        self.cid = c["id"]
        jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Java Dev",
            "company": "Acme", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": "Java", "posted_at": "",
            "salary": "$120k", "employment_type": ""})
        with db.get_conn() as conn:
            conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 91.5, '{}', '[]', '2026-11-01T00:00:00Z')",
                (self.cid, jid))

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_snapshot_carries_workspace_facts(self):
        snap = assistant.build_snapshot()
        self.assertIn("Pat Dev", snap)
        self.assertIn("91.5", snap)
        self.assertIn("Total matches: 1", snap)
        self.assertIn("Java Dev at Acme", snap)

    def test_chat_without_ai_settings_gives_setup_help(self):
        out = assistant.chat("show my top matches")
        self.assertFalse(out["ai"])
        self.assertIn("Settings", out["reply"])

    def test_chat_uses_model_with_snapshot_in_prompt(self):
        db.set_setting("llm_base_url", "https://example.invalid/v1")
        db.set_setting("llm_api_key", "k")
        db.set_setting("llm_model", "m")
        seen = {}

        def stub(settings, messages):
            seen["messages"] = messages
            return "Pat Dev's best match is Java Dev at Acme (91.5)."

        self._orig = assistant._call_llm
        assistant._call_llm = stub
        try:
            out = assistant.chat("who has the best match?",
                                 [{"role": "user", "content": "hi"}])
        finally:
            assistant._call_llm = self._orig
        self.assertTrue(out["ai"])
        self.assertIn("91.5", out["reply"])
        system = seen["messages"][0]["content"]
        self.assertIn("Pat Dev", system)          # snapshot rode along
        self.assertIn("APP GUIDE", system)
        self.assertEqual(seen["messages"][-1]["content"],
                         "who has the best match?")


class AssistantHttpTests(unittest.TestCase):
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

    def test_endpoint_requires_auth(self):
        r = self.client.post("/api/assistant/chat",
                             json={"message": "hi"})
        self.assertEqual(r.status_code, 401)

    def test_endpoint_answers_with_fallback_when_no_ai(self):
        r = self.client.post("/api/assistant/chat",
                             headers=_basic("x", "main-pw"),
                             json={"message": "show my top matches",
                                   "history": []})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("reply", body)
        self.assertFalse(body["ai"])


if __name__ == "__main__":
    unittest.main()


class AssistantActionTests(unittest.TestCase):
    """Chat actions: 'tailor <name>'s resume' runs the tailor for real,
    'queue it' queues that match — flagged skills are reported, never
    silently added."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io"})
        db.upsert_resume(c["id"], "pat.docx",
                         "Pat Dev\nJava Spring Boot developer", ["java", "spring"])
        self.cid = c["id"]
        jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Java Dev",
            "company": "Acme", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": "Java Spring Boot role",
            "posted_at": "", "salary": "", "employment_type": ""})
        with db.get_conn() as conn:
            conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 88.0, '{}', '[]', '2026-11-01T00:00:00Z')",
                (self.cid, jid))
        self._orig = assistant._run_tailor
        assistant._run_tailor = lambda m: {
            "id": db.insert_tailored(m["id"], "TAILORED TEXT", "template",
                                     ["Kubernetes"]),
            "tailored_by": "template", "added_skills_flagged": ["Kubernetes"]}

    def tearDown(self):
        assistant._run_tailor = self._orig
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_tailor_then_queue_it(self):
        out = assistant.chat("Please tailor Pat's resume", actor="sam@x.io")
        self.assertEqual(out["action"]["type"], "tailored")
        self.assertIn("Kubernetes", out["reply"])       # flagged, surfaced
        self.assertIn("NOT added", out["reply"])
        out = assistant.chat("queue it", actor="sam@x.io")
        self.assertEqual(out["action"]["type"], "queued")
        apps = db.list_applications()
        self.assertEqual(len(apps), 1)
        self.assertEqual(apps[0]["status"], "queued")
        self.assertIsNotNone(apps[0]["tailored_resume_id"])

    def test_tailor_without_a_name_asks(self):
        out = assistant.chat("fix the resume to the max", actor="sam@x.io")
        self.assertIsNone(out["action"])
        self.assertIn("Pat Dev", out["reply"])

    def test_queue_it_without_tailor_falls_through(self):
        out = assistant.chat("queue it", actor="other@x.io")
        self.assertIsNone(out["action"])   # no pending action: normal chat

    def test_find_consultant_by_any_name_part(self):
        people = [{"name": "K. Abhinava"}, {"name": "Sandeep Kumar Reddy Gadige"},
                  {"name": "Seetha Kalyani Kotha"}]
        self.assertEqual(assistant._find_consultant(
            "tailor Abhinava's resume", people)["name"], "K. Abhinava")
        self.assertEqual(assistant._find_consultant(
            "fix Seetha resume", people)["name"], "Seetha Kalyani Kotha")
        self.assertEqual(assistant._find_consultant(
            "tailor Sandeep's resume", people)["name"],
            "Sandeep Kumar Reddy Gadige")
        self.assertIsNone(assistant._find_consultant(
            "tailor the resume", people))


class AssistantSkillConfirmTests(unittest.TestCase):
    """'Add the missing skills' must OFFER, never add. Only an explicit
    'confirm <skill>' from the person adds — and only that skill."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "t.db"
        db.init_db()
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io"})
        db.upsert_resume(c["id"], "pat.docx",
                         "Pat Dev\nJava Spring Boot developer", ["java"])
        self.cid = c["id"]
        jid = db.insert_job({
            "source": "t", "source_id": "s9", "title": "Java Dev",
            "company": "Acme", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": "Java Kubernetes Terraform role",
            "posted_at": "", "salary": "", "employment_type": ""})
        with db.get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 88.0, '{}', "
                "'[\"kubernetes\", \"terraform\"]', '2026-11-01T00:00:00Z')",
                (self.cid, jid))
            self.mid = cur.lastrowid
        self._orig = assistant._run_tailor
        assistant._run_tailor = lambda m: {
            "id": db.insert_tailored(m["id"], "TAILORED TEXT", "template",
                                     []),
            "tailored_by": "template", "added_skills_flagged": []}

    def tearDown(self):
        assistant._run_tailor = self._orig
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def _tailored(self):
        row = db.get_tailored_for_match(self.mid)
        return db.get_tailored(row["id"]) if row else None

    def test_offer_adds_nothing_then_confirm_adds_one(self):
        out = assistant.chat("add the missing skills for Pat",
                             actor="sam@x.io")
        self.assertEqual(out["action"]["type"], "skills_offered")
        t = self._tailored()
        self.assertEqual(t["user_confirmed_skills"], [])   # nothing added
        out = assistant.chat("confirm Kubernetes", actor="sam@x.io")
        self.assertEqual(out["action"]["type"], "skills_confirmed")
        self.assertEqual(out["action"]["added"], ["kubernetes"])
        t = self._tailored()
        self.assertEqual(t["user_confirmed_skills"], ["kubernetes"])
        self.assertIn("Kubernetes", t["tailored_text"])
        self.assertNotIn("Terraform", t["tailored_text"])
        out = assistant.chat("queue it", actor="sam@x.io")
        self.assertEqual(out["action"]["type"], "queued")

    def test_confirm_all_and_skip(self):
        assistant.chat("update the skills missed for this post for Pat",
                       actor="jo@x.io")
        out = assistant.chat("confirm all", actor="jo@x.io")
        self.assertEqual(sorted(out["action"]["added"]),
                         ["kubernetes", "terraform"])
        # a fresh offer, then skip: nothing more changes
        out = assistant.chat("add the missing skills for Pat",
                             actor="jo@x.io")
        self.assertIsNone(out["action"])     # nothing left to offer
        self.assertIn("Nothing is missing", out["reply"])

    def test_confirm_unknown_skill_adds_nothing(self):
        assistant.chat("add the missing skills for Pat", actor="sam@x.io")
        out = assistant.chat("confirm Cooking", actor="sam@x.io")
        self.assertIsNone(out["action"])
        self.assertEqual(self._tailored()["user_confirmed_skills"], [])
