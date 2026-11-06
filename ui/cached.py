# Cached calls into the services layer, so clicking around does not recompute everything.
from __future__ import annotations

import streamlit as st

from services import alerts, explanation_jobs, history
from services.contracts import Alert, Client


def alerts_for(client: Client) -> list[Alert]:
    # Detection and explanations have their own caches. Do not freeze pending
    # job statuses in Streamlit's 15-minute page-data cache.
    return alerts.get_alerts(client.client_id)


@st.cache_data(ttl=900, show_spinner=False)
def _price_view(client_id: int, ticker: str, profile: str, override: float | None, days: int) -> history.PriceView:
    return history.price_view(client_id, ticker, days)


def price_view_for(client: Client, ticker: str, days: int) -> history.PriceView:
    return _price_view(client.client_id, ticker, client.profile, client.sensitivity_override, days)


def clear_data() -> None:
    """Reload charts and retry failed explanations; active jobs remain shared."""
    explanation_jobs.retry_failed()
    _price_view.clear()
