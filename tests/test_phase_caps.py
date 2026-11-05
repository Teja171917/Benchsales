"""Per-phase caps (Nov 4 2026, evening): the unwedge budgets bounded each
fetch source, but a run still sat 40+ minutes in the post-fetch tail
(matching) after every source had reported, with status showing only
"running". Now prepare and match have wall-clock budgets too, the long
scoring loops raise matcher.PhaseTimeout when a budget is spent, the
collector marks the phase partial and STILL finishes the run, and the
status endpoint names the live phase."""
import inspect
import tempfile
import time
import unittest
from pathlib import Path

import collector
from app import autolearn, db, matcher, server


def past():
    return time.monotonic() - 1


class DeadlineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_matcher_loops_raise_on_spent_deadline(self):
        with self.assertRaises(matcher.PhaseTimeout):
            matcher.run_all(deadline=past())
        with self.assertRaises(matcher.PhaseTimeout):
            matcher.prune_misfits(deadline=past())
        with self.assertRaises(matcher.PhaseTimeout):
            matcher.rescore_existing(deadline=past())

    def test_maintain_raises_on_spent_deadline(self):
        with self.assertRaises(matcher.PhaseTimeout):
            autolearn.maintain(deadline=past())

    def test_no_deadline_means_no_raise(self):
        assert matcher.run_all() == 0
        assert matcher.prune_misfits() == 0
        assert matcher.rescore_existing() == 0
        assert autolearn.maintain()["rescored"] == 0


class CollectorPhaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_match_timeout_marks_phase_partial_and_run_finishes(self):
        orig_sources = collector.SOURCES
        orig_prepare = collector._prepare_all
        orig_run_all = matcher.run_all

        def boom(deadline=None):
            raise matcher.PhaseTimeout("spent")

        collector.SOURCES = []
        collector._prepare_all = lambda deadline=None: (
            [{"title": "Java", "location": ""}], {str(db.DB_PATH): {}})
        matcher.run_all = boom
        try:
            summary = collector.run()
        finally:
            collector.SOURCES = orig_sources
            collector._prepare_all = orig_prepare
            matcher.run_all = orig_run_all
        assert "finished" in summary
        match = summary["phases"]["match"]
        assert match["status"].startswith("partial"), match
        assert "budget" in match["status"]
        assert any("matcher" in e and "budget" in e
                   for e in summary["errors"]), summary["errors"]
        assert collector.PROGRESS["phase"] is None
        assert collector.PROGRESS["run_started"] is None

    def test_phases_are_timed_and_recorded(self):
        orig_sources = collector.SOURCES
        collector.SOURCES = []
        try:
            summary = collector.run()
        finally:
            collector.SOURCES = orig_sources
        for name in ("prepare", "fetch", "match"):
            ph = summary["phases"][name]
            assert ph["seconds"] >= 0, ph
            assert ph["status"] == "ok", ph


class StatusShapeTests(unittest.TestCase):
    def test_status_reports_live_phase(self):
        src = inspect.getsource(server.api_collect_status)
        assert '"phase"' in src and "PROGRESS" in src

    def test_last_result_carries_phases(self):
        assert '"phases"' in inspect.getsource(server._do_collect)


if __name__ == "__main__":
    unittest.main()
