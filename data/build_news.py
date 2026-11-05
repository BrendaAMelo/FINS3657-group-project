# Download the news snapshot for every ticker in the pool.
# Run from the repo root:  python -m data.build_news   (add --refresh to download again)
# It takes roughly 15-25 minutes because of the API rate limit.
# Safe to stop and rerun: tickers that are already saved are skipped.

from __future__ import annotations

import sys

import config
from data.errors import DataError
from data.news import fetch_range, save_snapshot, snapshot_exists


def main(refresh: bool = False) -> int:
    start, end = config.NEWS_SNAPSHOT_START, config.NEWS_SNAPSHOT_END
    failures: list[str] = []
    for ticker in config.SUPPORTED_TICKERS:
        if not refresh and snapshot_exists(ticker):
            print(f"skip    {ticker}: already saved")
            continue
        try:
            articles = fetch_range(ticker, start, end)
        except DataError as err:
            failures.append(ticker)
            print(f"FAILED  {ticker}: {err}")
            continue
        save_snapshot(ticker, articles, start, end)
        if not articles:
            print(f"ok      {ticker}: 0 articles (check the key and the dates)")
            continue
        first, last = articles[0].published.date(), articles[-1].published.date()
        late = " (starts late: possible lookback limit)" if (first - start).days > 7 else ""
        print(f"ok      {ticker}: {len(articles)} articles, {first} to {last}{late}")
    if failures:
        print(f"\n{len(failures)} failed: {', '.join(failures)}. Rerun to retry them.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(refresh="--refresh" in sys.argv))
