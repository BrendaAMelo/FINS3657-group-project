import streamlit as st

from ui.views import alerts, clients, help_page

st.set_page_config(page_title="Adviser Exception Monitor", page_icon=":material/monitoring:", layout="wide")

pages = [
    st.Page(alerts.render, title="Needs attention", icon=":material/notifications:", url_path="alerts", default=True),
    st.Page(help_page.render, title="How it works", icon=":material/help:", url_path="help"),
    st.Page(clients.render, title="Clients", icon=":material/group:", url_path="clients"),
    # st.Page(charts.render, title="Price charts", icon=":material/show_chart:", url_path="charts"),
]
st.navigation(pages).run()
