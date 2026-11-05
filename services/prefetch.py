"""Generate and cache explanations ahead of time: python -m services.prefetch --events

Prefetched explanations make the demo independent of the model and the network. Stage E will
call prefetch() with the real alerts for the demo clients.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable
from datetime import date

from data.errors import DataError
from data.events import load_events
from services.explain import explain

STANDARD_SUMMARY = "Price and volume moved unusually compared with this stock's own history."


def prefetch(pairs: Iterable[tuple[str, date, str]]) -> dict[str, int]:
    counts = {"ok": 0, "no_news": 0, "unavailable": 0}
    for ticker, day, summary in pairs:
        result = explain(ticker, day, summary)
        counts[result.status] += 1
        print(f"{result.status:<12}{ticker:<6}{day}")
    return counts


def event_pairs() -> list[tuple[str, date, str]]:
    events = load_events()
    return [(e.ticker, e.first_trading_day.date(), STANDARD_SUMMARY) for e in events.itertuples()]


def main(argv: list[str]) -> int:
    if "--events" not in argv:
        print("Usage: python -m services.prefetch --events")
        return 2
    try:
        counts = prefetch(event_pairs())
    except DataError as err:
        print(err)
        return 1
    print(f"\n{counts}")
    return 1 if counts["unavailable"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
