# Download and cache daily price history.
from __future__ import annotations

import json
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

import config
from data.errors import DataUnavailableError
from data.validate import validate_prices

try:
    from yfinance.exceptions import YFRateLimitError

    _RETRYABLE: tuple[type[Exception], ...] = (
        requests.exceptions.RequestException,
        OSError,
        YFRateLimitError,
    )
except ImportError:  # older yfinance versions
    _RETRYABLE = (requests.exceptions.RequestException, OSError)

PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]
_TICKER_PATTERN = re.compile(r"[A-Z.\-]{1,6}")


def _safe_ticker(ticker: str) -> str:
    # Tickers become file names, so reject anything that could escape the cache folder.
    if not isinstance(ticker, str) or not _TICKER_PATTERN.fullmatch(ticker):
        raise ValueError(f"Invalid ticker: {ticker!r}")
    return ticker


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw[PRICE_COLUMNS].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna(subset=["Close"])


def download_prices(ticker: str, start: date, end: date) -> pd.DataFrame:
    # Download split- and dividend-adjusted daily prices (both dates inclusive).
    last_error: Exception | None = None
    for attempt in range(1, config.FETCH_RETRIES + 1):
        try:
            raw = yf.Ticker(ticker).history(
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # yfinance's end is exclusive
                auto_adjust=True,
                actions=False,
            )
        except _RETRYABLE as err:
            last_error = err
        else:
            if not raw.empty:
                missing = [c for c in PRICE_COLUMNS if c not in raw.columns]
                if missing:
                    raise DataUnavailableError(f"Price data for {ticker} is missing columns: {', '.join(missing)}.")
                return _clean(raw)
            last_error = None
        if attempt < config.FETCH_RETRIES:
            time.sleep(config.FETCH_BACKOFF_SECONDS * 2 ** (attempt - 1))
    detail = f" ({type(last_error).__name__})" if last_error else ""
    raise DataUnavailableError(f"Could not download price data for {ticker}{detail}. Please try again later.")


def _paths(ticker: str) -> tuple[Path, Path]:
    folder = config.PRICE_CACHE_DIR
    return folder / f"{ticker}.csv", folder / f"{ticker}.meta.json"


def _write_cache(ticker: str, df: pd.DataFrame, start: date, end: date) -> None:
    csv_path, meta_path = _paths(ticker)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path)
    meta = {
        "ticker": ticker,
        "source": "yfinance (auto_adjust=True)",
        "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "rows": len(df),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _read_cache(ticker: str) -> pd.DataFrame | None:
    csv_path, _ = _paths(ticker)
    if not csv_path.exists():
        return None
    try:
        return pd.read_csv(csv_path, index_col="Date", parse_dates=True)
    except (OSError, ValueError) as err:
        raise DataUnavailableError(f"The saved price file for {ticker} is unreadable. Delete it and refresh.") from err


def cache_info(ticker: str) -> dict | None:
    # Return the cache metadata (retrieval date, source), or None if there is no cache.
    _, meta_path = _paths(_safe_ticker(ticker))
    if not meta_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def load_prices(ticker: str, refresh: bool = False, validate: bool = True) -> pd.DataFrame:
    # Return daily prices for a ticker, from the cache when possible.
    ticker = _safe_ticker(ticker)
    df = None if refresh else _read_cache(ticker)
    if df is None:
        df = download_prices(ticker, config.HISTORY_START, config.PRICE_DATA_END)
        _write_cache(ticker, df, config.HISTORY_START, config.PRICE_DATA_END)
    if validate:
        validate_prices(df, ticker)
    return df
