"""Download a reproducible ten-year price snapshot for model evaluation."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

import config
from data.errors import DataUnavailableError
from data.fetch import download_prices
from models.detectors import _validate


def default_as_of() -> date:
    # Exclude today's potentially incomplete US trading session.
    return datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)


def history_start(as_of: date) -> date:
    return (pd.Timestamp(as_of) - pd.DateOffset(years=10)).date()


def load_history(ticker: str, as_of: date, *, refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    """Fetch on first run; reuse only a snapshot for this exact requested date range."""
    if ticker not in config.STOCK_POOL:
        raise ValueError(f"Unsupported ticker: {ticker}")
    start = history_start(as_of)
    folder = config.DATA_DIR / "cache" / "model_prices" / f"{start}_{as_of}"
    path, meta_path = folder / f"{ticker}.csv", folder / f"{ticker}.json"
    if not refresh and path.exists() and meta_path.exists():
        prices = pd.read_csv(path, index_col="Date", parse_dates=True)
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("requested_start") != str(start) or metadata.get("requested_end") != str(as_of):
            raise DataUnavailableError(f"{ticker}: cached history dates do not match; rerun with --refresh.")
    else:
        prices = download_prices(ticker, start, as_of)
        _validate(prices)
        metadata = {
            "source": "Yahoo Finance via yfinance; auto_adjust=True",
            "ticker": ticker,
            "requested_start": str(start),
            "requested_end": str(as_of),
            "actual_start": str(prices.index.min().date()),
            "actual_end": str(prices.index.max().date()),
            "rows": len(prices),
            "retrieved_at": datetime.now(UTC).isoformat(),
        }
        folder.mkdir(parents=True, exist_ok=True)
        prices.to_csv(path, index_label="Date")
        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    _validate(prices)
    if prices.index.min().date() < start or prices.index.max().date() > as_of:
        raise DataUnavailableError(f"{ticker}: prices fall outside the requested ten-year interval.")
    if len(prices) < 150:
        raise DataUnavailableError(f"{ticker}: only {len(prices)} daily prices are available.")
    return prices, metadata
