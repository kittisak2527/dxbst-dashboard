import streamlit as st

st.set_page_config(page_title="เลขาตลาด • ทอง / BTC / EUR", layout="wide",
                   initial_sidebar_state="auto")

pages = {
    "📊 Technical": [
        st.Page("gold_page.py", title="ทองคำ", icon="🥇", default=True),
        st.Page("btc_page.py", title="BTCUSD", icon="💰"),
        st.Page("euro_page.py", title="EUR/USD", icon="💶"),
    ],
    "📰 Fundamental": [
        st.Page("gold_fund_page.py", title="พื้นฐานทองคำ", icon="🥇"),
    ],
}
st.navigation(pages).run()
