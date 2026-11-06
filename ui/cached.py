# Cached calls into the services layer, so clicking around does not recompute everything.
from __future__ import annotations

import streamlit as st

from services import alerts, history
from services.contracts import Alert, Client


@st.cache_data(ttl=900, show_spinner=False)
def _alerts(client_id: int, holdings: tuple[str, ...], profile: str, override: float | None) -> list[Alert]:
    return alerts.get_alerts(client_id)


def alerts_for(client: Client) -> list[Alert]:
    holdings = tuple(h.ticker for h in client.holdings)
    return _alerts(client.client_id, holdings, client.profile, client.sensitivity_override)


@st.cache_data(ttl=900, show_spinner=False)
def _price_view(client_id: int, ticker: str, profile: str, override: float | None, days: int) -> history.PriceView:
    return history.price_view(client_id, ticker, days)


def price_view_for(client: Client, ticker: str, days: int) -> history.PriceView:
    return _price_view(client.client_id, ticker, client.profile, client.sensitivity_override, days)
