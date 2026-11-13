"""Search rotation (Nov 13 2026): sources without built-in rotation
(Dice, Monster, SmartRecruiters, Phenom) used to run their searches
in the same fixed order every run, so when the 4-minute source
budget cut a run short it was the same tail searches that never ran
— SmartRecruiters left 11 searches on three straight live runs.
Now each run starts where the last one stopped, the offset persists
in settings, and across successive runs every search gets its turn.
Adzuna and JSearch keep their existing usage-based rotation and are
not touched by this one.
"""
import json
import tempfile
import unittest
from pathlib import Path

import collector
from app import db

QUERIES = [{"title": f"Q{i}"} for i in range(10)]


def titles(qs):
    return [q["title"] for q in qs]


class RotationHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_first_run_starts_at_the_top(self):
        rotated, off = collector._apply_rotation("dice", QUERIES)
        self.assertEqual(off, 0)
        self.assertEqual(titles(rotated), titles(QUERIES))

    def test_two_cut_short_runs_cover_every_search(self):
        # run 1: completes 6 of 10 before the budget stops it
        rotated, off = collector._apply_rotation("smartrecruiters", QUERIES)
        done1 = titles(rotated[:6])
        collector._advance_rotation("smartrecruiters", off, 6, len(rotated))
        # run 2: starts at Q6, completes 6 more (wrapping around)
        rotated2, off2 = collector._apply_rotation("smartrecruiters", QUERIES)
        self.assertEqual(off2, 6)
        self.assertEqual(titles(rotated2)[:4], ["Q6", "Q7", "Q8", "Q9"])
        done2 = titles(rotated2[:6])
        self.assertEqual(set(done1) | set(done2), set(titles(QUERIES)))
        collector._advance_rotation("smartrecruiters", off2, 6, len(rotated2))
        # run 3 starts at Q2 — the wheel keeps turning
        _, off3 = collector._apply_rotation("smartrecruiters", QUERIES)
        self.assertEqual(off3, 2)

    def test_full_run_leaves_the_offset_alone(self):
        db.set_setting("rotate_offset_dice", "4")
        rotated, off = collector._apply_rotation("dice", QUERIES)
        collector._advance_rotation("dice", off, len(rotated), len(rotated))
        self.assertEqual(db.get_setting("rotate_offset_dice"), "4")

    def test_offset_survives_a_shrinking_query_list(self):
        db.set_setting("rotate_offset_phenom", "9")
        rotated, off = collector._apply_rotation("phenom", QUERIES[:5])
        self.assertEqual(off, 4)   # 9 % 5 — wraps instead of breaking
        self.assertEqual(titles(rotated)[0], "Q4")

    def test_non_rotating_sources_are_untouched(self):
        db.set_setting("rotate_offset_adzuna", "3")
        rotated, off = collector._apply_rotation("adzuna", QUERIES)
        self.assertEqual(off, 0)
        self.assertEqual(titles(rotated), titles(QUERIES))
        collector._advance_rotation("adzuna", 0, 5, len(QUERIES))
        self.assertEqual(db.get_setting("rotate_offset_adzuna"), "3")

    def test_garbage_offset_falls_back_to_zero(self):
        db.set_setting("rotate_offset_dice", "not-a-number")
        _, off = collector._apply_rotation("dice", QUERIES)
        self.assertEqual(off, 0)


class RecordingSource:
    NAME = "dice"
    LABEL = "Dice (fake)"

    calls = []

    @staticmethod
    def enabled(settings):
        return True

    @staticmethod
    def fetch(query, settings):
        RecordingSource.calls.append(query["title"])
        return []


class RotationIntegrationTests(unittest.TestCase):
    """End-to-end through collector.run(): with no budget pressure a
    rotating source runs every search in order and the offset stays
    put; the persisted offset is what the NEXT run reads."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()
        db.set_setting("enabled_sources", json.dumps(["dice"]))
        RecordingSource.calls = []

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_run_uses_the_persisted_offset(self):
        db.set_setting("rotate_offset_dice", "7")
        orig_sources = collector.SOURCES
        orig_prepare = collector._prepare_all
        collector.SOURCES = [RecordingSource]
        collector._prepare_all = lambda deadline=None: (
            [dict(q) for q in QUERIES], {str(db.DB_PATH): {}})
        try:
            collector.run()
        finally:
            collector.SOURCES = orig_sources
            collector._prepare_all = orig_prepare
        self.assertEqual(RecordingSource.calls,
                         ["Q7", "Q8", "Q9", "Q0", "Q1", "Q2",
                          "Q3", "Q4", "Q5", "Q6"])
        # the run finished everything, so the offset stays at 7
        self.assertEqual(db.get_setting("rotate_offset_dice"), "7")


if __name__ == "__main__":
    unittest.main()
