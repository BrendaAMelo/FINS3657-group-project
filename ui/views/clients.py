from __future__ import annotations

import streamlit as st

import config
from data.errors import DataError
from services import clients
from services.contracts import Client, InputError
from ui import cached, formatting
from ui.components import disclaimer, flash, show_flash


def _add_client_section() -> None:
    st.subheader("Add a client")

    with st.form("add_client", clear_on_submit=True):
        name = st.text_input(
            "Client name or nickname",
            max_chars=60,
            help="Use a nickname. Do not enter real client details in this demo.",
        )
        profile = st.selectbox(
            "Risk profile",
            list(config.PROFILES),
            format_func=str.capitalize,
        )
        submitted = st.form_submit_button("Add client")

    for key, description in formatting.PROFILE_HELP.items():
        st.caption(f"**{key.capitalize()}**: {description}")

    if submitted:
        try:
            created = clients.add_client(name, profile)
        except InputError as err:
            st.error(str(err))
        else:
            st.session_state["client_id"] = created.client_id
            st.session_state["manage_client_selector"] = created.client_id
            flash(f"Added {created.name}. You can now add their holdings.")
            st.rerun()


def _client_selector() -> Client | None:
    all_clients = clients.list_clients()

    if not all_clients:
        st.info("Add a client above to get started.")
        return None

    by_id = {client.client_id: client for client in all_clients}
    ids = list(by_id)

    current = st.session_state.get("client_id")
    index = ids.index(current) if current in ids else 0

    st.subheader("Manage an existing client")
    selected_id = st.selectbox(
        "Select client",
        ids,
        index=index,
        format_func=lambda client_id: f"{by_id[client_id].name} ({by_id[client_id].profile.capitalize()})",
        key="manage_client_selector",
    )

    st.session_state["client_id"] = selected_id
    return by_id[selected_id]


def _profile_section(client: Client) -> None:
    st.subheader("Risk profile")

    profiles = list(config.PROFILES)
    choice = st.selectbox(
        "Profile",
        profiles,
        index=profiles.index(client.profile),
        format_func=str.capitalize,
        key=f"profile_{client.client_id}",
    )

    st.caption(formatting.PROFILE_HELP[choice])

    if choice != client.profile and st.button(
        "Save profile",
        key=f"save_profile_{client.client_id}",
    ):
        try:
            clients.set_profile(client.client_id, choice)
        except InputError as err:
            st.error(str(err))
        else:
            flash(f"{client.name} is now using the {choice} profile.")
            st.rerun()


def _holdings_section(client: Client) -> None:
    st.subheader("Holdings")

    if client.holdings:
        for holding in client.holdings:
            left, middle, right = st.columns([3, 2, 1])

            left.write(formatting.ticker_option_label(holding.ticker))
            middle.write("" if holding.quantity is None else f"{holding.quantity:g} shares")

            if right.button(
                "Remove",
                key=f"remove_{client.client_id}_{holding.ticker}",
            ):
                try:
                    clients.remove_holding(
                        client.client_id,
                        holding.ticker,
                    )
                except InputError as err:
                    st.error(str(err))
                else:
                    flash(f"Removed {holding.ticker} from {client.name}.")
                    st.rerun()
    else:
        st.info("No holdings yet. Add some below.")

    held = {holding.ticker for holding in client.holdings}
    available = formatting.available_tickers(held)

    st.markdown("#### Add multiple holdings")

    with st.form(
        f"add_holdings_{client.client_id}",
        clear_on_submit=True,
    ):
        selected = st.multiselect(
            "Select supported stocks",
            available,
            format_func=formatting.ticker_option_label,
            placeholder="Choose one or more stocks",
        )

        typed = st.text_area(
            "Or enter tickers",
            placeholder="For example: KO, PG, AAPL",
            help="Separate tickers with commas, spaces or new lines.",
            height=80,
        )

        submitted = st.form_submit_button("Add selected holdings")

    st.caption(f"{len(config.SUPPORTED_TICKERS)} stocks are supported. See How it works for the full list.")

    if submitted:
        typed_tickers = typed.replace(",", " ").replace("\n", " ").split()
        requested = list(dict.fromkeys(selected + typed_tickers))

        if not requested:
            st.warning("Select or enter at least one ticker.")
            return

        try:
            updated, added, skipped = clients.add_holdings(
                client.client_id,
                requested,
            )
        except InputError as err:
            st.error(str(err))
            return

        if added:
            st.success(f"Added {len(added)} holding(s): {', '.join(added)}.")

        if skipped:
            st.warning("Some tickers were not added:")
            for ticker, reason in skipped:
                st.write(f"- **{ticker or '(blank)'}**: {reason}")

        if added:
            message = f"Added {len(added)} holding(s). Checking alerts and preparing news explanations automatically."
            if skipped:
                message += " Skipped: " + "; ".join(f"{ticker}: {reason}" for ticker, reason in skipped)
            flash(message, kind="warning" if skipped else "success")
            st.session_state["open_alerts_after_holdings"] = True
            st.rerun()


def _reset_override_slider(
    checkbox_key: str,
    slider_key: str,
    default_threshold: float,
) -> None:
    # Reset the slider before Streamlit recreates it when override is disabled.
    if not st.session_state[checkbox_key]:
        st.session_state[slider_key] = default_threshold


def _sensitivity_section(client: Client) -> None:
    st.subheader("Sensitivity")

    st.caption("Lower thresholds generate more alerts. An override applies only to this client.")

    default_threshold = float(config.PROFILES[client.profile]["z_threshold"])
    default_threshold = min(
        max(default_threshold, config.OVERRIDE_MIN),
        config.OVERRIDE_MAX,
    )

    checkbox_key = f"override_on_{client.client_id}"
    slider_key = f"override_value_{client.client_id}"

    # Initialise widget state before creating either widget.
    if checkbox_key not in st.session_state:
        st.session_state[checkbox_key] = client.sensitivity_override is not None

    if slider_key not in st.session_state:
        st.session_state[slider_key] = (
            float(client.sensitivity_override) if client.sensitivity_override is not None else default_threshold
        )

    # If the override is currently off, ensure the slider reflects
    # the current profile threshold before the slider is instantiated.
    if not st.session_state[checkbox_key]:
        st.session_state[slider_key] = default_threshold

    enabled = st.checkbox(
        "Override the profile's threshold",
        key=checkbox_key,
        on_change=_reset_override_slider,
        args=(checkbox_key, slider_key, default_threshold),
    )

    value = st.slider(
        "Threshold",
        min_value=float(config.OVERRIDE_MIN),
        max_value=float(config.OVERRIDE_MAX),
        step=float(config.OVERRIDE_STEP),
        key=slider_key,
        disabled=not enabled,
    )

    if enabled:
        st.caption(f"Custom threshold: {value:.1f}")
    else:
        st.caption(f"Using the standard {client.profile} profile threshold: {default_threshold:.1f}")

    if st.button(
        "Save sensitivity",
        key=f"save_override_{client.client_id}",
    ):
        try:
            clients.set_sensitivity_override(
                client.client_id,
                value if enabled else None,
            )
        except InputError as err:
            st.error(str(err))
        else:
            flash("Custom sensitivity saved." if enabled else "Override removed. The profile threshold is active.")
            st.rerun()


def _delete_section(client: Client) -> None:
    with st.expander("Delete this client"):
        st.warning("Deleting this client will permanently remove their holdings and saved alert review statuses.")

        confirmed = st.checkbox(
            "I understand this action cannot be undone.",
            key=f"confirm_delete_{client.client_id}",
        )

        # Scope the red styling to this particular button.
        with st.container(key=f"delete-client-{client.client_id}"):
            st.markdown(
                """
                <style>
                .st-key-delete-client-"""
                + str(client.client_id)
                + """ 
                button[kind="primary"] {
                    background-color: #dc2626;
                    border-color: #dc2626;
                    color: white;
                }
                .st-key-delete-client-"""
                + str(client.client_id)
                + """
                button[kind="primary"]:hover {
                    background-color: #b91c1c;
                    border-color: #b91c1c;
                    color: white;
                }
                </style>
                """,
                unsafe_allow_html=True,
            )

            if st.button(
                "Delete client permanently",
                type="primary",
                disabled=not confirmed,
                key=f"delete_{client.client_id}",
            ):
                try:
                    clients.delete_client(client.client_id)
                except InputError as err:
                    st.error(str(err))
                else:
                    st.session_state.pop("client_id", None)
                    st.session_state.pop("manage_client_selector", None)
                    flash(f"Deleted {client.name}.")
                    st.rerun()


def render() -> None:
    st.title("Clients")
    disclaimer()
    show_flash()

    # Adding a client is the primary action on this page.
    _add_client_section()

    st.divider()

    client = _client_selector()
    if client is None:
        return

    st.divider()
    st.subheader(client.name)

    try:
        active_alert_count = len(cached.alerts_for(client))
    except (DataError, InputError):
        active_alert_count = "Unavailable"

    overview = st.columns(4)
    overview[0].metric("Holdings", len(client.holdings))
    overview[1].metric("Active alerts", active_alert_count)
    overview[2].metric("Risk profile", client.profile.capitalize())
    overview[3].metric(
        "Custom threshold",
        "On" if client.sensitivity_override is not None else "Off",
    )

    _profile_section(client)
    st.divider()

    _holdings_section(client)
    st.divider()

    _sensitivity_section(client)
    st.divider()

    _delete_section(client)
