"""Cover letters: template facts-only generation, the LLM path with a
stubbed model, storage, and the HTTP endpoints."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from app import accounts, coverletter, db  # noqa: E402


def _basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(
        f"{user}:{pw}".encode()).decode()}


CONSULTANT = {"name": "Pat Dev", "email": "pat@x.io", "phone": "555-0100",
              "location": "Dallas, TX"}
JOB = {"title": "Senior Java Developer", "company": "Acme Corp",
       "description": "Needs Java, Spring Boot and Kubernetes experience."}
RESUME = "Pat Dev\nJava developer skilled in Java and Spring Boot."


class CoverLetterUnitTests(unittest.TestCase):
    def test_template_uses_only_real_facts(self):
        text, made_by = coverletter.generate(CONSULTANT, JOB, RESUME, {})
        self.assertEqual(made_by, "template")
        self.assertIn("Pat Dev", text)
        self.assertIn("Senior Java Developer", text)
        self.assertIn("Acme Corp", text)
        self.assertIn("Java", text)               # a genuinely shared skill
        self.assertNotIn("Kubernetes", text)      # not on the resume: kept out
        self.assertNotIn("years of experience", text)

    def test_llm_path_when_configured(self):
        settings = {"llm_base_url": "https://example.invalid/v1",
                    "llm_api_key": "k", "llm_model": "m"}
        orig = coverletter._llm_letter
        coverletter._llm_letter = lambda c, j, r, s: "Dear Hiring Manager,\nPat fits."
        try:
            text, made_by = coverletter.generate(CONSULTANT, JOB, RESUME,
                                                 settings)
        finally:
            coverletter._llm_letter = orig
        self.assertEqual(made_by, "llm")
        self.assertIn("Pat fits", text)


class CoverLetterHttpTests(unittest.TestCase):
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
        c = db.create_consultant({"name": "Pat Dev", "email": "pat@x.io",
                                  "location": "Dallas, TX"})
        db.upsert_resume(c["id"], "pat.docx", RESUME, ["java"])
        jid = db.insert_job({
            "source": "t", "source_id": "s1", "title": "Senior Java Developer",
            "company": "Acme Corp", "location": "Remote", "remote_flag": 1,
            "url": "", "description": JOB["description"], "posted_at": "",
            "salary": "", "employment_type": "fulltime"})
        with db.get_conn() as conn:
            cur = conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 90.0, '{}', '[]', '2026-11-01T00:00:00Z')",
                (c["id"], jid))
            self.mid = cur.lastrowid
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

    def test_generate_get_and_auth(self):
        h = _basic("x", "main-pw")
        r = self.client.get(f"/api/matches/{self.mid}/cover-letter",
                            headers=h)
        self.assertEqual(r.status_code, 404)      # none yet
        r = self.client.post(f"/api/matches/{self.mid}/cover-letter",
                             headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["made_by"], "template")
        self.assertIn("Acme Corp", body["text"])
        r = self.client.get(f"/api/matches/{self.mid}/cover-letter",
                            headers=h)
        self.assertEqual(r.status_code, 200)
        r = self.client.post(f"/api/matches/{self.mid}/cover-letter")
        self.assertEqual(r.status_code, 401)      # auth required
        r = self.client.post("/api/matches/9999/cover-letter", headers=h)
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
