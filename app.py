import time
import threading
import json
import io
import urllib.request
from datetime import datetime

import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="เลขาตลาด • Multi-Asset Dashboard", layout="wide")

# ============================================================
#  CONFIG
# ============================================================
STATUS_FILE = "bot_status.json"
LOG_FILE = "bot_log.jsonl"
LOOP_INTERVAL = 30
MAX_LOG_LINES = 200
THREAD_NAME = "MarketWorker"

# การ์ดภาวะตลาด: yfinance + 1 ตัวจาก FRED (TIPS)
CARDS = [
    {"label": "ทองคำ (GC=F)",      "src": "yf", "ticker": "GC=F",     "dec": 2, "suf": ""},
    {"label": "EUR/USD",           "src": "yf", "ticker": "EURUSD=X", "dec": 4, "suf": ""},
    {"label": "Dow (YM=F)",        "src": "yf", "ticker": "YM=F",     "dec": 0, "suf": ""},
    {"label": "S&P (ES=F)",        "src": "yf", "ticker": "ES=F",     "dec": 2, "suf": ""},
    {"label": "Nasdaq (NQ=F)",     "src": "yf", "ticker": "NQ=F",     "dec": 2, "suf": ""},
    {"label": "Bitcoin (BTC)",     "src": "yf", "ticker": "BTC-USD",  "dec": 0, "suf": ""},
    {"label": "DXY",               "src": "yf", "ticker": "DX-Y.NYB", "dec": 2, "suf": ""},
    {"label": "US 10Y Yield",      "src": "yf", "ticker": "^TNX",     "dec": 2, "suf": "%"},
    {"label": "US 10Y Real (TIPS)", "src": "fred", "series": "DFII10"},
]

# สินทรัพย์ที่แสดงตารางวิเคราะห์ (label, ticker, ทศนิยม)
ANALYSIS_ASSETS = [
    ("ทองคำ (GC=F)", "GC=F", 2),
    ("EUR/USD", "EURUSD=X", 4),
    ("Dow (YM=F)", "YM=F", 0),
    ("Bitcoin (BTC)", "BTC-USD", 0),
]


# ============================================================
#  DATA LAYER
# ============================================================
def _raw_quote(ticker: str):
    """ราคา + %เปลี่ยน + ราคาปิดย้อนหลัง 10 วัน. ไม่มี st.* -> ใช้ใน thread ได้"""
    df = yf.Ticker(ticker).history(period="15d", interval="1d")
    if df is None or df.empty:
        return None
    df = df.dropna()
    if len(df) < 2:
        return None
    closes = [float(c) for c in df["Close"].tolist()]
    price, prev_close = closes[-1], closes[-2]
    return {
        "price": price,
        "change_pct": (price - prev_close) / prev_close * 100 if prev_close else 0.0,
        "closes": closes[-10:],
    }


def _prev_session_hl(ticker: str):
    """หา High/Low/Close ของ 'วันก่อนหน้า' จากข้อมูลรายชั่วโมง (เลี่ยง H/L รายวันที่เพี้ยน)"""
    df = yf.Ticker(ticker).history(period="7d", interval="60m")
    if df is None or df.empty:
        return None
    df = df.dropna()
    if df.empty:
        return None
    dates = sorted(set(df.index.date))
    if len(dates) < 2:
        return None
    prev_date = dates[-2]
    day = df[df.index.date == prev_date]
    if day.empty:
        return None
    h, l, c = float(day["High"].max()), float(day["Low"].min()), float(day["Close"].iloc[-1])
    if h <= l:
        return None
    return {"high": h, "low": l, "close": c, "date": str(prev_date)}


def _fetch_fred(series_id: str):
    """ดึงค่าล่าสุดจาก FRED ผ่านลิงก์ CSV สาธารณะ (ไม่ต้องใช้ API key)"""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    with urllib.request.urlopen(url, timeout=10) as resp:
        text = resp.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(text))
    val_col = df.columns[-1]
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[val_col])
    if df.empty:
        return None
    value = float(df[val_col].iloc[-1])
    prev = float(df[val_col].iloc[-2]) if len(df) >= 2 else value
    return {"value": value, "change_pp": value - prev}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_quote(ticker: str):
    return _raw_quote(ticker)


@st.cache_data(ttl=300, show_spinner=False)
def fetch_prev_session(ticker: str):
    return _prev_session_hl(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_fred(series_id: str):
    try:
        return _fetch_fred(series_id)
    except Exception:
        return None


# ============================================================
#  LEVEL MATH
# ============================================================
def classic_pivot(h, l, c):
    pp = (h + l + c) / 3
    return {"R2": pp + (h - l), "R1": 2 * pp - l, "PP": pp,
            "S1": 2 * pp - h, "S2": pp - (h - l)}


def swing_range(closes):
    hi, lo = max(closes), min(closes)
    if hi == lo:
        return {k: hi for k in ["R2", "R1", "PP", "S1", "S2"]}
    mid = (hi + lo) / 2
    return {"R2": hi, "R1": (hi + mid) / 2, "PP": mid,
            "S1": (mid + lo) / 2, "S2": lo}


def level_df(levels, dec):
    return pd.DataFrame({
        "ระดับ": ["R2 แนวต้าน", "R1 แนวต้าน", "Pivot/กึ่งกลาง", "S1 แนวรับ", "S2 แนวรับ"],
        "ราคา": [f"{levels[k]:,.{dec}f}" for k in ["R2", "R1", "PP", "S1", "S2"]],
    })


def trend_label(price, pp):
    return "🟢 Bullish (เหนือกึ่งกลาง)" if price > pp else "🔴 Bearish (ใต้กึ่งกลาง)"


# ============================================================
#  STATUS / LOG
# ============================================================
def load_bot_status() -> bool:
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("is_running", False)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def save_bot_status(is_running: bool) -> None:
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"is_running": is_running}, f)


def write_log(message: str) -> None:
    record = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "msg": message}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_logs(limit: int = 10):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    if len(lines) > MAX_LOG_LINES:
        lines = lines[-MAX_LOG_LINES:]
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)
    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ============================================================
#  BACKGROUND WORKER (เตรียมไว้ทำแจ้งเตือนภายหลัง)
# ============================================================
def run_strategy() -> str:
    q = _raw_quote("GC=F")
    if not q:
        return "ดึงราคาทองไม่สำเร็จรอบนี้"
    return f"ทองล่าสุด {q['price']:,.2f} ({q['change_pct']:+.2f}%)"


def trading_bot_worker() -> None:
    write_log("✅ เริ่มติดตามราคาเบื้องหลัง")
    while load_bot_status():
        try:
            write_log(run_strategy())
        except Exception as e:
            write_log(f"⚠️ error: {e}")
        for _ in range(LOOP_INTERVAL * 2):
            if not load_bot_status():
                break
            time.sleep(0.5)
    write_log("🛑 ปิดการติดตามเบื้องหลัง")


def ensure_worker_running() -> None:
    if THREAD_NAME not in [t.name for t in threading.enumerate()]:
        threading.Thread(target=trading_bot_worker, name=THREAD_NAME, daemon=True).start()


# ============================================================
#  SESSION INIT
# ============================================================
if "bot_running" not in st.session_state:
    st.session_state.bot_running = load_bot_status()
if st.session_state.bot_running:
    ensure_worker_running()


# ============================================================
#  UI
# ============================================================
st.title("เลขาตลาด • Multi-Asset Dashboard")
st.caption("ข้อมูล: Yahoo Finance (ราคา) + FRED (TIPS) • Pivot รายวันจาก H/L รายชั่วโมง + กรอบ 10 วัน")

with st.sidebar:
    st.header("⚙️ ระบบควบคุม")
    st.subheader("🟢 เปิดแจ้งเตือน" if st.session_state.bot_running else "🔴 ปิดแจ้งเตือน")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("▶️ เปิด", disabled=st.session_state.bot_running, use_container_width=True):
            save_bot_status(True); st.session_state.bot_running = True
            ensure_worker_running(); st.rerun()
    with c2:
        if st.button("⏹️ ปิด", disabled=not st.session_state.bot_running, use_container_width=True):
            save_bot_status(False); st.session_state.bot_running = False; st.rerun()
    st.divider()
    if st.button("🔄 รีเฟรชข้อมูลทันที", use_container_width=True):
        fetch_quote.clear(); fetch_prev_session.clear(); fetch_fred.clear(); st.rerun()


def render_card(col, spec):
    if spec["src"] == "yf":
        q = fetch_quote(spec["ticker"])
        if q:
            col.metric(spec["label"], f"{q['price']:,.{spec['dec']}f}{spec['suf']}",
                       f"{q['change_pct']:+.2f}%")
        else:
            col.metric(spec["label"], "n/a", "ดึงไม่ได้")
    else:  # fred
        d = fetch_fred(spec["series"])
        if d:
            col.metric(spec["label"], f"{d['value']:.2f}%", f"{d['change_pp']:+.2f} pp")
        else:
            col.metric(spec["label"], "n/a", "FRED ดึงไม่ได้")


@st.fragment(run_every="30s")
def market_panel():
    st.subheader("📊 ภาวะตลาด (อัปเดตอัตโนมัติ)")
    for i in range(0, len(CARDS), 4):
        cols = st.columns(4)
        for col, spec in zip(cols, CARDS[i:i + 4]):
            render_card(col, spec)

    st.divider()
    tabs = st.tabs([a[0] for a in ANALYSIS_ASSETS])
    for tab, (label, ticker, dec) in zip(tabs, ANALYSIS_ASSETS):
        with tab:
            q = fetch_quote(ticker)
            if not q:
                st.warning(f"ดึงข้อมูล {label} ไม่ได้ในรอบนี้"); continue

            # --- Pivot รายวัน (จาก H/L รายชั่วโมง) ---
            sess = fetch_prev_session(ticker)
            daily, daily_note = None, ""
            if sess:
                daily = classic_pivot(sess["high"], sess["low"], sess["close"])
                daily_note = f"Classic Pivot • H/L รายชั่วโมงของวันที่ {sess['date']}"

            rng = swing_range(q["closes"])
            bias_ref = daily["PP"] if daily else rng["PP"]

            st.markdown(f"### {label} — {trend_label(q['price'], bias_ref)}")
            st.caption(f"ราคาล่าสุด {q['price']:,.{dec}f}  ({q['change_pct']:+.2f}%)")

            cA, cB = st.columns(2)
            with cA:
                st.markdown("**📍 Pivot รายวัน (Day Trade)**")
                if daily:
                    st.table(level_df(daily, dec))
                    st.caption(daily_note)
                else:
                    st.info("ยังดึง H/L รายชั่วโมงไม่ได้ — ใช้กรอบ 10 วันทางขวาแทนไปก่อน")
            with cB:
                st.markdown("**🗺️ กรอบภาพใหญ่ 10 วัน (Swing)**")
                st.table(level_df(rng, dec))
                st.caption("จากกรอบราคาปิด 10 วันล่าสุด")


market_panel()

st.divider()
st.subheader("📋 Live Log")


@st.fragment(run_every="2s")
def live_panel():
    logs = read_logs(limit=10)
    if logs:
        st.caption(f"💓 heartbeat ล่าสุด: {logs[-1]['ts']}")
        st.code("\n".join(f"[{x['ts']}] {x['msg']}" for x in reversed(logs)), language=None)
    else:
        st.caption("สแตนด์บาย รอการบันทึก...")


live_panel()
