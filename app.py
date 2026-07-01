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


@st.cache_data(ttl=3600, show_spinner="กำลังสแกน OI ของแต่ละ expiry เพื่อหางวดหลัก...")
def best_expiry(ticker, expiries, scan_limit=12):
    """เลือก expiry ที่ OI รวม (call+put) หนาสุด จากงวดใกล้ ๆ ตาม scan_limit"""
    best, best_oi = None, -1.0
    for e in expiries[:scan_limit]:
        try:
            c, p = get_chain(ticker, e)
            tot = float(c["openInterest"].sum() + p["openInterest"].sum())
        except Exception:
            tot = 0.0
        if tot > best_oi:
            best_oi, best = tot, e
    return best


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

# เลือกงวดที่ OI หนาสุดเป็นค่าเริ่มต้น
default_exp = best_expiry(ticker, tuple(expiries))
default_idx = expiries.index(default_exp) if default_exp in expiries else 0

c1, c2 = st.columns(2)
expiry = c1.selectbox("วันหมดอายุ (expiry) — ค่าเริ่มต้น = งวด OI หนาสุด",
                      expiries, index=default_idx)
pct = c2.slider("ช่วง strike รอบราคา (±%)", 5, 50, 20)

calls, puts = get_chain(ticker, expiry)

# --- OI รวมทั้งงวด (ทุก strike) -> ใช้กับ PCR ---
tot_call = float(calls["openInterest"].sum())
tot_put = float(puts["openInterest"].sum())
pcr = tot_put / tot_call if tot_call else 0.0

# --- กรอบ strike รอบราคา -> ใช้กับ walls + กราฟ ---
lo, hi = spot * (1 - pct / 100), spot * (1 + pct / 100)
c = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)]
p = puts[(puts["strike"] >= lo) & (puts["strike"] <= hi)]
if c.empty or p.empty:
    st.warning("ไม่มี strike ในช่วงที่เลือก ลองขยายช่วง ±%")
    st.stop()

call_wall = float(c.loc[c["openInterest"].idxmax(), "strike"])
put_wall = float(p.loc[p["openInterest"].idxmax(), "strike"])
mp = max_pain(c, p)

# --- แถวเมตริก 1: OI รวม + PCR (อธิบายว่าทำไม PCR เป็นเท่านี้) ---
r1 = st.columns(4)
r1[0].metric("Spot", f"{spot:,.2f}")
r1[1].metric("Call OI รวม (ทั้งงวด)", f"{tot_call:,.0f}")
r1[2].metric("Put OI รวม (ทั้งงวด)", f"{tot_put:,.0f}")
r1[3].metric("PCR (Put/Call)", f"{pcr:.2f}")

# --- แถวเมตริก 2: walls + max pain ---
r2 = st.columns(3)
r2[0].metric("Call Wall (แนวต้าน)", f"{call_wall:,.0f}")
r2[1].metric("Put Wall (แนวรับ)", f"{put_wall:,.0f}")
r2[2].metric("Max Pain", f"{mp:,.0f}" if mp is not None else "n/a")

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
