"""Skill-gap rollup: missing skills across a consultant's matches,
counted per match, with the endpoint alongside."""
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


class SkillGapTests(unittest.TestCase):
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
        self.cid = c["id"]
        missing_sets = [["kubernetes", "aws"], ["kubernetes"],
                        ["kubernetes", "aws", "terraform"]]
        for i, missing in enumerate(missing_sets):
            jid = db.insert_job({
                "source": "t", "source_id": f"s{i}", "title": "Java Dev",
                "company": f"Co{i}", "location": "Remote", "remote_flag": 1,
                "url": "", "description": "Java Kubernetes AWS",
                "posted_at": "", "salary": "", "employment_type": ""})
            with db.get_conn() as conn:
                conn.execute(
                    'INSERT INTO "matches"(consultant_id, job_id, score, '
                    'score_breakdown_json, missing_skills_json, created_at) '
                    "VALUES (?, ?, 80.0, '{}', ?, '2026-11-01T00:00:00Z')",
                    (self.cid, jid, json.dumps(missing)))
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

    def test_rollup_counts_matches_per_gap(self):
        out = db.skill_gaps(self.cid)
        self.assertEqual(out["matches_considered"], 3)
        counts = {g["skill"]: g["matches_missing"] for g in out["gaps"]}
        self.assertEqual(counts, {"kubernetes": 3, "aws": 2,
                                  "terraform": 1})
        self.assertEqual(out["gaps"][0]["skill"], "kubernetes")

    def test_endpoint_shape_and_auth(self):
        h = _basic("x", "main-pw")
        r = self.client.get(f"/api/consultants/{self.cid}/skill-gaps",
                            headers=h)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["consultant_name"], "Pat Dev")
        self.assertIn("demand_jobs", body["gaps"][0])
        r = self.client.get("/api/consultants/9999/skill-gaps", headers=h)
        self.assertEqual(r.status_code, 404)
        r = self.client.get(f"/api/consultants/{self.cid}/skill-gaps")
        self.assertEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
