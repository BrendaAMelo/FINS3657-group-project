# Check that the tiers match realised volatility
from __future__ import annotations

import numpy as np
import pandas as pd

import config
from data.errors import DataError
from data.fetch import load_prices


def main() -> int:
    rows = []
    for ticker, info in config.STOCK_POOL.items():
        try:
            close = load_prices(ticker)["Close"]
        except DataError as err:
            print(f"skipped {ticker}: {err}")
            continue
        returns = close.pct_change().dropna()
        returns = returns[returns.index < pd.Timestamp(config.EVENT_WINDOW_START)]
        rows.append(
            {
                "ticker": ticker,
                "tier": info["tier"],
                "annualised_volatility": float(returns.std() * np.sqrt(252)),
            }
        )
    table = pd.DataFrame(rows).sort_values(["tier", "annualised_volatility"])
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(config.RESULTS_DIR / "tier_volatility.csv", index=False)
    print(table.round(3).to_string(index=False))
    print()
    summary = table.groupby("tier")["annualised_volatility"].agg(["min", "median", "max"])
    print(summary.round(3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
