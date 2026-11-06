"""Optional cache warming; the app also generates missing explanations automatically.

Use --alerts for current clients or --tickers for a prepared demo pool.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from datetime import date

import config
from data.errors import DataError
from data.events import load_events
from services import clients, detection
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


def alert_pairs() -> list[tuple[str, date, str]]:
    pairs = set()
    for client in clients.list_clients():
        for holding in client.holdings:
            for flag in detection.get_flags(holding.ticker, client.profile, client.sensitivity_override):
                pairs.add((flag.ticker, flag.day, flag.summary))
    return sorted(pairs)


def ticker_pairs(tickers: list[str], profiles: list[str]) -> list[tuple[str, date, str]]:
    return sorted(
        {
            (flag.ticker, flag.day, flag.summary)
            for ticker in tickers
            for profile in profiles
            for flag in detection.get_flags(ticker, profile)
        }
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--events", action="store_true", help="Legacy labelled-event examples")
    modes.add_argument("--alerts", action="store_true", help="Actual flags for existing client holdings/settings")
    modes.add_argument("--tickers", nargs="+", choices=config.SUPPORTED_TICKERS, help="Actual flags for these stocks")
    parser.add_argument("--profiles", nargs="+", choices=tuple(config.PROFILES), default=list(config.PROFILES))
    if not argv:
        parser.print_usage()
        return 2
    args = parser.parse_args(argv)
    try:
        pairs = (
            event_pairs()
            if args.events
            else (alert_pairs() if args.alerts else ticker_pairs(args.tickers, args.profiles))
        )
        counts = prefetch(pairs)
    except DataError as err:
        print(err)
        return 1
    print(f"\n{counts}")
    return 1 if counts["unavailable"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
