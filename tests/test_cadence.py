"""Refresh cadence: hourly collections, office every few hours (Nov 2)."""

from datetime import datetime, timedelta, timezone

from app import autolearn


def _settings(**over):
    s = {"collect_interval_minutes": "60",
         "enabled_sources": '["adzuna"]',
         "adzuna_app_id": "x", "adzuna_app_key": "y",
         "adzuna_daily_budget": "80"}
    s.update(over)
    return s


def test_budget_cannot_push_interval_past_hourly(monkeypatch):
    monkeypatch.setattr(autolearn, "queries_for_run",
                        lambda settings: [{"title": "x"}] * 10)
    # cost 20/run, budget 80 -> 4 runs/day -> old math slowed to 360 min
    assert autolearn.effective_interval_minutes(_settings()) == 60


def test_slower_choice_is_respected(monkeypatch):
    monkeypatch.setattr(autolearn, "queries_for_run",
                        lambda settings: [{"title": "x"}] * 2)
    assert autolearn.effective_interval_minutes(
        _settings(collect_interval_minutes="120",
                  adzuna_daily_budget="240")) == 120


def test_office_due_gate():
    from app.server import _office_due
    now = datetime(2026, 11, 2, 22, 0, tzinfo=timezone.utc)
    assert _office_due("", now) is True
    assert _office_due("garbage", now) is True
    assert _office_due((now - timedelta(hours=1)).isoformat(), now) is False
    assert _office_due((now - timedelta(hours=5)).isoformat(), now) is True
