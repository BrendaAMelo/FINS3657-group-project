"""Download ten years of Yahoo prices, run detectors, and measure exact-day event recall.

From the repository root: python -m models.evaluate --profiles balanced
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import numpy as np
import pandas as pd
import requests
import sklearn

import config
from data.errors import DataError, DataQualityError
from models.detectors import run_models
from models.history import default_as_of, history_start, load_history


def sheet_csv_url(source: str) -> str:
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
    query, fragment = parse_qs(parsed.query), parse_qs(parsed.fragment)
    gid = fragment.get("gid", query.get("gid", ["0"]))[0]
    if not gid.isdigit():
        raise ValueError("Google Sheets tab gid must be numeric.")
    return f"https://docs.google.com/spreadsheets/d/{match[1]}/export?format=csv&gid={gid}"


def resolve_events_source(source: str | Path | None) -> str | Path:
    """Default to data/events.csv, or the single CSV directly inside data/."""
    if source is not None:
        source = str(source)
        if source.startswith(("https://", "http://")):
            return source
        path = Path(source)
        if path.is_absolute():
            return path
        return config.ROOT / path if path.parts[0] == "data" else config.DATA_DIR / path
    canonical = config.DATA_DIR / "events.csv"
    if canonical.exists():
        return canonical
    candidates = sorted(config.DATA_DIR.glob("*.csv"))
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ValueError("Put your ground-truth CSV in data/events.csv, or specify --events FILE.csv.")
    raise ValueError(
        "Multiple CSV files in data/. Select one with --events FILE.csv: " + ", ".join(p.name for p in candidates)
    )


def _split(dates: pd.Series) -> pd.Series:
    return (dates >= pd.Timestamp(config.SPLIT_CUTOFF)).map({True: "test", False: "dev"})


def read_events(source: str | Path) -> pd.DataFrame:
    """Read selected positive events; shared IDs are ignored and no fixed year window is imposed."""
    source = resolve_events_source(source)
    if isinstance(source, Path):
        csv_text = source.read_text(encoding="utf-8-sig")
    else:
        response = requests.get(sheet_csv_url(source), timeout=30)
        response.raise_for_status()
        if "text/html" in response.headers.get("Content-Type", "").lower():
            raise ValueError("The sheet requires sign-in. Download its events tab as CSV and pass that file.")
        csv_text = response.content.decode("utf-8-sig")
    header = csv_text.splitlines()[0] if csv_text else ""
    frame = pd.read_csv(
        StringIO(csv_text), dtype=str, keep_default_na=False, sep=";" if header.count(";") > header.count(",") else ","
    )
    frame.columns = frame.columns.str.strip()
    missing = {"event_id", "ticker", "first_trading_day"} - set(frame.columns)
    if missing:
        raise DataQualityError("Events CSV is missing columns: " + ", ".join(sorted(missing)))
    frame = frame.apply(lambda col: col.str.strip())
    if "is_example" in frame:
        frame = frame.loc[frame.is_example.str.upper() != "TRUE"].copy()
    frame = frame.reset_index(drop=True)
    frame["ticker"] = frame.ticker.str.upper()
    frame["first_trading_day"] = pd.to_datetime(frame.first_trading_day, format="%Y-%m-%d", errors="coerce")
    problems = []
    if frame.event_id.eq("").any() or frame.event_id.duplicated().any():
        problems.append("event_id must be nonempty and unique")
    for row in frame.itertuples():
        if row.ticker not in config.STOCK_POOL:
            problems.append(f"{row.event_id}: unsupported ticker {row.ticker!r}")
        if pd.isna(row.first_trading_day):
            problems.append(f"{row.event_id}: first_trading_day must be YYYY-MM-DD")
        elif row.first_trading_day.weekday() >= 5:
            problems.append(f"{row.event_id}: first_trading_day falls on a weekend")
    if problems:
        raise DataQualityError("Problems in the events file: " + "; ".join(problems))
    frame["shared_event_id"] = ""
    frame["tier"] = frame.ticker.map(lambda ticker: config.STOCK_POOL[ticker]["tier"])
    if "category" not in frame:
        frame["category"] = ""
    frame["split"] = _split(frame.first_trading_day)
    return frame


def evaluate_predictions(
    predictions: pd.DataFrame, events: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Recall on listed events at exactly first_trading_day. Unlisted alerts are unlabelled."""
    p = predictions.copy()
    required = {"date", "ticker", "model", "profile", "is_anomaly", "is_scored"}
    if not required.issubset(p.columns) or p.empty:
        raise ValueError("Predictions are empty or missing required columns.")
    if events.empty:
        raise ValueError("No non-example events are available for evaluation.")
    p["date"] = pd.to_datetime(p.date, errors="raise")
    if p.date.isna().any() or p.duplicated(["date", "ticker", "model", "profile"]).any():
        raise ValueError("Prediction dates must be valid, with one row per date/ticker/model/profile.")
    for col in ("is_anomaly", "is_scored"):
        if not pd.api.types.is_bool_dtype(p[col]) or p[col].isna().any():
            raise ValueError(f"Prediction {col} must contain non-null booleans.")
    if (p.is_anomaly & ~p.is_scored).any():
        raise ValueError("An unscored prediction cannot be an anomaly.")
    events = events.copy()
    events["first_trading_day"] = pd.to_datetime(events.first_trading_day, errors="raise")
    if events.first_trading_day.isna().any() or events.event_id.duplicated().any():
        raise ValueError("Events need valid first_trading_day dates and unique event IDs.")
    events["split"] = _split(events.first_trading_day)
    p["split"] = _split(p.date)
    event_rows, summaries, alert_frames = [], [], []
    for (model, profile), group in p.groupby(["model", "profile"], sort=True):
        group = group.copy()
        group["matched_event_ids"] = ""
        local = []
        for event in events.itertuples():
            match = group.loc[(group.ticker == event.ticker) & (group.date == event.first_trading_day)]
            row = match.iloc[0] if len(match) else None
            status = (
                "unscored_missing_date"
                if row is None
                else ("unscored_insufficient_history" if not row.is_scored else ("hit" if row.is_anomaly else "miss"))
            )
            if status == "hit":
                index = match.index[0]
                prior = group.at[index, "matched_event_ids"]
                group.at[index, "matched_event_ids"] = "|".join(filter(None, [prior, event.event_id]))
            local.append(
                {
                    "event_id": event.event_id,
                    "ticker": event.ticker,
                    "tier": getattr(event, "tier", ""),
                    "category": getattr(event, "category", ""),
                    "first_trading_day": event.first_trading_day,
                    "split": event.split,
                    "model": model,
                    "profile": profile,
                    "status": status,
                    "close_price": row.get("close_price", np.nan) if row is not None else np.nan,
                    "daily_return": row.get("daily_return", np.nan) if row is not None else np.nan,
                    "score": row.get("score", np.nan) if row is not None else np.nan,
                    "threshold": row.get("threshold", np.nan) if row is not None else np.nan,
                }
            )
        audit = pd.DataFrame(local)
        event_rows.extend(local)
        flags = group.loc[group.is_anomaly].copy()
        flags["status"] = np.where(flags.matched_event_ids.ne(""), "matched", "unlabelled")
        alert_frames.append(flags)
        for split in ("all", "dev", "test"):
            subset = audit if split == "all" else audit.loc[audit.split == split]
            scored = subset.loc[subset.status.isin(["hit", "miss"])]
            hits = int(scored.status.eq("hit").sum())
            recall = hits / len(scored) if len(scored) else np.nan
            split_days = group if split == "all" else group.loc[group.split == split]
            scored_days = split_days.loc[split_days.is_scored]
            total_alerts = int(scored_days.is_anomaly.sum())
            alert_rate = total_alerts / len(scored_days) if len(scored_days) else np.nan
            summaries.append(
                {
                    "model": model,
                    "profile": profile,
                    "split": split,
                    "sheet_events": len(subset),
                    "scored_events": len(scored),
                    "events_hit": hits,
                    "events_missed": len(scored) - hits,
                    "events_unscored": len(subset) - len(scored),
                    "event_recall": recall,
                    "detection_rate_pct": 100 * recall,
                    "scored_ticker_days": len(scored_days),
                    "total_alerts": total_alerts,
                    "alert_rate": alert_rate,
                    "alerts_per_100_days": 100 * alert_rate,
                    "coverage_pct": 100 * len(scored) / len(subset) if len(subset) else np.nan,
                    "true_positive": hits,
                    "false_negative": len(scored) - hits,
                    "false_positive": np.nan,
                    "true_negative": np.nan,
                    "precision": np.nan,
                    "recall": recall,
                    "f1_score": np.nan,
                    "accuracy": np.nan,
                }
            )
    return pd.DataFrame(summaries), pd.DataFrame(event_rows), pd.concat(alert_frames, ignore_index=True)


def format_evaluation_report(summary: pd.DataFrame) -> str:
    lines = [
        "SELECTED-EVENT EVALUATION - exact first_trading_day only",
        "Each listed event is one positive example, including market-wide events.",
        "Unlisted stock-days are unlabelled: FP/TN, precision, F1 and overall accuracy are not estimable.",
        "Main metric: event recall = detected / scored listed events. Coverage reports missing model data.",
        "Alert rate = all alerts / scored stock-days, including alerts outside the CSV. "
        "This is not a false-alarm rate.",
    ]
    for row in summary.itertuples():
        recall = "N/A" if pd.isna(row.event_recall) else f"{row.detection_rate_pct:.2f}%"
        coverage = "N/A" if pd.isna(row.coverage_pct) else f"{row.coverage_pct:.2f}%"
        alert_rate = "N/A" if pd.isna(row.alert_rate) else f"{row.alerts_per_100_days:.2f} per 100 stock-days"
        lines.extend(
            [
                "",
                f"{row.model} | profile={row.profile} | split={row.split}",
                f"Detected: {row.events_hit}/{row.scored_events} | Event recall: {recall}",
                f"Alert rate: {alert_rate} ({row.total_alerts} alerts / {row.scored_ticker_days} scored stock-days)",
                f"Missed: {row.events_missed} | Unscored: {row.events_unscored} | Coverage: {coverage}",
                "Positive-only confusion counts (event units):",
                f"  Actual listed event: No alert (FN)={row.false_negative}; Alert (TP)={row.true_positive}",
                "  Actual negative:     TN=N/A; FP=N/A (no labelled negatives)",
                "Precision: N/A | F1-score: N/A | Overall accuracy: N/A",
            ]
        )
    return "\n".join(lines)


def export_detected_events(audit: pd.DataFrame) -> Path:
    """One record per listed ticker/date detected by any model/profile in this run."""
    detected = (
        audit.loc[audit.status.eq("hit"), ["first_trading_day", "ticker"]]
        .drop_duplicates()
        .sort_values(["first_trading_day", "ticker"])
    )
    records = [
        {"flag": True, "event_date": pd.Timestamp(row.first_trading_day).strftime("%Y-%m-%d"), "ticker": row.ticker}
        for row in detected.itertuples(index=False)
    ]
    path = config.RESULTS_DIR / "detected_events.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", help="CSV filename inside data/; defaults to data/events.csv or its sole CSV")
    parser.add_argument("--predict-only", action="store_true")
    parser.add_argument("--tickers", nargs="+", choices=config.SUPPORTED_TICKERS)
    parser.add_argument("--profiles", nargs="+", choices=tuple(config.PROFILES), default=tuple(config.PROFILES))
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "output" / "event_recall")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=default_as_of(), help="Last price date (YYYY-MM-DD)"
    )
    parser.add_argument("--refresh", action="store_true", help="Redownload the ten-year Yahoo snapshot")
    args = parser.parse_args(argv)
    try:
        if args.as_of > default_as_of():
            raise ValueError("--as-of must be no later than the previous New York calendar day.")
        source = None if args.predict_only else resolve_events_source(args.events)
        events = None if args.predict_only else read_events(source)
        if events is not None and events.empty:
            raise ValueError("The events CSV has no non-example rows.")
        tickers = tuple(
            dict.fromkeys(
                args.tickers or (sorted(events.ticker.unique()) if events is not None else config.SUPPORTED_TICKERS)
            )
        )
        profiles = tuple(dict.fromkeys(args.profiles))
        start = history_start(args.as_of)
        if events is not None:
            if not events.first_trading_day.between(pd.Timestamp(start), pd.Timestamp(args.as_of)).all():
                raise ValueError(f"Event dates must fall within the requested history: {start} through {args.as_of}.")
            score_start = events.first_trading_day.min()
        else:
            score_start = pd.Timestamp(args.as_of) - pd.DateOffset(years=1)
        outputs, fitting, history = [], {}, {}
        print(f"Yahoo Finance history: {start} through {args.as_of}; scoring starts {score_start.date()}.")
        print("Isolation Forest fitting/calibration uses only history before scoring starts.")
        for ticker in tickers:
            print(f"Loading {ticker}...")
            prices, history[ticker] = load_history(ticker, args.as_of, refresh=args.refresh)
            output, fitting[ticker] = run_models(
                prices, ticker, start=score_start, end=args.as_of, profiles=profiles, allow_insufficient_history=True
            )
            outputs.append(output)
        predictions = pd.concat(outputs, ignore_index=True)
        args.output.mkdir(parents=True, exist_ok=True)
        predictions.to_csv(args.output / "predictions.csv", index=False, date_format="%Y-%m-%d")
        if events is not None:
            summary, audit, alerts = evaluate_predictions(predictions, events)
            detected_path = export_detected_events(audit)
            print(f"Saved detected events to {detected_path.resolve()}")
            for name, frame in (
                ("events_snapshot", events),
                ("metrics", summary),
                ("event_matches", audit),
                ("alert_matches", alerts),
            ):
                frame.to_csv(args.output / f"{name}.csv", index=False, date_format="%Y-%m-%d")
            report = format_evaluation_report(summary)
            (args.output / "metrics.txt").write_text(report + "\n", encoding="utf-8")
            print(report)
        metadata = {
            "mode": "predict_only" if args.predict_only else "selected_event_recall",
            "events_source": str(source) if source is not None else None,
            "requested_history_start": str(start),
            "as_of": str(args.as_of),
            "history": history,
            "scoring_start": str(score_start.date()),
            "ignored_event_columns": ["shared_event_id"],
            "matching": "same ticker, exact first_trading_day; market-wide events included",
            "evaluation_unit": "listed event",
            "alert_rate_definition": "all flagged stock-days / scored stock-days in the prediction period, by split",
            "unlisted_days": "unlabelled; not negatives",
            "split_cutoff": str(config.SPLIT_CUTOFF),
            "fixed_threshold": config.FIXED_THRESHOLD_PCT,
            "zscore_window": config.ZSCORE_WINDOW,
            "profiles": {p: config.PROFILES[p] for p in profiles},
            "fitting": fitting,
            "versions": {"numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__},
        }
        (args.output / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Saved results to {args.output.resolve()}")
    except (DataError, OSError, ValueError, requests.RequestException) as err:
        print(f"ERROR: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
