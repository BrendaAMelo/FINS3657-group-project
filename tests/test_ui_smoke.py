from dataclasses import replace
from datetime import date

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from data.errors import DataError, DataUnavailableError
from services import clients
from services.contracts import Alert, Source
from services.history import FlagPoint, PriceView
from ui import cached

TIMEOUT = 15


def alerts_page():
    from ui.views import alerts

    alerts.render()


def help_page():
    from ui.views import help_page

    help_page.render()


def create_test_client(name="Smoke test client", ticker="KO"):
    client = clients.add_client(name, "balanced")
    if ticker:
        clients.add_holding(client.client_id, ticker)
    return clients.get_client(client.client_id)


def run(page, client=None):
    at = AppTest.from_function(page, default_timeout=TIMEOUT)

    if client is not None:
        at.session_state["client_id"] = client.client_id

    at.run()
    if page is alerts_page:
        at.button[0].click().run()
    return at


def fake_alert(ticker="KO", status="ok", client_id=1):
    return Alert(
        client_id=client_id,
        ticker=ticker,
        alert_date=date(2026, 3, 12),
        severity="high",
        detector="isolation_forest",
        score=0.9,
        summary="Unusual volume.",
        explanation="Revenue was $5 billion." if status == "ok" else "No clear news found for this move.",
        explanation_status=status,
        sources=(Source("A story", "https://example.com/1"),) if status == "ok" else (),
    )


def test_dashboard_loads_only_on_manual_refresh(monkeypatch):
    client = create_test_client()
    calls = []

    def load(selected, *, generate_explanations=False):
        assert generate_explanations
        calls.append(selected.client_id)
        return [fake_alert(client_id=selected.client_id)]

    monkeypatch.setattr(cached, "alerts_for", load)
    at = AppTest.from_function(alerts_page, default_timeout=TIMEOUT).run()
    assert not at.exception
    assert not calls
    assert not at.metric
    assert any("Click Refresh dashboard" in item.value for item in at.info)

    at.button[0].click().run()
    assert not at.exception
    assert client.client_id in calls
    first_load = list(calls)

    at.text_input[0].set_value("KO").run()
    at.selectbox[1].set_value("Newest first").run()
    review = next(widget for widget in at.selectbox if widget.label == "Review status")
    review.set_value("Reviewed").run()
    assert not at.exception
    assert calls == first_load
    assert clients.get_alert_reviews(client.client_id)[("KO", "2026-03-12", "isolation_forest")] == "Reviewed"

    at.button[0].click().run()
    assert not at.exception
    assert calls == first_load * 2

    clients.add_holding(client.client_id, "PG")
    at.run()
    assert not at.exception
    assert calls == first_load * 2
    assert any("holdings have changed" in item.value for item in at.info)
    assert not at.metric
    at.button[0].click().run()
    assert not at.exception
    assert calls == first_load * 3
    assert at.metric


def test_alerts_page_shows_metrics_and_cards(monkeypatch):
    client = create_test_client()

    monkeypatch.setattr(
        cached,
        "alerts_for",
        lambda selected, **kwargs: [
            fake_alert("KO", client_id=selected.client_id),
        ],
    )

    at = run(alerts_page, client)

    assert not at.exception
    assert len(at.metric) >= 3
    assert any("KO" in item.value for item in at.markdown)


def test_alerts_page_handles_no_alerts(monkeypatch):
    client = create_test_client()

    monkeypatch.setattr(
        cached,
        "alerts_for",
        lambda selected, **kwargs: [],
    )

    at = run(alerts_page, client)

    assert not at.exception
    assert len(at.metric) >= 3
    assert any("Nothing unusual" in item.value for item in at.success)


def test_alerts_page_handles_clients_without_holdings(monkeypatch):
    empty = clients.add_client("Empty client", "balanced")

    assert empty.holdings == ()

    def should_not_run(selected, **kwargs):
        pytest.fail("Alerts should not be generated without holdings")

    monkeypatch.setattr(cached, "alerts_for", should_not_run)

    at = AppTest.from_function(alerts_page, default_timeout=TIMEOUT)
    at.session_state["client_id"] = empty.client_id
    at.run()

    assert not at.exception
    assert any("holdings" in item.value.lower() for item in at.info)


def test_alerts_page_shows_data_errors_politely(monkeypatch):
    create_test_client(ticker="KO")

    def broken(selected, **kwargs):
        raise DataError("service down")

    monkeypatch.setattr(cached, "alerts_for", broken)

    at = AppTest.from_function(alerts_page, default_timeout=TIMEOUT)
    at.run()
    at.button[0].click().run()

    assert not at.exception

    # Errors are displayed as warnings inside the client data issues expander.
    assert any("service down" in item.value for item in at.warning)


def test_help_page_lists_the_supported_stocks():
    at = run(help_page)
    assert not at.exception
    assert any("How it works" in t.value for t in at.title)


def clients_page():
    from ui.views import clients

    clients.render()


def test_clients_page_with_no_holdings_still_renders():
    empty = create_test_client(
        name="Empty holdings client",
        ticker=None,
    )

    at = run(clients_page, empty)

    assert not at.exception
    assert any("No holdings" in item.value for item in at.info)


def test_clients_page_renders_for_existing_client():
    client = create_test_client(name="Existing test client")

    at = run(clients_page, client)

    assert not at.exception
    assert any("Add a client" in item.value for item in at.subheader)


def test_alerts_page_shows_alerts_for_multiple_clients(monkeypatch):
    client_one = create_test_client(
        name="First test client",
        ticker="KO",
    )
    client_two = create_test_client(
        name="Second test client",
        ticker="PG",
    )

    def fake_alerts_for(selected, **kwargs):
        return [
            fake_alert(
                ticker=selected.holdings[0].ticker,
                client_id=selected.client_id,
            )
        ]

    monkeypatch.setattr(cached, "alerts_for", fake_alerts_for)

    first_page = run(alerts_page, client_one)
    assert not first_page.exception
    assert any("KO" in item.value for item in first_page.markdown)

    second_page = run(alerts_page, client_two)
    assert not second_page.exception
    assert any("PG" in item.value for item in second_page.markdown)


def charts_page():
    from ui.views import charts

    charts.render()


def fake_view(with_flags=True):
    prices = pd.DataFrame({"Date": pd.bdate_range("2026-03-02", periods=5), "Close": [10.0, 10.2, 9.8, 10.1, 10.3]})
    flags = (FlagPoint(date(2026, 3, 4), 9.8, "high", "isolation_forest", "Unusual volume."),)
    return PriceView("KO", prices, flags if with_flags else ())


@pytest.mark.parametrize("with_flags", [True, False])
def test_charts_page_renders_with_and_without_flags(monkeypatch, with_flags):
    client = create_test_client()
    monkeypatch.setattr(cached, "price_view_for", lambda client, ticker, days: fake_view(with_flags))
    at = run(charts_page, client)
    assert not at.exception
    assert any("Price charts" in title.value for title in at.title)
    if with_flags:
        assert any("Flagged days" in title.value for title in at.subheader)
    else:
        assert any("No unusual" in item.value for item in at.success)


def test_charts_page_reports_data_errors(monkeypatch):
    client = create_test_client()

    def broken(client, ticker, days):
        raise DataUnavailableError("prices missing")

    monkeypatch.setattr(cached, "price_view_for", broken)
    at = run(charts_page, client)
    assert not at.exception and "prices missing" in at.error[0].value


def test_incomplete_monitoring_is_not_reported_as_all_clear(monkeypatch):
    client = create_test_client()

    def broken(selected, **kwargs):
        raise DataUnavailableError("missing history")

    monkeypatch.setattr(cached, "alerts_for", broken)
    at = run(alerts_page, client)
    assert not at.exception
    assert not any("Nothing unusual" in item.value for item in at.success)
    assert any("could not be completed" in item.value for item in at.warning)


@pytest.mark.parametrize("final_status", ["ok", "no_news", "unavailable"])
def test_dashboard_waits_for_all_explanations_without_reprompting(monkeypatch, final_status):
    client = create_test_client()
    ready = fake_alert(client_id=client.client_id)
    pending = replace(
        fake_alert(ticker="PG", client_id=client.client_id),
        explanation_status="pending",
        sources=(),
        explanation="Preparing a news explanation.",
        related_news=(Source("Related report", "https://example.com/related"),),
    )
    current = [[ready]]
    requests = []

    def load(selected, *, generate_explanations=False):
        requests.append(generate_explanations)
        return current[0]

    monkeypatch.setattr(cached, "alerts_for", load)
    at = run(alerts_page, client)
    assert not at.exception
    assert at.metric  # Previously displayed results must also disappear during a new batch.

    current[0] = [ready, pending]
    at.button[0].click().run()
    assert not at.exception
    assert requests.count(True) == 2
    assert at.button[0].disabled
    assert not at.metric and not at.selectbox and not at.text_input
    assert not any("Revenue was" in item.value or "Related report" in item.value for item in at.markdown)
    assert any("1 remaining" in item.value for item in at.info)

    at.run()  # A progress check reads existing work without requesting generation.
    assert not at.exception
    assert requests.count(True) == 2
    assert not at.metric

    current[0] = [ready, replace(pending, explanation_status=final_status, explanation="Finished processing.")]
    at.run()  # Completion reveals the full batch without another Refresh click.
    assert not at.exception
    assert requests.count(True) == 2
    assert not at.button[0].disabled
    assert at.metric
    assert any("Revenue was" in item.value for item in at.markdown)
    assert not any("remaining" in item.value for item in at.info)
    completed_requests = list(requests)
    at.run()
    assert requests == completed_requests  # Polling stops when the batch has finished.


def test_adding_holdings_requests_automatic_dashboard_navigation(monkeypatch):
    client = create_test_client(ticker=None)
    monkeypatch.setattr(cached, "alerts_for", lambda selected, **kwargs: [])
    at = run(clients_page, client)
    at.multiselect[0].set_value(["AAPL", "MSFT", "NVDA"])
    next(button for button in at.button if button.label == "Add selected holdings").click().run()
    assert not at.exception
    assert {h.ticker for h in clients.get_client(client.client_id).holdings} == {"AAPL", "MSFT", "NVDA"}
    assert at.session_state["open_alerts_after_holdings"] is True


def test_full_app_consumes_dashboard_navigation_request(monkeypatch):
    create_test_client()
    monkeypatch.setattr(cached, "alerts_for", lambda selected, **kwargs: [])
    at = AppTest.from_file("../app.py", default_timeout=TIMEOUT)
    at.session_state["open_alerts_after_holdings"] = True
    at.run()
    assert not at.exception
    assert any(title.value == "Anomaly Dashboard" for title in at.title)
    with pytest.raises(KeyError):
        _ = at.session_state["open_alerts_after_holdings"]
