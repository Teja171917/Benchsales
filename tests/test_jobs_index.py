"""Fuzzy-duplicate index (Nov 9 2026): insert_job's duplicate check
matches lower(title)/lower(company)/lower(location) across the whole
jobs table. Without an index that is a full scan on every insert, in
every workspace database; the expression index turns it into a lookup.
Pins that init_db creates the index and the planner uses it for the
exact duplicate-check query insert_job runs.
"""
import tempfile
import unittest
from pathlib import Path

from app import db

DUP_SQL = ("SELECT id FROM jobs WHERE lower(title)=lower(?) AND "
           "lower(company)=lower(?) AND lower(location)=lower(?)")


class JobsIndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_fuzzy_index_exists_and_planner_uses_it(self):
        with db.get_conn() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
                " AND name='idx_jobs_fuzzy_key'").fetchone()
            self.assertIsNotNone(row)
            plan = conn.execute("EXPLAIN QUERY PLAN " + DUP_SQL,
                                ("T", "C", "L")).fetchall()
        self.assertTrue(
            any("idx_jobs_fuzzy_key" in r["detail"] for r in plan),
            [r["detail"] for r in plan])


if __name__ == "__main__":
    unittest.main()
