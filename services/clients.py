# Client and holding management, stored in SQLite.
from __future__ import annotations

import math
import re
import sqlite3
from contextlib import closing

import config
from data import db
from services.contracts import Client, Holding, InputError

# Fictional demo clients, seeded when the database is empty. KO is held by all three.
DEMO_CLIENTS = [
    ("Demo client A", "conservative", ["KO", "PG", "JNJ", "WMT", "PEP"]),
    ("Demo client B", "balanced", ["KO", "AAPL", "JPM", "XOM", "V"]),
    ("Demo client C", "aggressive", ["KO", "NVDA", "TSLA", "CRWD", "NFLX"]),
]


def ensure_ready() -> None:
    """Create the tables if needed and seed the demo clients if there are none."""
    db.init_db()
    with closing(db.connect()) as conn:
        if conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] > 0:
            return
        for name, profile, tickers in DEMO_CLIENTS:
            cur = conn.execute("INSERT INTO clients (name, profile) VALUES (?, ?)", (name, profile))
            conn.executemany(
                "INSERT INTO holdings (client_id, ticker, quantity) VALUES (?, ?, NULL)",
                [(cur.lastrowid, ticker) for ticker in tickers],
            )
        conn.commit()


def _open() -> sqlite3.Connection:
    ensure_ready()
    return db.connect()


def _to_client(conn: sqlite3.Connection, row: sqlite3.Row) -> Client:
    holdings = conn.execute(
        "SELECT ticker, quantity FROM holdings WHERE client_id = ? ORDER BY rowid",
        (row["id"],),
    ).fetchall()
    return Client(
        client_id=row["id"],
        name=row["name"],
        profile=row["profile"],
        sensitivity_override=row["sensitivity_override"],
        holdings=tuple(Holding(h["ticker"], h["quantity"]) for h in holdings),
    )


def validate_ticker(raw: str) -> str:
    # Return the cleaned ticker, or raise InputError with a friendly message.
    ticker = (raw or "").strip().upper()
    if not ticker:
        raise InputError("Please enter a ticker.")
    if not re.fullmatch(r"[A-Z.\-]{1,6}", ticker):
        raise InputError("Tickers use 1-6 letters, for example KO.")
    if ticker not in config.SUPPORTED_TICKERS:
        raise InputError(f"'{ticker}' isn't supported yet. Supported tickers: {', '.join(config.SUPPORTED_TICKERS)}.")
    return ticker


def list_clients() -> list[Client]:
    with closing(_open()) as conn:
        rows = conn.execute("SELECT id, name, profile, sensitivity_override FROM clients ORDER BY id").fetchall()
        return [_to_client(conn, row) for row in rows]


def get_client(client_id: int) -> Client:
    with closing(_open()) as conn:
        row = conn.execute(
            "SELECT id, name, profile, sensitivity_override FROM clients WHERE id = ?",
            (client_id,),
        ).fetchone()
        if row is None:
            raise InputError("That client doesn't exist.")
        return _to_client(conn, row)


def add_client(name: str, profile: str) -> Client:
    name = (name or "").strip()
    if not name:
        raise InputError("Please enter a client name.")
    if len(name) > 60:
        raise InputError("Client names are limited to 60 characters.")
    if profile not in config.PROFILES:
        raise InputError(f"Risk profile must be one of: {', '.join(config.PROFILES)}.")
    with closing(_open()) as conn:
        cur = conn.execute("INSERT INTO clients (name, profile) VALUES (?, ?)", (name, profile))
        conn.commit()
        return Client(client_id=int(cur.lastrowid), name=name, profile=profile)


def add_holding(client_id: int, ticker: str, quantity: float | None = None) -> Client:
    client = get_client(client_id)  # raises InputError if the client doesn't exist
    ticker = validate_ticker(ticker)
    if quantity is not None and (not math.isfinite(quantity) or quantity <= 0):
        raise InputError("Quantity must be greater than zero.")
    if any(h.ticker == ticker for h in client.holdings):
        raise InputError(f"{ticker} is already in this client's holdings.")
    with closing(_open()) as conn:
        try:
            conn.execute(
                "INSERT INTO holdings (client_id, ticker, quantity) VALUES (?, ?, ?)",
                (client_id, ticker, quantity),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise InputError(f"{ticker} is already in this client's holdings.") from None
    return get_client(client_id)
