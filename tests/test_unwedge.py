"""Unwedging (Nov 4 2026): a runaway collection froze the scheduler —
and the office that rode its loop — for 9+ hours. Defenses: a per-source
wall-clock budget in the collector, collections kicked onto threads, and
the office on its own loop."""
import inspect
import tempfile
import time
import types
import unittest
from pathlib import Path

import collector
from app import db
from app import server


class CollectorBudgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = db.DB_PATH
        db.DB_PATH = Path(self.tmp.name) / "bench.db"
        db.init_db()

    def tearDown(self):
        db.DB_PATH = self._old
        self.tmp.cleanup()

    def test_source_budget_stops_a_source_before_it_starts(self):
        calls = []
        fake = types.SimpleNamespace(
            NAME="dice", LABEL="Dice",
            enabled=lambda settings: True,
            fetch=lambda q, settings: calls.append(q) or [])
        orig_sources, orig_budget = collector.SOURCES, collector.SOURCE_BUDGET_SECONDS
        orig_prepare = collector._prepare_all
        collector.SOURCES = [fake]
        collector.SOURCE_BUDGET_SECONDS = 0
        collector._prepare_all = lambda: ([{"title": "Java", "location": ""}],
                                          {str(db.DB_PATH): {}})
        try:
            summary = collector.run()
        finally:
            collector.SOURCES, collector.SOURCE_BUDGET_SECONDS = orig_sources, orig_budget
            collector._prepare_all = orig_prepare
        assert calls == []                      # never fetched: budget already spent
        st = summary["sources"]["dice"]["status"]
        assert "budget" in st, st


class LoopShapeTests(unittest.TestCase):
    def test_office_has_its_own_loop(self):
        assert hasattr(server, "_office_loop")
        assert "_maybe_run_office" in inspect.getsource(server._office_loop)
        assert "_maybe_run_office" not in inspect.getsource(server._auto_collect_loop)
        assert "_do_collect()" not in inspect.getsource(server._auto_collect_loop)


class KickTests(unittest.TestCase):
    def test_kick_claims_running_and_releases(self):
        orig = server._do_collect
        server._do_collect = lambda: time.sleep(0.4)
        server._collect_status["running"] = False
        try:
            assert server._kick_collect() is True
            assert server._kick_collect() is False   # already claimed
            deadline = time.time() + 5
            while server._collect_status["running"] and time.time() < deadline:
                time.sleep(0.05)
            assert server._collect_status["running"] is False
            assert server._kick_collect() is True    # free again afterwards
            deadline = time.time() + 5
            while server._collect_status["running"] and time.time() < deadline:
                time.sleep(0.05)
        finally:
            server._do_collect = orig
            server._collect_status["running"] = False
