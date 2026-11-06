"""# Price history with the flagged days marked, for the charts. The UI calls this, not the data layer.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd
from models.detectors import get_flags  # Stage C: adjust if your module or columns differ

from data.fetch import load_prices
from services import clients
from services.contracts import InputError

PRIMARY_DETECTOR = "isolation_forest"  # chart only this detector's flags when present


@dataclass(frozen=True)
class FlagPoint:
    day: date
    close: float
    severity: str
    detector: str
    summary: str


@dataclass(frozen=True)
class PriceView:
    ticker: str
    prices: pd.DataFrame  # columns: Date, Close
    flags: tuple[FlagPoint, ...]


def price_view(client_id: int, ticker: str, days: int = 120) -> PriceView:
    client = clients.get_client(client_id)
    ticker = clients.validate_ticker(ticker)
    if ticker not in {h.ticker for h in client.holdings}:
        raise InputError(f"{ticker} is not in this client's holdings.")

    closes = load_prices(ticker, validate=False)["Close"].tail(days)
    flags = get_flags(
        ticker,
        client.profile,
        closes.index.min().date(),
        closes.index.max().date(),
        client.sensitivity_override,
    )
    points: list[FlagPoint] = []
    if not flags.empty:
        if PRIMARY_DETECTOR in set(flags["detector"]):
            flags = flags[flags["detector"] == PRIMARY_DETECTOR]
        for row in flags.itertuples():
            day = pd.Timestamp(row.date).normalize()
            if day in closes.index:
                points.append(
                    FlagPoint(
                        day=day.date(),
                        close=float(closes.loc[day]),
                        severity=str(row.severity),
                        detector=str(row.detector),
                        summary=str(row.summary),
                    )
                )
    prices = closes.rename("Close").rename_axis("Date").reset_index()
    return PriceView(ticker=ticker, prices=prices, flags=tuple(points))"""
