from datetime import date

import pandas as pd

from services import prefetch
from services.contracts import Explanation


def test_prefetch_counts_each_status(monkeypatch):
    statuses = iter(["ok", "no_news", "unavailable", "ok"])
    monkeypatch.setattr(prefetch, "explain", lambda ticker, day, summary: Explanation("t", next(statuses)))
    pairs = [("KO", date(2026, 3, 12), "s")] * 4
    assert prefetch.prefetch(pairs) == {"ok": 2, "no_news": 1, "unavailable": 1}


def test_event_pairs_use_the_first_trading_day(monkeypatch):
    events = pd.DataFrame({"ticker": ["KO"], "first_trading_day": pd.to_datetime(["2026-03-12"])})
    monkeypatch.setattr(prefetch, "load_events", lambda: events)
    assert prefetch.event_pairs() == [("KO", date(2026, 3, 12), prefetch.STANDARD_SUMMARY)]


def test_exit_code_signals_unavailable_explanations(monkeypatch):
    monkeypatch.setattr(prefetch, "event_pairs", lambda: [("KO", date(2026, 3, 12), "s")])
    monkeypatch.setattr(prefetch, "explain", lambda t, d, s: Explanation("t", "unavailable"))
    assert prefetch.main(["--events"]) == 1
    monkeypatch.setattr(prefetch, "explain", lambda t, d, s: Explanation("t", "ok"))
    assert prefetch.main(["--events"]) == 0


def test_missing_flag_prints_usage():
    assert prefetch.main([]) == 2
