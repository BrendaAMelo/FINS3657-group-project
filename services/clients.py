# Client and holding management. DUMMY VERSION. Should be replaced with SQLite later

from __future__ import annotations

import re
from dataclasses import replace

import config
from services.contracts import Client, Holding, InputError

_clients: dict[int, Client] = {}
_next_id = 1


def _seed() -> None:
    global _next_id
    demo = [
        ("Demo client A", "conservative", ["KO", "JNJ", "PG"]),
        ("Demo client B", "balanced", ["KO", "JPM", "MSFT"]),
        ("Demo client C", "aggressive", ["KO", "NVDA", "TSLA"]),
    ]
    for name, profile, tickers in demo:
        _clients[_next_id] = Client(
            client_id=_next_id,
            name=name,
            profile=profile,
            holdings=tuple(Holding(t) for t in tickers),
        )
        _next_id += 1


_seed()


def validate_ticker(raw: str) -> str:
    # Return the cleaned ticker, or raise InputError with message.
    ticker = (raw or "").strip().upper()
    if not ticker:
        raise InputError("Please enter a ticker.")
    if not re.fullmatch(r"[A-Z.\-]{1,6}", ticker):
        raise InputError("Tickers use 1-6 letters, for example KO.")
    if ticker not in config.SUPPORTED_TICKERS:
        raise InputError(f"'{ticker}' isn't supported yet. Supported tickers: {', '.join(config.SUPPORTED_TICKERS)}.")
    return ticker


def list_clients() -> list[Client]:
    return list(_clients.values())


def get_client(client_id: int) -> Client:
    try:
        return _clients[client_id]
    except KeyError:
        raise InputError("That client doesn't exist.") from None


def add_client(name: str, profile: str) -> Client:
    global _next_id
    name = (name or "").strip()
    if not name:
        raise InputError("Please enter a client name.")
    if len(name) > 60:
        raise InputError("Client names are limited to 60 characters.")
    if profile not in config.PROFILES:
        raise InputError(f"Risk profile must be one of: {', '.join(config.PROFILES)}.")
    client = Client(client_id=_next_id, name=name, profile=profile)
    _clients[_next_id] = client
    _next_id += 1
    return client


def add_holding(client_id: int, ticker: str, quantity: float | None = None) -> Client:
    client = get_client(client_id)
    ticker = validate_ticker(ticker)
    if quantity is not None and quantity <= 0:
        raise InputError("Quantity must be greater than zero.")
    if any(h.ticker == ticker for h in client.holdings):
        raise InputError(f"{ticker} is already in this client's holdings.")
    updated = replace(client, holdings=client.holdings + (Holding(ticker, quantity),))
    _clients[client_id] = updated
    return updated
