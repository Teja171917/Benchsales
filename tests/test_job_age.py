"""Two-week posting window (Nov 13 2026): Teja's rule — pull only
postings from the last 14 days, nothing older. Enforced in both
places, mirroring the US filter's design: the fetch door refuses a
posting whose date is known to be too old, and a per-workspace sweep
in prepare removes old postings already in the pool. A posting with
a blank or unparseable date is always kept — its age can't be
proven (manual URL imports carry no date). The window is the
max_job_age_days setting (default 14; 0 = no limit).
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import collector
from app import db


def _job(source_id, posted_at):
    # title carries the id: insert_job fuzzy-dedupes on
    # title+company+location, so identical titles would collapse
    return {"source": "fake", "source_id": source_id,
            "title": f"Java Developer {source_id}",
            "company": "Acme", "location": "Houston, TX",
            "description": "java", "url": "", "employment_type": "",
            "posted_at": posted_at}


def _iso(days_ago):
    return (datetime.now(timezone.utc)
            - timedelta(days=days_ago)).isoformat()


class MaxAgeSettingTests(unittest.TestCase):
    def test_default_and_parsing(self):
        self.assertEqual(collector._max_age_days({}), 14)
        self.assertEqual(collector._max_age_days(
            {"max_job_age_days": "7"}), 7)
        self.assertEqual(collector._max_age_days(
            {"max_job_age_days": "0"}), 0)      # 0 = limit off
        self.assertEqual(collector._max_age_days(
            {"max_job_age_days": "junk"}), 14)  # garbage -> default


class PurgeOldJobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_purge_removes_only_provably_old_jobs(self):
        old = db.insert_job(_job("old", _iso(20)))
        edge = db.insert_job(_job("edge", _iso(13)))
        fresh = db.insert_job(_job("fresh", _iso(1)))
        blank = db.insert_job(_job("blank", ""))
        junk = db.insert_job(_job("junk", "sometime last spring"))
        self.assertIsNotNone(old)
        c = db.create_consultant({"name": "Pat Dev"})
        with db.get_conn() as conn:
            for jid in (old, fresh):
                conn.execute(
                    "INSERT INTO matches (consultant_id, job_id, score,"
                    " created_at) VALUES (?, ?, 80, 'now')",
                    (c["id"], jid))
        out = db.purge_old_jobs(14)
        self.assertEqual(out, {"jobs": 1, "matches": 1})
        remaining = {r["source_id"] for r in
                     db.get_conn().execute("SELECT source_id FROM jobs")}
        self.assertEqual(remaining, {"edge", "fresh", "blank", "junk"})
        # the old job's match cascaded away; the fresh one survives
        left = db.get_conn().execute(
            "SELECT COUNT(*) FROM matches").fetchone()[0]
        self.assertEqual(left, 1)

    def test_zero_days_is_a_no_op(self):
        db.insert_job(_job("old", _iso(90)))
        self.assertEqual(db.purge_old_jobs(0), {"jobs": 0, "matches": 0})
        self.assertEqual(db.count_jobs(), 1)


class FakeAgedSource:
    NAME = "fake"
    LABEL = "Fake"

    @staticmethod
    def enabled(settings):
        return True

    @staticmethod
    def fetch(query, settings):
        return [_job("old", _iso(30)), _job("fresh", _iso(2)),
                _job("blank", "")]


class FetchDoorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        db.set_setting("enabled_sources", json.dumps(["fake"]))

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def _run(self):
        orig_sources = collector.SOURCES
        orig_prepare = collector._prepare_all
        collector.SOURCES = [FakeAgedSource]
        # _prepare_all is stubbed, so the prepare-phase age sweep does
        # not run here — this test isolates the FETCH door
        collector._prepare_all = lambda deadline=None: (
            [{"title": "Java"}], {str(db.DB_PATH): {}})
        try:
            return collector.run()
        finally:
            collector.SOURCES = orig_sources
            collector._prepare_all = orig_prepare

    def test_old_postings_never_reach_the_database(self):
        self._run()
        remaining = {r["source_id"] for r in
                     db.get_conn().execute("SELECT source_id FROM jobs")}
        self.assertEqual(remaining, {"fresh", "blank"})

    def test_limit_off_lets_everything_through(self):
        db.set_setting("max_job_age_days", "0")
        self._run()
        self.assertEqual(db.count_jobs(), 3)


if __name__ == "__main__":
    unittest.main()
