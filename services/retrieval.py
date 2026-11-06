# Find the news that could explain a flagged day, from the saved snapshot (no network).
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import cache, lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

import config
from data.fetch import load_prices
from data.news import Article, Snapshot, load_snapshot

EASTERN = ZoneInfo("America/New_York")
MIN_RELEVANCE = 2


@dataclass(frozen=True)
class Retrieved:
    ticker: str
    window_start: date
    window_end: date
    articles: tuple[Article, ...]  # relevant, de-duplicated, ranked, at most NEWS_MAX_ARTICLES
    distinct_relevant: int  # count before the cap
    covered: bool  # False if the window reaches outside the downloaded snapshot


def news_window(calendar: pd.DatetimeIndex, flag_date: date, before: int, after: int) -> tuple[date, date]:
    # Trading-day window around a flagged day (a weekend date snaps to the next trading day).
    position = min(int(calendar.searchsorted(pd.Timestamp(flag_date))), len(calendar) - 1)
    start = calendar[max(position - before, 0)]
    end = calendar[min(position + after, len(calendar) - 1)]
    return start.date(), end.date()


def et_date(article: Article) -> date:
    # Publication date in US Eastern time, the market's calendar.
    return article.published.astimezone(EASTERN).date()


@cache
def _patterns(ticker: str) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    aliases = config.NEWS_ALIASES.get(ticker)
    if not aliases:
        raise ValueError(f"No news aliases configured for {ticker}")
    names = "|".join(re.escape(alias) for alias in aliases)
    name_pattern = re.compile(rf"(?<!\w)(?:{names})(?!\w)", re.IGNORECASE)
    # Short tickers (KO, V, BA) are ordinary words or letters, so only longer symbols count
    symbol_pattern = re.compile(rf"(?<!\w)\$?{re.escape(ticker)}(?!\w)") if len(ticker) >= 3 else None
    return name_pattern, symbol_pattern


def relevance_score(article: Article, ticker: str) -> int:
    # Higher means more clearly about this company. A headline mention is the strongest signal.
    name, symbol = _patterns(ticker)
    score = 0
    if name.search(article.headline):
        score += 3
    if symbol and symbol.search(article.headline):
        score += 3
    if name.search(article.summary):
        score += 1
    if symbol and symbol.search(article.summary):
        score += 1
    related = {t.strip().upper() for t in article.related.split(",") if t.strip()}
    if ticker in related and len(related) <= 3:  # roundups tag many tickers: no credit
        score += 1
    return score


def _tokens(headline: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", headline.lower()))


def deduplicate(articles: list[Article]) -> list[Article]:
    # Drop copies and near-copies of the same headline, keeping the earliest.
    kept: list[tuple[Article, frozenset[str]]] = []
    for article in sorted(articles, key=lambda a: a.published):
        tokens = _tokens(article.headline)
        if any(
            tokens and other and len(tokens & other) / len(tokens | other) >= config.NEWS_DUPLICATE_SIMILARITY
            for _, other in kept
        ):
            continue
        kept.append((article, tokens))
    return [article for article, _ in kept]


@lru_cache(maxsize=32)
def _saved_snapshot(ticker: str, path: Path, modified: int) -> Snapshot:
    # Parsing a compressed year of news for every flagged day is unnecessary.
    # File identity/mtime keeps refreshes and isolated test snapshots separate.
    return load_snapshot(ticker)


def retrieve(ticker: str, flag_date: date, start: date | None = None) -> Retrieved:
    # Relevant, distinct, ranked articles around a flagged day.

    # `start` overrides the window start (the coverage count starts at the announcement day).
    calendar = load_prices(ticker, validate=False).index
    window_start, window_end = news_window(
        calendar, flag_date, config.NEWS_BEFORE_TRADING_DAYS, config.NEWS_AFTER_TRADING_DAYS
    )
    if start is not None:
        window_start = start
    path = config.NEWS_CACHE_DIR / f"{ticker}.json.gz"
    snapshot = _saved_snapshot(ticker, path, path.stat().st_mtime_ns) if path.exists() else load_snapshot(ticker)
    position = int(calendar.searchsorted(pd.Timestamp(flag_date)))
    full_calendar_window = (
        position < len(calendar)
        and position + config.NEWS_AFTER_TRADING_DAYS < len(calendar)
        and (start is not None or position >= config.NEWS_BEFORE_TRADING_DAYS)
    )
    covered = full_calendar_window and snapshot.start <= window_start and window_end <= snapshot.end

    scores: dict[str, int] = {}
    candidates: list[Article] = []
    for article in snapshot.articles:
        if not window_start <= et_date(article) <= window_end:
            continue
        score = relevance_score(article, ticker)
        if score >= MIN_RELEVANCE:
            scores[article.id] = score
            candidates.append(article)

    distinct = deduplicate(candidates)
    ranked = sorted(
        distinct,
        key=lambda a: (-scores[a.id], abs((et_date(a) - flag_date).days), a.published),
    )
    return Retrieved(
        ticker=ticker,
        window_start=window_start,
        window_end=window_end,
        articles=tuple(ranked[: config.NEWS_MAX_ARTICLES]),
        distinct_relevant=len(distinct),
        covered=covered,
    )
