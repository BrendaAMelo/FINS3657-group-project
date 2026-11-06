import streamlit as st

from ui.views import alerts, charts, clients, help_page

st.set_page_config(page_title="Adviser Exception Monitor", page_icon=":material/monitoring:", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stForm"],
    [data-baseweb="input"],
    [data-baseweb="input"] input,
    [data-baseweb="textarea"],
    [data-baseweb="textarea"] textarea,
    [data-testid="stSelectbox"] [data-baseweb="select"] > div,
    [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
    [data-baseweb="popover"] [role="listbox"] {
        background-color: #BDC0C0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

pages = [
    st.Page(alerts.render, title="Dashboard", icon=":material/notifications:", url_path="alerts", default=True),
    st.Page(help_page.render, title="How it works", icon=":material/help:", url_path="help"),
    st.Page(clients.render, title="Clients", icon=":material/group:", url_path="clients"),
    st.Page(charts.render, title="Price charts", icon=":material/show_chart:", url_path="charts"),
]
navigation = st.navigation(pages)
if st.session_state.pop("open_alerts_after_holdings", False):
    st.switch_page(pages[0])
navigation.run()
