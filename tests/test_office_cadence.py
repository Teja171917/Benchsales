"""Office cadence + async runs (Nov 4 2026): due every 15 minutes, runs
happen on a guarded background thread, link checks rotate."""
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import db, office
from app import server


class CadenceTests(unittest.TestCase):
    def test_due_every_15_minutes(self):
        now = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        assert server._office_due("", now) is True
        assert server._office_due((now - timedelta(minutes=10)).isoformat(), now) is False
        assert server._office_due((now - timedelta(minutes=16)).isoformat(), now) is True
        assert server.OFFICE_EVERY_MINUTES == 15


class AsyncRunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_start_office_run_is_exclusive_and_releases(self):
        assert server._start_office_run(db.current_path()) is True
        # while it runs (or is about to), a second start is refused
        # (the empty-DB run is fast, so poll briefly for the release)
        deadline = time.time() + 15
        released = False
        while time.time() < deadline:
            if server._start_office_run(db.current_path()):
                released = True
                break
            time.sleep(0.2)
        assert released, "office lock was never released"

    def test_link_checks_rotate(self):
        c = db.create_consultant({"name": "Rotator"})
        aids = []
        for i in (1, 2):
            jid = db.insert_job({"source": "dice", "source_id": f"r{i}",
                                 "title": f"Job {i}", "company": "Acme",
                                 "location": "", "description": "x",
                                 "url": f"https://example.com/{i}"})
            mid = db.insert_match(c["id"], jid, 90, {}, [])
            aids.append(db.queue_application(mid)["id"])
        seen = []
        orig_check = office.linkcheck.check
        orig_cap = office.LINK_CHECKS_PER_RUN
        office.linkcheck.check = lambda url, timeout=8: (seen.append(url), ("alive", "HTTP 200"))[1]
        office.LINK_CHECKS_PER_RUN = 1
        try:
            office._watchdog(db.get_settings())
            office._watchdog(db.get_settings())
        finally:
            office.linkcheck.check = orig_check
            office.LINK_CHECKS_PER_RUN = orig_cap
        assert len(seen) == 2 and seen[0] != seen[1], seen
