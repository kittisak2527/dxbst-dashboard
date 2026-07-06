import streamlit as st

st.set_page_config(page_title="เลขาตลาด • ทอง / BTC", layout="wide",
                   initial_sidebar_state="auto")

pages = [
    st.Page("gold_page.py", title="ทองคำ", icon="🥇", default=True),
    st.Page("btc_page.py", title="BTCUSD", icon="💰"),
]
st.navigation(pages).run()
