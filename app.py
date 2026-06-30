import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="Options OI Dashboard", layout="wide")

# Phase 1: GLD (ฟรีผ่าน yfinance)  |  Phase 3 จะเพิ่ม BTC ผ่าน Deribit
UNDERLYINGS = {"GLD (Gold ETF)": "GLD"}


# ============================================================
#  DATA
# ============================================================
@st.cache_data(ttl=300, show_spinner=False)
def get_spot(ticker):
    df = yf.Ticker(ticker).history(period="5d", interval="1d")
    if df is None or df.empty:
        return None
    return float(df["Close"].dropna().iloc[-1])


@st.cache_data(ttl=300, show_spinner=False)
def get_expiries(ticker):
    try:
        return list(yf.Ticker(ticker).options)
    except Exception:
        return []


@st.cache_data(ttl=300, show_spinner=False)
def get_chain(ticker, expiry):
    oc = yf.Ticker(ticker).option_chain(expiry)
    cols = ["strike", "openInterest", "volume", "impliedVolatility"]
    calls = oc.calls[cols].copy()
    puts = oc.puts[cols].copy()
    for d in (calls, puts):
        d["openInterest"] = d["openInterest"].fillna(0)
        d["volume"] = d["volume"].fillna(0)
    return calls, puts


# ============================================================
#  METRICS
# ============================================================
def max_pain(calls, puts):
    """ราคาที่ทำให้ผู้ถือ option ขาดทุนรวมมากสุด (writer จ่ายน้อยสุด)"""
    strikes = sorted(set(calls["strike"]) | set(puts["strike"]))
    if not strikes:
        return None
    co = dict(zip(calls["strike"], calls["openInterest"]))
    po = dict(zip(puts["strike"], puts["openInterest"]))
    best, best_pay = None, None
    for S in strikes:
        pay = sum((S - K) * oi for K, oi in co.items() if S > K) \
            + sum((K - S) * oi for K, oi in po.items() if S < K)
        if best_pay is None or pay < best_pay:
            best_pay, best = pay, S
    return best


# ============================================================
#  UI
# ============================================================
st.title("📊 Options OI Dashboard — Phase 1 (GLD)")
st.caption("ข้อมูล option chain จาก Yahoo Finance • OI walls + PCR + Max Pain")

name = st.selectbox("Underlying", list(UNDERLYINGS.keys()))
ticker = UNDERLYINGS[name]

spot = get_spot(ticker)
expiries = get_expiries(ticker)
if spot is None or not expiries:
    st.error("ดึงราคา/วันหมดอายุไม่ได้ในรอบนี้ — ลองรีโหลดหน้าอีกครั้ง")
    st.stop()

c1, c2 = st.columns(2)
expiry = c1.selectbox("วันหมดอายุ (expiry)", expiries)
pct = c2.slider("ช่วง strike รอบราคา (±%)", 5, 50, 20)

calls, puts = get_chain(ticker, expiry)

lo, hi = spot * (1 - pct / 100), spot * (1 + pct / 100)
c = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)]
p = puts[(puts["strike"] >= lo) & (puts["strike"] <= hi)]

if c.empty or p.empty:
    st.warning("ไม่มี strike ในช่วงที่เลือก ลองขยายช่วง ±%")
    st.stop()

call_oi = float(c["openInterest"].sum())
put_oi = float(p["openInterest"].sum())
pcr = put_oi / call_oi if call_oi else 0.0
call_wall = float(c.loc[c["openInterest"].idxmax(), "strike"])
put_wall = float(p.loc[p["openInterest"].idxmax(), "strike"])
mp = max_pain(c, p)

# --- เมตริก ---
m = st.columns(5)
m[0].metric("Spot", f"{spot:,.2f}")
m[1].metric("PCR (Put/Call OI)", f"{pcr:.2f}")
m[2].metric("Call Wall (แนวต้าน)", f"{call_wall:,.0f}")
m[3].metric("Put Wall (แนวรับ)", f"{put_wall:,.0f}")
m[4].metric("Max Pain", f"{mp:,.0f}" if mp is not None else "n/a")

st.caption(
    "Call Wall = strike ที่ call OI หนาสุด (มักเป็นแนวต้าน/แม่เหล็ก) • "
    "Put Wall = strike ที่ put OI หนาสุด (มักเป็นแนวรับ) • "
    "PCR > 1 = put มากกว่า call • Max Pain = ราคาที่ราคามักถูกดูดเข้าใกล้ช่วงใกล้หมดอายุ"
)

# --- กราฟ OI ราย strike ---
st.subheader("Open Interest ราย strike")
strikes = sorted(set(c["strike"]) | set(p["strike"]))
co = dict(zip(c["strike"], c["openInterest"]))
po = dict(zip(p["strike"], p["openInterest"]))
chart_df = pd.DataFrame(
    {"Call OI": [co.get(s, 0) for s in strikes],
     "Put OI": [po.get(s, 0) for s in strikes]},
    index=[f"{s:g}" for s in strikes],
)
st.bar_chart(chart_df)
st.caption(f"กรอบ strike: {lo:,.0f} – {hi:,.0f} • วันหมดอายุ {expiry}")
