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
EVENT_WINDOW_END = date(2026, 10, 27)
SPLIT_CUTOFF = date(2026, 5, 1)  # first_trading_day < cutoff -> dev; >= cutoff -> test
MIN_HISTORY_DAYS = 500  # roughly two years of trading days
EVENT_MATCH_DAYS = 1  # a flag within first trading day + 1 day counts as a hit

# Price data
PRICE_DATA_END = date(2026, 10, 30)  # last trading day in the cached snapshot
FEATURE_WINDOW = 20  # trading days used for rolling features
FETCH_RETRIES = 3
FETCH_BACKOFF_SECONDS = 2.0
MAX_GAP_DAYS = 10  # calendar days between trading days before we flag a gap
MAX_ZERO_VOLUME_SHARE = 0.02
MAX_STALE_DAYS = 30  # data ending this long before PRICE_DATA_END looks delisted

# Events file
EVENT_CATEGORIES = (
    "Earnings surprise",
    "Management change",
    "Regulatory or legal",
    "Product or clinical news",
    "M&A or major corporate action",
    "Operational incident",
    "Sector or industry shock",
    "Market-wide shock",
)
MARKET_WIDE_CATEGORY = "Market-wide shock"
EVENT_TIMINGS = ("pre_market", "intraday", "after_close")
EVENT_SOURCE_TYPES = ("primary", "secondary")

# Stock pool (Up to date - 1/11/2026)
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


# News
NEWS_BASE_URL = "https://finnhub.io/api/v1"
NEWS_TIMEOUT_SECONDS = 15
NEWS_REQUESTS_PER_MINUTE = 50  # the free tier allows about 60
NEWS_RETRIES = 3
NEWS_BACKOFF_SECONDS = 5.0
NEWS_CHUNK_DAYS = 7
NEWS_SPLIT_THRESHOLD = 200  # a chunk this big may be truncated by the API: refetch in halves
NEWS_MAX_SUMMARY_CHARS = 400
NEWS_SNAPSHOT_START = date(2025, 11, 1)
NEWS_SNAPSHOT_END = PRICE_DATA_END
NEWS_BEFORE_TRADING_DAYS = 1  # news window: trading days before the flagged day...
NEWS_AFTER_TRADING_DAYS = 3  # ...and after it
NEWS_MAX_ARTICLES = 8  # articles passed to the language model
NEWS_DUPLICATE_SIMILARITY = 0.8
COVERAGE_SPARSE_MAX = 2  # 0 = none, 1-2 = sparse, 3-9 = normal, 10+ = heavy
COVERAGE_NORMAL_MAX = 9

# Names used to decide whether an article is really about the company
NEWS_ALIASES: dict[str, tuple[str, ...]] = {
    "KO": ("Coca-Cola", "Coca Cola", "Coke"),
    "PG": ("Procter & Gamble", "P&G"),
    "JNJ": ("Johnson & Johnson", "J&J"),
    "WMT": ("Walmart",),
    "PEP": ("PepsiCo", "Pepsi"),
    "AAPL": ("Apple",),
    "MSFT": ("Microsoft",),
    "JPM": ("JPMorgan", "JP Morgan"),
    "XOM": ("Exxon", "ExxonMobil"),
    "DIS": ("Disney",),
    "V": ("Visa",),
    "META": ("Meta Platforms", "Facebook"),
    "TSLA": ("Tesla",),
    "NVDA": ("Nvidia",),
    "CRWD": ("CrowdStrike",),
    "INTC": ("Intel",),
    "UNH": ("UnitedHealth", "UnitedHealthcare"),
    "LLY": ("Eli Lilly", "Lilly"),
    "NFLX": ("Netflix",),
    "BA": ("Boeing",),
}

# Language model and explanations
LLM_TIMEOUT_SECONDS = 60
LLM_MAX_TOKENS = 400
LLM_RETRIES = 3
LLM_BACKOFF_SECONDS = 3.0
EXPLANATION_ATTEMPTS = 2
EXPLANATION_MAX_CHARS = 700
PROMPT_VERSION = "v2"
EXPLANATION_CACHE_DIR = DATA_DIR / "cache" / "explanations"
