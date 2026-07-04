import io
import json
import urllib.parse
import urllib.request
from datetime import datetime

import streamlit as st
import yfinance as yf
import pandas as pd

st.set_page_config(page_title="เลขาตลาด • ทองคำ", layout="wide",
                   initial_sidebar_state="collapsed")

# ====== โหมดแชร์ (view-only ถาวร) — แก้ค่าพวกนี้ในโค้ดก่อน deploy ======
PRIMARY = "GC"          # อ้างอิงราคาทอง: "GC" (Yahoo futures) หรือ "XAU" (Twelve Data spot; ต้องตั้ง Secrets)
REFRESH_SECONDS = 1800  # ออโต้รีเฟรชทุก 30 นาที

# ============================================================
#  CONFIG
# ============================================================
GC_YF = "GC=F"        # ทอง Futures (COMEX) จาก Yahoo
XAU_TD = "XAU/USD"    # ทอง Spot จาก Twelve Data
DXY_YF = "DX-Y.NYB"
OPTIONS_TICKER = "GLD"

LEVEL_ORDER = ["R3", "R2", "R1", "PP", "S1", "S2", "S3"]
LEVEL_NAMES = ["R3 แนวต้าน", "R2 แนวต้าน", "R1 แนวต้าน", "Pivot/กึ่งกลาง",
               "S1 แนวรับ", "S2 แนวรับ", "S3 แนวรับ"]


# ============================================================
#  HELPERS / DATA
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
    return _with_retry(lambda: _yf_series(symbol, "1d", "1mo"))


@st.cache_data(ttl=600, show_spinner=False)
def yf_hourly(symbol):
    return _with_retry(lambda: _yf_series(symbol, "60m", "7d"))


def _td_series(symbol, interval, size, key):
    url = ("https://api.twelvedata.com/time_series?symbol="
           + urllib.parse.quote(symbol)
           + f"&interval={interval}&outputsize={size}&apikey={key}")
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode())
    if data.get("status") != "ok" or not data.get("values"):
        return None
    vals = list(reversed(data["values"]))
    return pd.DataFrame({"dt": pd.to_datetime([v["datetime"] for v in vals]),
                         "high": [float(v["high"]) for v in vals],
                         "low": [float(v["low"]) for v in vals],
                         "close": [float(v["close"]) for v in vals]})


@st.cache_data(ttl=600, show_spinner=False)
def td_daily(symbol, key):
    return _with_retry(lambda: _td_series(symbol, "1day", 30, key))


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


@st.cache_data(ttl=900, show_spinner=False)
def opt_expiries(ticker):
    return _with_retry(lambda: list(yf.Ticker(ticker).options))


@st.cache_data(ttl=900, show_spinner=False)
def opt_chain(ticker, expiry):
    def _f():
        oc = yf.Ticker(ticker).option_chain(expiry)
        c = oc.calls[["strike", "openInterest"]].copy()
        p = oc.puts[["strike", "openInterest"]].copy()
        for d in (c, p):
            d["openInterest"] = d["openInterest"].fillna(0)
        return c, p
    return _with_retry(_f)


def pick_monthly(exps):
    for e in exps:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            if d.weekday() == 4 and 15 <= d.day <= 21:
                return e
        except Exception:
            continue
    return exps[0] if exps else None


# ============================================================
#  GOLD LOGIC
# ============================================================
def gold_quote(ref, key):
    """ref = 'GC' (Yahoo futures) หรือ 'XAU' (Twelve Data spot)"""
    df = td_daily(XAU_TD, key) if ref == "XAU" else yf_daily(GC_YF)
    if df is None or len(df) < 2:
        return None
    closes = df["close"].tolist()
    price, prev = closes[-1], closes[-2]
    return {"price": price,
            "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            "closes": closes[-10:], "df": df}


def gold_pivot_ref(ref, key):
    if ref == "XAU":
        df = td_daily(XAU_TD, key)
        if df is None or len(df) < 2:
            return None
        p = df.iloc[-2]
        if p["high"] > p["low"]:
            return {"high": float(p["high"]), "low": float(p["low"]), "close": float(p["close"]),
                    "how": "Classic Pivot • แท่งวันก่อน (Twelve Data / XAU)"}
        return None
    h = yf_hourly(GC_YF)
    if h is None or h.empty:
        return None
    h = h.copy(); h["d"] = pd.to_datetime(h["dt"]).dt.date
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
            "how": f"Classic Pivot • H/L รายชั่วโมงวันที่ {dates[-2]} (Yahoo / GC)"}


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


def level_df(levels, dec=2):
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


def gold_confluence(ref, key):
    q = gold_quote(ref, key)
    if not q:
        return None
    price, mom = q["price"], q["change_pct"]
    ref_hl = gold_pivot_ref(ref, key)
    daily = classic_pivot(ref_hl["high"], ref_hl["low"], ref_hl["close"]) if ref_hl else None
    rng = swing_range(q["closes"])
    pp_daily = daily["PP"] if daily else rng["PP"]
    mid = rng["PP"]

    dxy_q = gold_quote_dxy()
    dxy_chg = dxy_q["change_pct"] if dxy_q else None
    tips = fred_latest("DFII10")
    tips_chg = tips["change_pp"] if tips else None

    gld_pcr = gld_mp = gld_spot = None
    try:
        exps = opt_expiries(OPTIONS_TICKER)
        me = pick_monthly(exps)
        if me:
            c, p = opt_chain(OPTIONS_TICKER, me)
            tc, tp = float(c["openInterest"].sum()), float(p["openInterest"].sum())
            gld_pcr = tp / tc if tc else None
            gld_mp = max_pain(c, p)
            if (tc + tp) < 1000 or (gld_pcr and (gld_pcr > 3 or gld_pcr < 0.2)):
                gld_mp = None  # ข้อมูล options เพี้ยน -> ไม่ใช้เป็นสัญญาณ confluence
            gdf = yf_daily(OPTIONS_TICKER)
            gld_spot = float(gdf["close"].iloc[-1]) if gdf is not None and len(gdf) else None
    except Exception:
        pass

    sig = []
    def add(name, v, detail): sig.append({"name": name, "v": v, "detail": detail})

    add("ราคา vs Pivot รายวัน", 1 if price > pp_daily else -1,
        f"{price:,.2f} {'>' if price > pp_daily else '<'} {pp_daily:,.2f}")
    add("ราคา vs กรอบ 10 วัน", 1 if price > mid else -1,
        f"{price:,.2f} {'>' if price > mid else '<'} {mid:,.2f}")
    if dxy_chg is None:
        add("DXY (ดอลลาร์)", 0, "n/a")
    elif dxy_chg > 0.05:
        add("DXY (ดอลลาร์)", -1, f"ดอลลาร์แข็ง {dxy_chg:+.2f}% → กดทอง")
    elif dxy_chg < -0.05:
        add("DXY (ดอลลาร์)", 1, f"ดอลลาร์อ่อน {dxy_chg:+.2f}% → หนุนทอง")
    else:
        add("DXY (ดอลลาร์)", 0, f"ทรงตัว {dxy_chg:+.2f}%")
    if tips_chg is None:
        add("Real Yield (TIPS)", 0, "n/a")
    elif tips_chg >= 0.01:
        add("Real Yield (TIPS)", -1, f"{tips_chg:+.2f} pp → กดทอง")
    elif tips_chg <= -0.01:
        add("Real Yield (TIPS)", 1, f"{tips_chg:+.2f} pp → หนุนทอง")
    else:
        add("Real Yield (TIPS)", 0, "ทรงตัว")
    if mom > 0.1:
        add("โมเมนตัมวันนี้", 1, f"{mom:+.2f}%")
    elif mom < -0.1:
        add("โมเมนตัมวันนี้", -1, f"{mom:+.2f}%")
    else:
        add("โมเมนตัมวันนี้", 0, f"{mom:+.2f}%")
    if gld_mp and gld_spot:
        if gld_spot < gld_mp * 0.995:
            add("Options (Max Pain)", 1, f"GLD {gld_spot:.2f} < MaxPain {gld_mp:.0f} → แรงดึงขึ้น")
        elif gld_spot > gld_mp * 1.005:
            add("Options (Max Pain)", -1, f"GLD {gld_spot:.2f} > MaxPain {gld_mp:.0f} → แรงดึงลง")
        else:
            add("Options (Max Pain)", 0, f"GLD ใกล้ MaxPain {gld_mp:.0f}")
    else:
        add("Options (Max Pain)", 0, "n/a")

    net = sum(s["v"] for s in sig)
    bull = sum(1 for s in sig if s["v"] > 0)
    bear = sum(1 for s in sig if s["v"] < 0)
    rp = min(bull, bear)
    if net == 0:
        rp += 1
    if abs(mom) > 1.0:
        rp += 1
    if daily and any(v and abs(price - v) / price < 0.003 for v in daily.values()):
        rp += 1
    grade = max(1, min(5, 1 + rp))
    bias = "Bullish" if net > 0 else "Bearish" if net < 0 else "Neutral"
    return {"net": net, "bull": bull, "bear": bear, "bias": bias, "grade": grade, "sig": sig}


@st.cache_data(ttl=600, show_spinner=False)
def _dxy_df():
    return yf_daily(DXY_YF)


def gold_quote_dxy():
    df = _dxy_df()
    if df is None or len(df) < 2:
        return None
    c = df["close"].tolist()
    return {"change_pct": (c[-1] - c[-2]) / c[-2] * 100 if c[-2] else 0.0}


# ============================================================
#  CONFIG (view-only — ไม่มีปุ่มให้ผู้ชมแตะ)
# ============================================================
td_key = resolve_td_key("")          # ดึงจาก Streamlit Secrets เท่านั้น
primary = PRIMARY
if primary == "XAU" and not td_key:
    primary = "GC"
interval = REFRESH_SECONDS

# ซ่อนเมนู/ฟุตเตอร์/แถบข้างของ Streamlit ให้ผู้ชมเห็นหน้าสะอาด
st.markdown("""<style>
#MainMenu {visibility:hidden;}
footer {visibility:hidden;}
[data-testid="stSidebar"] {display:none;}
[data-testid="stToolbar"] {display:none;}
</style>""", unsafe_allow_html=True)


# ============================================================
#  RENDER SECTIONS
# ============================================================
def render_confluence():
    st.header("🥇 สรุปทองคำ (Gold Confluence)")
    g = gold_confluence(primary, td_key)
    if not g:
        st.warning("ยังประเมินทองไม่ได้ในรอบนี้"); return
    biasmap = {"Bullish": "🟢 Bullish", "Bearish": "🔴 Bearish", "Neutral": "⚪ Neutral"}
    risklabel = {1: "ต่ำมาก", 2: "ต่ำ", 3: "ปานกลาง", 4: "สูง", 5: "สูงมาก"}
    cols = st.columns(3)
    cols[0].metric(f"ทิศทาง (อ้างอิง {primary})", biasmap[g["bias"]], f"คะแนนรวม {g['net']:+d}")
    cols[1].metric("ความเสี่ยง (เกรด)", f"{g['grade']}/5", risklabel[g["grade"]])
    cols[2].metric("สัญญาณ หนุน / กด", f"{g['bull']} ↑ / {g['bear']} ↓")
    st.table(pd.DataFrame({
        "สัญญาณ": [s["name"] for s in g["sig"]],
        "อ่านได้": [("🟢 หนุน" if s["v"] > 0 else "🔴 กด" if s["v"] < 0 else "⚪ กลาง") for s in g["sig"]],
        "รายละเอียด": [s["detail"] for s in g["sig"]],
    }))
    if g["grade"] >= 4:
        note = "สัญญาณขัดแย้ง/อยู่จุดตัดสินใจ — ความไม่แน่นอนสูง ควรระวังเป็นพิเศษ"
    elif g["grade"] <= 2 and g["bias"] != "Neutral":
        note = f"สัญญาณส่วนใหญ่สอดคล้องไป{('ทางขึ้น' if g['bias']=='Bullish' else 'ทางลง')} (ความไม่แน่นอนต่ำ)"
    else:
        note = "สัญญาณผสม ทิศทางยังไม่ชัด"
    st.info("📝 " + note)
    st.caption("⚠️ สรุปเชิงกลไกเพื่อการศึกษา ไม่ใช่สัญญาณซื้อขาย/คำแนะนำ — บริหารความเสี่ยงเสมอ")


def render_zone_radar():
    st.header("📍 เรดาร์โซน — ราคาทองอยู่ใกล้แนวไหน")
    q = gold_quote(primary, td_key)
    if not q:
        st.info("ยังดึงราคาทองไม่ได้ในรอบนี้"); return
    price = q["price"]
    levels = []
    rh = gold_pivot_ref(primary, td_key)
    if rh:
        dp = classic_pivot(rh["high"], rh["low"], rh["close"])
        nm = {"R3": "Pivot R3", "R2": "Pivot R2", "R1": "Pivot R1", "PP": "Pivot กลาง",
              "S1": "Pivot S1", "S2": "Pivot S2", "S3": "Pivot S3"}
        for k, v in dp.items():
            levels.append((nm[k], v))
    try:
        exps = opt_expiries(OPTIONS_TICKER); me = pick_monthly(exps)
        gdf = yf_daily(OPTIONS_TICKER)
        gld_spot = float(gdf["close"].iloc[-1]) if gdf is not None and len(gdf) else None
        if me and gld_spot:
            c, p = opt_chain(OPTIONS_TICKER, me)
            tc, tp = float(c["openInterest"].sum()), float(p["openInterest"].sum())
            pcr = tp / tc if tc else 0.0
            lo, hi = gld_spot * 0.8, gld_spot * 1.2
            cc = c[(c.strike >= lo) & (c.strike <= hi)]
            pp = p[(p.strike >= lo) & (p.strike <= hi)]
            if not cc.empty and not pp.empty:
                cw = float(cc.loc[cc.openInterest.idxmax(), "strike"])
                pw = float(pp.loc[pp.openInterest.idxmax(), "strike"])
                mp = max_pain(cc, pp)
                anom = (tc + tp) < 1000 or pcr > 3 or (0 < pcr < 0.2) or (mp is not None and cw == pw == mp)
                if not anom:
                    mult = price / gld_spot
                    levels += [("Call Wall", cw * mult), ("Put Wall", pw * mult)]
                    if mp:
                        levels.append(("Max Pain", mp * mult))
    except Exception:
        pass

    above = sorted([(n, v) for n, v in levels if v > price], key=lambda x: x[1])
    below = sorted([(n, v) for n, v in levels if v < price], key=lambda x: -x[1])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"ราคาทอง ({primary})", f"{price:,.2f}")
    if above:
        n, v = above[0]; c2.metric("แนวต้านใกล้สุด ↑", f"{v:,.2f}", f"{(v-price)/price*100:+.2f}% • {n}")
    else:
        c2.metric("แนวต้านใกล้สุด ↑", "-")
    if below:
        n, v = below[0]; c3.metric("แนวรับใกล้สุด ↓", f"{v:,.2f}", f"{(v-price)/price*100:+.2f}% • {n}")
    else:
        c3.metric("แนวรับใกล้สุด ↓", "-")

    fired = False
    if above and abs(above[0][1] - price) / price < 0.003:
        n, v = above[0]; fired = True
        st.warning(f"⚡ ราคากำลังทดสอบ {n} ({v:,.2f}) — เฝ้าดูปฏิกิริยา: เด้งลง = โดนต้าน, "
                   "ทะลุด้วยเนื้อแท่ง+ยืนได้ = สัญญาณแรง (อย่าเพิ่งสวนก่อนยืนยัน)")
    if below and abs(below[0][1] - price) / price < 0.003:
        n, v = below[0]; fired = True
        st.warning(f"⚡ ราคากำลังทดสอบ {n} ({v:,.2f}) — เฝ้าดูการเด้ง: อย่ารับมีดตก, "
                   "หลุดด้วยเนื้อแท่ง = อ่อนแรงอาจลงต่อ (รอสัญญาณยืนยันก่อนเข้า)")
    if not fired:
        parts = []
        if above:
            parts.append(f"ต้านถัดไป {above[0][0]} +{(above[0][1]-price)/price*100:.2f}%")
        if below:
            parts.append(f"รับถัดไป {below[0][0]} {(below[0][1]-price)/price*100:.2f}%")
        st.info("📝 ราคายังอยู่กลางโซน • " + " | ".join(parts) + " — ยังไม่ถึงจุดตัดสินใจ")

    walls = [(n, v) for n, v in levels if n in ("Call Wall", "Put Wall", "Max Pain")]
    pivs = [(n, v) for n, v in levels if n.startswith("Pivot")]
    quality = []
    for wn, wv in walls:
        for pn, pv in pivs:
            if abs(wv - pv) / price < 0.003:
                quality.append(f"{wn} ≈ {pn} (~{(wv+pv)/2:,.0f})")
    if quality:
        st.success("⭐ โซนคุณภาพ (options ทับ pivot): " + " • ".join(quality))
    st.caption("แตะโซนให้ 'รอสัญญาณยืนยัน' ไม่เดาล่วงหน้า • เป็นการเพิ่มความน่าจะเป็น ไม่ใช่การทำนาย • วาง SL ทุกไม้")


def render_compare(key):
    st.header("⚖️ GC (Futures) vs XAU (Spot) + Basis")
    gc = gold_quote("GC", key)
    xau = gold_quote("XAU", key)
    rows = []
    if gc:
        rows.append(["GC (Futures)", f"{gc['price']:,.2f}", f"{gc['change_pct']:+.2f}%", "Yahoo"])
    else:
        rows.append(["GC (Futures)", "n/a", "-", "Yahoo"])
    if xau:
        rows.append(["XAU (Spot)", f"{xau['price']:,.2f}", f"{xau['change_pct']:+.2f}%", "Twelve Data"])
    else:
        rows.append(["XAU (Spot)", "n/a (ต้องมี TD key)", "-", "Twelve Data"])
    if gc and xau:
        basis = gc["price"] - xau["price"]
        basis_pct = basis / xau["price"] * 100 if xau["price"] else 0.0
        rows.append(["Basis (GC − XAU)", f"{basis:+,.2f}", f"{basis_pct:+.2f}%", ""])
    st.table(pd.DataFrame(rows, columns=["รายการ", "ราคา", "% วันนี้", "แหล่ง"]))
    st.caption("Basis = ราคา GC (futures) − XAU (spot) • ปกติ futures สูงกว่า spot เล็กน้อย (ค่าดอกเบี้ย/เวลาถึงหมดอายุ) • "
               "ต่างกันหลักสิบจุดเป็นเรื่องปกติ ถ้าแคบ/กว้างผิดปกติค่อยสังเกต")


def render_macro():
    st.header("🌍 ปัจจัยมาโครที่มีผลต่อทอง")
    dxy = _dxy_df()
    yld = fred_latest("DGS10")
    tips = fred_latest("DFII10")
    cols = st.columns(3)
    if dxy is not None and len(dxy) >= 2:
        c = dxy["close"].tolist()
        cols[0].metric("DXY (ดอลลาร์)", f"{c[-1]:,.2f}",
                       f"{(c[-1]-c[-2])/c[-2]*100:+.2f}%")
    else:
        cols[0].metric("DXY (ดอลลาร์)", "n/a", "")
    cols[1].metric("US 10Y Yield", f"{yld['value']:.2f}%" if yld else "n/a",
                   f"{yld['change_pp']:+.2f} pp" if yld else "")
    cols[2].metric("US 10Y Real (TIPS)", f"{tips['value']:.2f}%" if tips else "n/a",
                   f"{tips['change_pp']:+.2f} pp" if tips else "")
    st.caption("ดอลลาร์แข็ง / real yield ขึ้น → มักกดทอง (และกลับกัน)")


def render_pivots(key):
    st.header(f"🎯 แนวรับ/แนวต้าน (Pivot) — {primary}")
    q = gold_quote(primary, key)
    if not q:
        st.warning(f"ดึง {primary} ไม่ได้ (XAU ต้องมี TD key)"); return
    rh = gold_pivot_ref(primary, key)
    daily = classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = swing_range(q["closes"])
    bias = daily["PP"] if daily else rng["PP"]
    badge = "🟢 Bullish" if q["price"] > bias else "🔴 Bearish"
    st.markdown(f"### {primary} — {badge}")
    st.caption(f"ราคาล่าสุด {q['price']:,.2f} ({q['change_pct']:+.2f}%)")
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**📍 Pivot รายวัน (Day Trade)**")
        if daily:
            st.table(level_df(daily)); st.caption(rh["how"])
        else:
            st.info("ดึง H/L รายวันไม่ได้ — ใช้กรอบ 10 วันทางขวา")
    with cB:
        st.markdown("**🗺️ กรอบ 10 วัน (Swing)**")
        st.table(level_df(rng)); st.caption("จากกรอบราคาปิด 10 วัน")


def render_options():
    st.header("🧊 Options OI — GLD (สรุป)")
    try:
        exps = opt_expiries(OPTIONS_TICKER)
        gdf = yf_daily(OPTIONS_TICKER)
        spot = float(gdf["close"].iloc[-1]) if gdf is not None and len(gdf) else None
    except Exception:
        exps, spot = [], None
    if not exps or spot is None:
        st.warning("ดึง option chain ไม่ได้ (อาจติด rate limit) — ลองรีเฟรช"); return
    expiry = pick_monthly(exps)
    st.caption(f"งวด (รายเดือน): {expiry}")
    try:
        calls, puts = opt_chain(OPTIONS_TICKER, expiry)
    except Exception:
        st.warning("ดึง chain งวดนี้ไม่สำเร็จ — ลองรีเฟรช"); return
    tot_c, tot_p = float(calls["openInterest"].sum()), float(puts["openInterest"].sum())
    pcr = tot_p / tot_c if tot_c else 0.0
    lo, hi = spot * 0.8, spot * 1.2
    c = calls[(calls.strike >= lo) & (calls.strike <= hi)]
    p = puts[(puts.strike >= lo) & (puts.strike <= hi)]
    if c.empty or p.empty:
        st.info("ไม่มี strike ในช่วงนี้"); return
    cw = float(c.loc[c.openInterest.idxmax(), "strike"])
    pw = float(p.loc[p.openInterest.idxmax(), "strike"])
    mp = max_pain(c, p)
    r = st.columns(5)
    r[0].metric("Spot GLD", f"{spot:,.2f}")
    r[1].metric("PCR", f"{pcr:.2f}")
    r[2].metric("Call Wall", f"{cw:,.0f}")
    r[3].metric("Put Wall", f"{pw:,.0f}")
    r[4].metric("Max Pain", f"{mp:,.0f}" if mp else "n/a")
    st.caption("Call Wall = แนวต้าน • Put Wall = แนวรับ • PCR>1 = put มากกว่า call • คิดในกรอบ ±20% รอบราคา")

    # ---- ตัวกันข้อมูลเพี้ยน (anomaly guard) ----
    issues = []
    if (tot_c + tot_p) < 1000:
        issues.append("OI รวมน้อยผิดปกติ (งวดบาง)")
    if pcr > 3 or (0 < pcr < 0.2):
        issues.append(f"PCR สุดโต่ง ({pcr:.2f})")
    if mp is not None and cw == pw == mp:
        issues.append("Call/Put Wall + Max Pain กองที่ strike เดียว")
    if issues:
        st.warning("⚠️ ข้อมูล Options งวดนี้อาจเพี้ยน: " + " • ".join(issues)
                   + " — ลองเปลี่ยน expiry เป็นงวดรายเดือน หรือกดรีเฟรช ก่อนนำค่าไปใช้")

    # ---- แปลง wall เป็นสเกลราคาทอง (ข้ามถ้าข้อมูลเพี้ยน) ----
    if issues:
        st.info("⏸️ ข้ามการแปลงสเกลทอง เพราะข้อมูลงวดนี้ผิดปกติ — แก้ให้ค่ากระจายปกติก่อนค่อยนำไปใช้")
    else:
        gq = gold_quote(primary, td_key)
        gold_price = gq["price"] if gq else None
        if gold_price and spot:
            mult = gold_price / spot
            st.markdown(f"**🪙 แปลงเป็นสเกลทอง ({primary}) • ตัวคูณ ×{mult:.2f}**")
            r2 = st.columns(4)
            r2[0].metric("ทองอ้างอิง", f"{gold_price:,.2f}")
            r2[1].metric("Call Wall → ทอง", f"{cw*mult:,.0f}")
            r2[2].metric("Put Wall → ทอง", f"{pw*mult:,.0f}")
            r2[3].metric("Max Pain → ทอง", f"{mp*mult:,.0f}" if mp else "n/a")
            st.caption("แปลงจาก strike GLD × (ราคาทอง ÷ ราคา GLD) • เป็นค่าประมาณ (GLD ไม่ตาม spot เป๊ะ 100%) "
                       "ใช้เป็นโซนอ้างอิง/วางเส้นบนกราฟทองได้")


@st.fragment(run_every=interval)
def body():
    st.title("เลขาตลาด • ทองคำ (Gold Focus)")
    st.caption(f"อัปเดตล่าสุด {datetime.now().strftime('%H:%M:%S')} • โหมดดูอย่างเดียว • "
               f"รีเฟรชอัตโนมัติทุก 30 นาที • อ้างอิง {primary}")
    render_confluence()
    st.divider(); render_zone_radar()
    st.divider(); render_compare(td_key)
    st.divider(); render_macro()
    st.divider(); render_pivots(td_key)
    st.divider(); render_options()
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • เป็นข้อมูลดีเลย์ ไม่ใช่ราคาสดของโบรกเกอร์ • ไม่ใช่คำแนะนำการลงทุน")


body()
