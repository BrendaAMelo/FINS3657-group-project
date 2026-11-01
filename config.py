# Central settings. Change values here, not inside other modules.
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")  # does nothing if .env doesn't exist

# Paths
DATA_DIR = ROOT / "data"
PRICE_CACHE_DIR = DATA_DIR / "cache" / "prices"
NEWS_CACHE_DIR = DATA_DIR / "cache" / "news"
EVENTS_CSV = DATA_DIR / "events.csv"
DB_PATH = DATA_DIR / "app.db"
RESULTS_DIR = ROOT / "results"

# Dates
HISTORY_START = date(2022, 1, 1)  # prices are pulled from here onwards for model fitting
EVENT_WINDOW_START = date(2025, 11, 1)
EVENT_WINDOW_END = date(2026, 10, 15)
SPLIT_CUTOFF = date(2026, 5, 1)  # first_trading_day < cutoff -> dev; >= cutoff -> test
MIN_HISTORY_DAYS = 500  # roughly two years of trading days
EVENT_MATCH_DAYS = 1  # a flag within first trading day + 1 day counts as a hit

# Stock pool (PLACEHOLDER: to be finished)
_POOL_ROWS: list[tuple[str, str, str, str]] = [
    # (ticker, company, sector, tier)
    ("KO", "The Coca-Cola Company", "Consumer staples", "calm"),
    ("PG", "Procter & Gamble", "Consumer staples", "calm"),
    ("JNJ", "Johnson & Johnson", "Health care", "calm"),
    ("WMT", "Walmart", "Consumer staples", "calm"),
    ("PEP", "PepsiCo", "Consumer staples", "calm"),
    ("AAPL", "Apple", "Technology", "balanced"),
    ("MSFT", "Microsoft", "Technology", "balanced"),
    ("JPM", "JPMorgan Chase", "Financials", "balanced"),
    ("XOM", "Exxon Mobil", "Energy", "balanced"),
    ("DIS", "The Walt Disney Company", "Communication services", "balanced"),
    ("V", "Visa", "Financials", "balanced"),
    ("META", "Meta Platforms", "Communication services", "balanced"),
    ("TSLA", "Tesla", "Consumer discretionary", "volatile"),
    ("NVDA", "NVIDIA", "Technology", "volatile"),
    ("CRWD", "CrowdStrike", "Technology", "volatile"),
    ("INTC", "Intel", "Technology", "volatile"),
    ("UNH", "UnitedHealth Group", "Health care", "volatile"),
    ("LLY", "Eli Lilly", "Health care", "volatile"),
    ("NFLX", "Netflix", "Communication services", "volatile"),
    ("BA", "Boeing", "Industrials", "volatile"),
]
STOCK_POOL: dict[str, dict[str, str]] = {
    ticker: {"company": company, "sector": sector, "tier": tier} for ticker, company, sector, tier in _POOL_ROWS
}
SUPPORTED_TICKERS: tuple[str, ...] = tuple(sorted(STOCK_POOL))
TICKERS_BY_TIER: dict[str, tuple[str, ...]] = {
    tier: tuple(t for t, info in STOCK_POOL.items() if info["tier"] == tier)
    for tier in ("calm", "balanced", "volatile")
}

# Detectors
FIXED_THRESHOLD_PCT = 0.05  # baseline 1: flag if |daily return| > 5%
ZSCORE_WINDOW = 60  # baseline 2: rolling window in trading days

# Risk profiles -> sensitivity. PLACEHOLDER VALUES!!!!
# Lower z_threshold / lower quantile = more alerts (more sensitive).
PROFILES: dict[str, dict[str, float]] = {
    "conservative": {"z_threshold": 2.5, "iforest_quantile": 0.97},
    "balanced": {"z_threshold": 3.0, "iforest_quantile": 0.98},
    "aggressive": {"z_threshold": 3.5, "iforest_quantile": 0.99},
}


# Secrets
def get_secret(name: str, default: str | None = None) -> str | None:
    # Read a secret from the environment (.env locally) or Streamlit secrets (when deployed).
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st
        from streamlit.errors import StreamlitSecretNotFoundError
    except ImportError:
        return default
    try:
        return st.secrets.get(name, default)
    except (FileNotFoundError, StreamlitSecretNotFoundError):
        return default
