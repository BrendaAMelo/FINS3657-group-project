# Small Streamlit helpers shared by every page.
from __future__ import annotations

import streamlit as st

from services import clients
from services.contracts import Client

DISCLAIMER = "Information only. This tool flags unusual activity and does not give financial advice."


def disclaimer() -> None:
    st.caption(DISCLAIMER)


def flash(message: str, kind: str = "success") -> None:
    # Queue a message to show after the next rerun.
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    item = st.session_state.pop("flash", None)
    if item:
        kind, message = item
        {"success": st.success, "warning": st.warning, "error": st.error}.get(kind, st.info)(message)


def pick_client() -> Client | None:
    # Sidebar client selector shared by every page. Returns None if there are no clients.
    all_clients = clients.list_clients()
    if not all_clients:
        st.info("There are no clients yet. Add one on the Clients page.")
        return None
    by_id = {c.client_id: c for c in all_clients}
    ids = list(by_id)
    current = st.session_state.get("client_id")
    chosen = st.sidebar.selectbox(
        "Client",
        ids,
        index=ids.index(current) if current in ids else 0,
        format_func=lambda i: f"{by_id[i].name} ({by_id[i].profile})",
    )
    st.session_state["client_id"] = chosen
    return by_id[chosen]
