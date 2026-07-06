"""ฟังก์ชัน/ธีมที่ใช้ร่วมกันระหว่างหน้า ทองคำ และ BTCUSD"""
import io
import json
import urllib.parse
import urllib.request

import streamlit as st
import yfinance as yf
import pandas as pd

LEVEL_ORDER = ["R3", "R2", "R1", "PP", "S1", "S2", "S3"]
LEVEL_NAMES = ["R3 แนวต้าน", "R2 แนวต้าน", "R1 แนวต้าน", "Pivot/กึ่งกลาง",
               "S1 แนวรับ", "S2 แนวรับ", "S3 แนวรับ"]


# ---------- utils ----------
def resolve_td_key(sidebar_val):
    if sidebar_val:
        return sidebar_val
    try:
        return st.secrets["TWELVEDATA_KEY"]
    except Exception:
        return ""


def with_retry(fn, tries=3, wait=2.0):
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


def http_json(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ---------- ราคา (Yahoo / Twelve Data) ----------
def _yf_series(symbol, interval, period):
    df = yf.Ticker(symbol).history(period=period, interval=interval)
    if df is None or df.empty:
        return None
    df = df.dropna()
    if df.empty:
        return None
    return pd.DataFrame({"dt": df.index,
                         "high": df["High"].astype(float).values,
                         "low": df["Low"].astype(float).values,
                         "close": df["Close"].astype(float).values})


@st.cache_data(ttl=600, show_spinner=False)
def yf_daily(symbol):
    return with_retry(lambda: _yf_series(symbol, "1d", "1mo"))


@st.cache_data(ttl=600, show_spinner=False)
def yf_hourly(symbol):
    return with_retry(lambda: _yf_series(symbol, "60m", "7d"))


def _td_series(symbol, interval, size, key):
    url = ("https://api.twelvedata.com/time_series?symbol="
           + urllib.parse.quote(symbol)
           + f"&interval={interval}&outputsize={size}&apikey={key}")
    data = http_json(url)
    if data.get("status") != "ok" or not data.get("values"):
        return None
    vals = list(reversed(data["values"]))
    return pd.DataFrame({"dt": pd.to_datetime([v["datetime"] for v in vals]),
                         "high": [float(v["high"]) for v in vals],
                         "low": [float(v["low"]) for v in vals],
                         "close": [float(v["close"]) for v in vals]})


@st.cache_data(ttl=600, show_spinner=False)
def td_daily(symbol, key):
    return with_retry(lambda: _td_series(symbol, "1day", 30, key))


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


# ---------- คณิต pivot / กรอบ / max pain ----------
def classic_pivot(h, l, c):
    pp = (h + l + c) / 3
    return {"R3": h + 2 * (pp - l), "R2": pp + (h - l), "R1": 2 * pp - l, "PP": pp,
            "S1": 2 * pp - h, "S2": pp - (h - l), "S3": l - 2 * (h - pp)}


def swing_range(closes):
    last = closes[-10:]
    hi, lo = max(last), min(last)
    if hi == lo:
        return {k: hi for k in LEVEL_ORDER}
    mid = (hi + lo) / 2; q = (hi - lo) / 4
    return {"R3": mid + 3 * q, "R2": mid + 2 * q, "R1": mid + q, "PP": mid,
            "S1": mid - q, "S2": mid - 2 * q, "S3": mid - 3 * q}


def level_df(levels, dec=2):
    return pd.DataFrame({"ระดับ": LEVEL_NAMES,
                         "ราคา": [f"{levels[k]:,.{dec}f}" for k in LEVEL_ORDER]})


def max_pain(calls, puts):
    """calls/puts: list ของ {'strike':float, 'oi':float}"""
    ks = sorted(set([o["strike"] for o in calls]) | set([o["strike"] for o in puts]))
    if not ks:
        return None
    best, bp = None, None
    for S in ks:
        pay = 0.0
        for o in calls:
            if S > o["strike"]:
                pay += (S - o["strike"]) * o["oi"]
        for o in puts:
            if S < o["strike"]:
                pay += (o["strike"] - S) * o["oi"]
        if bp is None or pay < bp:
            bp, best = pay, S
    return best


# ---------- confluence เกรดเสี่ยง (ใช้ร่วม) ----------
def grade_from_votes(votes, mom, near_level):
    """votes: list ของ +1/-1/0 -> คืน dict bias/grade/net/bull/bear"""
    net = sum(votes)
    bull = sum(1 for v in votes if v > 0)
    bear = sum(1 for v in votes if v < 0)
    rp = min(bull, bear)
    if net == 0:
        rp += 1
    if abs(mom) > 1.0:
        rp += 1
    if near_level:
        rp += 1
    grade = max(1, min(5, 1 + rp))
    bias = "Bullish" if net > 0 else "Bearish" if net < 0 else "Neutral"
    return {"net": net, "bull": bull, "bear": bear, "grade": grade, "bias": bias}


# ---------- ธีม + การ์ด ----------
def apply_theme():
    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;500;600;700&display=swap');
:root{--gold:#e8c565;--gold2:#c9a13b;--card:#16203a;--line:#243350;--txt:#e8ecf3;--muted:#9fb0c8;}
html,body,[class*="css"],.stApp,[data-testid="stAppViewContainer"]{font-family:'IBM Plex Sans Thai',sans-serif!important;}
.stApp,[data-testid="stAppViewContainer"]{
  background:radial-gradient(1100px 550px at 18% -12%, #16223f 0%, #0b1220 58%)!important;color:var(--txt);}
[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer,[data-testid="stToolbar"]{visibility:hidden;display:none;}
[data-testid="stSidebar"]{background:#0d1526!important;border-right:1px solid var(--line);}
[data-testid="stSidebarNav"] a span{color:var(--txt)!important;}
h1{color:var(--gold)!important;font-weight:700!important;letter-spacing:.3px;}
h2,h3{color:var(--txt)!important;font-weight:600!important;}
h2{border-left:4px solid var(--gold);padding-left:12px;margin-top:.2rem;}
[data-testid="stMetric"]{
  background:linear-gradient(180deg,#18233f 0%,#131c30 100%);border:1px solid var(--line);
  border-radius:14px;padding:14px 16px;box-shadow:0 4px 18px rgba(0,0,0,.35);}
[data-testid="stMetric"]:hover{border-color:var(--gold2);}
[data-testid="stMetricLabel"] p{color:var(--muted)!important;font-size:.8rem!important;}
[data-testid="stMetricValue"]{color:var(--txt)!important;font-weight:700!important;}
[data-testid="stTable"] table{border-collapse:separate;border-spacing:0;border-radius:12px;overflow:hidden;}
[data-testid="stTable"] thead th{background:#1a2542!important;color:var(--gold)!important;font-weight:600;}
[data-testid="stTable"] tbody tr:nth-child(even){background:rgba(255,255,255,.02);}
[data-testid="stTable"] td,[data-testid="stTable"] th{border-color:var(--line)!important;color:var(--txt);}
[data-testid="stAlert"]{border-radius:12px;border:1px solid var(--line);}
[data-testid="stCaptionContainer"],small{color:var(--muted)!important;}
hr{border-color:var(--line)!important;}
[data-baseweb="select"]>div{background:#131c30!important;border-color:var(--line)!important;}
</style>""", unsafe_allow_html=True)


def hero_cards(items):
    """items: list ของ (label, big_text, sub, color) -> การ์ด 3 ใบแบบไล่สี"""
    card = ("background:linear-gradient(180deg,#18233f,#131c30);border:1px solid #243350;"
            "border-radius:14px;padding:16px 18px;flex:1;min-width:150px;"
            "box-shadow:0 4px 18px rgba(0,0,0,.35);")
    lbl = "color:#9fb0c8;font-size:.8rem;"
    big = "font-size:1.7rem;font-weight:700;line-height:1.35;"
    html = '<div style="display:flex;gap:14px;flex-wrap:wrap;margin:4px 0 16px;">'
    for label, big_text, sub, color in items:
        html += (f'<div style="{card}border-left:4px solid {color};">'
                 f'<div style="{lbl}">{label}</div>'
                 f'<div style="color:{color};{big}">{big_text}</div>'
                 f'<div style="{lbl}">{sub}</div></div>')
    html += '</div>'
    st.markdown(html, unsafe_allow_html=True)


def zone_note_and_quality(price, above, below, levels):
    """คืน (fired_msgs[], quality[]) สำหรับเรดาร์โซน"""
    fired = []
    if above and abs(above[0]["v"] - price) / price < 0.003:
        n, v = above[0]["name"], above[0]["v"]
        fired.append(("warn", f"⚡ ราคากำลังทดสอบ {n} ({v:,.2f}) — เฝ้าดูปฏิกิริยา: "
                              "เด้งลง=โดนต้าน, ทะลุเนื้อแท่ง+ยืนได้=ไปต่อ (อย่าเพิ่งสวนก่อนยืนยัน)"))
    if below and abs(below[0]["v"] - price) / price < 0.003:
        n, v = below[0]["name"], below[0]["v"]
        fired.append(("warn", f"⚡ ราคากำลังทดสอบ {n} ({v:,.2f}) — เฝ้าดูการเด้ง: "
                              "อย่ารับมีดตก, หลุดเนื้อแท่ง=อ่อนแรงอาจลงต่อ (รอสัญญาณยืนยัน)"))
    walls = [x for x in levels if x["name"] in ("Call Wall", "Put Wall", "Max Pain")]
    pivs = [x for x in levels if str(x["name"]).startswith("Pivot")]
    quality = []
    for w in walls:
        for p in pivs:
            if abs(w["v"] - p["v"]) / price < 0.003:
                quality.append(f'{w["name"]} ≈ {p["name"]} (~{(w["v"]+p["v"])/2:,.0f})')
    return fired, quality
