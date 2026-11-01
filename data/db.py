# SQLite access. Use ? placeholders for every value, never string-built SQL.
from __future__ import annotations

import sqlite3
from contextlib import closing

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    profile TEXT NOT NULL CHECK (profile IN ('conservative', 'balanced', 'aggressive')),
    sensitivity_override REAL
);
CREATE TABLE IF NOT EXISTS holdings (
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    ticker TEXT NOT NULL,
    quantity REAL,
    PRIMARY KEY (client_id, ticker)
);
"""


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with closing(connect()) as conn:
        conn.executescript(SCHEMA)
        conn.commit()
