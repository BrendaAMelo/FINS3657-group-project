from __future__ import annotations

from collections import defaultdict

import streamlit as st

import config
from data.errors import DataError
from services import clients as client_service
from services.contracts import Alert, InputError
from ui import cached, formatting
from ui.components import disclaimer, show_flash

REVIEW_STATUSES = (
    "Unreviewed",
    "Reviewed",
    "Follow-up required",
)


def _alert_key(alert: Alert) -> tuple[str, str, str]:
    return (
        alert.ticker,
        alert.alert_date.isoformat(),
        alert.detector,
    )


def _sort_key(alert: Alert, sort_by: str, client_name: str):
    severity_rank = {
        "high": 0,
        "medium": 1,
        "low": 2,
    }

    if sort_by == "Oldest first":
        return (alert.alert_date, severity_rank.get(alert.severity, 99))

    if sort_by == "Client":
        return (client_name.casefold(), alert.ticker)

    if sort_by == "Stock":
        return (alert.ticker, client_name.casefold())

    if sort_by == "Newest first":
        return (-alert.alert_date.toordinal(), severity_rank.get(alert.severity, 99))

    # Default: highest severity first, then newest.
    return (
        severity_rank.get(alert.severity, 99),
        -alert.alert_date.toordinal(),
        client_name.casefold(),
        alert.ticker,
    )


def _save_review(
    client_id: int,
    alert: Alert,
    widget_key: str,
) -> None:
    try:
        client_service.set_alert_review(
            client_id=client_id,
            ticker=alert.ticker,
            alert_date=alert.alert_date.isoformat(),
            detector=alert.detector,
            status=st.session_state[widget_key],
        )
    except InputError as err:
        st.error(str(err))


def _render_alert(
    alert: Alert,
    client_name: str,
    review_status: str,
) -> None:
    with st.container(border=True):
        left, right = st.columns([4, 1])

        left.markdown(f"**{alert.ticker}** · {formatting.severity_label(alert.severity)}")
        right.caption(formatting.format_date(alert.alert_date))

        st.caption(f"Client: {client_name}")
        st.markdown(formatting.escape_markdown(alert.summary))

        explanation = formatting.escape_markdown(alert.explanation)
        kind = formatting.explanation_kind(alert.explanation_status)

        if kind == "warning":
            st.warning(explanation)
        elif kind == "info":
            st.info(explanation)
        else:
            st.markdown(explanation)

        if alert.sources:
            st.caption("Sources")
            for source in alert.sources:
                st.markdown("- " + formatting.source_markdown(source))

        if alert.related_news and alert.explanation_status != "ok":
            st.caption("Related news — these articles do not necessarily explain the move")
            for source in alert.related_news:
                st.markdown("- " + formatting.source_markdown(source))

        if not alert.validated:
            st.caption("Experimental configuration: severity and sensitivity settings are not validated risk measures.")

        review_key = f"review_{alert.client_id}_{alert.ticker}_{alert.alert_date.isoformat()}_{alert.detector}"

        # Initialise the widget from the database, but do not overwrite
        # a value already held by Streamlit during the current interaction.
        if review_key not in st.session_state:
            st.session_state[review_key] = review_status

        st.selectbox(
            "Review status",
            REVIEW_STATUSES,
            key=review_key,
            on_change=_save_review,
            args=(alert.client_id, alert, review_key),
        )

        with st.expander("Technical details"):
            st.write(f"Detector: {alert.detector} · Score: {alert.score:.2f}")


@st.fragment(run_every="2s")
def render() -> None:
    st.title("Needs attention")
    disclaimer()
    show_flash()

    all_clients = client_service.list_clients()

    if not all_clients:
        st.info("There are no clients yet. Add your first client on the Clients page.")
        return

    st.caption(
        "A consolidated view of unusual activity across all clients and holdings. "
        "Review an alert without removing it from the monitoring results."
    )

    st.caption(f"Market-data snapshot through {formatting.format_date(config.PRICE_DATA_END)}.")
    st.caption(
        "Isolation Forest alerts across the historical monitoring period. News explanations are retrospective "
        "and can include articles published after the flagged day. Missing explanations do not invalidate alerts."
    )
    if st.button("Refresh and retry unavailable explanations"):
        cached.clear_data()

    all_alerts: list[tuple[Alert, str]] = []
    client_errors: list[tuple[str, str]] = []
    reviews_by_client: dict[int, dict] = {}

    with st.spinner("Checking all client holdings..."):
        for client in all_clients:
            if not client.holdings:
                continue

            try:
                client_alerts = cached.alerts_for(client)
                all_alerts.extend((alert, client.name) for alert in client_alerts)
                reviews_by_client[client.client_id] = client_service.get_alert_reviews(client.client_id)
            except (DataError, InputError) as err:
                # Keep displaying other clients if one client's data fails.
                client_errors.append((client.name, str(err)))

    if client_errors:
        with st.expander(
            f"{len(client_errors)} client data issue(s)",
            expanded=True,
        ):
            for name, message in client_errors:
                st.warning(f"{name}: {message}")

    pending = sum(alert.explanation_status == "pending" for alert, _ in all_alerts)
    if pending:
        st.info(f"Preparing {pending} news explanation(s). Alerts are ready; explanations update automatically.")

    if not any(client.holdings for client in all_clients):
        st.info("No clients have holdings yet. Add holdings on the Clients page.")
        return

    total_holdings = sum(len(client.holdings) for client in all_clients)
    total_clients = len(all_clients)

    high_count = sum(a.severity == "high" for a, _ in all_alerts)
    medium_count = sum(a.severity == "medium" for a, _ in all_alerts)
    low_count = sum(a.severity == "low" for a, _ in all_alerts)

    review_count = {"Unreviewed": 0, "Reviewed": 0, "Follow-up required": 0}
    for alert, _ in all_alerts:
        saved = reviews_by_client.get(alert.client_id, {}).get(
            _alert_key(alert),
            "Unreviewed",
        )
        review_count[saved] = review_count.get(saved, 0) + 1

    metrics = st.columns(5)
    metrics[0].metric("Clients", total_clients)
    metrics[1].metric("Holdings", total_holdings)
    metrics[2].metric("High", high_count)
    metrics[3].metric("Medium", medium_count)
    metrics[4].metric("Low", low_count)

    st.divider()

    controls = st.columns([2, 2, 2, 2])

    grouping = controls[0].selectbox(
        "Group by",
        ["Client", "Stock"],
    )

    sort_by = controls[1].selectbox(
        "Sort by",
        ["Severity (highest first)", "Newest first", "Oldest first", "Client", "Stock"],
    )

    severity_filter = controls[2].multiselect(
        "Severity",
        ["high", "medium", "low"],
        default=["high", "medium", "low"],
        format_func=str.capitalize,
    )

    review_filter = controls[3].multiselect(
        "Review status",
        list(REVIEW_STATUSES),
        default=list(REVIEW_STATUSES),
    )

    search = (
        st.text_input(
            "Search clients or stocks",
            placeholder="Client name, ticker or company name...",
        )
        .strip()
        .casefold()
    )

    filtered: list[tuple[Alert, str]] = []

    for alert, client_name in all_alerts:
        status = reviews_by_client.get(alert.client_id, {}).get(
            _alert_key(alert),
            "Unreviewed",
        )

        company = formatting.ticker_option_label(alert.ticker)

        if alert.severity not in severity_filter:
            continue

        if status not in review_filter:
            continue

        if search and not any(search in value.casefold() for value in (client_name, alert.ticker, company)):
            continue

        filtered.append((alert, client_name))

    filtered.sort(key=lambda item: _sort_key(item[0], sort_by, item[1]))

    st.subheader(f"{len(filtered)} warning(s) to review")

    if not filtered:
        if all_alerts:
            st.success("No warnings match those filters.")
        elif client_errors:
            st.warning("Monitoring could not be completed for some clients. Check the data issues above.")
        else:
            st.success("Nothing unusual to review across the current holdings.")
        return

    if grouping == "Client":
        grouped = defaultdict(list)
        for item in filtered:
            grouped[item[1]].append(item)

        for client_name, items in sorted(grouped.items()):
            st.markdown(f"### {client_name} · {len(items)} warning(s)")

            for alert, name in items:
                status = reviews_by_client.get(alert.client_id, {}).get(
                    _alert_key(alert),
                    "Unreviewed",
                )
                _render_alert(alert, name, status)

    else:
        grouped = defaultdict(list)
        for item in filtered:
            grouped[item[0].ticker].append(item)

        for ticker, items in sorted(grouped.items()):
            st.markdown(f"### {formatting.ticker_option_label(ticker)} · {len(items)} client warning(s)")

            for alert, name in items:
                status = reviews_by_client.get(alert.client_id, {}).get(
                    _alert_key(alert),
                    "Unreviewed",
                )
                _render_alert(alert, name, status)
