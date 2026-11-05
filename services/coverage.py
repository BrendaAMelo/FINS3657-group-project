# Count the news around each event: python -m services.coverage
# The window runs from the announcement day to 3 trading days after the first trading day.
# Writes results/event_news_coverage.csv (copy the values into the shared sheet if wanted).

from __future__ import annotations

import pandas as pd

import config
from data.errors import DataError
from data.events import load_events
from services.retrieval import retrieve

COLUMNS = ["event_id", "ticker", "first_trading_day", "news_article_count", "news_coverage"]


def coverage_level(count: int) -> str:
    if count <= 0:
        return "none"
    if count <= config.COVERAGE_SPARSE_MAX:
        return "sparse"
    if count <= config.COVERAGE_NORMAL_MAX:
        return "normal"
    return "heavy"


def build_table(events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for event in events.itertuples():
        found = retrieve(
            event.ticker,
            event.first_trading_day.date(),
            start=event.announcement_date.date(),
        )
        count = found.distinct_relevant if found.covered else None
        rows.append(
            {
                "event_id": event.event_id,
                "ticker": event.ticker,
                "first_trading_day": event.first_trading_day.date().isoformat(),
                "news_article_count": count,
                "news_coverage": coverage_level(count) if count is not None else "unknown",
            }
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def news_quota_warnings(table: pd.DataFrame) -> list[str]:
    warnings: list[str] = []
    thin = int(table["news_coverage"].isin(["none", "sparse"]).sum())
    if thin < 2:
        warnings.append(f"only {thin} events with sparse or no news (need at least 2)")
    unknown = int((table["news_coverage"] == "unknown").sum())
    if unknown:
        warnings.append(f"{unknown} events fall outside the downloaded news snapshot")
    return warnings


def main() -> int:
    try:
        table = build_table(load_events())
    except DataError as err:
        print(err)
        return 1
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(config.RESULTS_DIR / "event_news_coverage.csv", index=False)
    print(table.to_string(index=False))
    print()
    print(table["news_coverage"].value_counts().to_string())
    for warning in news_quota_warnings(table):
        print("WARNING:", warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
