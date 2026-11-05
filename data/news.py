# Download, store and load company news from Finnhub. All news network code lives here.

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import requests

import config
from data.errors import DataUnavailableError

log = logging.getLogger(__name__)
_TICKER_PATTERN = re.compile(r"[A-Z.\-]{1,6}")  # same rule as data.fetch: tickers become file names


@dataclass(frozen=True)
class Article:
    id: str
    ticker: str
    published: datetime  # timezone-aware, UTC
    headline: str
    summary: str
    source: str
    url: str
    related: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "id": self.id,
            "ticker": self.ticker,
            "published": self.published.isoformat(),
            "headline": self.headline,
            "summary": self.summary,
            "source": self.source,
            "url": self.url,
            "related": self.related,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> Article:
        return cls(
            id=data["id"],
            ticker=data["ticker"],
            published=datetime.fromisoformat(data["published"]),
            headline=data["headline"],
            summary=data["summary"],
            source=data["source"],
            url=data["url"],
            related=data.get("related", ""),
        )


@dataclass(frozen=True)
class Snapshot:
    ticker: str
    start: date
    end: date
    retrieved_at: str
    articles: tuple[Article, ...]


class _RateLimiter:
    # Keeps requests at least 60/per_minute seconds apart.

    def __init__(self, per_minute: int) -> None:
        self.interval = 60.0 / per_minute
        self._last = 0.0

    def wait(self) -> None:
        delay = self._last + self.interval - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._last = time.monotonic()


_limiter = _RateLimiter(config.NEWS_REQUESTS_PER_MINUTE)


def _safe_ticker(ticker: str) -> str:
    if not isinstance(ticker, str) or not _TICKER_PATTERN.fullmatch(ticker):
        raise ValueError(f"Invalid ticker: {ticker!r}")
    return ticker


def _api_key() -> str:
    key = config.get_secret("NEWS_API_KEY")
    if not key:
        raise DataUnavailableError("No news API key is configured (set NEWS_API_KEY).")
    return key


def _parse(ticker: str, item: dict) -> Article | None:
    # Turn one API item into an Article, or None if it is unusable.
    try:
        timestamp = int(item["datetime"])
        published = datetime.fromtimestamp(timestamp, tz=UTC)
    except (KeyError, TypeError, ValueError, OSError, OverflowError):
        return None
    headline = str(item.get("headline") or "").strip()
    url = str(item.get("url") or "").strip()
    if timestamp <= 0 or not headline or not url.startswith(("http://", "https://")):
        return None
    return Article(
        id=str(item.get("id") or hashlib.sha256(url.encode()).hexdigest()[:12]),
        ticker=ticker,
        published=published,
        headline=headline,
        summary=str(item.get("summary") or "").strip()[: config.NEWS_MAX_SUMMARY_CHARS],
        source=str(item.get("source") or "").strip(),
        url=url,
        related=str(item.get("related") or "").strip(),
    )


def _articles_from(ticker: str, response: requests.Response) -> list[Article]:
    try:
        payload = response.json()
    except ValueError as err:
        raise DataUnavailableError("The news API returned unreadable data.") from err
    if not isinstance(payload, list):
        raise DataUnavailableError("The news API returned an unexpected response.")
    parsed = (_parse(ticker, item) for item in payload if isinstance(item, dict))
    return [article for article in parsed if article is not None]


def fetch_company_news(ticker: str, start: date, end: date) -> list[Article]:
    # One request for [start, end]. Transient failures are retried.
    ticker = _safe_ticker(ticker)
    headers = {"X-Finnhub-Token": _api_key()}  # a header keeps the key out of URLs and logs
    params = {"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()}
    problem = "no response"
    for attempt in range(1, config.NEWS_RETRIES + 1):
        _limiter.wait()
        try:
            response = requests.get(
                f"{config.NEWS_BASE_URL}/company-news",
                params=params,
                headers=headers,
                timeout=config.NEWS_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as err:
            problem = type(err).__name__
        else:
            status = response.status_code
            if status in (401, 403):
                raise DataUnavailableError("The news API rejected the key. Check NEWS_API_KEY.")
            if status == 200:
                return _articles_from(ticker, response)
            if status != 429 and status < 500:
                raise DataUnavailableError(f"The news API returned HTTP {status}.")
            problem = f"HTTP {status}"
        if attempt < config.NEWS_RETRIES:
            time.sleep(config.NEWS_BACKOFF_SECONDS * attempt)
    raise DataUnavailableError(f"Could not download news for {ticker} ({problem}).")


def _fetch_split(ticker: str, start: date, end: date) -> list[Article]:
    # Ask for one extra day, so a chunk is fully covered even if the API's end date is exclusive.
    articles = fetch_company_news(ticker, start, end + timedelta(days=1))
    if len(articles) < config.NEWS_SPLIT_THRESHOLD:
        return articles
    if start == end:
        log.warning("%s on %s returned %d articles; the API may have truncated them", ticker, start, len(articles))
        return articles
    middle = start + (end - start) // 2
    return _fetch_split(ticker, start, middle) + _fetch_split(ticker, middle + timedelta(days=1), end)


def fetch_range(ticker: str, start: date, end: date) -> list[Article]:
    # All articles for [start, end]: weekly chunks, big chunks split, duplicates removed.
    found: dict[str, Article] = {}
    day = start
    while day <= end:
        chunk_end = min(day + timedelta(days=config.NEWS_CHUNK_DAYS - 1), end)
        for article in _fetch_split(ticker, day, chunk_end):
            found[article.id] = article
        day = chunk_end + timedelta(days=1)
    return sorted(found.values(), key=lambda a: a.published)


def _snapshot_path(ticker: str) -> Path:
    return config.NEWS_CACHE_DIR / f"{ticker}.json.gz"


def snapshot_exists(ticker: str) -> bool:
    return _snapshot_path(_safe_ticker(ticker)).exists()


def save_snapshot(ticker: str, articles: list[Article], start: date, end: date) -> None:
    ticker = _safe_ticker(ticker)
    path = _snapshot_path(ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "meta": {
            "ticker": ticker,
            "source": "finnhub /company-news",
            "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "articles": len(articles),
        },
        "articles": [article.to_dict() for article in articles],
    }
    temporary = path.with_suffix(".tmp")
    with gzip.open(temporary, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)
    temporary.replace(path)  # a stopped download never leaves a half-written snapshot


def load_snapshot(ticker: str) -> Snapshot:
    path = _snapshot_path(_safe_ticker(ticker))
    try:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        meta = payload["meta"]
        return Snapshot(
            ticker=ticker,
            start=date.fromisoformat(meta["start"]),
            end=date.fromisoformat(meta["end"]),
            retrieved_at=meta["retrieved_at"],
            articles=tuple(Article.from_dict(item) for item in payload["articles"]),
        )
    except FileNotFoundError as err:
        raise DataUnavailableError(f"No saved news for {ticker}. Run: python -m data.build_news") from err
    except (OSError, ValueError, KeyError, TypeError) as err:
        raise DataUnavailableError(f"The saved news file for {ticker} is unreadable.") from err
