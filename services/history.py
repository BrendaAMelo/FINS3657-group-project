"""Price history with the same real flags used by the alert dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from services import clients, detection
from services.contracts import InputError


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
    prices: pd.DataFrame
    flags: tuple[FlagPoint, ...]


def price_view(client_id: int, ticker: str, days: int = 120) -> PriceView:
    client = clients.get_client(client_id)
    ticker = clients.validate_ticker(ticker)
    if ticker not in {h.ticker for h in client.holdings}:
        raise InputError(f"{ticker} is not in this client's holdings.")
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise InputError("Choose a positive number of trading days.")
    prices, flags = detection.snapshot(ticker, client.profile, client.sensitivity_override)
    closes = prices.Close.tail(days)
    points = tuple(
        FlagPoint(f.day, float(closes.loc[pd.Timestamp(f.day)]), f.severity, f.detector, f.summary)
        for f in flags
        if pd.Timestamp(f.day) in closes.index
    )
    return PriceView(ticker, closes.rename("Close").rename_axis("Date").reset_index(), points)
