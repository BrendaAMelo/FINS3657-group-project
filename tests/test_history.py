"""import pandas as pd
import pytest

from services import clients, history
from services.contracts import InputError


@pytest.fixture
def setup(monkeypatch, make_prices):
    prices = make_prices(n=300)
    calls = []
    monkeypatch.setattr(history, "load_prices", lambda ticker, validate=False: prices)

    def fake_flags(ticker, profile, start, end, sensitivity_override=None):
        calls.append((ticker, profile, start, end, sensitivity_override))
        return pd.DataFrame(
            {
                "date": [prices.index[-5], prices.index[-20], pd.Timestamp("2000-01-03")],
                "detector": ["isolation_forest", "z_score", "isolation_forest"],
                "score": [0.9, 0.5, 0.7],
                "severity": ["high", "low", "medium"],
                "summary": ["a", "b", "c"],
            }
        )

    monkeypatch.setattr(history, "get_flags", fake_flags)
    client = clients.add_client("Chart client", "aggressive")
    clients.add_holding(client.client_id, "KO")
    clients.set_sensitivity_override(client.client_id, 3.2)
    return prices, calls, client


def test_view_has_prices_and_only_primary_detector_flags_on_trading_days(setup):
    prices, _, client = setup
    view = history.price_view(client.client_id, "KO", days=100)
    assert list(view.prices.columns) == ["Date", "Close"] and len(view.prices) == 100
    assert [f.severity for f in view.flags] == ["high"]  # the 2000 date and z-score row are dropped
    assert view.flags[0].close == pytest.approx(float(prices["Close"].iloc[-5]))


def test_the_clients_settings_are_passed_to_the_detector(setup):
    _, calls, client = setup
    history.price_view(client.client_id, "KO", days=100)
    ticker, profile, _, _, override = calls[0]
    assert (ticker, profile, override) == ("KO", "aggressive", 3.2)


def test_all_flags_are_kept_when_the_primary_detector_is_absent(monkeypatch, setup):
    prices, _, client = setup
    only_z = pd.DataFrame(
        {"date": [prices.index[-3]], "detector": ["z_score"], "score": [1.0], "severity": ["low"], "summary": ["z"]}
    )
    monkeypatch.setattr(history, "get_flags", lambda *a, **k: only_z)
    assert len(history.price_view(client.client_id, "KO").flags) == 1


def test_no_flags_gives_an_empty_tuple(monkeypatch, setup):
    _, _, client = setup
    monkeypatch.setattr(history, "get_flags", lambda *a, **k: pd.DataFrame())
    assert history.price_view(client.client_id, "KO").flags == ()


def test_holdings_must_belong_to_the_client(setup):
    _, _, client = setup
    with pytest.raises(InputError):
        history.price_view(client.client_id, "PG")
    with pytest.raises(InputError):
        history.price_view(client.client_id, "ZZZZ")
    with pytest.raises(InputError):
        history.price_view(10**9, "KO")"""
