"""Compare daily detections with the project's validated events sheet.

Run from the repository root: python -m models.evaluate --events events.csv
"""

from __future__ import annotations

import argparse
import json
import re
import tempfile
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import numpy as np
import pandas as pd
import requests
import sklearn

import config
from data.errors import DataError
from data.events import load_events, market_wide_days, quota_warnings
from data.validate import validate_prices
from models.detectors import run_models


def sheet_csv_url(source: str) -> str:
    """Accept an ordinary Google Sheet tab URL or a published CSV URL."""
    parsed = urlparse(source)
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com":
        raise ValueError("Use an HTTPS docs.google.com spreadsheet link or a local CSV file.")
    if re.fullmatch(r"/spreadsheets/d/e/[A-Za-z0-9_-]+/pub", parsed.path):
        query = parse_qs(parsed.query)
        query["output"] = ["csv"]
        return parsed._replace(query=urlencode(query, doseq=True), fragment="").geturl()
    match = re.match(r"^/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
    if not match:
        raise ValueError("Unrecognised Google Sheets link. Export the events tab as CSV instead.")
    query = parse_qs(parsed.query)
    fragment = parse_qs(parsed.fragment)
    gid = fragment.get("gid", query.get("gid", ["0"]))[0]
    if not gid.isdigit():
        raise ValueError("Google Sheets tab gid must be numeric.")
    return f"https://docs.google.com/spreadsheets/d/{match[1]}/export?format=csv&gid={gid}"


def read_events(source: str | Path) -> pd.DataFrame:
    """Ignore shared_event_id for evaluation; validate all remaining event fields."""
    source = str(source)
    if not source.startswith(("https://", "http://")):
        csv_text = Path(source).read_text(encoding="utf-8-sig")
    else:
        response = requests.get(sheet_csv_url(source), timeout=30)
        response.raise_for_status()
        if "text/html" in response.headers.get("Content-Type", "").lower():
            raise ValueError("The sheet requires sign-in. Download its events tab as CSV and pass that file.")
        csv_text = response.content.decode("utf-8-sig")
    header = csv_text.splitlines()[0] if csv_text else ""
    delimiter = ";" if header.count(";") > header.count(",") else ","
    frame = pd.read_csv(StringIO(csv_text), dtype=str, keep_default_na=False, sep=delimiter)
    # The evaluator matches ticker/date only. Neutralise this optional column in
    # a temporary copy, preserving the source file and the shared data validator.
    frame["shared_event_id"] = ""
    with tempfile.TemporaryDirectory(prefix="event-sheet-") as folder:
        path = Path(folder) / "events.csv"
        frame.to_csv(path, index=False, encoding="utf-8")
        return load_events(path)


def _split(dates: pd.Series) -> pd.Series:
    return (dates >= pd.Timestamp(config.SPLIT_CUTOFF)).map({True: "test", False: "dev"})


def _classification_metrics(days: pd.DataFrame) -> dict:
    """Binary metrics on scored ticker-days, assuming unlisted days are negative."""
    actual, predicted = days["event_label"], days["is_anomaly"]
    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": tp / (tp + fp) if tp + fp else np.nan,
        "recall": tp / (tp + fn) if tp + fn else np.nan,
        "f1_score": 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else np.nan,
    }


def format_evaluation_report(summary: pd.DataFrame) -> str:
    """Readable terminal output, also suitable for saving as a text report."""

    def score(value):
        return "N/A" if pd.isna(value) else f"{value:.4f}"

    lines = [
        "MODEL EVALUATION (one observation = one ticker-day)",
        "Positive label: a listed company-event matching window; all other scored days are assumed negative.",
        "Market-wide days and unavailable model scores are excluded. Unlisted real events can inflate false positives.",
        "Precision/recall/F1 use ticker-days; event recall separately measures distinct events detected.",
        "Scores range from 0 to 1; N/A means the denominator is zero.",
    ]
    for row in summary.itertuples(index=False):
        lines.extend(
            [
                "",
                f"{row.model} | profile={row.profile} | split={row.split}",
                f"Scored ticker-days: {row.scored_ticker_days}",
                "Confusion matrix (rows = actual, columns = predicted):",
                "                          No alert       Alert",
                f"  No listed event      TN={row.true_negative:>7}   FP={row.false_positive:>7}",
                f"  Listed event window  FN={row.false_negative:>7}   TP={row.true_positive:>7}",
                f"Precision: {score(row.precision)}  Recall: {score(row.recall)}  F1-score: {score(row.f1_score)}",
                f"Event recall: {score(row.event_recall)} ({row.events_hit}/{row.scored_events} events detected; "
                f"{row.events_unscored} unscored)",
            ]
        )
    return "\n".join(lines)


def evaluate_predictions(
    predictions: pd.DataFrame,
    events: pd.DataFrame,
    *,
    match_days: int = config.EVENT_MATCH_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return summary, event-level audit and flagged-day audit.

    Match the same ticker from first_trading_day through +match_days CALENDAR days,
    within the same dev/test split. Market-wide first days are globally unscored,
    following data.events.market_wide_days. Classification uses ticker-days with
    unlisted days assumed negative; event_recall separately counts distinct events.
    """
    if not isinstance(match_days, int) or match_days < 0:
        raise ValueError("match_days must be a nonnegative integer.")
    if events.empty:
        raise ValueError("No non-example events are available for evaluation.")
    p = predictions.copy()
    required = {"date", "ticker", "model", "profile", "is_anomaly", "is_scored"}
    if not required.issubset(p.columns) or p.empty:
        raise ValueError("Predictions are empty or missing required columns.")
    p["date"] = pd.to_datetime(p["date"], errors="raise")
    if p["date"].isna().any() or p.duplicated(["date", "ticker", "model", "profile"]).any():
        raise ValueError("Prediction dates must be valid, with one row per date/ticker/model/profile.")
    for col in ("is_anomaly", "is_scored"):
        if not pd.api.types.is_bool_dtype(p[col]) or p[col].isna().any():
            raise ValueError(f"Prediction {col} must contain non-null booleans.")
    if (p.is_anomaly & ~p.is_scored).any():
        raise ValueError("An unscored prediction cannot be an anomaly.")
    events = events.copy()
    events["first_trading_day"] = pd.to_datetime(events["first_trading_day"])
    events["split"] = _split(events["first_trading_day"])
    p["split"] = _split(p["date"])
    first, last = pd.Timestamp(config.EVENT_WINDOW_START), pd.Timestamp(config.EVENT_WINDOW_END)
    p = p.loc[p.date.between(first, last + pd.Timedelta(days=match_days))].copy()
    market_days = market_wide_days(events)
    p["market_wide"] = p.date.isin(market_days)
    p["matched_event_ids"] = ""
    p["event_label"] = False
    event_rows, summaries, alert_frames = [], [], []
    for (model, profile), group in p.groupby(["model", "profile"], sort=True):
        covered_tickers = set(group.ticker)
        local_events = []
        for _, event in events.iterrows():
            first_day = event.first_trading_day
            eligible = group.loc[
                (group.ticker == event.ticker)
                & (group.split == event.split)
                & group.date.between(first_day, first_day + pd.Timedelta(days=match_days))
                & group.is_scored
                & ~group.market_wide
            ]
            matches = eligible.loc[eligible.is_anomaly]
            if event.category != config.MARKET_WIDE_CATEGORY and first_day not in market_days:
                # Union of event windows: a date counts once even when events overlap.
                # Labels on available days remain valid if the event's first day is missing.
                group.loc[eligible.index, "event_label"] = True
            if event.category == config.MARKET_WIDE_CATEGORY or first_day in market_days:
                status = "unscored_market_wide"
            elif event.ticker not in covered_tickers:
                status = "not_evaluated_ticker"
            elif not ((eligible.date == first_day).any()):
                status = "unscored_missing_first_day"
            else:
                status = "hit" if len(matches) else "miss"
                for index in matches.index:
                    previous = group.at[index, "matched_event_ids"]
                    group.at[index, "matched_event_ids"] = "|".join(filter(None, [previous, event.event_id]))
            local_events.append(
                {
                    "event_id": event.event_id,
                    "ticker": event.ticker,
                    "tier": event.tier,
                    "category": event.category,
                    "first_trading_day": first_day,
                    "split": event.split,
                    "model": model,
                    "profile": profile,
                    "status": status,
                    "first_alert_date": matches.date.min() if status == "hit" else pd.NaT,
                    "delay_calendar_days": (matches.date.min() - first_day).days if status == "hit" else np.nan,
                    "matched_alert_count": len(matches) if status == "hit" else 0,
                }
            )
        audit = pd.DataFrame(local_events)
        event_rows.extend(local_events)
        flags = group.loc[group.is_anomaly].copy()
        flags["status"] = np.where(
            flags.market_wide, "unscored_market_wide", np.where(flags.matched_event_ids != "", "matched", "unmatched")
        )
        alert_frames.append(flags.drop(columns="market_wide"))
        for split in ("dev", "test"):
            subset = audit.loc[audit.split == split]
            scored = subset.loc[subset.status.isin(["hit", "miss"])]
            hits = int((scored.status == "hit").sum())
            split_flags = flags.loc[flags.split == split]
            n_matched = int((split_flags.status == "matched").sum())
            n_unmatched = int((split_flags.status == "unmatched").sum())
            n_flags = n_matched + n_unmatched
            n_days = int(((group.split == split) & group.is_scored & ~group.market_wide).sum())
            days = group.loc[(group.split == split) & group.is_scored & ~group.market_wide]
            summaries.append(
                {
                    "model": model,
                    "profile": profile,
                    "split": split,
                    **_classification_metrics(days),
                    "sheet_events": len(subset),
                    "scored_events": len(scored),
                    "events_hit": hits,
                    "events_missed": len(scored) - hits,
                    "events_unscored": len(subset) - len(scored),
                    "event_recall": hits / len(scored) if len(scored) else np.nan,
                    "scored_ticker_days": n_days,
                    "scored_alerts": n_flags,
                    "matched_alerts": n_matched,
                    "unmatched_alerts": n_unmatched,
                    "unscored_alerts": int((split_flags.status == "unscored_market_wide").sum()),
                    "sheet_match_rate": n_matched / n_flags if n_flags else np.nan,
                    "alerts_per_100_days": 100 * n_flags / n_days if n_days else np.nan,
                }
            )
    if not summaries:
        raise ValueError("No predictions overlap the configured evaluation period.")
    return pd.DataFrame(summaries), pd.DataFrame(event_rows), pd.concat(alert_frames, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", default=str(config.EVENTS_CSV), help="Events CSV path or Google Sheets URL")
    parser.add_argument("--predict-only", action="store_true", help="Generate model output without event evaluation")
    parser.add_argument("--tickers", nargs="+", choices=config.SUPPORTED_TICKERS, default=config.SUPPORTED_TICKERS)
    parser.add_argument("--profiles", nargs="+", choices=tuple(config.PROFILES), default=tuple(config.PROFILES))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "output")
    parser.add_argument("--match-days", type=int, default=config.EVENT_MATCH_DAYS)
    args = parser.parse_args(argv)
    try:
        if args.match_days < 0:
            raise ValueError("--match-days cannot be negative.")
        tickers, profiles = tuple(dict.fromkeys(args.tickers)), tuple(dict.fromkeys(args.profiles))
        events = None if args.predict_only else read_events(args.events)
        if events is not None and events.empty:
            raise ValueError("The events sheet has no non-example rows. Use --predict-only to inspect models.")
        outputs, fitting = [], {}
        end = min(
            pd.Timestamp(config.PRICE_DATA_END),
            pd.Timestamp(config.EVENT_WINDOW_END) + pd.Timedelta(days=args.match_days),
        )
        for ticker in tickers:
            # Evaluation uses the saved snapshot only: never silently download or replace prices.
            path = config.PRICE_CACHE_DIR / f"{ticker}.csv"
            prices = pd.read_csv(path, index_col="Date", parse_dates=True)
            validate_prices(prices, ticker)
            output, fitting[ticker] = run_models(prices, ticker, end=end, profiles=profiles)
            outputs.append(output)
        predictions = pd.concat(outputs, ignore_index=True)
        summaries = audit = alerts = None
        if events is not None:
            summaries, audit, alerts = evaluate_predictions(predictions, events, match_days=args.match_days)
            for warning in quota_warnings(events):
                print("WARNING:", warning)
        args.output.mkdir(parents=True, exist_ok=True)
        predictions.to_csv(args.output / "predictions.csv", index=False, date_format="%Y-%m-%d")
        if events is not None:
            events.to_csv(args.output / "events_snapshot.csv", index=False, date_format="%Y-%m-%d")
            for name, frame in (("metrics", summaries), ("event_matches", audit), ("alert_matches", alerts)):
                frame.to_csv(args.output / f"{name}.csv", index=False, date_format="%Y-%m-%d")
            report = format_evaluation_report(summaries)
            print(report)
            (args.output / "metrics.txt").write_text(report + "\n", encoding="utf-8")
        else:
            print(
                "Prediction-only run: precision, recall, F1 and confusion matrices "
                "require --events and no --predict-only."
            )
        metadata = {
            "ignored_event_columns": ["shared_event_id"],
            "mode": "predict_only" if args.predict_only else "evaluate",
            "event_window_start": str(config.EVENT_WINDOW_START),
            "event_window_end": str(config.EVENT_WINDOW_END),
            "prediction_end": str(end.date()),
            "split_cutoff": str(config.SPLIT_CUTOFF),
            "match_calendar_days": args.match_days,
            "matching": "same ticker, forward only, same split",
            "classification_unit": "ticker-day",
            "classification_labels": "union of company-event windows positive; other scored days assumed negative",
            "undefined_classification_metrics": "NaN in CSV / N/A in terminal (zero denominator)",
            "fixed_threshold": config.FIXED_THRESHOLD_PCT,
            "zscore_window": config.ZSCORE_WINDOW,
            "profiles": {p: config.PROFILES[p] for p in profiles},
            "fitting": fitting,
            "versions": {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__},
            "limitations": "Unmatched alerts are not verified false positives; sheet coverage may be incomplete.",
        }
        (args.output / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Saved {len(predictions)} prediction rows to {args.output.resolve()}")
    except (DataError, OSError, ValueError, requests.RequestException) as err:
        print(f"ERROR: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
