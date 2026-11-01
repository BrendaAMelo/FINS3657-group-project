# Health check of the cached price data: python -m data.sanity_check
from __future__ import annotations

import pandas as pd

import config
from data.errors import DataError
from data.features import build_features
from data.fetch import cache_info, load_prices

LARGE_MOVE = 0.25  # one-day moves this big get a note to review
LONG_RUN = 10  # days in a row of unusually high volume
SPLIT_RATIOS = (2, 3, 4, 5, 10, 15, 20)
# Large moves reviewed and confirmed as real events: (ticker, date) -> reason
KNOWN_LARGE_MOVES = {("NFLX", "2022-04-20"): "Q1 2022 subscriber loss"}


def looks_like_split(ret: float, tolerance: float = 0.03) -> bool:
    # True if a one-day return has the shape of a stock split (price cut to 1/k or raised k-fold).
    ratio = 1 + ret
    return any(abs(ratio - 1 / k) < tolerance or abs(ratio / k - 1) < tolerance for k in SPLIT_RATIOS)


def longest_run(mask: pd.Series) -> int:
    groups = (mask != mask.shift()).cumsum()
    runs = mask.groupby(groups).sum()
    return int(runs.max()) if len(runs) else 0


def check_ticker(ticker: str) -> dict:
    prices = load_prices(ticker)
    returns = prices["Close"].pct_change().dropna()
    feats = build_features(prices)
    info = cache_info(ticker) or {}
    gaps = prices.index.to_series().diff().dt.days.dropna()
    return {
        "ticker": ticker,
        "rows": len(prices),
        "first": prices.index.min().date(),
        "last": prices.index.max().date(),
        "last_close": round(float(prices["Close"].iloc[-1]), 2),
        "max_abs_move": round(float(returns.abs().max()), 3),
        "max_move_date": returns.abs().idxmax().date(),
        "zero_vol_days": int((prices["Volume"] <= 0).sum()),
        "max_gap_days": int(gaps.max()),
        "feature_rows": len(feats),
        "feature_rows_expected": len(prices) - config.FEATURE_WINDOW - 1,
        "high_vol_run": longest_run(feats["vol_ratio"] > 3),
        "retrieved": str(info.get("retrieved_at", "?"))[:10],
        "split_dates": [d.date() for d, r in returns.items() if looks_like_split(r)],
    }


def main() -> int:
    rows, warnings, notes = [], [], []
    for ticker in config.SUPPORTED_TICKERS:
        try:
            rows.append(check_ticker(ticker))
        except DataError as err:
            warnings.append(f"{ticker}: {err}")
    if not rows:
        print("\n".join(warnings) or "No data found. Run: python -m data.build_cache")
        return 1

    table = pd.DataFrame(rows).drop(columns=["split_dates"])
    print(table.to_string(index=False))

    common_rows = int(table["rows"].mode().iloc[0])
    end = pd.Timestamp(config.PRICE_DATA_END).date()
    for r in rows:
        t = r["ticker"]
        if r["rows"] != common_rows:
            warnings.append(f"{t}: {r['rows']} rows, most tickers have {common_rows}")
        if (end - r["last"]).days > 3:
            warnings.append(f"{t}: data ends {r['last']}, expected about {end}")
        if r["split_dates"]:
            dates = ", ".join(str(d) for d in r["split_dates"])
            warnings.append(f"{t}: split-shaped price change on {dates} (unadjusted split?)")
        if r["max_abs_move"] > LARGE_MOVE:
            key = (t, str(r["max_move_date"]))
            reason = KNOWN_LARGE_MOVES.get(key)
            if reason:
                notes.append(f"{t}: {r['max_abs_move']:.0%} move on {key[1]} is a known event ({reason})")
            else:
                notes.append(f"{t}: {r['max_abs_move']:.0%} move on {key[1]}, check the news")
        if r["high_vol_run"] >= LONG_RUN:
            warnings.append(f"{t}: {r['high_vol_run']} days in a row of very high volume")
        if r["feature_rows"] != r["feature_rows_expected"]:
            warnings.append(f"{t}: {r['feature_rows']} feature rows, expected {r['feature_rows_expected']}")
    print()
    print("\n".join(f"NOTE: {n}" for n in notes))
    print("\n".join(f"WARNING: {w}" for w in warnings) or "No warnings.")
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
