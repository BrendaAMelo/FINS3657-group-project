from __future__ import annotations

import pandas as pd
import pytest

import config
from data.errors import DataQualityError
from data.events import REQUIRED_COLUMNS
from models.evaluate import evaluate_predictions, format_evaluation_report, main, read_events, sheet_csv_url


def predictions(dates, flags, ticker="KO", scored=None):
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates),
            "ticker": ticker,
            "model": "fixed_threshold",
            "profile": "balanced",
            "is_anomaly": flags,
            "is_scored": [True] * len(dates) if scored is None else scored,
        }
    )


def events(*rows):
    records = []
    for i, row in enumerate(rows):
        values = {
            "event_id": f"E{i}",
            "ticker": "KO",
            "tier": "calm",
            "category": "Earnings surprise",
            "first_trading_day": "2026-02-05",
        }
        values.update(row)
        records.append(values)
    return pd.DataFrame(records)


def test_match_window_is_forward_calendar_days_not_trading_days():
    p = predictions(["2026-02-05", "2026-02-06", "2026-02-09"], [True, False, True])
    summary, audit, alerts = evaluate_predictions(p, events({"first_trading_day": "2026-02-06"}))
    assert audit.status.tolist() == ["miss"]  # Thursday is early, Monday outside +1 calendar day.
    assert summary.iloc[0].event_recall == 0
    assert alerts.status.tolist() == ["unmatched", "unmatched"]


def test_repeated_alerts_count_one_event_hit_and_two_matched_days():
    p = predictions(["2026-02-05", "2026-02-06"], [True, True])
    summary, audit, alerts = evaluate_predictions(p, events({}))
    assert summary.iloc[0].events_hit == 1
    assert summary.iloc[0].matched_alerts == 2
    assert summary.iloc[0].event_recall == 1
    assert audit.iloc[0].matched_alert_count == 2
    assert len(alerts) == 2


def test_one_flag_can_cover_multiple_same_day_sheet_events_without_duplicate_alerts():
    p = predictions(["2026-02-05"], [True])
    summary, _, alerts = evaluate_predictions(p, events({}, {}))
    assert summary.iloc[0].events_hit == 2
    assert summary.iloc[0].matched_alerts == 1
    assert alerts.iloc[0].matched_event_ids == "E0|E1"


def test_wrong_ticker_is_not_a_match():
    p = pd.concat(
        [predictions(["2026-02-05"], [False]), predictions(["2026-02-05"], [True], ticker="PG")], ignore_index=True
    )
    _, audit, alerts = evaluate_predictions(p, events({}))
    assert audit.iloc[0].status == "miss"
    assert alerts.iloc[0].status == "unmatched"


def test_market_wide_days_are_globally_unscored():
    p = predictions(["2026-02-05", "2026-02-06"], [True, False], ticker="PG")
    summary, audit, alerts = evaluate_predictions(p, events({"category": config.MARKET_WIDE_CATEGORY}))
    assert audit.iloc[0].status == "unscored_market_wide"
    assert alerts.iloc[0].status == "unscored_market_wide"
    assert summary.iloc[0].scored_alerts == 0
    assert pd.isna(summary.iloc[0].event_recall)


def test_missing_prediction_is_not_counted_as_a_miss():
    p = predictions(["2026-02-06"], [True])
    summary, audit, _ = evaluate_predictions(p, events({}))
    assert audit.iloc[0].status == "unscored_missing_first_day"
    assert summary.iloc[0].events_missed == 0
    assert summary.iloc[0].events_unscored == 1


def test_alert_cannot_cross_dev_test_boundary():
    p = predictions(["2026-04-30", "2026-05-01"], [False, True])
    summary, audit, alerts = evaluate_predictions(p, events({"first_trading_day": "2026-04-30"}))
    assert audit.iloc[0].status == "miss"
    assert alerts.iloc[0].status == "unmatched"
    assert summary.iloc[1].split == "test"


def test_no_alerts_has_undefined_match_rate():
    p = predictions(["2026-02-05"], [False])
    summary, _, alerts = evaluate_predictions(p, events({}))
    assert pd.isna(summary.iloc[0].sheet_match_rate)
    assert summary.iloc[0].event_recall == 0
    assert alerts.empty


def test_duplicate_predictions_rejected():
    p = predictions(["2026-02-05", "2026-02-05"], [True, True])
    with pytest.raises(ValueError, match="one row"):
        evaluate_predictions(p, events({}))


def test_empty_events_rejected():
    with pytest.raises(ValueError, match="No non-example"):
        evaluate_predictions(predictions(["2026-02-05"], [True]), pd.DataFrame())


@pytest.mark.parametrize(
    ("url", "ending"),
    [
        ("https://docs.google.com/spreadsheets/d/abc_123/edit#gid=42", "format=csv&gid=42"),
        ("https://docs.google.com/spreadsheets/d/abc_123/edit?gid=17", "format=csv&gid=17"),
        ("https://docs.google.com/spreadsheets/d/e/abc/pub?output=html", "output=csv"),
    ],
)
def test_sheet_urls_select_correct_tab(url, ending):
    assert sheet_csv_url(url).endswith(ending)


def test_non_google_url_rejected():
    with pytest.raises(ValueError, match="docs.google.com"):
        sheet_csv_url("https://example.com/spreadsheets/d/abc")


def test_events_loader_reuses_schema_and_excludes_examples(tmp_path):
    row = dict.fromkeys(REQUIRED_COLUMNS, "")
    row.update(
        event_id="E1",
        ticker="KO",
        tier="calm",
        category="Earnings surprise",
        event_description="An event",
        announcement_date="2026-02-05",
        announcement_timing="intraday",
        first_trading_day="2026-02-05",
        source_type="primary",
        primary_source_url="https://example.com",
    )
    path = tmp_path / "events.csv"
    pd.DataFrame([row, dict(row, event_id="example", is_example="TRUE")]).to_csv(path, index=False)
    result = read_events(path)
    assert result.event_id.tolist() == ["E1"]
    assert result.split.tolist() == ["dev"]


def test_private_sheet_gives_actionable_error(monkeypatch):
    class Response:
        headers = {"Content-Type": "text/html"}

        def raise_for_status(self):
            pass

    monkeypatch.setattr("models.evaluate.requests.get", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="sign-in"):
        read_events("https://docs.google.com/spreadsheets/d/abc/edit")


@pytest.mark.parametrize("delimiter", [",", ";"])
@pytest.mark.parametrize("has_shared_column", [True, False])
def test_import_ignores_shared_ids_without_modifying_source(tmp_path, delimiter, has_shared_column):
    base = dict.fromkeys(REQUIRED_COLUMNS, "")
    base.update(
        ticker="KO",
        tier="calm",
        category="Market-wide shock",
        event_description='News, with "quotes";',
        announcement_timing="intraday",
        source_type="primary",
        primary_source_url="https://example.com",
        shared_event_id="FED_20260916",
    )
    rows = [
        dict(base, event_id="E019", announcement_date="2025-12-10", first_trading_day="2025-12-10"),
        dict(base, event_id="E020", announcement_date="2026-09-16", first_trading_day="2026-09-16"),
    ]
    frame = pd.DataFrame(rows)
    if not has_shared_column:
        frame = frame.drop(columns="shared_event_id")
    path = tmp_path / "events.csv"
    frame.to_csv(path, index=False, sep=delimiter, encoding="utf-8-sig")
    original = path.read_bytes()
    loaded = read_events(path)
    assert loaded.shared_event_id.tolist() == ["", ""]
    assert loaded.split.tolist() == ["dev", "test"]
    assert loaded.first_trading_day.dt.strftime("%Y-%m-%d").tolist() == ["2025-12-10", "2026-09-16"]
    assert loaded.event_description.tolist() == [base["event_description"]] * 2
    assert path.read_bytes() == original
    frame.loc[0, "ticker"] = "INVALID"
    frame.to_csv(path, index=False, sep=delimiter)
    with pytest.raises(DataQualityError, match="ticker"):
        read_events(path)


def test_missing_sheet_does_not_produce_results(tmp_path):
    assert main(["--events", str(tmp_path / "missing.csv"), "--output", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()


def test_full_cli_writes_auditable_outputs(tmp_path, monkeypatch, capsys):
    import numpy as np

    dates = pd.bdate_range("2022-01-03", "2026-10-30", name="Date")
    close = 100 * np.exp(np.cumsum(np.random.default_rng(12).normal(0, 0.01, len(dates))))
    prices = pd.DataFrame({"Open": close, "Close": close, "Volume": 1_000_000}, index=dates)
    cache = tmp_path / "prices"
    cache.mkdir()
    prices.to_csv(cache / "KO.csv")
    monkeypatch.setattr(config, "PRICE_CACHE_DIR", cache)
    row = dict.fromkeys(REQUIRED_COLUMNS, "")
    row.update(
        event_id="SYNTHETIC",
        ticker="KO",
        tier="calm",
        category="Earnings surprise",
        event_description="Synthetic integration-test event",
        announcement_date="2026-02-05",
        announcement_timing="intraday",
        first_trading_day="2026-02-05",
        source_type="primary",
        primary_source_url="https://example.com",
    )
    sheet = tmp_path / "events.csv"
    pd.DataFrame([row]).to_csv(sheet, index=False)
    output = tmp_path / "output"
    assert main(["--events", str(sheet), "--tickers", "KO", "--profiles", "balanced", "--output", str(output)]) == 0
    assert {p.name for p in output.iterdir()} == {
        "predictions.csv",
        "metrics.csv",
        "metrics.txt",
        "event_matches.csv",
        "alert_matches.csv",
        "events_snapshot.csv",
        "run_metadata.json",
    }
    assert len(pd.read_csv(output / "metrics.csv")) == 6
    assert len(pd.read_csv(output / "event_matches.csv")) == 3
    terminal = capsys.readouterr().out
    for label in ("Confusion matrix", "Precision:", "Recall:", "F1-score:"):
        assert label in terminal
        assert label in (output / "metrics.txt").read_text(encoding="utf-8")


def test_classification_counts_and_scores_use_the_same_ticker_day_unit():
    p = predictions(
        ["2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06", "2026-02-09"],
        [True, False, True, True, False, False],
    )
    summary, _, _ = evaluate_predictions(
        p, events({"first_trading_day": "2026-02-02"}, {"first_trading_day": "2026-02-04"}), match_days=0
    )
    row = summary.iloc[0]
    assert (row.true_positive, row.false_positive, row.false_negative, row.true_negative) == (2, 1, 0, 3)
    assert row.precision == pytest.approx(2 / 3)
    assert row.recall == 1
    assert row.f1_score == pytest.approx(0.8)
    assert row.true_positive + row.false_positive + row.false_negative + row.true_negative == row.scored_ticker_days


def test_day_recall_is_distinct_from_event_recall_and_overlapping_events_count_once():
    p = predictions(["2026-02-05", "2026-02-06"], [True, False])
    summary, _, _ = evaluate_predictions(p, events({}, {}))
    row = summary.iloc[0]
    assert row.events_hit == 2
    assert (row.true_positive, row.false_negative) == (1, 1)
    assert row.event_recall == 1
    assert row.recall == 0.5
    assert row.precision == 1
    assert row.f1_score == pytest.approx(2 / 3)


def test_classification_excludes_market_wide_and_missing_scores():
    p = predictions(["2026-02-04", "2026-02-05", "2026-02-06"], [False, True, False], scored=[False, True, True])
    summary, _, _ = evaluate_predictions(p, events({"category": config.MARKET_WIDE_CATEGORY}))
    row = summary.iloc[0]
    assert row.scored_ticker_days == 1
    assert (row.true_positive, row.false_positive, row.false_negative, row.true_negative) == (0, 0, 0, 1)
    assert pd.isna(row.precision) and pd.isna(row.recall) and pd.isna(row.f1_score)
    assert "Precision: N/A" in format_evaluation_report(summary)


def test_no_alerts_with_positive_labels_has_zero_recall_and_f1():
    summary, _, _ = evaluate_predictions(predictions(["2026-02-05"], [False]), events({}))
    row = summary.iloc[0]
    assert row.false_negative == 1
    assert row.recall == 0 and row.f1_score == 0
    assert pd.isna(row.precision)


def test_event_labels_do_not_cross_split_or_match_wrong_ticker():
    p = pd.concat(
        [predictions(["2026-04-30", "2026-05-01"], [False, True]), predictions(["2026-04-30"], [True], ticker="PG")],
        ignore_index=True,
    )
    summary, _, _ = evaluate_predictions(p, events({"first_trading_day": "2026-04-30"}))
    dev, test = summary.iloc[0], summary.iloc[1]
    assert dev.false_negative == 1 and dev.false_positive == 1
    assert test.true_positive == 0 and test.false_positive == 1
    assert pd.isna(test.recall)
