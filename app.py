import io
import json
import urllib.parse
import urllib.request

import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="เลขาตลาด • All-in-One", layout="wide")

# ============================================================
#  CONFIG
#  yf = ticker ฝั่ง Yahoo | td = symbol ฝั่ง Twelve Data (None = ใช้ Yahoo เสมอ)
#  หมายเหตุ: ดัชนี/DXY ตั้ง td=None เพราะ TD ฟรีมีแต่ ETF ที่ scale ต่างกัน
#           -> ให้ gold/forex/BTC (scale ตรงกัน) ไปดึง TD, ที่เหลือคง Yahoo
# ============================================================
ASSETS = [
    {"label": "ทองคำ",     "yf": "GC=F",     "td": "XAU/USD", "dec": 2, "suf": "", "pivot": True},
    {"label": "EUR/USD",   "yf": "EURUSD=X", "td": "EUR/USD", "dec": 4, "suf": "", "pivot": True},
    {"label": "USD/JPY",   "yf": "USDJPY=X", "td": "USD/JPY", "dec": 3, "suf": "", "pivot": True},
    {"label": "GBP/USD",   "yf": "GBPUSD=X", "td": "GBP/USD", "dec": 4, "suf": "", "pivot": True},
    {"label": "GBP/JPY",   "yf": "GBPJPY=X", "td": "GBP/JPY", "dec": 3, "suf": "", "pivot": True},
    {"label": "Dow",       "yf": "YM=F",     "td": None,      "dec": 0, "suf": "", "pivot": True},
    {"label": "S&P",       "yf": "ES=F",     "td": None,      "dec": 2, "suf": "", "pivot": True},
    {"label": "Nasdaq",    "yf": "NQ=F",     "td": None,      "dec": 2, "suf": "", "pivot": True},
    {"label": "Bitcoin",   "yf": "BTC-USD",  "td": "BTC/USD", "dec": 0, "suf": "", "pivot": True},
    {"label": "DXY",       "yf": "DX-Y.NYB", "td": None,      "dec": 2, "suf": "", "pivot": False},
]
MACRO = [   # ดึงจาก FRED เสมอ (ฟรี ไม่ต้อง key, ไม่ขึ้นกับ toggle)
    {"label": "US 10Y Yield",      "fred": "DGS10"},
    {"label": "US 10Y Real (TIPS)", "fred": "DFII10"},
]
OPTIONS_TICKER = "GLD"   # options ใช้ Yahoo เสมอ (TD ฟรีไม่มี options)

LEVEL_ORDER = ["R3", "R2", "R1", "PP", "S1", "S2", "S3"]
LEVEL_NAMES = ["R3 แนวต้าน", "R2 แนวต้าน", "R1 แนวต้าน", "Pivot/กึ่งกลาง",
               "S1 แนวรับ", "S2 แนวรับ", "S3 แนวรับ"]


# ============================================================
#  HELPERS
# ============================================================
def _with_retry(fn, tries=3, wait=2.0):
    import time
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            last = e
            m = str(e).lower()
            if "rate" in m or "limit" in m or "too many" in m:
                time.sleep(wait * (i + 1)); continue
            raise
    raise last


def resolve_td_key(sidebar_val):
    if sidebar_val:
        return sidebar_val
    try:
        return st.secrets["TWELVEDATA_KEY"]
    except Exception:
        return ""


# ---------- Yahoo ----------
def _yf_series(symbol, interval, period):
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df is None or df.empty:
        return None
    df = df.dropna()
    if df.empty:
        return None
    return pd.DataFrame({
        "dt": df.index,
        "high": df["High"].astype(float).values,
        "low": df["Low"].astype(float).values,
        "close": df["Close"].astype(float).values,
    })


@st.cache_data(ttl=120, show_spinner=False)
def yf_daily(symbol):
    return _with_retry(lambda: _yf_series(symbol, "1d", "15d"))


@st.cache_data(ttl=300, show_spinner=False)
def yf_hourly(symbol):
    return _with_retry(lambda: _yf_series(symbol, "60m", "7d"))


# ---------- Twelve Data ----------
def _td_series(symbol, interval, size, key):
    url = ("https://api.twelvedata.com/time_series?symbol="
           + urllib.parse.quote(symbol)
           + f"&interval={interval}&outputsize={size}&apikey={key}")
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode())
    if data.get("status") != "ok" or not data.get("values"):
        return None
    vals = list(reversed(data["values"]))  # เก่า -> ใหม่
    return pd.DataFrame({
        "dt": pd.to_datetime([v["datetime"] for v in vals]),
        "high": [float(v["high"]) for v in vals],
        "low": [float(v["low"]) for v in vals],
        "close": [float(v["close"]) for v in vals],
    })


@st.cache_data(ttl=120, show_spinner=False)
def td_daily(symbol, key):
    return _with_retry(lambda: _td_series(symbol, "1day", 15, key))


# ---------- FRED ----------
@st.cache_data(ttl=3600, show_spinner=False)
def fred_latest(series_id):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            text = resp.read().decode("utf-8")
        df = pd.read_csv(io.StringIO(text))
        col = df.columns[-1]
        df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=[col])
        if df.empty:
            return None
        v = float(df[col].iloc[-1])
        prev = float(df[col].iloc[-2]) if len(df) >= 2 else v
        return {"value": v, "change_pp": v - prev}
    except Exception:
        return None


# ---------- Options (Yahoo) ----------
@st.cache_data(ttl=600, show_spinner=False)
def opt_expiries(ticker):
    return _with_retry(lambda: list(yf.Ticker(ticker).options))


@st.cache_data(ttl=600, show_spinner=False)
def opt_chain(ticker, expiry):
    def _f():
        oc = yf.Ticker(ticker).option_chain(expiry)
        cols = ["strike", "openInterest"]
        c = oc.calls[cols].copy(); p = oc.puts[cols].copy()
        for d in (c, p):
            d["openInterest"] = d["openInterest"].fillna(0)
        return c, p
    return _with_retry(_f)


# ============================================================
#  BUSINESS LOGIC
# ============================================================
def use_td_for(asset, source):
    return source == "td" and asset.get("td")


def get_quote(asset, source, key):
    df = td_daily(asset["td"], key) if use_td_for(asset, source) else yf_daily(asset["yf"])
    if df is None or len(df) < 2:
        return None
    closes = df["close"].tolist()
    price, prev = closes[-1], closes[-2]
    return {"price": price,
            "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            "closes": closes[-10:]}


def get_pivot_ref(asset, source, key):
    if use_td_for(asset, source):
        df = td_daily(asset["td"], key)
        if df is None or len(df) < 2:
            return None
        p = df.iloc[-2]
        if p["high"] > p["low"]:
            return {"high": float(p["high"]), "low": float(p["low"]), "close": float(p["close"]),
                    "how": "Classic Pivot • แท่งวันก่อน (Twelve Data)"}
        return None
    h = yf_hourly(asset["yf"])
    if h is None or h.empty:
        return None
    h = h.copy()
    h["d"] = pd.to_datetime(h["dt"]).dt.date
    dates = sorted(set(h["d"]))
    if len(dates) < 2:
        return None
    day = h[h["d"] == dates[-2]]
    if day.empty:
        return None
    hi, lo, cl = float(day["high"].max()), float(day["low"].min()), float(day["close"].iloc[-1])
    if hi <= lo:
        return None
    return {"high": hi, "low": lo, "close": cl,
            "how": f"Classic Pivot • H/L รายชั่วโมงวันที่ {dates[-2]} (Yahoo)"}


def classic_pivot(h, l, c):
    pp = (h + l + c) / 3
    return {"R3": h + 2 * (pp - l), "R2": pp + (h - l), "R1": 2 * pp - l, "PP": pp,
            "S1": 2 * pp - h, "S2": pp - (h - l), "S3": l - 2 * (h - pp)}


def swing_range(closes):
    hi, lo = max(closes), min(closes)
    if hi == lo:
        return {k: hi for k in LEVEL_ORDER}
    mid = (hi + lo) / 2; q = (hi - lo) / 4
    return {"R3": mid + 3 * q, "R2": mid + 2 * q, "R1": mid + q, "PP": mid,
            "S1": mid - q, "S2": mid - 2 * q, "S3": mid - 3 * q}


def level_df(levels, dec):
    return pd.DataFrame({"ระดับ": LEVEL_NAMES,
                         "ราคา": [f"{levels[k]:,.{dec}f}" for k in LEVEL_ORDER]})


def max_pain(calls, puts):
    strikes = sorted(set(calls["strike"]) | set(puts["strike"]))
    if not strikes:
        return None
    co = dict(zip(calls["strike"], calls["openInterest"]))
    po = dict(zip(puts["strike"], puts["openInterest"]))
    best, bp = None, None
    for S in strikes:
        pay = sum((S - K) * oi for K, oi in co.items() if S > K) \
            + sum((K - S) * oi for K, oi in po.items() if S < K)
        if bp is None or pay < bp:
            bp, best = pay, S
    return best


# ============================================================
#  SIDEBAR
# ============================================================
with st.sidebar:
    st.header("⚙️ ตั้งค่า")
    src_label = st.radio("แหล่งข้อมูลราคา",
                         ["Yahoo (ค่าเริ่มต้น)", "Twelve Data (beta)"], index=0)
    source = "td" if src_label.startswith("Twelve") else "yahoo"
    key_input = st.text_input("Twelve Data API key (ถ้าไม่ใส่ใน Secrets)",
                              type="password", value="")
    td_key = resolve_td_key(key_input)
    if source == "td" and not td_key:
        st.warning("ยังไม่มี TD key — สลับกลับ Yahoo ให้ชั่วคราว")
        source = "yahoo"
    if st.button("🔄 รีเฟรชข้อมูลทันที", use_container_width=True):
        st.cache_data.clear(); st.rerun()
    st.caption("gold/forex/BTC ใช้ตามแหล่งที่เลือก • ดัชนี/DXY ใช้ Yahoo เสมอ • yield/TIPS ใช้ FRED เสมอ")


# ============================================================
#  MAIN — หน้าเดียวเลื่อนลงเห็นครบ
# ============================================================
st.title("เลขาตลาด • All-in-One Dashboard")
st.caption(f"แหล่งราคา: {'Twelve Data' if source=='td' else 'Yahoo Finance'} "
           "• Pivot 7 ระดับ • Options OI (GLD)")

# ---------- 1) ภาวะตลาด ----------
st.header("📊 ภาวะตลาด")
cards = ASSETS + [{"macro": m} for m in MACRO]
flat = ASSETS + MACRO
for i in range(0, len(flat), 4):
    cols = st.columns(4)
    for col, item in zip(cols, flat[i:i + 4]):
        if "fred" in item:
            d = fred_latest(item["fred"])
            if d:
                col.metric(item["label"], f"{d['value']:.2f}%", f"{d['change_pp']:+.2f} pp")
            else:
                col.metric(item["label"], "n/a", "FRED")
        else:
            q = get_quote(item, source, td_key)
            if q:
                col.metric(item["label"], f"{q['price']:,.{item['dec']}f}{item['suf']}",
                           f"{q['change_pct']:+.2f}%")
            else:
                col.metric(item["label"], "n/a", "ดึงไม่ได้")

# ---------- 2) Pivot รับ/ต้าน ----------
st.header("🎯 แนวรับ/แนวต้าน (Pivot)")
piv_assets = [a for a in ASSETS if a.get("pivot")]
tabs = st.tabs([a["label"] for a in piv_assets])
for tab, a in zip(tabs, piv_assets):
    with tab:
        q = get_quote(a, source, td_key)
        if not q:
            st.warning(f"ดึง {a['label']} ไม่ได้ในรอบนี้"); continue
        ref = get_pivot_ref(a, source, td_key)
        daily = classic_pivot(ref["high"], ref["low"], ref["close"]) if ref else None
        rng = swing_range(q["closes"])
        bias = daily["PP"] if daily else rng["PP"]
        badge = "🟢 Bullish" if q["price"] > bias else "🔴 Bearish"
        st.markdown(f"### {a['label']} — {badge}")
        st.caption(f"ราคาล่าสุด {q['price']:,.{a['dec']}f} ({q['change_pct']:+.2f}%)")
        cA, cB = st.columns(2)
        with cA:
            st.markdown("**📍 Pivot รายวัน (Day Trade)**")
            if daily:
                st.table(level_df(daily, a["dec"])); st.caption(ref["how"])
            else:
                st.info("ดึง H/L รายวันไม่ได้ — ใช้กรอบ 10 วันทางขวา")
        with cB:
            st.markdown("**🗺️ กรอบ 10 วัน (Swing)**")
            st.table(level_df(rng, a["dec"])); st.caption("จากกรอบราคาปิด 10 วัน")

# ---------- 3) Options OI (GLD) ----------
st.header("🧊 Options OI — GLD (Yahoo)")
try:
    exps = opt_expiries(OPTIONS_TICKER)
    gld = get_quote({"yf": OPTIONS_TICKER, "td": None, "dec": 2}, "yahoo", "")
    spot = gld["price"] if gld else None
except Exception:
    exps, spot = [], None

if not exps or spot is None:
    st.warning("ดึง option chain ไม่ได้ในรอบนี้ (อาจติด rate limit) — ลองรีเฟรช")
else:
    e1, e2 = st.columns(2)
    expiry = e1.selectbox("วันหมดอายุ", exps)
    pct = e2.slider("ช่วง strike ±%", 5, 50, 20)
    try:
        calls, puts = opt_chain(OPTIONS_TICKER, expiry)
        tot_c = float(calls["openInterest"].sum()); tot_p = float(puts["openInterest"].sum())
        pcr = tot_p / tot_c if tot_c else 0.0
        lo, hi = spot * (1 - pct / 100), spot * (1 + pct / 100)
        c = calls[(calls.strike >= lo) & (calls.strike <= hi)]
        p = puts[(puts.strike >= lo) & (puts.strike <= hi)]
        if c.empty or p.empty:
            st.info("ไม่มี strike ในช่วงนี้ ลองขยาย ±%")
        else:
            cw = float(c.loc[c.openInterest.idxmax(), "strike"])
            pw = float(p.loc[p.openInterest.idxmax(), "strike"])
            mp = max_pain(c, p)
            r = st.columns(5)
            r[0].metric("Spot GLD", f"{spot:,.2f}")
            r[1].metric("PCR", f"{pcr:.2f}")
            r[2].metric("Call Wall", f"{cw:,.0f}")
            r[3].metric("Put Wall", f"{pw:,.0f}")
            r[4].metric("Max Pain", f"{mp:,.0f}" if mp else "n/a")
            strikes = sorted(set(c.strike) | set(p.strike))
            co = dict(zip(c.strike, c.openInterest)); po = dict(zip(p.strike, p.openInterest))
            st.bar_chart(pd.DataFrame(
                {"Call OI": [co.get(s, 0) for s in strikes],
                 "Put OI": [po.get(s, 0) for s in strikes]},
                index=[f"{s:g}" for s in strikes]))
    except Exception:
        st.warning("ดึง chain งวดนี้ไม่สำเร็จ (อาจติด rate limit) — ลองรีเฟรช")

# ---------- Footer ----------
st.divider()
st.caption("⚠️ ข้อมูลเพื่อการศึกษาเท่านั้น • เป็นข้อมูลดีเลย์ ไม่ใช่ราคาสดของโบรกเกอร์ "
           "• ไม่ใช่คำแนะนำการลงทุน โปรดตัดสินใจด้วยวิจารณญาณของตนเอง")
