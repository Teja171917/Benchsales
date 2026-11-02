"""Database concurrency: background writers (collection, the auth-tag
backfill, the backup stamp) must never make page reads fail with
"database is locked". That failure mode intermittently blanked views
— the Matches consultant filter never populated because the view's
first await (GET /api/consultants) 500'd while a write lock was held.
The fix: WAL mode + busy_timeout on every connection, and the
backfill committing in small chunks outside the classify step."""
import tempfile
import threading
import time
import unittest
from pathlib import Path

from app import db


class ConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_conn_pragmas(self):
        with db.get_conn() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            busy = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        self.assertEqual(mode, "wal")
        self.assertEqual(busy, 30000)

    def _hold_write_lock(self, hold_seconds=0.4):
        """A worker thread holds an open write transaction (its own
        connection — sqlite connections are thread-affine). Returns
        the thread once the lock is held."""
        locked = threading.Event()

        def worker():
            conn = db.get_conn()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "UPDATE settings SET value='x'"
                    " WHERE key='backup_stamp'")
                locked.set()
                time.sleep(hold_seconds)
                conn.commit()
            finally:
                conn.close()

        t = threading.Thread(target=worker)
        t.start()
        self.assertTrue(locked.wait(5))
        return t

    def test_reader_survives_open_write_transaction(self):
        db.create_consultant({"name": "Reader Test"})
        t = self._hold_write_lock(0.6)
        try:
            # a page read must still succeed while the writer holds
            rows = db.list_consultants()
            self.assertEqual([r["name"] for r in rows], ["Reader Test"])
        finally:
            t.join()

    def test_writer_waits_instead_of_erroring(self):
        t = self._hold_write_lock(0.4)
        try:
            # this write overlaps the held lock: it must wait (busy
            # timeout) and succeed, not raise "database is locked"
            db.log_activity("tailor", "waited out the lock")
        finally:
            t.join()
        kinds = [e["kind"] for e in db.list_activity(5)]
        self.assertIn("tailor", kinds)

    def test_backfill_runs_while_reads_continue(self):
        db.create_consultant({"name": "Backfill Test"})
        with db.get_conn() as conn:
            for i in range(120):
                conn.execute(
                    "INSERT INTO jobs(source, source_id, title, company,"
                    " location, url, description, fetched_at, auth_tag)"
                    " VALUES ('test', ?, ?, 'Co', 'Remote', ?,"
                    " 'No sponsorship available for this role.',"
                    " '2026-11-02T00:00:00Z', NULL)",
                    (f"t{i}", f"Job {i}", f"http://x/{i}"))
            conn.commit()
        errors = []

        def reader():
            try:
                for _ in range(20):
                    db.list_consultants()
                    time.sleep(0.01)
            except Exception as e:  # noqa: BLE001 - recorded, asserted
                errors.append(e)

        rt = threading.Thread(target=reader)
        rt.start()
        filled = 0
        while True:
            n = db.backfill_auth_tags(batch=40)
            if not n:
                break
            filled += n
        rt.join()
        self.assertEqual(errors, [])
        self.assertEqual(filled, 120)
        with db.get_conn() as conn:
            left = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE auth_tag IS NULL"
            ).fetchone()[0]
            tagged = conn.execute(
                "SELECT COUNT(*) FROM jobs"
                " WHERE auth_tag='no_sponsorship'").fetchone()[0]
        self.assertEqual(left, 0)
        self.assertEqual(tagged, 120)


if __name__ == "__main__":
    unittest.main()
