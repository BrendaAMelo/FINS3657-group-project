# A price chart per holding, with the days the tool flagged marked on it.
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from data.errors import DataError
from services.contracts import InputError
from services.history import PriceView
from ui import cached, formatting
from ui.components import disclaimer, pick_client

SEVERITY_COLORS = ["#d62728", "#ff7f0e", "#7f7f7f"]  # high, medium, low


def _flag_frame(view: PriceView) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Date": pd.Timestamp(f.day),
                "Close": f.close,
                "Severity": f.severity,
                "Detector": f.detector,
                "Summary": f.summary,
            }
            for f in view.flags
        ]
    )


def _chart(view: PriceView, flags: pd.DataFrame) -> alt.Chart:
    line = (
        alt.Chart(view.prices)
        .mark_line()
        .encode(
            x=alt.X("Date:T", title=None),
            y=alt.Y("Close:Q", title="Close price (USD)", scale=alt.Scale(zero=False)),
        )
    )
    if flags.empty:
        return line
    points = (
        alt.Chart(flags)
        .mark_point(filled=True, size=90)
        .encode(
            x="Date:T",
            y="Close:Q",
            color=alt.Color(
                "Severity:N",
                scale=alt.Scale(domain=list(formatting.SEVERITY_ORDER), range=SEVERITY_COLORS),
            ),
            tooltip=["Date:T", "Severity:N", "Detector:N", "Summary:N"],
        )
    )
    return line + points


def render() -> None:
    st.title("Price charts")
    disclaimer()
    client = pick_client()
    if client is None:
        return
    if not client.holdings:
        st.info(f"{client.name} has no holdings yet. Add some on the Clients page.")
        return

    ticker = st.selectbox("Holding", [h.ticker for h in client.holdings], format_func=formatting.ticker_option_label)
    days = st.radio("Period", [60, 120, 250], index=1, horizontal=True, format_func=lambda d: f"{d} trading days")
    try:
        with st.spinner("Loading prices..."):
            view = cached.price_view_for(client, ticker, days)
    except InputError as err:
        st.error(str(err))
        return
    except DataError as err:
        st.error(f"Market data is unavailable right now. {err}")
        return

    flags = _flag_frame(view)
    st.altair_chart(_chart(view, flags))
    st.caption(
        f"Settings: {client.profile.capitalize()} profile. Prices are split- and dividend-adjusted. "
        "Marked days behaved unusually compared with this stock's own history."
    )
    if flags.empty:
        st.success("No unusual days in this period for this client's settings.")
    else:
        st.subheader("Flagged days")
        table = flags[["Date", "Severity", "Detector", "Summary"]].copy()
        table["Date"] = table["Date"].dt.strftime("%a %d %b %Y")
        st.dataframe(table, hide_index=True)
