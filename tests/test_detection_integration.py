from datetime import date

import pandas as pd
import pytest

import config
from data.errors import DataQualityError
from models.detectors import isolation_forest
from services import alerts, clients, detection, prefetch
from services.contracts import Explanation, InputError


@pytest.fixture
def prepared(monkeypatch, make_prices, tmp_path):
    # Include both pre-cutoff training history and later, unused observations.
    prices = make_prices(n=1800, end="2026-11-04")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(detection, "load_history", lambda *args: (prices, {}))
    detection._detect.cache_clear()
    yield prices
    detection._detect.cache_clear()


def test_adapter_matches_stage_c_and_excludes_later_prices(prepared):
    prices, flags = detection.snapshot("KO", "balanced")
    assert prices.index.max().date() <= config.MONITORING_END
    expected, metadata = isolation_forest(prices, train_before=config.MONITORING_START, profiles=("balanced",))
    frame = expected["balanced"]
    expected_days = frame.index[frame.is_scored & frame.is_anomaly]
    assert {flag.day for flag in flags} == {day.date() for day in expected_days}
    assert pd.Timestamp(metadata["calibration_end"]).date() < config.MONITORING_START
    for flag in flags:
        assert flag.detector == "isolation_forest"
        assert flag.score == pytest.approx(float(frame.loc[pd.Timestamp(flag.day), "score"]))
        assert "[FAKE]" not in flag.summary


def test_future_changes_cannot_change_earlier_flags(monkeypatch, prepared):
    first = detection.get_flags("KO", "balanced")
    changed = prepared.copy()
    future = changed.index > pd.Timestamp("2026-05-01")
    changed.loc[future, ["Open", "Close"]] *= 10
    monkeypatch.setattr(detection, "load_history", lambda *args: (changed, {}))
    detection._detect.cache_clear()
    second = detection.get_flags("KO", "balanced")
    assert [f for f in first if f.day < date(2026, 5, 1)] == [f for f in second if f.day < date(2026, 5, 1)]


def test_override_changes_sensitivity_monotonically(prepared):
    sensitive = {f.day for f in detection.get_flags("KO", "balanced", 2.0)}
    middle = {f.day for f in detection.get_flags("KO", "balanced", 3.0)}
    strict = {f.day for f in detection.get_flags("KO", "balanced", 4.0)}
    assert strict <= middle <= sensitive
    assert len(sensitive) > len(strict)
    assert detection.forest_quantile("balanced", 3.0) == config.PROFILES["balanced"]["iforest_quantile"]


def test_cached_prices_cannot_be_mutated_by_a_caller(prepared):
    prices, _ = detection.snapshot("KO", "balanced")
    original = prices.Close.iloc[0]
    prices.iloc[0, prices.columns.get_loc("Close")] = -1
    assert detection.snapshot("KO", "balanced")[0].Close.iloc[0] == original


def test_insufficient_history_is_an_error_not_no_alerts(monkeypatch, prepared):
    monkeypatch.setattr(detection, "load_history", lambda *args: (prepared.tail(100), {}))
    with pytest.raises(DataQualityError, match="insufficient"):
        detection.get_flags("KO", "balanced")


@pytest.mark.parametrize("profile,override", [("invalid", None), ("balanced", 8), ("balanced", float("nan"))])
def test_bad_settings_rejected(profile, override):
    with pytest.raises(InputError):
        detection.forest_quantile(profile, override)


def test_alerts_and_prefetch_share_real_flags_and_settings(monkeypatch):
    one = clients.add_client("One", "conservative")
    two = clients.add_client("Two", "balanced")
    for client in (one, two):
        clients.add_holding(client.client_id, "KO")
    clients.set_sensitivity_override(one.client_id, 2.2)
    flags = (
        detection.Flag("KO", date(2026, 3, 12), "isolation_forest", 0.7, "high", "First real flag."),
        detection.Flag("KO", date(2026, 3, 13), "isolation_forest", 0.6, "low", "Second real flag."),
    )
    calls, explanations = [], []

    def get_flags(*args):
        calls.append(args)
        return flags

    def explain(ticker, day, summary):
        explanations.append((ticker, day, summary))
        return Explanation("Not prepared.", "unavailable")

    monkeypatch.setattr(detection, "get_flags", get_flags)
    monkeypatch.setattr(alerts, "explain", explain)
    result = alerts.get_alerts(one.client_id)
    assert len(result) == 2 and all(a.client_id == one.client_id for a in result)
    assert all(a.explanation_status == "unavailable" for a in result)
    assert explanations == [(flag.ticker, flag.day, flag.summary) for flag in flags]
    assert calls[0] == ("KO", "conservative", 2.2)
    assert prefetch.alert_pairs() == [(f.ticker, f.day, f.summary) for f in flags]
    assert len(prefetch.ticker_pairs(["KO"], ["balanced", "conservative"])) == 2


def test_alert_prefetch_cli_uses_detection_before_generation(monkeypatch):
    pair = ("KO", date(2026, 3, 12), "Actual summary.")
    monkeypatch.setattr(prefetch, "alert_pairs", lambda: [pair])
    seen = []

    def generate(*args):
        seen.append(args)
        return Explanation("No clear news found for this move.", "no_news")

    monkeypatch.setattr(prefetch, "explain", generate)
    assert prefetch.main(["--alerts"]) == 0
    assert seen == [pair]
