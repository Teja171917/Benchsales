"""Application-confirmation detection (mailwatch): strict positives,
rejection negatives, unique-match flips only — RSATECH tester feedback,
Nov 3 2026."""
import tempfile
import unittest
from pathlib import Path

from app import db, mailwatch


def test_detects_portal_confirmations():
    d = mailwatch.parse_confirmation(
        "Your application for Senior Java Developer at Randstad Digital was submitted",
        "Dear K Abhinava,\nThanks — your application was sent.",
        "Dice <noreply@dice.com>")
    assert d and d["portal"] == "Dice"
    assert "Java Developer" in d["title"] and "Randstad" in d["company"]
    d2 = mailwatch.parse_confirmation(
        "Your Indeed application has been submitted",
        "You applied for the position of Data Engineer at Palni Inc. Good luck!",
        "Indeed <donotreply@indeed.com>")
    assert d2 and d2["portal"] == "Indeed" and "Data Engineer" in d2["title"]
    d3 = mailwatch.parse_confirmation(
        "Thank you for applying",
        "Dear Praneeth Palle,\nWe have received your application for the "
        "Junior Data Engineer role.", "SmartRecruiters <no-reply@smartrecruiters.com>")
    assert d3 and d3["portal"] == "SmartRecruiters"


def test_rejects_non_confirmations():
    # a rejection that mentions the application must NOT count
    assert mailwatch.parse_confirmation(
        "Update on your application for Java Developer at Acme",
        "Unfortunately, we will not be moving forward with your application.",
        "noreply@acme.com") is None
    # an interview invite is not a submission confirmation
    assert mailwatch.parse_confirmation(
        "Interview request: Java Developer at Acme",
        "We'd like to schedule an interview.", "talent@acme.com") is None
    # a marketing digest
    assert mailwatch.parse_confirmation(
        "New jobs for you", "Check out these openings near you.",
        "jobs@dice.com") is None


_QUEUED = [
    {"id": 1, "status": "queued", "job_title": "Senior Java Developer",
     "company": "Randstad Digital", "consultant_name": "K. Abhinava"},
    {"id": 2, "status": "queued", "job_title": "Junior Data Engineer",
     "company": "Rize Beyond Banking", "consultant_name": "Praneeth Palle"},
    {"id": 3, "status": "applied", "job_title": "Senior Java Developer",
     "company": "Randstad Digital", "consultant_name": "K. Abhinava"},
]


def test_matcher_flips_only_unique_strong_matches():
    det = {"portal": "Dice", "title": "Senior Java Developer",
           "company": "Randstad Digital", "applicant": "K Abhinava"}
    hit = mailwatch.find_application(_QUEUED, det)
    assert hit and hit["id"] == 1           # the already-applied one is skipped
    det2 = {"portal": "Dice", "title": "Senior Java Developer",
            "company": "Unknown Corp", "applicant": ""}
    assert mailwatch.find_application(_QUEUED, det2) is None   # company mismatch
    det3 = {"portal": "", "title": "", "company": "", "applicant": ""}
    assert mailwatch.find_application(_QUEUED, det3) is None   # nothing extracted


class _FakeIMAP:
    MSGS = {}

    def __init__(self, host, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        return "OK", []

    def select(self, box, readonly=False):
        return "OK", []

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            import re as _re
            m = _re.search(r"UID (\d+):", str(args[-1]))
            lo = int(m.group(1)) if m else 0
            return "OK", [" ".join(str(u) for u in sorted(self.MSGS)
                                   if u >= lo).encode()]
        uid = int(args[0])
        return "OK", [(f"{uid} (BODY[HEADER] {{0}})", self.MSGS[uid])]


def _raw(subject, frm, body):
    return (f"From: {frm}\r\nSubject: {subject}\r\n"
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}").encode()


class PollFlipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        cid = db.create_consultant({"name": "K. Abhinava"})["id"]
        jid = db.insert_job({"source": "dice", "source_id": "MW1",
                             "title": "Senior Java Developer",
                             "company": "Randstad Digital",
                             "location": "Remote", "description": "Java."})
        mid = db.insert_match(cid, jid, 90, {}, ["go"])
        self.aid = db.queue_application(mid)["id"]
        db.set_setting("imap_enabled", "1")
        db.set_setting("imap_user", "team@example.com")
        db.set_setting("imap_pass", "app-password")
        _FakeIMAP.MSGS = {101: _raw(
            "Your application for Senior Java Developer at Randstad Digital was submitted",
            "Dice <noreply@dice.com>",
            "Dear K Abhinava,\nYour application was sent.")}
        self._ssl = mailwatch.imaplib.IMAP4_SSL
        mailwatch.imaplib.IMAP4_SSL = _FakeIMAP

    def tearDown(self):
        mailwatch.imaplib.IMAP4_SSL = self._ssl
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_poll_flips_the_card_once(self):
        out = mailwatch.poll_once()
        self.assertEqual(out["flipped"], 1)
        app = [a for a in db.list_applications() if a["id"] == self.aid][0]
        self.assertEqual(app["status"], "applied")
        self.assertIsNotNone(app["applied_at"])
        # watermark advanced: a second poll sees nothing new
        out2 = mailwatch.poll_once()
        self.assertEqual(out2["seen"], 0)
        acts = db.list_activity()
        self.assertTrue(any("confirmation email" in (a.get("summary") or "")
                            for a in acts))
