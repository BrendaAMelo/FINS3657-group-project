# Populate the price cache for every ticker in the pool.
from __future__ import annotations

import sys
import time

import config
from data.errors import DataError
from data.fetch import load_prices


def main(refresh: bool = False) -> int:
    failures: list[str] = []
    for ticker in config.SUPPORTED_TICKERS:
        try:
            df = load_prices(ticker, refresh=refresh)
        except DataError as err:
            failures.append(ticker)
            print(f"FAILED  {ticker}: {err}")
        else:
            first, last = df.index.min().date(), df.index.max().date()
            print(f"ok      {ticker}: {len(df)} rows, {first} to {last}")
            time.sleep(0.5)  # be gentle with the free service
    if failures:
        print(f"\n{len(failures)} failed: {', '.join(failures)}. Wait a bit and rerun.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(refresh="--refresh" in sys.argv))
