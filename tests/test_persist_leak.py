"""Regression: persist backup/restore must not leak temp snapshot folders.

backup() runs every 20s per database; before the Nov 14, 2026 fix each call
left its tempfile.mkdtemp() folder behind forever, and the accumulation
saturated the host until every route returned 500 (Nov 13-14 outages).
"""
import glob
import tempfile
import unittest
from pathlib import Path

from app import db, persist


class FakeStore:
    def __init__(self):
        self.files = {}
    def exists(self, name):
        return name in self.files
    def put(self, name, path):
        self.files[name] = open(path, "rb").read()
    def get(self, name, path):
        open(path, "wb").write(self.files[name])


def _snap_dirs():
    out = set()
    for p in glob.glob(str(Path(tempfile.gettempdir()) / "tmp*")):
        if Path(p, "snapshot.db").exists() or Path(p, "restore.db").exists():
            out.add(p)
    return out


class PersistLeakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = db.DB_PATH
        self.old_sig = persist._last_sig
        persist._last_sig = {}
        db.DB_PATH = Path(self.tmp.name) / "a" / "b.db"
        self.store = FakeStore()

    def tearDown(self):
        db.DB_PATH = self.old
        persist._last_sig = self.old_sig
        self.tmp.cleanup()

    def test_backup_and_restore_leave_no_temp_snapshots(self):
        db.init_db()
        db.set_setting("k", "v1")
        before = _snap_dirs()
        self.assertTrue(persist.backup(self.store))
        db.set_setting("k", "v2")
        self.assertTrue(persist.backup(self.store, force=True))
        db.DB_PATH.unlink()
        self.assertTrue(persist.restore(self.store))
        self.assertEqual(_snap_dirs() - before, set())


if __name__ == "__main__":
    unittest.main()
