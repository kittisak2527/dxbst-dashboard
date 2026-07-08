from datetime import datetime, timezone

import streamlit as st
import yfinance as yf
import altair as alt

import common as C

C.apply_theme()

# ====== ตั้งค่า (view-only) ======
PRIMARY = "EUR"
REFRESH_SECONDS = 1800
EUR_YF = "EURUSD=X"        # ราคา spot (Yahoo, forex 24/5 แท่งรายวันใช้ได้)
DXY_YF = "DX-Y.NYB"
OPTIONS_TICKER = "FXE"     # Invesco Euro Trust — ใช้เป็น options proxy ของ EUR (เหมือน GLD ของทอง)
DEC = 4                    # ทศนิยมราคายูโร


# ---------- ราคา/พีวอต ----------
def eur_quote():
    df = C.yf_daily(EUR_YF)
    if df is None or len(df) < 2:
        return None
    closes = df["close"].tolist()
    price, prev = closes[-1], closes[-2]
    return {"price": price, "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            "closes": closes[-10:], "df": df}


def eur_pivot_ref():
    df = C.yf_daily(EUR_YF)
    if df is None or len(df) < 2:
        return None
    p = df.iloc[-2]
    if p["high"] <= p["low"]:
        return None
    return {"high": float(p["high"]), "low": float(p["low"]), "close": float(p["close"]),
            "how": "Classic Pivot • แท่งวันก่อน (Yahoo EURUSD=X)"}


# ---------- FXE options ----------
@st.cache_data(ttl=900, show_spinner=False)
def opt_expiries():
    try:
        return C.with_retry(lambda: list(yf.Ticker(OPTIONS_TICKER).options))
    except Exception:
        return []


@st.cache_data(ttl=900, show_spinner=False)
def opt_chain(expiry):
    def _f():
        oc = yf.Ticker(OPTIONS_TICKER).option_chain(expiry)
        cols = ["strike", "openInterest", "impliedVolatility"]
        c = oc.calls[cols].copy()
        p = oc.puts[cols].copy()
        for d in (c, p):
            d["openInterest"] = d["openInterest"].fillna(0)
            d["impliedVolatility"] = d["impliedVolatility"].fillna(0)
        return c, p
    try:
        return C.with_retry(_f)
    except Exception:
        return None


def pick_monthly(exps):
    for e in exps:
        try:
            d = datetime.strptime(e, "%Y-%m-%d").date()
            if d.weekday() == 4 and 15 <= d.day <= 21:
                return e
        except Exception:
            continue
    return exps[0] if exps else None


def _pairs(df):
    return [{"strike": float(r.strike), "oi": float(r.openInterest)} for r in df.itertuples()]


def _dte_eur(exp):
    try:
        d = datetime.strptime(exp, "%Y-%m-%d")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0, (d - now).days)
    except Exception:
        return None


def fxe_snapshot():
    """สรุป options FXE (งวดรายเดือน) + ธงเพี้ยน — FXE บางกว่า GLD"""
    try:
        me = pick_monthly(opt_expiries())
        fdf = C.yf_daily(OPTIONS_TICKER)
        spot = float(fdf["close"].iloc[-1]) if fdf is not None and len(fdf) else None
        if not me or spot is None:
            return None
        ch = opt_chain(me)
        if not ch:
            return None
        calls, puts = ch
        totc, totp = float(calls["openInterest"].sum()), float(puts["openInterest"].sum())
        pcr = totp / totc if totc else 0.0
        lo, hi = spot * 0.8, spot * 1.2
        c = calls[(calls.strike >= lo) & (calls.strike <= hi)]
        p = puts[(puts.strike >= lo) & (puts.strike <= hi)]
        if c.empty or p.empty:
            return None
        cw = float(c.loc[c.openInterest.idxmax(), "strike"])
        pw = float(p.loc[p.openInterest.idxmax(), "strike"])
        mp = C.max_pain(_pairs(c), _pairs(p))
        anom = (totc + totp) < 200 or pcr > 3 or (0 < pcr < 0.2) or (mp is not None and cw == pw == mp)
        return {"expiry": me, "spot": spot, "pcr": pcr, "callWall": cw,
                "putWall": pw, "maxPain": mp, "anomalous": anom}
    except Exception:
        return None


def fxe_gex(pct=0.20):
    """GEX ราย strike จาก FXE (impliedVolatility) แปลงเป็นสเกล EUR"""
    try:
        me = pick_monthly(opt_expiries())
        fdf = C.yf_daily(OPTIONS_TICKER)
        fxe_spot = float(fdf["close"].iloc[-1]) if fdf is not None and len(fdf) else None
        q = eur_quote()
        if not me or fxe_spot is None or not q:
            return None
        ch = opt_chain(me)
        if not ch:
            return None
        calls, puts = ch
        lo, hi = fxe_spot * (1 - pct), fxe_spot * (1 + pct)
        opts = []
        for df, cp in ((calls, "C"), (puts, "P")):
            for r in df.itertuples():
                iv = float(r.impliedVolatility)
                if lo <= r.strike <= hi and iv > 0:
                    opts.append({"K": float(r.strike), "oi": float(r.openInterest), "iv": iv, "cp": cp})
        if not opts:
            return None
        d = datetime.strptime(me, "%Y-%m-%d")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        T = max((d - now).total_seconds() + 20 * 3600, 3600) / (365 * 24 * 3600)
        gx = C.compute_gex(opts, fxe_spot, T)
        if not gx:
            return None
        flip = C.gamma_flip(opts, fxe_spot, T, lo, hi)
        mult = q["price"] / fxe_spot
        return {"expiry": me, "fxe_spot": fxe_spot, "mult": mult, "eur_price": q["price"],
                "total": gx["total"], "regime": gx["regime"],
                "strikes_eur": [k * mult for k in gx["strikes"]],
                "net": [gx["net"][k] for k in gx["strikes"]],
                "call_wall": gx["call_wall"] * mult, "put_wall": gx["put_wall"] * mult,
                "flip": flip * mult if flip else None}
    except Exception:
        return None


# ---------- confluence (จูนสำหรับ EUR) ----------
def eur_confluence():
    q = eur_quote()
    if not q:
        return None
    price, mom = q["price"], q["change_pct"]
    rh = eur_pivot_ref()
    daily = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = C.swing_range(q["closes"])
    pp_daily = daily["PP"] if daily else rng["PP"]
    mid = rng["PP"]

    dxy = C.yf_daily(DXY_YF)
    dxy_chg = None
    if dxy is not None and len(dxy) >= 2:
        cc = dxy["close"].tolist(); dxy_chg = (cc[-1] - cc[-2]) / cc[-2] * 100 if cc[-2] else 0.0
    opt = fxe_snapshot()

    sig, detail = [], []
    def add(name, v, d): sig.append(v); detail.append({"name": name, "v": v, "detail": d})

    add("ราคา vs Pivot รายวัน", 1 if price > pp_daily else -1,
        f"{price:,.4f} {'>' if price > pp_daily else '<'} {pp_daily:,.4f}")
    add("ราคา vs กรอบ 10 วัน", 1 if price > mid else -1,
        f"{price:,.4f} {'>' if price > mid else '<'} {mid:,.4f}")
    if dxy_chg is None:
        add("DXY (ดอลลาร์)", 0, "n/a")
    elif dxy_chg > 0.05:
        add("DXY (ดอลลาร์)", -1, f"ดอลลาร์แข็ง {dxy_chg:+.2f}% → กด EUR")
    elif dxy_chg < -0.05:
        add("DXY (ดอลลาร์)", 1, f"ดอลลาร์อ่อน {dxy_chg:+.2f}% → หนุน EUR")
    else:
        add("DXY (ดอลลาร์)", 0, f"ทรงตัว {dxy_chg:+.2f}%")
    if mom > 0.1:
        add("โมเมนตัมวันนี้", 1, f"{mom:+.2f}%")
    elif mom < -0.1:
        add("โมเมนตัมวันนี้", -1, f"{mom:+.2f}%")
    else:
        add("โมเมนตัมวันนี้", 0, f"{mom:+.2f}%")
    if opt and not opt["anomalous"] and opt["maxPain"] and opt["spot"]:
        mp, sp = opt["maxPain"], opt["spot"]
        if sp < mp * 0.995:
            add("Options (Max Pain)", 1, f"FXE {sp:.2f} < MaxPain {mp:.0f} → แรงดึงขึ้น")
        elif sp > mp * 1.005:
            add("Options (Max Pain)", -1, f"FXE {sp:.2f} > MaxPain {mp:.0f} → แรงดึงลง")
        else:
            add("Options (Max Pain)", 0, f"FXE ใกล้ MaxPain {mp:.0f}")
    else:
        add("Options (Max Pain)", 0, "n/a")

    near = bool(daily and any(v and abs(price - v) / price < 0.002 for v in daily.values()))
    g = C.grade_from_votes(sig, mom, near)
    g.update({"detail": detail, "price": price})
    return g


# ---------- render ----------
def render_confluence():
    st.header("💶 สรุป EUR/USD (Confluence)")
    g = eur_confluence()
    if not g:
        st.warning("ยังประเมิน EUR ไม่ได้ในรอบนี้"); return
    bmap = {"Bullish": ("🟢", "#38c172"), "Bearish": ("🔴", "#e3506a"), "Neutral": ("⚪", "#9fb0c8")}
    bi, bc = bmap[g["bias"]]
    gcolor = "#38c172" if g["grade"] <= 2 else "#e8c565" if g["grade"] == 3 else "#e3506a"
    glabel = {1: "ต่ำมาก", 2: "ต่ำ", 3: "ปานกลาง", 4: "สูง", 5: "สูงมาก"}[g["grade"]]
    C.hero_cards([
        ("ทิศทาง (EUR/USD)", f"{bi} {g['bias']}", f"คะแนนรวม {g['net']:+d}", bc),
        ("ความเสี่ยง (เกรด)", f"{g['grade']}/5", glabel, gcolor),
        ("สัญญาณ หนุน / กด", f"{g['bull']} ↑ / {g['bear']} ↓", "จาก 5 สัญญาณ", "#e8c565"),
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
    st.header("📍 เรดาร์โซน — EUR อยู่ใกล้แนวไหน")
    q = eur_quote()
    if not q:
        st.info("ยังดึงราคา EUR ไม่ได้ในรอบนี้"); return
    price = q["price"]
    levels = []
    rh = eur_pivot_ref()
    if rh:
        dp = C.classic_pivot(rh["high"], rh["low"], rh["close"])
        nm = {"R3": "Pivot R3", "R2": "Pivot R2", "R1": "Pivot R1", "PP": "Pivot กลาง",
              "S1": "Pivot S1", "S2": "Pivot S2", "S3": "Pivot S3"}
        for k, v in dp.items():
            levels.append({"name": nm[k], "v": v})
    opt = fxe_snapshot()
    if opt and not opt["anomalous"] and opt["spot"]:
        mult = price / opt["spot"]
        levels.append({"name": "Call Wall", "v": opt["callWall"] * mult})
        levels.append({"name": "Put Wall", "v": opt["putWall"] * mult})
        if opt["maxPain"]:
            levels.append({"name": "Max Pain", "v": opt["maxPain"] * mult})
    gx = fxe_gex(0.20)
    if gx:
        levels.append({"name": "GEX Call Wall", "v": gx["call_wall"]})
        levels.append({"name": "GEX Put Wall", "v": gx["put_wall"]})
        if gx.get("flip"):
            levels.append({"name": "Gamma Flip", "v": gx["flip"]})
    above = sorted([x for x in levels if x["v"] > price], key=lambda x: x["v"])
    below = sorted([x for x in levels if x["v"] < price], key=lambda x: -x["v"])
    c1, c2, c3 = st.columns(3)
    c1.metric("ราคา EUR/USD", f"{price:,.4f}")
    if above:
        c2.metric("แนวต้านใกล้สุด ↑", f"{above[0]['v']:,.4f}",
                  f"{(above[0]['v']-price)/price*100:+.2f}% • {above[0]['name']}")
    else:
        c2.metric("แนวต้านใกล้สุด ↑", "-")
    if below:
        c3.metric("แนวรับใกล้สุด ↓", f"{below[0]['v']:,.4f}",
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
    st.caption("FXE เป็น options proxy ของ EUR (แปลงสเกลด้วยตัวคูณ) • แตะโซนให้รอสัญญาณยืนยัน • วาง SL ทุกไม้")


def render_macro():
    st.header("🌍 ปัจจัยมาโครที่มีผลต่อ EUR")
    dxy = C.yf_daily(DXY_YF)
    yld = C.fred_latest("DGS10")
    cols = st.columns(2)
    if dxy is not None and len(dxy) >= 2:
        cc = dxy["close"].tolist()
        cols[0].metric("DXY (ดอลลาร์)", f"{cc[-1]:,.2f}", f"{(cc[-1]-cc[-2])/cc[-2]*100:+.2f}%")
    else:
        cols[0].metric("DXY (ดอลลาร์)", "n/a", "")
    cols[1].metric("US 10Y Yield", f"{yld['value']:.2f}%" if yld else "n/a",
                   f"{yld['change_pp']:+.2f} pp" if yld else "")
    st.caption("ดอลลาร์แข็ง (DXY ขึ้น) → มักกด EUR/USD และกลับกัน")


def render_pivots():
    st.header("🎯 แนวรับ/แนวต้าน (Pivot) — EUR/USD")
    q = eur_quote()
    if not q:
        st.warning("ดึง EUR ไม่ได้"); return
    rh = eur_pivot_ref()
    daily = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = C.swing_range(q["closes"])
    bias = daily["PP"] if daily else rng["PP"]
    badge = "🟢 Bullish" if q["price"] > bias else "🔴 Bearish"
    st.markdown(f"### EUR/USD — {badge}")
    st.caption(f"ราคาล่าสุด {q['price']:,.4f} ({q['change_pct']:+.2f}%)")
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**📍 Pivot รายวัน (Day Trade)**")
        if daily:
            st.table(C.level_df(daily, dec=DEC)); st.caption(rh["how"])
        else:
            st.info("ดึง H/L รายวันไม่ได้ — ใช้กรอบ 10 วันทางขวา")
    with cB:
        st.markdown("**🗺️ กรอบ 10 วัน (Swing)**")
        st.table(C.level_df(rng, dec=DEC)); st.caption("จากกรอบราคาปิด 10 วัน")


def render_options():
    st.header("🧊 Options OI — FXE (สรุป)")
    opt = fxe_snapshot()
    if not opt:
        st.warning("ดึง FXE option chain ไม่ได้ (FXE บาง/ติด limit) — ลองรีเฟรช"); return
    dte = _dte_eur(opt["expiry"])
    dte_txt = f" • เหลือ {dte} วันถึงหมดอายุ" if dte is not None else ""
    st.caption(f"งวด (รายเดือน): {opt['expiry']}{dte_txt} • FXE เป็น proxy ของ EUR")
    r = st.columns(5)
    r[0].metric("Spot FXE", f"{opt['spot']:,.2f}")
    r[1].metric("PCR", f"{opt['pcr']:.2f}")
    r[2].metric("Call Wall", f"{opt['callWall']:,.0f}")
    r[3].metric("Put Wall", f"{opt['putWall']:,.0f}")
    r[4].metric("Max Pain", f"{opt['maxPain']:,.0f}" if opt["maxPain"] else "n/a",
                f"เหลือ {dte} วัน" if dte is not None else None, delta_color="off")
    st.caption("Call Wall = แนวต้าน • Put Wall = แนวรับ • PCR>1 = put มากกว่า call • กรอบ ±20%")
    if opt["anomalous"]:
        st.warning("⚠️ ข้อมูล FXE options งวดนี้บาง/เพี้ยน — ข้ามการแปลงสเกล (FXE ลิควิดน้อย เป็นเรื่องปกติ)")
        return
    q = eur_quote()
    if q:
        mult = q["price"] / opt["spot"]
        st.markdown(f"**💶 แปลงเป็นสเกล EUR • ตัวคูณ ×{mult:.4f}**")
        r2 = st.columns(4)
        r2[0].metric("EUR อ้างอิง", f"{q['price']:,.4f}")
        r2[1].metric("Call Wall → EUR", f"{opt['callWall']*mult:,.4f}")
        r2[2].metric("Put Wall → EUR", f"{opt['putWall']*mult:,.4f}")
        r2[3].metric("Max Pain → EUR", f"{opt['maxPain']*mult:,.4f}" if opt["maxPain"] else "n/a")
        st.caption("แปลงจาก strike FXE × (EUR ÷ FXE) • เป็นค่าประมาณ ใช้เป็นโซนอ้างอิง")


def render_gex():
    st.header("🧮 GEX by Strike — FXE (คำนวณเอง • สเกล EUR)")
    gx = fxe_gex(0.20)
    if not gx:
        st.info("ยังคำนวณ GEX ยูโรไม่ได้ (FXE options บาง/ไม่พร้อม) — ลองรีเฟรช"); return
    pos = gx["total"] >= 0
    rcolor = "#38c172" if pos else "#e3506a"
    flip = gx.get("flip")
    flip_txt = f"{flip:,.4f}" if flip else "n/a"
    if flip:
        side = "เหนือ Flip → หน่วง" if gx["eur_price"] >= flip else "ใต้ Flip → เร่ง"
    else:
        side = "หา Flip ไม่เจอในกรอบ"
    C.hero_cards([
        ("Regime (Net GEX รวม)", ("🟢 Positive" if pos else "🔴 Negative"),
         f"{'หน่วง' if pos else 'เร่ง'}", rcolor),
        ("Gamma Flip (สเกล EUR)", flip_txt, side, "#e8c565"),
        ("Call / Put GEX Wall", f"{gx['call_wall']:,.4f} / {gx['put_wall']:,.4f}",
         "แนวต้าน / แนวรับ (สเกล EUR)", "#e8c565"),
    ])
    df = C.pd.DataFrame({
        "strike": [f"{k:,.4f}" for k in gx["strikes_eur"]],
        "GEX": [v / 1e3 for v in gx["net"]],
    })
    df["ฝั่ง"] = ["Call (บวก)" if v >= 0 else "Put (ลบ)" for v in df["GEX"]]
    chart = alt.Chart(df).mark_bar().encode(
        x=alt.X("strike:N", title="Strike (สเกล EUR)", sort=list(df["strike"])),
        y=alt.Y("GEX:Q", title="Net GEX (สัมพัทธ์)"),
        color=alt.Color("ฝั่ง:N", scale=alt.Scale(domain=["Call (บวก)", "Put (ลบ)"],
                        range=["#38c172", "#e3506a"]), legend=alt.Legend(title=None)),
        tooltip=["strike", alt.Tooltip("GEX:Q", format="+.2f")],
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)
    st.caption(f"งวด {gx['expiry']} • FXE spot {gx['fxe_spot']:,.2f} • ตัวคูณสเกล EUR ×{gx['mult']:.4f} • กรอบ ±20% • "
               "gamma จาก impliedVolatility ของ FXE (Black-Scholes) — ค่าประมาณจาก FXE proxy (บาง)")
    st.info("📝 เหนือ Gamma Flip มักหน่วง / ใต้ Flip มักเร่ง • FXE ลิควิดน้อยกว่า GLD/Deribit มาก — "
            "ความแม่นต่ำกว่า ใช้เป็นบริบทคร่าวๆ ไม่ใช่สัญญาณ")


def render_pinescript():
    st.header("📋 PineScript — เส้น + แจ้งเตือน บนกราฟ EUR (ข้อมูลจริง)")
    opt = fxe_snapshot()
    q = eur_quote()
    if not opt or not q:
        st.info("ยังไม่มีข้อมูล options ในรอบนี้ — ลองรีเฟรช"); return
    if opt["anomalous"]:
        st.warning("⚠️ ข้อมูล FXE options งวดนี้บาง/เพี้ยน — ยังเจนเส้นไม่ได้ (FXE ลิควิดน้อย ลองรีเฟรช)"); return
    mult = q["price"] / opt["spot"]
    dte = _dte_eur(opt["expiry"])
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M UTC")
    walls = [(opt["callWall"] * mult, "Call Wall", "color.red", "hline.style_dashed", 2),
             (opt["putWall"] * mult, "Put Wall", "color.green", "hline.style_dashed", 2)]
    if opt["maxPain"]:
        walls.append((opt["maxPain"] * mult, "Max Pain", "color.yellow", "hline.style_dotted", 2))
    gx = fxe_gex(0.20)
    if gx:
        walls.append((gx["call_wall"], "GEX Call Wall", "color.orange", "hline.style_solid", 1))
        walls.append((gx["put_wall"], "GEX Put Wall", "color.aqua", "hline.style_solid", 1))
        if gx.get("flip"):
            walls.append((gx["flip"], "Gamma Flip", "color.fuchsia", "hline.style_solid", 2))
    rh = eur_pivot_ref()
    piv = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None

    lines = ["//@version=5",
             'indicator("EUR Levels [EURUSD]", overlay=true)',
             f"// FXE options (Yahoo) แปลงสเกล EUR ×{mult:.4f} • งวด {opt['expiry']} • proxy • {stamp}", ""]
    for v, t, c, s, w in walls:
        title = f"{t} {v:.4f}" if t != "Max Pain" else f"{t} {v:.4f}"
        lines.append(f'plot({v:.4f}, "{title}", color={c}, linewidth={w})')
    lines.append("")
    alert_levels = [(t, v) for v, t, c, s, w in walls]
    if piv:
        lines.append('showPivots = input.bool(true, "แสดง Pivot รายวัน (เรดาร์โซน)")')
        for name, col in [("R2", "color.gray"), ("R1", "color.gray"), ("PP", "color.blue"),
                          ("S1", "color.gray"), ("S2", "color.gray")]:
            lines.append(f'plot(showPivots ? {piv[name]:.4f} : na, "Pivot {name}", '
                         f'color=color.new({col}, 10), linewidth=1)')
            alert_levels.append((f"Pivot {name}", piv[name]))
        lines.append("")
    lines.append("if barstate.islast")
    for v, t, c, s, w in walls:
        lt = f"{t} {v:.4f}"
        if t == "Max Pain" and dte is not None:
            lt = f"{t} {v:.4f} | {opt['expiry']} ({dte}d)"
        lines.append(f'    label.new(bar_index + 2, {v:.4f}, "{lt}", '
                     f'style=label.style_label_right, color=color.new({c}, 70), '
                     f'textcolor=color.white, size=size.small)')
    if piv:
        lines.append("    if showPivots")
        for name in ["R2", "R1", "PP", "S1", "S2"]:
            lines.append(f'        label.new(bar_index + 2, {piv[name]:.4f}, "Pivot {name} {piv[name]:.4f}", '
                         f'style=label.style_label_right, color=color.new(color.gray, 80), '
                         f'textcolor=color.white, size=size.tiny)')
    lines.append("")
    lines += C.pine_alerts(alert_levels)
    st.code("\n".join(lines), language="pine")
    st.caption(f"ค่าแปลงสเกล EUR แล้ว (×{mult:.4f}) พล็อตบนกราฟ EUR/USD • มีป้ายชื่อกำกับแต่ละเส้น • "
               "ตั้งเตือน: คลิกขวากราฟ → Add alert → เลือกอินดิเคเตอร์นี้ → 'Any alert() function call' → Create • "
               "ราคาขยับมากให้ก๊อปใหม่ (snapshot)")


def _safe(fn, label):
    try:
        fn()
    except Exception:
        st.warning(f"⚠️ ส่วน «{label}» ขัดข้องชั่วคราว (แหล่งข้อมูลอาจติด rate limit) — "
                   "ส่วนอื่นยังใช้ได้ เดี๋ยวรอบถัดไปจะกลับมาเอง")


@st.fragment(run_every=REFRESH_SECONDS)
def body():
    st.title("เลขาตลาด • EUR/USD")
    st.caption(f"อัปเดตล่าสุด {datetime.now().strftime('%H:%M:%S')} • โหมดดูอย่างเดียว • "
               "รีเฟรชอัตโนมัติทุก 30 นาที • ราคา Yahoo • options FXE (proxy)")
    _safe(render_confluence, "สรุป EUR")
    st.divider(); _safe(render_zone_radar, "เรดาร์โซน")
    st.divider(); _safe(render_macro, "มาโคร")
    st.divider(); _safe(render_pivots, "Pivot")
    st.divider(); _safe(render_options, "Options")
    st.divider(); _safe(render_gex, "GEX")
    st.divider(); _safe(render_pinescript, "PineScript")
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • FXE เป็น proxy ลิควิดน้อย • ไม่ใช่ราคาสดโบรกเกอร์ • ไม่ใช่คำแนะนำการลงทุน")


body()
