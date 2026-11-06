# Plain-language explanation of what the tool does and where it falls short.
from __future__ import annotations

import streamlit as st

import config
from ui import formatting
from ui.components import disclaimer


def render() -> None:
    st.title("How it works")
    disclaimer()

    st.subheader("What it does")
    st.markdown(
        "Advisers cannot watch every holding of every client. This tool checks each holding "
        "against **its own recent behaviour** (price moves and trading volume) and lists only "
        "the days that look unusual, so you can see what needs attention first."
    )

    st.subheader("Risk profiles")
    for profile, text in formatting.PROFILE_HELP.items():
        st.markdown(f"- **{profile.capitalize()}**: {text}")

    st.subheader("Explanations")
    st.markdown(
        "For each alert the tool looks up news from the days around it and writes a short "
        "explanation using **only** that news, with links so you can check it. "
        "If nothing relevant turns up, it says *No clear news found*. "
        "Explanations can still be wrong or incomplete, so check the sources."
    )

    st.subheader("Limitations")
    st.markdown(
        "- Only the stocks listed below are supported. Each was checked during development; "
        "other stocks have not been evaluated.\n"
        f"- Prices and news are a fixed snapshot through "
        f"{formatting.format_date(config.PRICE_DATA_END)}. "
        "The dashboard does not represent live market monitoring.\n"
        "- It will miss some real events and raise some false alarms.\n"
        "- It describes what happened. It does not predict prices or recommend trades.\n"
        "- Use nicknames, not real client details, in this demo."
    )

    st.subheader("Reviewing alerts")
    st.markdown(
        "- **Unreviewed**: the alert has not yet been reviewed.\n"
        "- **Reviewed**: you have checked the alert and its available explanation.\n"
        "- **Follow-up required**: further investigation or action is needed.\n"
        "These statuses are for workflow tracking only. They do not change the "
        "underlying detection, severity or alert history."
    )

    st.subheader("Supported stocks")
    st.dataframe(formatting.ticker_table(), hide_index=True)
    st.caption(
        "Prices are split- and dividend-adjusted. News is from Finnhub; prices are from Yahoo Finance via yfinance."
    )
