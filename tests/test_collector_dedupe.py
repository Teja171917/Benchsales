"""Run-scoped dedupe (Nov 9 2026): whole-feed sources return the same
jobs for many search queries, and every repeat sighting used to pay a
full db.insert_job — three text classifiers plus a fuzzy table scan —
in the main database AND every company database. The Nov 9 live run
showed Adzuna, SmartRecruiters and Phenom each burning their entire
4-minute source budget with 8 searches left, mostly re-saving known
jobs. Now the collector processes each job once per run (identity =
source id, or the same fuzzy title+company+location key insert_job
checks), and insert_job runs its duplicate check before classifying.
"""
import json
import tempfile
import unittest
from pathlib import Path

import collector
from app import db

JOBS = [
    {"source": "fake", "source_id": "f1", "title": "Java Developer",
     "company": "Acme", "location": "Houston, TX", "description": "java",
     "url": "", "employment_type": ""},
    {"source": "fake", "source_id": "f2", "title": "SDET",
     "company": "Beta", "location": "Austin, TX", "description": "qa",
     "url": "", "employment_type": ""},
    {"source": "fake", "source_id": "f3", "title": "Data Engineer",
     "company": "Core", "location": "Dallas, TX", "description": "etl",
     "url": "", "employment_type": ""},
]


class FakeSource:
    NAME = "fake"
    LABEL = "Fake"

    @staticmethod
    def enabled(settings):
        return True

    @staticmethod
    def fetch(query, settings):
        return [dict(j) for j in JOBS]


class CollectorDedupeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        db.set_setting("enabled_sources", json.dumps(["fake"]))

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_repeat_sightings_never_reach_the_database(self):
        orig_sources = collector.SOURCES
        orig_prepare = collector._prepare_all
        orig_insert = db.insert_job
        calls = {"n": 0}

        def counting(job):
            calls["n"] += 1
            return orig_insert(job)

        queries = [{"title": "Java"}, {"title": "Developer"},
                   {"title": "Engineer"}]
        collector.SOURCES = [FakeSource]
        collector._prepare_all = lambda deadline=None: (
            queries, {str(db.DB_PATH): {}})
        db.insert_job = counting
        try:
            summary = collector.run()
        finally:
            collector.SOURCES = orig_sources
            collector._prepare_all = orig_prepare
            db.insert_job = orig_insert
        st = summary["sources"]["fake"]
        self.assertEqual(st["jobs"], 9)    # 3 queries x 3 jobs fetched
        self.assertEqual(st["new"], 3)     # but only the 3 unique jobs
        self.assertEqual(calls["n"], 3)    # reached insert_job at all
        self.assertEqual(db.count_jobs(), 3)


class InsertJobOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_duplicate_insert_skips_the_classifiers(self):
        job = dict(JOBS[0])
        self.assertIsNotNone(db.insert_job(job))
        calls = {"n": 0}
        orig = db.emptype.classify

        def counting(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)

        db.emptype.classify = counting
        try:
            self.assertIsNone(db.insert_job(dict(job)))
        finally:
            db.emptype.classify = orig
        self.assertEqual(calls["n"], 0)


if __name__ == "__main__":
    unittest.main()
