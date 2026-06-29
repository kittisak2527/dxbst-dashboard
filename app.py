import time
import threading
import json
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

# label -> (yahoo_ticker, ทศนิยม, suffix)
ASSETS = {
    "ทองคำ (GC=F)":   ("GC=F",      2, ""),
    "EUR/USD":        ("EURUSD=X",  4, ""),
    "Dow (YM=F)":     ("YM=F",      0, ""),
    "S&P (ES=F)":     ("ES=F",      2, ""),
    "Nasdaq (NQ=F)":  ("NQ=F",      2, ""),
    "Bitcoin (BTC)":  ("BTC-USD",   0, ""),
    "DXY":            ("DX-Y.NYB",  2, ""),
    "US 10Y Yield":   ("^TNX",      2, "%"),
}

ANALYSIS_ASSETS = ["ทองคำ (GC=F)", "EUR/USD", "Dow (YM=F)", "Bitcoin (BTC)"]


# ============================================================
#  DATA LAYER  (yfinance + cache)
# ============================================================
def _raw_quote(ticker: str):
    """ดึงราคา + %เปลี่ยน + OHLC แท่งก่อนหน้า + ราคาปิดย้อนหลัง. ไม่มี st.* -> ใช้ใน thread ได้"""
    df = yf.Ticker(ticker).history(period="15d", interval="1d")
    if df is None or df.empty:
        return None
    df = df.dropna()
    if len(df) < 2:
        return None
    closes = [float(c) for c in df["Close"].tolist()]
    price = closes[-1]
    prev_close = closes[-2]
    change_pct = (price - prev_close) / prev_close * 100 if prev_close else 0.0
    prev = df.iloc[-2]   # แท่งวันก่อนหน้า (สำหรับ Classic Pivot)
    return {
        "price": price,
        "change_pct": change_pct,
        "prev_high": float(prev["High"]),
        "prev_low": float(prev["Low"]),
        "prev_close": prev_close,
        "closes": closes[-10:],
    }


@st.cache_data(ttl=60, show_spinner=False)
def fetch_quote(ticker: str):
    return _raw_quote(ticker)


def compute_levels(q):
    """กันพลาด 2 ชั้น:
       - ถ้าแท่งวันก่อนมี range จริง (High>Low) -> Classic Pivot
       - ถ้า H/L เพี้ยน (เท่ากัน) -> ใช้กรอบราคาปิด 10 วันล่าสุด (ใช้แค่ Close ที่เชื่อถือได้)
    """
    h, l, c = q["prev_high"], q["prev_low"], q["prev_close"]
    if h > l:
        pp = (h + l + c) / 3
        levels = {
            "R2": pp + (h - l),
            "R1": 2 * pp - l,
            "PP": pp,
            "S1": 2 * pp - h,
            "S2": pp - (h - l),
        }
        return levels, "Classic Pivot (แท่งวันก่อนหน้า)"

    closes = q["closes"]
    hi, lo = max(closes), min(closes)
    if hi == lo:
        return {k: hi for k in ["R2", "R1", "PP", "S1", "S2"]}, "ข้อมูลไม่พอคำนวณ"
    mid = (hi + lo) / 2
    levels = {
        "R2": hi,
        "R1": (hi + mid) / 2,
        "PP": mid,
        "S1": (mid + lo) / 2,
        "S2": lo,
    }
    return levels, "กรอบราคาปิด 10 วันล่าสุด"


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
#  BACKGROUND WORKER (เตรียมไว้ทำ "แจ้งเตือน")
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
st.caption("ข้อมูลจาก Yahoo Finance (yfinance) • แนวรับ/ต้านปรับวิธีคำนวณอัตโนมัติตามคุณภาพข้อมูล")

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
        fetch_quote.clear(); st.rerun()


@st.fragment(run_every="30s")
def market_panel():
    st.subheader("📊 ภาวะตลาด (อัปเดตอัตโนมัติ)")
    labels = list(ASSETS.keys())
    for row_start in range(0, len(labels), 4):
        cols = st.columns(4)
        for col, label in zip(cols, labels[row_start:row_start + 4]):
            ticker, dec, suf = ASSETS[label]
            q = fetch_quote(ticker)
            if q:
                col.metric(label, f"{q['price']:,.{dec}f}{suf}", f"{q['change_pct']:+.2f}%")
            else:
                col.metric(label, "n/a", "ดึงไม่ได้")

    st.divider()
    tabs = st.tabs(ANALYSIS_ASSETS)
    for tab, label in zip(tabs, ANALYSIS_ASSETS):
        with tab:
            ticker, dec, _ = ASSETS[label]
            q = fetch_quote(ticker)
            if not q:
                st.warning(f"ดึงข้อมูล {label} ไม่ได้ในรอบนี้"); continue
            piv, method = compute_levels(q)
            st.markdown(f"### {label} — {trend_label(q['price'], piv['PP'])}")
            st.caption(f"ราคาล่าสุด {q['price']:,.{dec}f}  ({q['change_pct']:+.2f}%)")
            df = pd.DataFrame({
                "ระดับ": ["R2 แนวต้าน", "R1 แนวต้าน", "Pivot/กึ่งกลาง", "S1 แนวรับ", "S2 แนวรับ"],
                "ราคา": [f"{piv[k]:,.{dec}f}" for k in ["R2", "R1", "PP", "S1", "S2"]],
            })
            st.table(df)
            st.caption(f"วิธีคำนวณ: {method}")


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
