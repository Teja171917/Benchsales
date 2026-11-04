"""Experience levels, the W2-only tagging fix, and the job-boards directory
— RSATECH tester feedback, Nov 3 2026."""
import os
import tempfile
import unittest
from pathlib import Path

from app import db, emptype, levels


def test_level_title_signals():
    c = levels.classify_level
    assert c("Solutions Architect") == "architect"
    assert c("Principal Software Engineer") == "principal"
    assert c("Lead Java Developer (Hybrid W2 only)") == "lead"
    assert c("Sr. Java Developer") == "senior"
    assert c("Senior Data Engineer") == "senior"
    assert c("Junior Data Engineer") == "entry"
    assert c("Software Engineering Intern") == "intern"
    assert c("Data Engineer") == ""          # nothing stated -> unstated


def test_level_years_fallback():
    c = levels.classify_level
    assert c("Java Developer", "Requires 10+ years of experience") == "lead"
    assert c("Java Developer", "8-10 years experience required") == "senior"
    assert c("Java Developer", "3-5 years of experience") == "mid"
    assert c("Java Developer", "0-2 years experience; new grads ok") == "entry"
    # a title signal always beats the years in the boilerplate
    assert c("Junior Developer", "Our leads have 15 years experience") == "entry"


def test_w2_contract_tagging_stays_truthful():
    # "W2 contract" is a real engagement (vendor's W2 employee on a
    # contract assignment), so the tags keep both words; keeping W2-only
    # postings out of a no-W2 view is the FILTER's job (empPasses in
    # app.js), not the tagger's.
    tags = emptype.classify("Contract", "Lead Java Developer (Hybrid W2 only)",
                            "This is a W2 only position. No C2C.")
    assert tags == ["w2", "contract"], tags
    tags2 = emptype.classify("Contract", "Java Developer",
                             "Contract role, C2C or W2 both accepted.")
    assert "c2c" in tags2 and "w2" in tags2 and "contract" in tags2, tags2


def test_emp_filter_excludes_unselected_engagement_models():
    """The empPasses rule in app.js (Teja's rule): ANY engagement tag
    outside the selection hides the job — a W2 tag excludes it from a
    C2C/Contract/C2H view even alongside selected tags."""
    js = (Path(__file__).resolve().parent.parent / "frontend" / "app.js").read_text()
    assert "ENG_TAGS.includes(t) && !wanted.includes(t)" in js


class BoardsAndBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_insert_classifies_level_and_backfill_fills_old_rows(self):
        jid = db.insert_job({"source": "dice", "source_id": "L1",
                             "title": "Lead Java Developer",
                             "company": "Acme", "location": "Remote",
                             "description": "Own the platform."})
        self.assertIsNotNone(jid)
        self.assertEqual(db.get_job(jid)["exp_level"], "lead")
        with db.get_conn() as conn:
            conn.execute("UPDATE jobs SET exp_level=NULL WHERE id=?", (jid,))
            conn.commit()
        self.assertEqual(db.backfill_levels(), 1)
        self.assertEqual(db.get_job(jid)["exp_level"], "lead")
        self.assertEqual(db.backfill_levels(), 0)

    def test_job_boards_endpoint_serves_the_list(self):
        os.environ.pop("BENCHPILOT_COMPANIES", None)
        os.environ.pop("BENCHPILOT_PASSWORD", None)
        from fastapi.testclient import TestClient
        from app import server
        client = TestClient(server.app, raise_server_exceptions=False)
        r = client.get("/api/job-boards")
        self.assertEqual(r.status_code, 200)
        boards = r.json()["boards"]
        self.assertGreaterEqual(len(boards), 90)
        names = {b["name"] for b in boards}
        self.assertIn("Insight Global", names)
        self.assertIn("Judge Group", names)
        self.assertTrue(all("url" in b for b in boards))
