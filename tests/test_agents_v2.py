"""Agent upgrades (Nov 4 2026): Tracker replaces Outreach, Watchdog checks
posting links, Compliance checks visas."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db, linkcheck, office


def test_linkcheck_classification():
    c = linkcheck.classify
    assert c(404, "")[0] == "dead"
    assert c(410, "")[0] == "dead"
    assert c(200, "This position has been filled.")[0] == "dead"
    assert c(200, "Apply now for this great role")[0] == "alive"
    # bot walls and server errors are UNKNOWN, never "dead"
    assert c(403, "")[0] == "unknown"
    assert c(500, "")[0] == "unknown"
    assert linkcheck.check("")[0] == "unknown"


class AgentDbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def _consultant(self, name, visa=None):
        c = db.create_consultant({"name": name})
        if visa:
            db.update_consultant(c["id"], {"visa_status": visa})
        return c["id"]

    def _job_match_queue(self, cid, title, desc, url=""):
        jid = db.insert_job({"source": "dice", "source_id": title,
                             "title": title, "company": "Acme",
                             "location": "Remote", "description": desc,
                             "url": url})
        mid = db.insert_match(cid, jid, 90, {}, [])
        return mid, db.queue_application(mid)["id"]

    def test_compliance_flags_visa_conflict_and_blank_status(self):
        cid = self._consultant("Hari H1B", visa="H1B")
        self._job_match_queue(cid, "Java Developer",
                              "US citizens only. Must be a US citizen.")
        cid2 = self._consultant("No Status Yet")          # visa blank
        self._job_match_queue(cid2, "Data Engineer", "Build pipelines.")
        out = office._compliance(db.get_settings())
        issues = {(i["issue"], i["consultant_name"]) for i in out["items"]}
        assert ("Visa / work-auth conflict", "Hari H1B") in issues
        assert ("Visa status not set", "No Status Yet") in issues
        assert out["visa_conflicts"] == 1
        assert out["blank_visa"] == ["No Status Yet"]
        # visa conflicts are flagged, never quarantined
        assert all(not i["quarantined"] for i in out["items"]
                   if i["issue"].startswith("Visa"))

    def test_watchdog_flags_dead_posting_link(self):
        cid = self._consultant("K. Abhinava", visa="US Citizen")
        _, aid = self._job_match_queue(
            cid, "Java Developer", "Write Java.",
            url="https://example.com/job/1")
        orig = office.linkcheck.check
        office.linkcheck.check = lambda url, timeout=8: ("dead", "HTTP 404")
        try:
            out = office._watchdog(db.get_settings())
        finally:
            office.linkcheck.check = orig
        assert out["links_dead"] == 1 and out["links_checked"] == 1
        assert out["dead_items"] and out["dead_items"][0]["app_id"] == aid
        app = [a for a in db.list_applications() if a["id"] == aid][0]
        assert "Posting link looks closed" in (app["notes"] or "")

    def test_tracker_reports_funnel_movement_and_stuck(self):
        cid = self._consultant("Praneeth Palle", visa="H1B")
        _, aid = self._job_match_queue(cid, "Data Engineer", "Pipelines.")
        db.update_application(aid, "screening", None)
        old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        with db.get_conn() as conn:
            conn.execute("UPDATE applications SET updated_at=? WHERE id=?",
                         (old, aid))
            conn.commit()
        db.log_activity("applied_detected", "Marked Applied from a Dice "
                        "confirmation email", actor="mailwatch")
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        out = office._tracker(db.get_settings(), since)
        assert out["pipeline"].get("screening") == 1
        assert out["stuck"] == 1
        assert out["items"][0]["app_id"] == aid
        assert out["email_flips"] == 1

    def test_office_briefing_has_tracker_not_outreach(self):
        br = office.run_office()
        assert "tracker" in br["agents"]
        assert "outreach" not in br["agents"]
