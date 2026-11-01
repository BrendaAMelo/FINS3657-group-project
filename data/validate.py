# Checks that a price table is good enough to model.
from __future__ import annotations

import pandas as pd

import config
from data.errors import DataQualityError

REQUIRED_COLUMNS = ("Open", "Close", "Volume")


def price_problems(df: pd.DataFrame) -> list[str]:
    # Return a list of human-readable problems (empty means the data is fine).
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        return [f"missing columns: {', '.join(missing)}"]

    problems: list[str] = []
    if len(df) < config.MIN_HISTORY_DAYS:
        problems.append(f"only {len(df)} days of history (at least {config.MIN_HISTORY_DAYS} needed)")
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        problems.append("dates are not sorted and unique")
    if df[list(REQUIRED_COLUMNS)].isna().any().any():
        problems.append("contains missing values")
    if (df["Close"] <= 0).any() or (df["Open"] <= 0).any():
        problems.append("contains zero or negative prices")
    if len(df) > 1:
        gaps = df.index.to_series().diff().dt.days.dropna()
        if int(gaps.max()) > config.MAX_GAP_DAYS:
            problems.append(f"has a gap of {int(gaps.max())} days between trading days")
    if len(df) and (df["Volume"] <= 0).mean() > config.MAX_ZERO_VOLUME_SHARE:
        problems.append("has too many days with no trading volume")
    if len(df):
        last = df.index.max()
        if (pd.Timestamp(config.PRICE_DATA_END) - last).days > config.MAX_STALE_DAYS:
            problems.append(f"data ends on {last.date()}, well before {config.PRICE_DATA_END} (possibly delisted)")
    return problems


def validate_prices(df: pd.DataFrame, ticker: str) -> None:
    # Raise DataQualityError listing every problem found.
    problems = price_problems(df)
    if problems:
        raise DataQualityError(f"{ticker}: " + "; ".join(problems))
