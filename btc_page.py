from datetime import datetime, timezone

import streamlit as st
import altair as alt

import common as C

C.apply_theme()

# ====== ตั้งค่า (view-only) ======
REFRESH_SECONDS = 1800
BTC_YF = "BTC-USD"        # ราคา (24/7 ไม่มีปัญหาแท่งเพี้ยน)
NASDAQ_YF = "^IXIC"       # ตัวแทน risk sentiment
DXY_YF = "DX-Y.NYB"
DERIBIT = "https://www.deribit.com/api/v2/public/"


# ---------- ราคา/พีวอต BTC ----------
def btc_quote():
    df = C.yf_daily(BTC_YF)
    if df is None or len(df) < 2:
        return None
    closes = df["close"].tolist()
    price, prev = closes[-1], closes[-2]
    return {"price": price, "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            "closes": closes[-10:], "df": df}


def btc_pivot_ref():
    df = C.yf_daily(BTC_YF)
    if df is None or len(df) < 2:
        return None
    p = df.iloc[-2]           # BTC เทรด 24/7 → แท่งวันก่อนใช้ได้เลย
    if p["high"] <= p["low"]:
        return None
    return {"high": float(p["high"]), "low": float(p["low"]), "close": float(p["close"]),
            "how": "Classic Pivot • แท่งวันก่อน (Yahoo BTC-USD)"}


# ---------- Deribit options (ของจริง ฟรี) ----------
@st.cache_data(ttl=300, show_spinner=False)
def deribit_index():
    try:
        j = C.http_json(DERIBIT + "get_index_price?index_name=btc_usd")
        return float(j["result"]["index_price"])
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def deribit_options():
    """คืน dict สรุป options BTC งวดที่ OI หนาสุด (สเกล USD ตรงกับราคา BTC)"""
    try:
        j = C.http_json(DERIBIT + "get_book_summary_by_currency?currency=BTC&kind=option")
        rows = j.get("result", [])
    except Exception:
        return None
    if not rows:
        return None
    by_exp = {}
    for it in rows:
        name = it.get("instrument_name", "")
        parts = name.split("-")
        if len(parts) != 4:
            continue
        _, exp, strike, cp = parts
        try:
            strike = float(strike)
        except Exception:
            continue
        oi = float(it.get("open_interest") or 0)
        d = by_exp.setdefault(exp, {"calls": [], "puts": [], "totC": 0.0, "totP": 0.0})
        rec = {"strike": strike, "oi": oi}
        if cp == "C":
            d["calls"].append(rec); d["totC"] += oi
        elif cp == "P":
            d["puts"].append(rec); d["totP"] += oi
    if not by_exp:
        return None
    exp = max(by_exp, key=lambda e: by_exp[e]["totC"] + by_exp[e]["totP"])
    d = by_exp[exp]
    spot = deribit_index()
    if not spot:
        return None
    lo, hi = spot * 0.8, spot * 1.2
    calls = [o for o in d["calls"] if lo <= o["strike"] <= hi]
    puts = [o for o in d["puts"] if lo <= o["strike"] <= hi]
    if not calls or not puts:
        return None
    pcr = d["totP"] / d["totC"] if d["totC"] else 0.0
    cw = max(calls, key=lambda o: o["oi"])["strike"]
    pw = max(puts, key=lambda o: o["oi"])["strike"]
    mp = C.max_pain(calls, puts)
    anom = (d["totC"] + d["totP"]) < 50 or pcr > 3 or (0 < pcr < 0.2) or (mp is not None and cw == pw == mp)
    return {"expiry": exp, "spot": spot, "pcr": pcr, "callWall": cw,
            "putWall": pw, "maxPain": mp, "anomalous": anom}


@st.cache_data(ttl=900, show_spinner=False)
def deribit_gex(pct=0.20):
    """คำนวณ GEX ราย strike จาก Deribit (ใช้ mark_iv + Black-Scholes)"""
    try:
        j = C.http_json(DERIBIT + "get_book_summary_by_currency?currency=BTC&kind=option")
        rows = j.get("result", [])
    except Exception:
        return None
    if not rows:
        return None
    parsed, exp_oi = [], {}
    for it in rows:
        parts = it.get("instrument_name", "").split("-")
        if len(parts) != 4:
            continue
        _, exp, strike, cp = parts
        try:
            strike = float(strike)
        except Exception:
            continue
        oi = float(it.get("open_interest") or 0)
        parsed.append({"exp": exp, "K": strike, "cp": cp, "oi": oi,
                       "iv": it.get("mark_iv"), "S": it.get("underlying_price")})
        exp_oi[exp] = exp_oi.get(exp, 0.0) + oi
    if not exp_oi:
        return None
    exp = max(exp_oi, key=lambda e: exp_oi[e])
    spot = deribit_index()
    if not spot:
        for p in parsed:
            if p["exp"] == exp and p["S"]:
                spot = float(p["S"]); break
    if not spot:
        return None
    try:
        expd = datetime.strptime(exp, "%d%b%y")
    except Exception:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    T = max((expd - now).total_seconds() + 8 * 3600, 3600) / (365 * 24 * 3600)
    lo, hi = spot * (1 - pct), spot * (1 + pct)
    per = {}
    for p in parsed:
        if p["exp"] != exp or p["K"] < lo or p["K"] > hi or p["iv"] is None:
            continue
        g = C.bs_gamma(spot, p["K"], T, float(p["iv"]) / 100.0)
        gex = g * p["oi"] * (spot ** 2) * 0.01     # multiplier=1 (1 สัญญา=1 BTC)
        d = per.setdefault(p["K"], {"call": 0.0, "put": 0.0})
        d["call" if p["cp"] == "C" else "put"] += gex
    if not per:
        return None
    strikes = sorted(per)
    net = {k: per[k]["call"] - per[k]["put"] for k in strikes}   # call บวก / put ลบ
    total = sum(net.values())
    call_wall = max(strikes, key=lambda k: per[k]["call"])
    put_wall = max(strikes, key=lambda k: per[k]["put"])
    return {"expiry": exp, "spot": spot, "strikes": strikes, "net": net,
            "total": total, "call_wall": call_wall, "put_wall": put_wall}


def nasdaq_change():
    df = C.yf_daily(NASDAQ_YF)
    if df is None or len(df) < 2:
        return None
    c = df["close"].tolist()
    return (c[-1] - c[-2]) / c[-2] * 100 if c[-2] else 0.0


def dxy_change():
    df = C.yf_daily(DXY_YF)
    if df is None or len(df) < 2:
        return None
    c = df["close"].tolist()
    return (c[-1] - c[-2]) / c[-2] * 100 if c[-2] else 0.0


# ---------- confluence (จูนสำหรับ BTC) ----------
def btc_confluence():
    q = btc_quote()
    if not q:
        return None
    price, mom = q["price"], q["change_pct"]
    rh = btc_pivot_ref()
    daily = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = C.swing_range(q["closes"])
    pp_daily = daily["PP"] if daily else rng["PP"]
    mid = rng["PP"]
    dxy_chg = dxy_change()
    ndx_chg = nasdaq_change()
    opt = deribit_options()

    sig, detail = [], []
    def add(name, v, d): sig.append(v); detail.append({"name": name, "v": v, "detail": d})

    add("ราคา vs Pivot รายวัน", 1 if price > pp_daily else -1,
        f"{price:,.0f} {'>' if price > pp_daily else '<'} {pp_daily:,.0f}")
    add("ราคา vs กรอบ 10 วัน", 1 if price > mid else -1,
        f"{price:,.0f} {'>' if price > mid else '<'} {mid:,.0f}")
    if dxy_chg is None:
        add("DXY (ดอลลาร์)", 0, "n/a")
    elif dxy_chg > 0.05:
        add("DXY (ดอลลาร์)", -1, f"ดอลลาร์แข็ง {dxy_chg:+.2f}% → กด BTC")
    elif dxy_chg < -0.05:
        add("DXY (ดอลลาร์)", 1, f"ดอลลาร์อ่อน {dxy_chg:+.2f}% → หนุน BTC")
    else:
        add("DXY (ดอลลาร์)", 0, f"ทรงตัว {dxy_chg:+.2f}%")
    if ndx_chg is None:
        add("Nasdaq (risk sentiment)", 0, "n/a")
    elif ndx_chg > 0.1:
        add("Nasdaq (risk sentiment)", 1, f"{ndx_chg:+.2f}% → risk-on หนุน BTC")
    elif ndx_chg < -0.1:
        add("Nasdaq (risk sentiment)", -1, f"{ndx_chg:+.2f}% → risk-off กด BTC")
    else:
        add("Nasdaq (risk sentiment)", 0, f"ทรงตัว {ndx_chg:+.2f}%")
    if mom > 0.1:
        add("โมเมนตัมวันนี้", 1, f"{mom:+.2f}%")
    elif mom < -0.1:
        add("โมเมนตัมวันนี้", -1, f"{mom:+.2f}%")
    else:
        add("โมเมนตัมวันนี้", 0, f"{mom:+.2f}%")
    if opt and not opt["anomalous"] and opt["maxPain"] and opt["spot"]:
        mp, sp = opt["maxPain"], opt["spot"]
        if sp < mp * 0.995:
            add("Options (Max Pain)", 1, f"{sp:,.0f} < MaxPain {mp:,.0f} → แรงดึงขึ้น")
        elif sp > mp * 1.005:
            add("Options (Max Pain)", -1, f"{sp:,.0f} > MaxPain {mp:,.0f} → แรงดึงลง")
        else:
            add("Options (Max Pain)", 0, f"ใกล้ MaxPain {mp:,.0f}")
    else:
        add("Options (Max Pain)", 0, "n/a")

    near = bool(daily and any(v and abs(price - v) / price < 0.003 for v in daily.values()))
    g = C.grade_from_votes(sig, mom, near)
    g.update({"detail": detail, "price": price})
    return g


# ---------- render ----------
def render_confluence():
    st.header("₿ สรุป BTCUSD (Confluence)")
    g = btc_confluence()
    if not g:
        st.warning("ยังประเมิน BTC ไม่ได้ในรอบนี้"); return
    bmap = {"Bullish": ("🟢", "#38c172"), "Bearish": ("🔴", "#e3506a"), "Neutral": ("⚪", "#9fb0c8")}
    bi, bc = bmap[g["bias"]]
    gcolor = "#38c172" if g["grade"] <= 2 else "#e8c565" if g["grade"] == 3 else "#e3506a"
    glabel = {1: "ต่ำมาก", 2: "ต่ำ", 3: "ปานกลาง", 4: "สูง", 5: "สูงมาก"}[g["grade"]]
    C.hero_cards([
        ("ทิศทาง (BTCUSD)", f"{bi} {g['bias']}", f"คะแนนรวม {g['net']:+d}", bc),
        ("ความเสี่ยง (เกรด)", f"{g['grade']}/5", glabel, gcolor),
        ("สัญญาณ หนุน / กด", f"{g['bull']} ↑ / {g['bear']} ↓", "จาก 6 สัญญาณ", "#e8c565"),
    ])
    st.table(C.pd.DataFrame({
        "สัญญาณ": [s["name"] for s in g["detail"]],
        "อ่านได้": [("🟢 หนุน" if s["v"] > 0 else "🔴 กด" if s["v"] < 0 else "⚪ กลาง") for s in g["detail"]],
        "รายละเอียด": [s["detail"] for s in g["detail"]],
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
    st.header("📍 เรดาร์โซน — BTC อยู่ใกล้แนวไหน")
    q = btc_quote()
    if not q:
        st.info("ยังดึงราคา BTC ไม่ได้ในรอบนี้"); return
    price = q["price"]
    levels = []
    rh = btc_pivot_ref()
    if rh:
        dp = C.classic_pivot(rh["high"], rh["low"], rh["close"])
        nm = {"R3": "Pivot R3", "R2": "Pivot R2", "R1": "Pivot R1", "PP": "Pivot กลาง",
              "S1": "Pivot S1", "S2": "Pivot S2", "S3": "Pivot S3"}
        for k, v in dp.items():
            levels.append({"name": nm[k], "v": v})
    opt = deribit_options()
    if opt and not opt["anomalous"]:
        # Deribit strike เป็น USD อยู่แล้ว → ใช้ตรงๆ ไม่ต้องแปลงสเกล
        levels.append({"name": "Call Wall", "v": opt["callWall"]})
        levels.append({"name": "Put Wall", "v": opt["putWall"]})
        if opt["maxPain"]:
            levels.append({"name": "Max Pain", "v": opt["maxPain"]})
    above = sorted([x for x in levels if x["v"] > price], key=lambda x: x["v"])
    below = sorted([x for x in levels if x["v"] < price], key=lambda x: -x["v"])
    c1, c2, c3 = st.columns(3)
    c1.metric("ราคา BTC", f"{price:,.0f}")
    if above:
        c2.metric("แนวต้านใกล้สุด ↑", f"{above[0]['v']:,.0f}",
                  f"{(above[0]['v']-price)/price*100:+.2f}% • {above[0]['name']}")
    else:
        c2.metric("แนวต้านใกล้สุด ↑", "-")
    if below:
        c3.metric("แนวรับใกล้สุด ↓", f"{below[0]['v']:,.0f}",
                  f"{(below[0]['v']-price)/price*100:+.2f}% • {below[0]['name']}")
    else:
        c3.metric("แนวรับใกล้สุด ↓", "-")
    fired, quality = C.zone_note_and_quality(price, above, below, levels)
    if fired:
        for _, m in fired:
            st.warning(m)
    else:
        parts = []
        if above:
            parts.append(f"ต้านถัดไป {above[0]['name']} +{(above[0]['v']-price)/price*100:.2f}%")
        if below:
            parts.append(f"รับถัดไป {below[0]['name']} {(below[0]['v']-price)/price*100:.2f}%")
        st.info("📝 ราคายังอยู่กลางโซน • " + " | ".join(parts) + " — ยังไม่ถึงจุดตัดสินใจ")
    if quality:
        st.success("⭐ โซนคุณภาพ (options ทับ pivot): " + " • ".join(quality))
    st.caption("Deribit = options BTC ของจริง (สเกล USD ตรงกับราคา — ไม่ต้องแปลง) • แตะโซนให้รอสัญญาณยืนยัน • วาง SL ทุกไม้")


def render_pivots():
    st.header("🎯 แนวรับ/แนวต้าน (Pivot) — BTCUSD")
    q = btc_quote()
    if not q:
        st.warning("ดึง BTC ไม่ได้"); return
    rh = btc_pivot_ref()
    daily = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = C.swing_range(q["closes"])
    bias = daily["PP"] if daily else rng["PP"]
    badge = "🟢 Bullish" if q["price"] > bias else "🔴 Bearish"
    st.markdown(f"### BTCUSD — {badge}")
    st.caption(f"ราคาล่าสุด {q['price']:,.0f} ({q['change_pct']:+.2f}%)")
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**📍 Pivot รายวัน (Day Trade)**")
        if daily:
            st.table(C.level_df(daily, dec=0)); st.caption(rh["how"])
        else:
            st.info("ดึง H/L รายวันไม่ได้ — ใช้กรอบ 10 วันทางขวา")
    with cB:
        st.markdown("**🗺️ กรอบ 10 วัน (Swing)**")
        st.table(C.level_df(rng, dec=0)); st.caption("จากกรอบราคาปิด 10 วัน")


def render_options():
    st.header("🧊 Options OI — Deribit BTC (สรุป)")
    opt = deribit_options()
    if not opt:
        st.warning("ดึง Deribit ไม่ได้ในรอบนี้ — ลองรีเฟรช"); return
    st.caption(f"งวด (OI หนาสุด): {opt['expiry']} • สเกล USD ตรงกับราคา BTC")
    r = st.columns(5)
    r[0].metric("Index (spot)", f"{opt['spot']:,.0f}")
    r[1].metric("PCR", f"{opt['pcr']:.2f}")
    r[2].metric("Call Wall", f"{opt['callWall']:,.0f}")
    r[3].metric("Put Wall", f"{opt['putWall']:,.0f}")
    r[4].metric("Max Pain", f"{opt['maxPain']:,.0f}" if opt["maxPain"] else "n/a")
    st.caption("Call Wall = แนวต้าน • Put Wall = แนวรับ • PCR>1 = put มากกว่า call • กรอบ ±20%")
    if opt["anomalous"]:
        st.warning("⚠️ ข้อมูล options งวดนี้อาจเพี้ยน — ใช้เฉพาะ pivot (ลองรีเฟรช)")


def render_gex():
    st.header("🧮 GEX by Strike — Deribit BTC (คำนวณเอง)")
    gx = deribit_gex(0.20)
    if not gx:
        st.warning("ดึง/คำนวณ GEX ไม่ได้ในรอบนี้ (Deribit อาจไม่พร้อม) — ลองรีเฟรช"); return
    total_m = gx["total"] / 1e6
    pos = gx["total"] >= 0
    rcolor = "#38c172" if pos else "#e3506a"
    C.hero_cards([
        ("Regime (Net GEX รวม)", ("🟢 Positive" if pos else "🔴 Negative"),
         f"{total_m:+,.1f}M • {'หน่วง' if pos else 'เร่ง'}", rcolor),
        ("Call GEX Wall", f"{gx['call_wall']:,.0f}", "แนวต้านเชิงโครงสร้าง", "#e8c565"),
        ("Put GEX Wall", f"{gx['put_wall']:,.0f}", "แนวรับเชิงโครงสร้าง", "#e8c565"),
    ])
    df = C.pd.DataFrame({
        "strike": [str(int(k)) for k in gx["strikes"]],
        "GEX": [gx["net"][k] / 1e6 for k in gx["strikes"]],
    })
    df["ฝั่ง"] = ["Call (บวก)" if v >= 0 else "Put (ลบ)" for v in df["GEX"]]
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("strike:N", title="Strike", sort=list(df["strike"])),
        y=alt.Y("GEX:Q", title="Net GEX (ล้าน USD ต่อ 1%)"),
        color=alt.Color("ฝั่ง:N", scale=alt.Scale(domain=["Call (บวก)", "Put (ลบ)"],
                        range=["#38c172", "#e3506a"]), legend=alt.Legend(title=None)),
        tooltip=["strike", alt.Tooltip("GEX:Q", format="+.2f")],
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)
    st.caption(f"งวด {gx['expiry']} • spot {gx['spot']:,.0f} • กรอบ ±20% • "
               "GEX = gamma×OI×spot²×0.01 (Call บวก / Put ลบ) • gamma คำนวณจาก mark_iv ของ Deribit (Black-Scholes)")
    st.info("📝 Positive GEX รวม = ดีลเลอร์มักหน่วงราคา (ตลาดนิ่ง/เข้ากรอบ) • Negative = เร่งราคา (ผันผวน/cascade) • "
            "อิงสมมติฐาน 'dealer short call / long put' ซึ่งไม่จริงเสมอไป — ใช้เป็นบริบท ไม่ใช่สัญญาณ")


@st.fragment(run_every=REFRESH_SECONDS)
def body():
    st.title("เลขาตลาด • BTCUSD")
    st.caption(f"อัปเดตล่าสุด {datetime.now().strftime('%H:%M:%S')} • โหมดดูอย่างเดียว • "
               "รีเฟรชอัตโนมัติทุก 30 นาที • ราคา Yahoo • options Deribit")
    render_confluence()
    st.divider(); render_zone_radar()
    st.divider(); render_pivots()
    st.divider(); render_options()
    st.divider(); render_gex()
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • เป็นข้อมูลดีเลย์ ไม่ใช่ราคาสดของโบรกเกอร์ • ไม่ใช่คำแนะนำการลงทุน")


body()
