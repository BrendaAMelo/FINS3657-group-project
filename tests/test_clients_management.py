import pytest

import config
from services import clients
from services.contracts import InputError


@pytest.fixture
def client():
    created = clients.add_client("Managed", "balanced")
    clients.add_holding(created.client_id, "KO", 10)
    clients.add_holding(created.client_id, "PG")
    return clients.get_client(created.client_id)


def tickers(client_id):
    return [h.ticker for h in clients.get_client(client_id).holdings]


def test_remove_holding_keeps_the_others(client):
    updated = clients.remove_holding(client.client_id, "ko")
    assert [h.ticker for h in updated.holdings] == ["PG"]
    assert tickers(client.client_id) == ["PG"]


def test_removing_something_not_held_raises(client):
    with pytest.raises(InputError):
        clients.remove_holding(client.client_id, "AAPL")
    assert tickers(client.client_id) == ["KO", "PG"]


def test_remove_from_unknown_client_raises():
    with pytest.raises(InputError):
        clients.remove_holding(10**9, "KO")


def test_delete_client_removes_it_and_its_holdings(client):
    clients.delete_client(client.client_id)
    with pytest.raises(InputError):
        clients.get_client(client.client_id)
    assert all(c.client_id != client.client_id for c in clients.list_clients())


def test_delete_unknown_client_raises():
    with pytest.raises(InputError):
        clients.delete_client(10**9)


def test_set_profile(client):
    assert clients.set_profile(client.client_id, "aggressive").profile == "aggressive"
    assert clients.get_client(client.client_id).profile == "aggressive"


@pytest.mark.parametrize("profile", ["reckless", "", None])
def test_invalid_profiles_are_rejected_and_nothing_changes(client, profile):
    with pytest.raises(InputError):
        clients.set_profile(client.client_id, profile)
    assert clients.get_client(client.client_id).profile == "balanced"


def test_override_can_be_set_and_cleared(client):
    value = (config.OVERRIDE_MIN + config.OVERRIDE_MAX) / 2
    assert clients.set_sensitivity_override(client.client_id, value).sensitivity_override == value
    assert clients.set_sensitivity_override(client.client_id, None).sensitivity_override is None


@pytest.mark.parametrize("value", [config.OVERRIDE_MIN - 0.5, config.OVERRIDE_MAX + 0.5, float("nan"), float("inf")])
def test_out_of_range_overrides_are_rejected(client, value):
    with pytest.raises(InputError):
        clients.set_sensitivity_override(client.client_id, value)
    assert clients.get_client(client.client_id).sensitivity_override is None


def test_override_for_unknown_client_raises():
    with pytest.raises(InputError):
        clients.set_sensitivity_override(10**9, config.OVERRIDE_MIN)
