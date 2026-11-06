import pytest

from services import clients, detection, history
from services.contracts import InputError


@pytest.fixture
def setup(monkeypatch, make_prices):
    prices = make_prices(n=300)
    flags = (
        detection.Flag("KO", prices.index[-5].date(), "isolation_forest", 0.7, "high", "Unusual features."),
        detection.Flag("KO", prices.index[-200].date(), "isolation_forest", 0.6, "low", "Older flag."),
    )
    calls = []

    def snapshot(*args):
        calls.append(args)
        return prices, flags

    monkeypatch.setattr(detection, "snapshot", snapshot)
    client = clients.add_client("Chart client", "aggressive")
    clients.add_holding(client.client_id, "KO")
    clients.set_sensitivity_override(client.client_id, 3.2)
    return prices, flags, calls, client


def test_chart_uses_matching_flags_and_actual_closes(setup):
    prices, flags, calls, client = setup
    view = history.price_view(client.client_id, "KO", days=100)
    assert list(view.prices.columns) == ["Date", "Close"]
    assert len(view.prices) == 100
    assert [point.day for point in view.flags] == [flags[0].day]
    assert view.flags[0].close == pytest.approx(float(prices.Close.iloc[-5]))
    assert calls == [("KO", "aggressive", 3.2)]


def test_wider_chart_keeps_older_flags_without_changing_detection(setup):
    _, flags, calls, client = setup
    view = history.price_view(client.client_id, "KO", days=250)
    assert {point.day for point in view.flags} == {flag.day for flag in flags}
    assert calls == [("KO", "aggressive", 3.2)]


def test_no_flags_still_returns_prices(monkeypatch, setup):
    prices, _, _, client = setup
    monkeypatch.setattr(detection, "snapshot", lambda *args: (prices, ()))
    view = history.price_view(client.client_id, "KO")
    assert view.flags == () and not view.prices.empty


def test_holdings_must_belong_to_client(setup):
    _, _, _, client = setup
    for client_id, ticker in [(client.client_id, "PG"), (client.client_id, "ZZZZ"), (10**9, "KO")]:
        with pytest.raises(InputError):
            history.price_view(client_id, ticker)


@pytest.mark.parametrize("days", [0, -1, True, 1.5])
def test_invalid_period_rejected(setup, days):
    with pytest.raises(InputError):
        history.price_view(setup[-1].client_id, "KO", days)
