import sqlite3
from contextlib import closing

import pytest

import config
from data import db
from services import clients


def test_demo_clients_are_seeded_once():
    assert len(clients.list_clients()) == len(clients.DEMO_CLIENTS)
    clients.ensure_ready()
    clients.ensure_ready()
    assert len(clients.list_clients()) == len(clients.DEMO_CLIENTS)


def test_init_db_is_idempotent():
    db.init_db()
    db.init_db()
    assert len(clients.list_clients()) == len(clients.DEMO_CLIENTS)


def test_data_persists_across_connections():
    client = clients.add_client("Persistent", "balanced")
    clients.add_holding(client.client_id, "KO", 5)
    again = clients.get_client(client.client_id)
    assert [h.ticker for h in again.holdings] == ["KO"]
    assert again.holdings[0].quantity == 5


def test_holdings_keep_the_order_they_were_added_in():
    client = clients.add_client("Ordered", "balanced")
    for ticker in ("PG", "KO", "AAPL"):
        clients.add_holding(client.client_id, ticker)
    assert [h.ticker for h in clients.get_client(client.client_id).holdings] == [
        "PG",
        "KO",
        "AAPL",
    ]


def test_hostile_input_is_stored_literally_and_tables_survive():
    nasty = "Robert'); DROP TABLE clients;--"
    client = clients.add_client(nasty, "balanced")
    assert clients.get_client(client.client_id).name == nasty
    assert len(clients.list_clients()) == len(clients.DEMO_CLIENTS) + 1


def test_database_rejects_an_invalid_profile():
    with closing(db.connect()) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO clients (name, profile) VALUES (?, ?)", ("X", "reckless"))


def test_database_accepts_every_configured_profile():
    # Guards against config.PROFILES and the schema's CHECK list drifting apart.
    with closing(db.connect()) as conn:
        for profile in config.PROFILES:
            conn.execute("INSERT INTO clients (name, profile) VALUES (?, ?)", ("X", profile))
        conn.commit()


def test_database_enforces_one_row_per_holding():
    client = clients.add_client("Unique", "balanced")
    with closing(db.connect()) as conn:
        conn.execute("INSERT INTO holdings (client_id, ticker) VALUES (?, ?)", (client.client_id, "KO"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO holdings (client_id, ticker) VALUES (?, ?)",
                (client.client_id, "KO"),
            )


def test_deleting_a_client_removes_their_holdings():
    client = clients.add_client("Temporary", "balanced")
    clients.add_holding(client.client_id, "KO")
    with closing(db.connect()) as conn:
        conn.execute("DELETE FROM clients WHERE id = ?", (client.client_id,))
        conn.commit()
        remaining = conn.execute("SELECT COUNT(*) FROM holdings WHERE client_id = ?", (client.client_id,)).fetchone()[0]
    assert remaining == 0
