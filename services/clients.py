# Client and holding management, stored in SQLite.
from __future__ import annotations

import math
import re
import sqlite3
from contextlib import closing

import config
from data import db
from services.contracts import Client, Holding, InputError


def ensure_ready() -> None:
    """Initialise the database without automatically creating clients."""
    db.init_db()


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


def remove_holding(client_id: int, ticker: str) -> Client:
    get_client(client_id)  # raises InputError if the client doesn't exist
    ticker = validate_ticker(ticker)
    with closing(_open()) as conn:
        cur = conn.execute("DELETE FROM holdings WHERE client_id = ? AND ticker = ?", (client_id, ticker))
        conn.commit()
        removed = cur.rowcount
    if removed == 0:
        raise InputError(f"{ticker} is not in this client's holdings.")
    return get_client(client_id)


def delete_client(client_id: int) -> None:
    get_client(client_id)

    with closing(_open()) as conn:
        _ensure_alert_reviews(conn)

        conn.execute(
            "DELETE FROM alert_reviews WHERE client_id = ?",
            (client_id,),
        )
        conn.execute(
            "DELETE FROM clients WHERE id = ?",
            (client_id,),
        )
        conn.commit()


def set_profile(client_id: int, profile: str) -> Client:
    get_client(client_id)
    if profile not in config.PROFILES:
        raise InputError(f"Risk profile must be one of: {', '.join(config.PROFILES)}.")
    with closing(_open()) as conn:
        conn.execute("UPDATE clients SET profile = ? WHERE id = ?", (profile, client_id))
        conn.commit()
    return get_client(client_id)


def set_sensitivity_override(client_id: int, value: float | None) -> Client:
    get_client(client_id)
    if value is not None and not (math.isfinite(value) and config.OVERRIDE_MIN <= value <= config.OVERRIDE_MAX):
        raise InputError(f"Sensitivity must be between {config.OVERRIDE_MIN} and {config.OVERRIDE_MAX}.")
    with closing(_open()) as conn:
        conn.execute("UPDATE clients SET sensitivity_override = ? WHERE id = ?", (value, client_id))
        conn.commit()
    return get_client(client_id)


def add_holdings(
    client_id: int,
    tickers: list[str],
) -> tuple[Client, list[str], list[tuple[str, str]]]:
    # Add multiple holdings, returning the updated client, successes and failures.
    get_client(client_id)

    added: list[str] = []
    skipped: list[tuple[str, str]] = []

    # Validate and insert each ticker independently. One duplicate or invalid
    # ticker should not prevent the remaining valid tickers being added.
    for raw_ticker in dict.fromkeys(tickers):
        try:
            ticker = validate_ticker(raw_ticker)
            add_holding(client_id, ticker)
        except InputError as err:
            skipped.append((str(raw_ticker).strip().upper(), str(err)))
        else:
            added.append(ticker)

    return get_client(client_id), added, skipped


def _ensure_alert_reviews(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS alert_reviews (
            client_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            alert_date TEXT NOT NULL,
            detector TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK (status IN ('Unreviewed', 'Reviewed', 'Follow-up required')),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (client_id, ticker, alert_date, detector)
        )
        """
    )


def get_alert_reviews(client_id: int) -> dict[tuple[str, str, str], str]:
    # Return saved review statuses keyed by ticker, alert date and detector.
    get_client(client_id)

    with closing(_open()) as conn:
        _ensure_alert_reviews(conn)
        rows = conn.execute(
            """
            SELECT ticker, alert_date, detector, status
            FROM alert_reviews
            WHERE client_id = ?
            """,
            (client_id,),
        ).fetchall()

    return {(row["ticker"], row["alert_date"], row["detector"]): row["status"] for row in rows}


def set_alert_review(
    client_id: int,
    ticker: str,
    alert_date: str,
    detector: str,
    status: str,
) -> None:
    # Save a review status without changing the underlying alert.
    get_client(client_id)

    allowed = {"Unreviewed", "Reviewed", "Follow-up required"}
    if status not in allowed:
        raise InputError(f"Review status must be one of: {', '.join(sorted(allowed))}.")

    ticker = validate_ticker(ticker)
    alert_date = str(alert_date)

    with closing(_open()) as conn:
        _ensure_alert_reviews(conn)
        conn.execute(
            """
            INSERT INTO alert_reviews
                (client_id, ticker, alert_date, detector, status, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(client_id, ticker, alert_date, detector)
            DO UPDATE SET
                status = excluded.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            (client_id, ticker, alert_date, detector, status),
        )
        conn.commit()
