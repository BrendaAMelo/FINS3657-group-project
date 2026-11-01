# Contract tests: what the UI is allowed to rely on from services.clients and services.alerts.

# These pass against the dummy in-memory services and must keep passing when
# the real implementations (SQLite, models, news) replace them.

import dataclasses
import re
from datetime import date

import pytest

import config
from services import alerts, clients
from services.contracts import Alert, InputError

SEVERITIES = {"high", "medium", "low"}
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
EXPLANATION_STATUSES = {"ok", "no_news", "unavailable"}
FORBIDDEN_ADVICE = re.compile(
    r"\b(you should (buy|sell|hold)|buy now|sell now|we recommend (buying|selling)|"
    r"(buy|sell) (more|this|the stock))\b",
    re.IGNORECASE,
)


@pytest.fixture
def client():
    """A fresh client with no holdings, so tests never depend on each other."""
    return clients.add_client("Test client", "balanced")


def _assert_valid_alert(alert: Alert, owner_id: int) -> None:
    assert isinstance(alert, Alert)
    assert alert.client_id == owner_id
    assert isinstance(alert.ticker, str) and alert.ticker
    assert isinstance(alert.alert_date, date)
    assert alert.severity in SEVERITIES
    assert alert.explanation_status in EXPLANATION_STATUSES
    assert isinstance(alert.score, float)
    assert isinstance(alert.validated, bool)
    assert isinstance(alert.detector, str) and alert.detector
    assert isinstance(alert.summary, str) and alert.summary.strip()
    assert isinstance(alert.explanation, str) and alert.explanation.strip()
    for source in alert.sources:
        assert source.title.strip()
        assert source.url.startswith(("http://", "https://"))


# validate_ticker
@pytest.mark.parametrize("ticker", config.SUPPORTED_TICKERS)
def test_every_supported_ticker_is_accepted(ticker):
    assert clients.validate_ticker(ticker) == ticker


def test_ticker_is_trimmed_and_uppercased():
    sample = config.SUPPORTED_TICKERS[0]
    assert clients.validate_ticker(f"  {sample.lower()} ") == sample


def test_stock_pool_is_well_formed():
    assert len(config.STOCK_POOL) >= 15
    for ticker, info in config.STOCK_POOL.items():
        assert ticker == ticker.upper()
        assert set(info) == {"company", "sector", "tier"}
        assert info["tier"] in {"calm", "balanced", "volatile"}
    assert all(config.TICKERS_BY_TIER[t] for t in ("calm", "balanced", "volatile"))


@pytest.mark.parametrize(
    "bad",
    [None, "", "   ", "123", "KO1", "K O", "KO; DROP TABLE clients", "TOOLONGTICKER"],
)
def test_malformed_tickers_are_rejected(bad):
    with pytest.raises(InputError):
        clients.validate_ticker(bad)


def test_unsupported_ticker_message_lists_supported_ones():
    with pytest.raises(InputError) as exc:
        clients.validate_ticker("ZZZZ")
    message = str(exc.value)
    assert "ZZZZ" in message
    assert all(t in message for t in config.SUPPORTED_TICKERS)


# add_client
def test_add_client_returns_clean_client_and_lists_it():
    new = clients.add_client("  New client  ", "aggressive")
    assert new.name == "New client"
    assert new.profile == "aggressive"
    assert new.holdings == ()
    assert any(c.client_id == new.client_id for c in clients.list_clients())


def test_client_ids_are_unique():
    a = clients.add_client("A", "balanced")
    b = clients.add_client("B", "balanced")
    assert a.client_id != b.client_id


@pytest.mark.parametrize("profile", list(config.PROFILES))
def test_every_configured_profile_is_accepted(profile):
    assert clients.add_client("P", profile).profile == profile


@pytest.mark.parametrize("profile", ["reckless", "", None, "very aggressive"])
def test_invalid_profiles_are_rejected(profile):
    with pytest.raises(InputError):
        clients.add_client("Test", profile)


@pytest.mark.parametrize("name", [None, "", "   "])
def test_empty_names_are_rejected(name):
    with pytest.raises(InputError):
        clients.add_client(name, "balanced")


def test_name_length_boundary():
    assert clients.add_client("x" * 60, "balanced").name == "x" * 60
    with pytest.raises(InputError):
        clients.add_client("x" * 61, "balanced")


def test_seeded_demo_clients_cover_every_profile():
    assert {c.profile for c in clients.list_clients()} >= set(config.PROFILES)


# get_client
def test_get_client_returns_the_right_client(client):
    assert clients.get_client(client.client_id).name == "Test client"


def test_get_unknown_client_raises():
    with pytest.raises(InputError):
        clients.get_client(10**9)


# add_holding
def test_add_holding_updates_the_client(client):
    sample = config.SUPPORTED_TICKERS[0]
    updated = clients.add_holding(client.client_id, sample, 10)
    assert [h.ticker for h in updated.holdings] == [sample]
    assert updated.holdings[0].quantity == 10
    assert clients.get_client(client.client_id).holdings == updated.holdings


def test_add_holding_normalises_ticker(client):
    sample = config.SUPPORTED_TICKERS[0]
    updated = clients.add_holding(client.client_id, f" {sample.lower()} ")
    assert updated.holdings[0].ticker == sample


def test_quantity_is_optional(client):
    sample = config.SUPPORTED_TICKERS[0]
    assert clients.add_holding(client.client_id, sample, None).holdings[0].quantity is None


@pytest.mark.parametrize("quantity", [0, -1, -0.5, float("nan"), float("inf")])
def test_non_positive_quantity_is_rejected(client, quantity):
    with pytest.raises(InputError):
        clients.add_holding(client.client_id, config.SUPPORTED_TICKERS[0], quantity)
    assert clients.get_client(client.client_id).holdings == ()


def test_duplicate_holding_is_rejected_and_nothing_changes(client):
    sample = config.SUPPORTED_TICKERS[0]
    clients.add_holding(client.client_id, sample)
    with pytest.raises(InputError):
        clients.add_holding(client.client_id, sample.lower())
    assert len(clients.get_client(client.client_id).holdings) == 1


def test_unsupported_ticker_does_not_change_holdings(client):
    with pytest.raises(InputError):
        clients.add_holding(client.client_id, "ZZZZ")
    assert clients.get_client(client.client_id).holdings == ()


def test_add_holding_to_unknown_client_raises():
    with pytest.raises(InputError):
        clients.add_holding(10**9, config.SUPPORTED_TICKERS[0])


def test_same_ticker_can_be_held_by_different_clients():
    sample = config.SUPPORTED_TICKERS[0]
    a = clients.add_client("A", "conservative")
    b = clients.add_client("B", "aggressive")
    clients.add_holding(a.client_id, sample)
    clients.add_holding(b.client_id, sample)
    assert clients.get_client(a.client_id).holdings[0].ticker == sample
    assert clients.get_client(b.client_id).holdings[0].ticker == sample


def test_returned_objects_are_immutable(client):
    with pytest.raises(dataclasses.FrozenInstanceError):
        client.name = "Changed"


# get_alerts
def test_alerts_are_valid_for_every_seeded_client():
    for c in clients.list_clients():
        for alert in alerts.get_alerts(c.client_id):
            _assert_valid_alert(alert, c.client_id)


def test_alerts_are_ranked_by_severity_then_score():
    for c in clients.list_clients():
        result = alerts.get_alerts(c.client_id)
        keys = [(SEVERITY_ORDER[a.severity], -a.score) for a in result]
        assert keys == sorted(keys)


def test_alerts_only_cover_the_clients_holdings_once_each():
    for c in clients.list_clients():
        held = {h.ticker for h in c.holdings}
        tickers = [a.ticker for a in alerts.get_alerts(c.client_id)]
        assert set(tickers) <= held
        assert len(tickers) == len(set(tickers))


def test_alert_tickers_belong_to_the_supported_pool():
    for c in clients.list_clients():
        for alert in alerts.get_alerts(c.client_id):
            assert alert.ticker in config.SUPPORTED_TICKERS


def test_sources_are_present_exactly_when_the_explanation_is_ok():
    for c in clients.list_clients():
        for alert in alerts.get_alerts(c.client_id):
            assert bool(alert.sources) == (alert.explanation_status == "ok")


def test_no_news_alerts_say_so_plainly():
    for c in clients.list_clients():
        for alert in alerts.get_alerts(c.client_id):
            if alert.explanation_status == "no_news":
                assert "no clear news found" in alert.explanation.lower()


def test_alert_text_contains_no_buy_or_sell_advice():
    for c in clients.list_clients():
        for alert in alerts.get_alerts(c.client_id):
            assert not FORBIDDEN_ADVICE.search(alert.summary)
            assert not FORBIDDEN_ADVICE.search(alert.explanation)


def test_empty_portfolio_gives_no_alerts(client):
    assert alerts.get_alerts(client.client_id) == []


def test_alerts_for_unknown_client_raise():
    with pytest.raises(InputError):
        alerts.get_alerts(10**9)


def test_each_call_returns_a_fresh_list():
    cid = clients.list_clients()[0].client_id
    first = alerts.get_alerts(cid)
    first.clear()
    assert alerts.get_alerts(cid)


def test_alerts_are_immutable():
    cid = clients.list_clients()[0].client_id
    alert = alerts.get_alerts(cid)[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        alert.severity = "low"


# get_secrets
def test_get_secret_prefers_environment(monkeypatch):
    monkeypatch.setenv("SOME_KEY", "from-env")
    assert config.get_secret("SOME_KEY") == "from-env"


def test_get_secret_falls_back_to_default(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    assert config.get_secret("MISSING_KEY", "fallback") == "fallback"
