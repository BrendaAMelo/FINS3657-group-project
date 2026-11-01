# Load and validate the event list (events.csv), the answer key for evaluation.
from __future__ import annotations

from pathlib import Path

import pandas as pd

import config
from data.errors import DataError, DataQualityError, DataUnavailableError

REQUIRED_COLUMNS = [
    "event_id",
    "ticker",
    "company",
    "sector",
    "tier",
    "category",
    "event_description",
    "announcement_date",
    "announcement_timing",
    "first_trading_day",
    "split",
    "shared_event_id",
    "source_type",
    "primary_source_url",
    "secondary_source_url",
    "saved_article_extract",
    "price_reaction_bucket",
    "news_coverage",
    "news_article_count",
    "researcher",
    "notes",
    "is_example",
]
DATE_COLUMNS = ("announcement_date", "first_trading_day")
MAX_REPORTED_PROBLEMS = 10


def _detect_delimiter(path: Path) -> str:
    with path.open(encoding="utf-8-sig") as handle:
        header = handle.readline()
    return ";" if header.count(";") > header.count(",") else ","


def load_events(path: Path | None = None, include_examples: bool = False) -> pd.DataFrame:
    # Return the validated events with dates parsed and `split` computed from the cut-off.
    path = path or config.EVENTS_CSV
    try:
        df = pd.read_csv(
            path,
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
            sep=_detect_delimiter(path),
        )
    except FileNotFoundError as err:
        raise DataUnavailableError(f"Events file not found: {path}") from err
    except (OSError, ValueError) as err:
        raise DataUnavailableError(f"Events file could not be read: {path}") from err

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataQualityError(f"The events file is missing columns: {', '.join(missing)}")

    df = df.apply(lambda col: col.str.strip())
    if not include_examples:
        df = df[df["is_example"].str.upper() != "TRUE"]
    df = df.reset_index(drop=True)
    for col in DATE_COLUMNS:
        df[col] = pd.to_datetime(df[col], format="%Y-%m-%d", errors="coerce")

    problems = _row_problems(df)
    if problems:
        shown = problems[:MAX_REPORTED_PROBLEMS]
        extra = len(problems) - len(shown)
        suffix = f"; ...and {extra} more" if extra > 0 else ""
        raise DataQualityError("Problems in the events file: " + "; ".join(shown) + suffix)

    cutoff = pd.Timestamp(config.SPLIT_CUTOFF)
    df["split"] = (df["first_trading_day"] >= cutoff).map({True: "test", False: "dev"})
    return df


def _date_problems(row: pd.Series, window_start: pd.Timestamp, window_end: pd.Timestamp) -> list[str]:
    announced, first = row["announcement_date"], row["first_trading_day"]
    out = [
        f"{name} is not a valid YYYY-MM-DD date"
        for name, value in (("announcement_date", announced), ("first_trading_day", first))
        if pd.isna(value)
    ]
    if out:
        return out
    if first.weekday() >= 5:
        out.append("first_trading_day falls on a weekend")
    if not window_start <= first <= window_end:
        out.append(f"first_trading_day {first.date()} is outside the event window")
    timing = row["announcement_timing"]
    if timing == "after_close" and first <= announced:
        out.append("after_close announcements need a later first_trading_day")
    if timing in ("pre_market", "intraday") and first < announced:
        out.append(f"{timing} announcements cannot have an earlier first_trading_day")
    return out


def _row_problems(df: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    window_start = pd.Timestamp(config.EVENT_WINDOW_START)
    window_end = pd.Timestamp(config.EVENT_WINDOW_END)

    repeated = df["event_id"].duplicated(keep=False) & (df["event_id"] != "")
    for event_id in df.loc[repeated, "event_id"].unique():
        problems.append(f"{event_id}: event_id is used more than once")

    for pos, row in df.iterrows():
        label = row["event_id"] or f"row {pos + 1}"
        found: list[str] = []
        if not row["event_id"]:
            found.append("event_id is empty")
        pool = config.STOCK_POOL.get(row["ticker"])
        if pool is None:
            found.append(f"ticker '{row['ticker']}' is not in the stock pool")
        elif row["tier"] != pool["tier"]:
            found.append(f"tier '{row['tier']}' does not match the pool tier '{pool['tier']}'")
        if row["category"] not in config.EVENT_CATEGORIES:
            found.append(f"unknown category '{row['category']}'")
        if row["announcement_timing"] not in config.EVENT_TIMINGS:
            found.append("announcement_timing must be one of: " + ", ".join(config.EVENT_TIMINGS))
        if row["source_type"] not in config.EVENT_SOURCE_TYPES:
            found.append("source_type must be primary or secondary")
        else:
            needed = f"{row['source_type']}_source_url"
            if not row[needed].startswith("http"):
                found.append(f"{needed} must start with http")
        if not row["event_description"]:
            found.append("event_description is empty")
        found += _date_problems(row, window_start, window_end)
        problems.extend(f"{label}: {text}" for text in found)

    shared = df[df["shared_event_id"] != ""]
    for shared_id, group in shared.groupby("shared_event_id"):
        if group["first_trading_day"].nunique() > 1:
            problems.append(f"{shared_id}: rows sharing this id have different first_trading_day values")
    return problems


def market_wide_days(events: pd.DataFrame) -> set[pd.Timestamp]:
    # Days on which a market-wide event happened; flags on these days are 'unscored'.
    rows = events[events["category"] == config.MARKET_WIDE_CATEGORY]
    return set(rows["first_trading_day"])


def quota_warnings(events: pd.DataFrame) -> list[str]:
    # Compare the event list with the agreed quotas and say what's still missing.
    warnings: list[str] = []
    total = len(events)
    if total < 15:
        warnings.append(f"only {total} events (aim for 15-25 or more)")
    for split in ("dev", "test"):
        count = int((events["split"] == split).sum())
        if count < 7:
            warnings.append(f"only {count} {split} events (need at least 7)")
    per_ticker = events["ticker"].value_counts()
    too_many = per_ticker[per_ticker > 3]
    if not too_many.empty:
        warnings.append("more than 3 events for: " + ", ".join(too_many.index))
    calm_with_events = len(set(config.TICKERS_BY_TIER["calm"]) & set(events["ticker"]))
    if calm_with_events < 4:
        warnings.append(f"only {calm_with_events} calm-tier stocks have an event (need 4)")
    market_wide = int((events["category"] == config.MARKET_WIDE_CATEGORY).sum())
    if market_wide > 4:
        warnings.append(f"{market_wide} market-wide rows (at most 4)")
    categories = events["category"].nunique()
    if categories < 5:
        warnings.append(f"only {categories} categories used (need at least 5)")
    return warnings


def main() -> int:
    # Print a quick summary of the events file: python -m data.events
    try:
        events = load_events()
    except DataError as err:
        print(err)
        return 1
    dev, test = int((events["split"] == "dev").sum()), int((events["split"] == "test").sum())
    print(f"{len(events)} events ({dev} dev, {test} test)")
    print(events.groupby("tier")["event_id"].count().to_string())
    for warning in quota_warnings(events):
        print("WARNING:", warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
