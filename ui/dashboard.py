import streamlit as st

from services import alerts, clients
from services.contracts import InputError

SEVERITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}


def render() -> None:
    st.title("Needs attention today")
    st.caption("Information only. This is not financial advice.")

    all_clients = clients.list_clients()
    if not all_clients:
        st.info("No clients yet.")
        return

    by_name = {c.name: c for c in all_clients}
    choice = st.sidebar.selectbox("Client", list(by_name))
    client = by_name[choice]
    st.sidebar.write(f"Risk profile: {client.profile.capitalize()}")
    st.sidebar.write("Holdings: " + ", ".join(h.ticker for h in client.holdings))

    try:
        result = alerts.get_alerts(client.client_id)
    except InputError as err:
        st.error(str(err))
        return

    if not result:
        st.success("Nothing unusual today.")
        return

    for a in result:
        with st.container(border=True):
            st.markdown(f"**{a.ticker}** · {SEVERITY_LABEL[a.severity]}")
            st.write(a.summary)
            st.write(a.explanation)
            for s in a.sources:
                st.markdown(f"- [{s.title}]({s.url})")
