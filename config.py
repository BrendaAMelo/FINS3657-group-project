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
HISTORY_START = date(
    2022, 1, 1
)  # prices are pulled from here onwards for model fitting
EVENT_WINDOW_START = date(2025, 11, 1)
EVENT_WINDOW_END = date(2026, 10, 15)
SPLIT_CUTOFF = date(2026, 5, 1)  # first_trading_day < cutoff -> dev; >= cutoff -> test
MIN_HISTORY_DAYS = 500  # roughly two years of trading days
EVENT_MATCH_DAYS = 1  # a flag within first trading day + 1 day counts as a hit

# Stock pool (PLACEHOLDER: to be finished)
STOCK_POOL: dict[str, dict[str, str]] = {
    "KO": {
        "company": "The Coca-Cola Company",
        "sector": "Consumer staples",
        "tier": "calm",
    },
    "JNJ": {"company": "Johnson & Johnson", "sector": "Health care", "tier": "calm"},
    "PG": {"company": "Procter & Gamble", "sector": "Consumer staples", "tier": "calm"},
    "JPM": {"company": "JPMorgan Chase", "sector": "Financials", "tier": "balanced"},
    "MSFT": {"company": "Microsoft", "sector": "Technology", "tier": "balanced"},
    "NVDA": {"company": "NVIDIA", "sector": "Technology", "tier": "volatile"},
    "TSLA": {
        "company": "Tesla",
        "sector": "Consumer discretionary",
        "tier": "volatile",
    },
}
SUPPORTED_TICKERS: tuple[str, ...] = tuple(sorted(STOCK_POOL))

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

        return st.secrets.get(name, default)
    except Exception: #noqa: BLE001
        return default
