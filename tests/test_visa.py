"""Work-auth (visa) tags: postings are tagged ONLY from wording they
actually state, consultants' free-text visa status normalises to a
key, conflicts between the two are computed per match, and legacy
jobs backfill."""
import tempfile
import unittest
from pathlib import Path

from app import db, visa


class ClassifyTests(unittest.TestCase):
    def test_citizens_only(self):
        self.assertEqual(visa.classify_auth(
            "This role is for US Citizens only."), "citizens_only")
        self.assertEqual(visa.classify_auth(
            "Must be a U.S. Citizen to apply."), "citizens_only")
        self.assertEqual(visa.classify_auth(
            "Active Secret Clearance required."), "citizens_only")

    def test_citizens_gc(self):
        self.assertEqual(visa.classify_auth(
            "Open to US Citizens or Green Card holders."), "citizens_gc")
        self.assertEqual(visa.classify_auth(
            "This is an ITAR-controlled position."), "citizens_gc")

    def test_no_sponsorship(self):
        self.assertEqual(visa.classify_auth(
            "We are unable to sponsor a visa at this time."),
            "no_sponsorship")
        self.assertEqual(visa.classify_auth(
            "Candidates must be authorized to work in the US without "
            "sponsorship."), "no_sponsorship")
        self.assertEqual(visa.classify_auth(
            "No sponsorship available for this role."), "no_sponsorship")

    def test_sponsorship_ok(self):
        self.assertEqual(visa.classify_auth(
            "H1B sponsorship available for the right candidate."),
            "sponsorship_ok")
        self.assertEqual(visa.classify_auth(
            "OPT candidates welcome to apply."), "sponsorship_ok")

    def test_silence_and_generic_wording_stay_unstated(self):
        self.assertEqual(visa.classify_auth("Great Java role in Houston."), "")
        self.assertEqual(visa.classify_auth(
            "Must be legally authorized to work in the United States."), "")
        self.assertEqual(visa.classify_auth(""), "")

    def test_restrictive_wording_wins(self):
        # both families present: the citizen bar is the binding one
        self.assertEqual(visa.classify_auth(
            "US Citizens only. We sponsor team events and lunches."),
            "citizens_only")


class StatusKeyTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(visa.status_key("US Citizen"), "citizen")
        self.assertEqual(visa.status_key("Green Card"), "green_card")
        self.assertEqual(visa.status_key("GC"), "green_card")
        self.assertEqual(visa.status_key("H1B"), "h1b")
        self.assertEqual(visa.status_key("OPT / STEM OPT EAD"), "opt_ead")
        self.assertEqual(visa.status_key("H4 EAD"), "h4_ead")
        self.assertEqual(visa.status_key("H-4 EAD"), "h4_ead")
        self.assertEqual(visa.status_key("TN"), "tn")
        self.assertEqual(visa.status_key(""), "")
        self.assertEqual(visa.status_key("L2 visa"), "other")


class CompatibleTests(unittest.TestCase):
    def test_matrix(self):
        self.assertTrue(visa.compatible("US Citizen", "citizens_only"))
        self.assertFalse(visa.compatible("Green Card", "citizens_only"))
        self.assertTrue(visa.compatible("Green Card", "citizens_gc"))
        self.assertFalse(visa.compatible("H1B", "no_sponsorship"))
        self.assertTrue(visa.compatible("H1B", "sponsorship_ok"))
        self.assertFalse(visa.compatible("OPT EAD", "citizens_gc"))
        self.assertTrue(visa.compatible("H4 EAD", "no_sponsorship"))
        self.assertTrue(visa.compatible("H4 EAD", "sponsorship_ok"))
        self.assertFalse(visa.compatible("H4 EAD", "citizens_gc"))
        self.assertFalse(visa.compatible("H4 EAD", "citizens_only"))
        self.assertIsNone(visa.compatible("H1B", ""))
        self.assertIsNone(visa.compatible("", "citizens_only"))
        self.assertIsNone(visa.compatible("L2 visa", "citizens_only"))


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def _job(self, desc, sid):
        return db.insert_job({
            "source": "t", "source_id": sid, "title": "Java Dev",
            "company": "Co", "location": "Houston, TX", "remote_flag": 0,
            "url": "", "description": desc, "posted_at": "",
            "salary": "", "employment_type": ""})

    def test_insert_classifies_and_matches_carry_the_verdict(self):
        jid = self._job("US Citizens only need apply.", "v1")
        row = db.get_job(jid)
        self.assertEqual(row["auth_tag"], "citizens_only")
        c = db.create_consultant({"name": "Hari H1B",
                                  "visa_status": "H1B"})
        with db.get_conn() as conn:
            conn.execute(
                'INSERT INTO "matches"(consultant_id, job_id, score, '
                'score_breakdown_json, missing_skills_json, created_at) '
                "VALUES (?, ?, 88.0, '{}', '[]', '2026-11-02T00:00:00Z')",
                (c["id"], jid))
        rows = db.list_matches()
        self.assertEqual(rows[0]["auth_tag"], "citizens_only")
        self.assertEqual(rows[0]["consultant_visa"], "H1B")
        self.assertIs(rows[0]["visa_ok"], False)

    def test_backfill_fills_legacy_rows(self):
        jid = self._job("No sponsorship available.", "v2")
        with db.get_conn() as conn:
            conn.execute("UPDATE jobs SET auth_tag=NULL WHERE id=?", (jid,))
        self.assertEqual(db.backfill_auth_tags(), 1)
        self.assertEqual(db.get_job(jid)["auth_tag"], "no_sponsorship")
        self.assertEqual(db.backfill_auth_tags(), 0)


if __name__ == "__main__":
    unittest.main()


# ---- stack titles: generic headlines still find their stack (Nov 2) ----
def test_stack_title_signatures():
    from app import matcher
    net = [".net", ".net core", "asp.net", "c#", "entity framework",
           "azure", "docker", "aws"]
    assert matcher.stack_title(net) == ".NET Developer"
    assert matcher.stack_title(["java", "spring boot", "sql"]) == "Java Developer"
    assert matcher.stack_title(["java", "sql", "jira"]) == ""      # java alone: no signal
    assert matcher.stack_title(["python", "airflow", "spark"]) == "Data Engineer"
    assert matcher.stack_title(["python", "django"]) == "Python Developer"
    assert matcher.stack_title(["python", "pandas"]) == ""         # python alone: no signal
    assert matcher.stack_title(["react", "css"]) == "React Developer"
    assert matcher.stack_title(["jira", "confluence"]) == ""


def test_titles_for_appends_stack_for_generic_headline():
    from app import matcher
    c = {"name": "Sandeep Kumar Reddy Gadige",
         "raw_text": "SANDEEP KUMAR REDDY GADIGE\nLead Developer | Principal Engineer",
         "skills": [".net", ".net core", "asp.net", "c#"],
         "target_roles": "", "filename": ""}
    titles = matcher.titles_for(c)
    assert ".NET Developer" in titles, titles
    typed = dict(c, target_roles=".NET Architect")
    assert matcher.titles_for(typed) == [".NET Architect"]   # typed roles win, untouched
