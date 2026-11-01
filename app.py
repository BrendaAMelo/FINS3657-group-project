import streamlit as st

from ui import dashboard

st.set_page_config(page_title="FINS3657: Group Project", layout="wide")
dashboard.render()
