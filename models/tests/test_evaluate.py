import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

import config
from data.errors import DataQualityError
from models.evaluate import (
    evaluate_predictions,
    export_detected_events,
    format_evaluation_report,
    main,
    read_events,
    resolve_events_source,
)
from models.history import history_start, load_history


def predictions(dates, flags, ticker="KO", scored=None):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "ticker": ticker,
            "model": "fixed_threshold",
            "profile": "balanced",
            "is_anomaly": flags,
            "is_scored": [True] * len(dates) if scored is None else scored,
            "score": 0.06,
            "threshold": 0.05,
            "close_price": 123.4,
            "daily_return": 0.06,
        }
    )


def events(*rows):
    return pd.DataFrame(
        [
            dict(
                {
                    "event_id": f"E{i}",
                    "ticker": "KO",
                    "first_trading_day": "2026-02-05",
                    "category": "Earnings surprise",
                },
                **row,
            )
            for i, row in enumerate(rows)
        ]
    )


def test_exact_day_only_no_adjacent_day_credit():
    p = predictions(["2026-02-04", "2026-02-05", "2026-02-06"], [True, False, True])
    summary, audit, alerts = evaluate_predictions(p, events({}))
    assert audit.status.tolist() == ["miss"]
    assert summary.iloc[0].event_recall == 0
    assert alerts.status.tolist() == ["unlabelled", "unlabelled"]


def test_selected_event_recall_and_no_invented_negatives():
    p = predictions(["2026-02-04", "2026-02-05", "2026-02-06"], [True, True, False])
    summary, audit, alerts = evaluate_predictions(p, events({}, {"first_trading_day": "2026-02-06"}))
    row = summary.iloc[0]
    assert row.split == "all"
    assert row.events_hit == 1 and row.events_missed == 1
    assert row.event_recall == 0.5 and row.detection_rate_pct == 50
    assert row.coverage_pct == 100
    assert row[["false_positive", "true_negative", "precision", "f1_score", "accuracy"]].isna().all()
    assert audit.iloc[0].close_price == 123.4
    assert alerts.status.tolist() == ["unlabelled", "matched"]
    report = format_evaluation_report(summary)
    assert "Event recall: 50.00%" in report and "Overall accuracy: N/A" in report


def test_market_wide_events_and_company_events_on_same_day_are_included():
    summary, audit, _ = evaluate_predictions(
        predictions(["2026-02-05"], [True]), events({"category": config.MARKET_WIDE_CATEGORY}, {})
    )
    assert audit.status.tolist() == ["hit", "hit"]
    assert summary.iloc[0].events_hit == 2 and summary.iloc[0].event_recall == 1


def test_missing_data_is_unscored_and_coverage_is_explicit():
    p = predictions(["2026-02-05", "2026-02-06"], [True, False], scored=[True, False])
    summary, audit, _ = evaluate_predictions(
        p, events({}, {"first_trading_day": "2026-02-06"}, {"first_trading_day": "2026-02-09"})
    )
    assert audit.status.tolist() == ["hit", "unscored_insufficient_history", "unscored_missing_date"]
    assert summary.iloc[0].events_unscored == 2
    assert summary.iloc[0].coverage_pct == pytest.approx(100 / 3)
    assert summary.iloc[0].event_recall == 1


def test_wrong_ticker_does_not_match():
    p = predictions(["2026-02-05"], [True], ticker="PG")
    summary, _, alerts = evaluate_predictions(p, events({}))
    assert summary.iloc[0].scored_events == 0
    assert pd.isna(summary.iloc[0].recall)
    assert alerts.iloc[0].status == "unlabelled"


def test_split_boundary_and_all_summary():
    p = predictions(["2026-04-30", "2026-05-01"], [False, True])
    summary, _, _ = evaluate_predictions(
        p, events({"first_trading_day": "2026-04-30"}, {"first_trading_day": "2026-05-01"})
    )
    assert summary.split.tolist() == ["all", "dev", "test"]
    assert summary.event_recall.tolist() == [0.5, 0, 1]


def test_duplicate_predictions_rejected():
    with pytest.raises(ValueError, match="one row"):
        evaluate_predictions(predictions(["2026-02-05"] * 2, [True, True]), events({}))


def test_alert_rate_includes_unlisted_alerts_and_counts_stock_days_once():
    p = pd.concat(
        [
            predictions(["2026-02-04", "2026-02-05", "2026-02-06"], [True, True, False]),
            predictions(["2026-02-05", "2026-02-06"], [False, False], ticker="PG", scored=[True, False]),
        ],
        ignore_index=True,
    )
    summary, _, _ = evaluate_predictions(p, events({}, {}))
    row = summary.iloc[0]
    assert row.events_hit == 2 and row.event_recall == 1
    assert row.scored_ticker_days == 4 and row.total_alerts == 2
    assert row.alert_rate == 0.5 and row.alerts_per_100_days == 50
    assert "Alert rate: 50.00 per 100 stock-days (2 alerts / 4 scored stock-days)" in format_evaluation_report(summary)
    assert pd.isna(row.false_positive)


def test_alert_rate_zero_alerts_and_no_scored_days():
    p = predictions(["2026-04-30", "2026-05-01"], [False, False], scored=[True, False])
    summary, _, _ = evaluate_predictions(p, events({"first_trading_day": "2026-04-30"}))
    all_rows, dev, test = summary.iloc[0], summary.iloc[1], summary.iloc[2]
    assert all_rows.alert_rate == 0 and dev.alert_rate == 0
    assert test.scored_ticker_days == 0 and pd.isna(test.alert_rate)
    assert "Alert rate: N/A" in format_evaluation_report(summary)


def test_alert_rate_is_calculated_separately_for_each_split():
    p = predictions(["2026-04-29", "2026-04-30", "2026-05-01"], [True, False, True])
    summary, _, _ = evaluate_predictions(p, events({"first_trading_day": "2026-04-30"}))
    assert summary.alert_rate.tolist() == [2 / 3, 0.5, 1]


@pytest.mark.parametrize("sep", [",", ";"])
def test_minimal_csv_and_conflicting_shared_ids_are_supported(tmp_path, sep):
    frame = events({"first_trading_day": "2019-01-07", "shared_event_id": "conflict"}, {"shared_event_id": "conflict"})
    path = tmp_path / "events.csv"
    frame.to_csv(path, index=False, sep=sep, encoding="utf-8-sig")
    original = path.read_bytes()
    loaded = read_events(path)
    assert len(loaded) == 2
    assert loaded.first_trading_day.iloc[0] == pd.Timestamp("2019-01-07")
    assert loaded.shared_event_id.tolist() == ["", ""]
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    "overrides",
    [{"ticker": "NOPE"}, {"first_trading_day": "bad"}, {"first_trading_day": "2026-02-07"}, {"event_id": ""}],
)
def test_invalid_essential_fields_fail(tmp_path, overrides):
    path = tmp_path / "events.csv"
    events(overrides).to_csv(path, index=False)
    with pytest.raises(DataQualityError):
        read_events(path)


def test_examples_are_excluded(tmp_path):
    path = tmp_path / "events.csv"
    events({}, {"ticker": "INVALID", "is_example": "TRUE"}).to_csv(path, index=False)
    assert len(read_events(path)) == 1


def test_source_resolution_uses_data_folder(monkeypatch, tmp_path):
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", folder)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    sample = folder / "newData.csv"
    sample.write_text("", encoding="utf-8")
    assert resolve_events_source(None) == sample
    assert resolve_events_source("newData.csv") == sample
    assert resolve_events_source("data/newData.csv") == sample
    (folder / "other.csv").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="Multiple"):
        resolve_events_source(None)
    canonical = folder / "events.csv"
    canonical.write_text("", encoding="utf-8")
    assert resolve_events_source(None) == canonical


def make_history():
    dates = pd.bdate_range("2016-11-04", "2026-11-04", name="Date")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(12).normal(0, 0.01, len(dates))))
    return pd.DataFrame({"Open": close, "Close": close, "Volume": 1_000_000}, index=dates)


def test_ten_year_download_cache_and_refresh(monkeypatch, tmp_path):
    calls = []

    def download(ticker, start, end):
        calls.append((ticker, start, end))
        return make_history()

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr("models.history.download_prices", download)
    as_of = date(2026, 11, 4)
    first, meta = load_history("KO", as_of)
    second, _ = load_history("KO", as_of)
    assert len(calls) == 1
    assert calls[0] == ("KO", date(2016, 11, 4), as_of)
    assert len(first) == len(second) and meta["requested_start"] == "2016-11-04"
    load_history("KO", as_of, refresh=True)
    assert len(calls) == 2
    assert history_start(date(2024, 2, 29)) == date(2014, 2, 28)


def test_full_default_workflow_downloads_runs_and_evaluates(monkeypatch, tmp_path, capsys):
    folder = tmp_path / "data"
    folder.mkdir()
    events({}).to_csv(folder / "sample.csv", index=False)
    monkeypatch.setattr(config, "DATA_DIR", folder)
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr("models.evaluate.default_as_of", lambda: date(2026, 11, 4))
    calls = []

    def download(ticker, start, end):
        calls.append((ticker, start, end))
        return make_history()

    monkeypatch.setattr("models.history.download_prices", download)
    output = tmp_path / "output"
    assert main(["--profiles", "balanced", "--output", str(output)]) == 0
    assert calls == [("KO", date(2016, 11, 4), date(2026, 11, 4))]
    summary = pd.read_csv(output / "metrics.csv")
    assert len(summary) == 9 and summary.precision.isna().all()
    audit = pd.read_csv(output / "event_matches.csv")
    assert len(audit) == 3 and audit.close_price.notna().all()
    assert "Event recall:" in capsys.readouterr().out
    assert "first_trading_day" in (output / "metrics.txt").read_text(encoding="utf-8")
    assert (config.RESULTS_DIR / "detected_events.json").exists()


def test_detected_json_deduplicates_hits_and_clears_previous_results(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path / "results")
    audit = pd.DataFrame(
        {
            "status": ["hit", "hit", "miss", "unscored_missing_date"],
            "ticker": ["KO", "KO", "PG", "V"],
            "first_trading_day": pd.to_datetime(["2026-02-05"] * 4),
        }
    )
    path = export_detected_events(audit)
    assert json.loads(path.read_text(encoding="utf-8")) == [{"flag": True, "event_date": "2026-02-05", "ticker": "KO"}]
    audit["status"] = "miss"
    export_detected_events(audit)
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_no_sheet_fails_before_download(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    assert main([]) == 1
