from datetime import datetime, timezone

import streamlit as st
import yfinance as yf

import common as C

C.apply_theme()

# ====== ตั้งค่า (view-only) ======
PRIMARY = "GC"            # "GC" (Yahoo futures) หรือ "XAU" (Twelve Data spot; ต้องตั้ง Secrets)
REFRESH_SECONDS = 1800
GC_YF = "GC=F"
XAU_TD = "XAU/USD"
DXY_YF = "DX-Y.NYB"
OPTIONS_TICKER = "GLD"

td_key = C.resolve_td_key("")
primary = PRIMARY
if primary == "XAU" and not td_key:
    primary = "GC"


# ---------- ราคา/พีวอตทอง ----------
def gold_quote(ref):
    df = C.td_daily(XAU_TD, td_key) if ref == "XAU" else C.yf_daily(GC_YF)
    if df is None or len(df) < 2:
        return None
    closes = df["close"].tolist()
    price, prev = closes[-1], closes[-2]
    return {"price": price, "change_pct": (price - prev) / prev * 100 if prev else 0.0,
            "closes": closes[-10:], "df": df}


def gold_pivot_ref(ref):
    if ref == "XAU":
        df = C.td_daily(XAU_TD, td_key)
        if df is None or len(df) < 2:
            return None
        p = df.iloc[-2]
        if p["high"] > p["low"]:
            return {"high": float(p["high"]), "low": float(p["low"]), "close": float(p["close"]),
                    "how": "Classic Pivot • แท่งวันก่อน (Twelve Data / XAU)"}
        return None
    h = C.yf_hourly(GC_YF)
    if h is None or h.empty:
        return None
    h = h.copy(); h["d"] = C.pd.to_datetime(h["dt"]).dt.date
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


@st.cache_data(ttl=900, show_spinner=False)
def opt_expiries():
    return C.with_retry(lambda: list(yf.Ticker(OPTIONS_TICKER).options))


@st.cache_data(ttl=900, show_spinner=False)
def opt_chain(expiry):
    def _f():
        oc = yf.Ticker(OPTIONS_TICKER).option_chain(expiry)
        c = oc.calls[["strike", "openInterest"]].copy()
        p = oc.puts[["strike", "openInterest"]].copy()
        for d in (c, p):
            d["openInterest"] = d["openInterest"].fillna(0)
        return c, p
    return C.with_retry(_f)


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


def gld_snapshot():
    """คืน dict ตัวเลข options GLD (งวดรายเดือน) + ธงเพี้ยน"""
    try:
        exps = opt_expiries()
        me = pick_monthly(exps)
        gdf = C.yf_daily(OPTIONS_TICKER)
        spot = float(gdf["close"].iloc[-1]) if gdf is not None and len(gdf) else None
        if not me or spot is None:
            return None
        calls, puts = opt_chain(me)
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
        anom = (totc + totp) < 1000 or pcr > 3 or (0 < pcr < 0.2) or (mp is not None and cw == pw == mp)
        return {"expiry": me, "spot": spot, "pcr": pcr, "callWall": cw,
                "putWall": pw, "maxPain": mp, "anomalous": anom}
    except Exception:
        return None


def gold_confluence():
    q = gold_quote(primary)
    if not q:
        return None
    price, mom = q["price"], q["change_pct"]
    rh = gold_pivot_ref(primary)
    daily = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = C.swing_range(q["closes"])
    pp_daily = daily["PP"] if daily else rng["PP"]
    mid = rng["PP"]

    dxy = C.yf_daily(DXY_YF)
    dxy_chg = None
    if dxy is not None and len(dxy) >= 2:
        cc = dxy["close"].tolist(); dxy_chg = (cc[-1] - cc[-2]) / cc[-2] * 100 if cc[-2] else 0.0
    tips = C.fred_latest("DFII10")
    opt = gld_snapshot()

    sig, detail = [], []
    def add(name, v, d): sig.append(v); detail.append({"name": name, "v": v, "detail": d})

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
    if not tips:
        add("Real Yield (TIPS)", 0, "n/a")
    elif tips["change_pp"] >= 0.01:
        add("Real Yield (TIPS)", -1, f"{tips['change_pp']:+.2f} pp → กดทอง")
    elif tips["change_pp"] <= -0.01:
        add("Real Yield (TIPS)", 1, f"{tips['change_pp']:+.2f} pp → หนุนทอง")
    else:
        add("Real Yield (TIPS)", 0, "ทรงตัว")
    if mom > 0.1:
        add("โมเมนตัมวันนี้", 1, f"{mom:+.2f}%")
    elif mom < -0.1:
        add("โมเมนตัมวันนี้", -1, f"{mom:+.2f}%")
    else:
        add("โมเมนตัมวันนี้", 0, f"{mom:+.2f}%")
    if opt and not opt["anomalous"] and opt["maxPain"] and opt["spot"]:
        mp, sp = opt["maxPain"], opt["spot"]
        if sp < mp * 0.995:
            add("Options (Max Pain)", 1, f"GLD {sp:.2f} < MaxPain {mp:.0f} → แรงดึงขึ้น")
        elif sp > mp * 1.005:
            add("Options (Max Pain)", -1, f"GLD {sp:.2f} > MaxPain {mp:.0f} → แรงดึงลง")
        else:
            add("Options (Max Pain)", 0, f"GLD ใกล้ MaxPain {mp:.0f}")
    else:
        add("Options (Max Pain)", 0, "n/a")

    near = bool(daily and any(v and abs(price - v) / price < 0.003 for v in daily.values()))
    g = C.grade_from_votes(sig, mom, near)
    g.update({"detail": detail, "price": price})
    return g


# ---------- render ----------
def render_confluence():
    st.header("🥇 สรุปทองคำ (Gold Confluence)")
    g = gold_confluence()
    if not g:
        st.warning("ยังประเมินทองไม่ได้ในรอบนี้"); return
    bmap = {"Bullish": ("🟢", "#38c172"), "Bearish": ("🔴", "#e3506a"), "Neutral": ("⚪", "#9fb0c8")}
    bi, bc = bmap[g["bias"]]
    gcolor = "#38c172" if g["grade"] <= 2 else "#e8c565" if g["grade"] == 3 else "#e3506a"
    glabel = {1: "ต่ำมาก", 2: "ต่ำ", 3: "ปานกลาง", 4: "สูง", 5: "สูงมาก"}[g["grade"]]
    C.hero_cards([
        (f"ทิศทาง (อ้างอิง {primary})", f"{bi} {g['bias']}", f"คะแนนรวม {g['net']:+d}", bc),
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
    st.header("📍 เรดาร์โซน — ราคาทองอยู่ใกล้แนวไหน")
    q = gold_quote(primary)
    if not q:
        st.info("ยังดึงราคาทองไม่ได้ในรอบนี้"); return
    price = q["price"]
    levels = []
    rh = gold_pivot_ref(primary)
    if rh:
        dp = C.classic_pivot(rh["high"], rh["low"], rh["close"])
        nm = {"R3": "Pivot R3", "R2": "Pivot R2", "R1": "Pivot R1", "PP": "Pivot กลาง",
              "S1": "Pivot S1", "S2": "Pivot S2", "S3": "Pivot S3"}
        for k, v in dp.items():
            levels.append({"name": nm[k], "v": v})
    opt = gld_snapshot()
    if opt and not opt["anomalous"] and opt["spot"]:
        mult = price / opt["spot"]
        levels.append({"name": "Call Wall", "v": opt["callWall"] * mult})
        levels.append({"name": "Put Wall", "v": opt["putWall"] * mult})
        if opt["maxPain"]:
            levels.append({"name": "Max Pain", "v": opt["maxPain"] * mult})
    above = sorted([x for x in levels if x["v"] > price], key=lambda x: x["v"])
    below = sorted([x for x in levels if x["v"] < price], key=lambda x: -x["v"])
    c1, c2, c3 = st.columns(3)
    c1.metric(f"ราคาทอง ({primary})", f"{price:,.2f}")
    if above:
        c2.metric("แนวต้านใกล้สุด ↑", f"{above[0]['v']:,.2f}",
                  f"{(above[0]['v']-price)/price*100:+.2f}% • {above[0]['name']}")
    else:
        c2.metric("แนวต้านใกล้สุด ↑", "-")
    if below:
        c3.metric("แนวรับใกล้สุด ↓", f"{below[0]['v']:,.2f}",
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
    st.caption("แตะโซนให้ 'รอสัญญาณยืนยัน' ไม่เดาล่วงหน้า • เพิ่มความน่าจะเป็น ไม่ใช่การทำนาย • วาง SL ทุกไม้")


def render_compare():
    st.header("⚖️ GC (Futures) vs XAU (Spot) + Basis")
    gc = gold_quote("GC"); xau = gold_quote("XAU")
    rows = []
    rows.append(["GC (Futures)", f"{gc['price']:,.2f}" if gc else "n/a",
                 f"{gc['change_pct']:+.2f}%" if gc else "-", "Yahoo"])
    rows.append(["XAU (Spot)", f"{xau['price']:,.2f}" if xau else "n/a (ต้องมี TD key)",
                 f"{xau['change_pct']:+.2f}%" if xau else "-", "Twelve Data"])
    if gc and xau:
        basis = gc["price"] - xau["price"]
        rows.append(["Basis (GC − XAU)", f"{basis:+,.2f}",
                     f"{basis/xau['price']*100:+.2f}%" if xau["price"] else "-", ""])
    st.table(C.pd.DataFrame(rows, columns=["รายการ", "ราคา", "% วันนี้", "แหล่ง"]))
    st.caption("Basis = GC (futures) − XAU (spot) • ปกติ futures สูงกว่า spot เล็กน้อย • ต่างหลักสิบจุดเป็นเรื่องปกติ")


def render_macro():
    st.header("🌍 ปัจจัยมาโครที่มีผลต่อทอง")
    dxy = C.yf_daily(DXY_YF)
    yld = C.fred_latest("DGS10"); tips = C.fred_latest("DFII10")
    cols = st.columns(3)
    if dxy is not None and len(dxy) >= 2:
        cc = dxy["close"].tolist()
        cols[0].metric("DXY (ดอลลาร์)", f"{cc[-1]:,.2f}", f"{(cc[-1]-cc[-2])/cc[-2]*100:+.2f}%")
    else:
        cols[0].metric("DXY (ดอลลาร์)", "n/a", "")
    cols[1].metric("US 10Y Yield", f"{yld['value']:.2f}%" if yld else "n/a",
                   f"{yld['change_pp']:+.2f} pp" if yld else "")
    cols[2].metric("US 10Y Real (TIPS)", f"{tips['value']:.2f}%" if tips else "n/a",
                   f"{tips['change_pp']:+.2f} pp" if tips else "")
    st.caption("ดอลลาร์แข็ง / real yield ขึ้น → มักกดทอง (และกลับกัน)")


def render_pivots():
    st.header(f"🎯 แนวรับ/แนวต้าน (Pivot) — {primary}")
    q = gold_quote(primary)
    if not q:
        st.warning(f"ดึง {primary} ไม่ได้ (XAU ต้องมี TD key)"); return
    rh = gold_pivot_ref(primary)
    daily = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None
    rng = C.swing_range(q["closes"])
    bias = daily["PP"] if daily else rng["PP"]
    badge = "🟢 Bullish" if q["price"] > bias else "🔴 Bearish"
    st.markdown(f"### {primary} — {badge}")
    st.caption(f"ราคาล่าสุด {q['price']:,.2f} ({q['change_pct']:+.2f}%)")
    cA, cB = st.columns(2)
    with cA:
        st.markdown("**📍 Pivot รายวัน (Day Trade)**")
        if daily:
            st.table(C.level_df(daily)); st.caption(rh["how"])
        else:
            st.info("ดึง H/L รายวันไม่ได้ — ใช้กรอบ 10 วันทางขวา")
    with cB:
        st.markdown("**🗺️ กรอบ 10 วัน (Swing)**")
        st.table(C.level_df(rng)); st.caption("จากกรอบราคาปิด 10 วัน")


def _dte_gold(exp):
    try:
        d = datetime.strptime(exp, "%Y-%m-%d")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return max(0, (d - now).days)
    except Exception:
        return None


def render_options():
    st.header("🧊 Options OI — GLD (สรุป)")
    opt = gld_snapshot()
    if not opt:
        st.warning("ดึง option chain ไม่ได้ (อาจติด rate limit) — ลองรีเฟรช"); return
    dte = _dte_gold(opt["expiry"])
    dte_txt = f" • เหลือ {dte} วันถึงหมดอายุ" if dte is not None else ""
    st.caption(f"งวด (รายเดือน): {opt['expiry']}{dte_txt}")
    r = st.columns(5)
    r[0].metric("Spot GLD", f"{opt['spot']:,.2f}")
    r[1].metric("PCR", f"{opt['pcr']:.2f}")
    r[2].metric("Call Wall", f"{opt['callWall']:,.0f}")
    r[3].metric("Put Wall", f"{opt['putWall']:,.0f}")
    r[4].metric("Max Pain", f"{opt['maxPain']:,.0f}" if opt["maxPain"] else "n/a",
                f"เหลือ {dte} วัน" if dte is not None else None, delta_color="off")
    st.caption("Call Wall = แนวต้าน • Put Wall = แนวรับ • PCR>1 = put มากกว่า call • กรอบ ±20%")
    if opt["anomalous"]:
        st.warning("⚠️ ข้อมูล Options งวดนี้อาจเพี้ยน — ข้ามการแปลงสเกลทอง (ลองรีเฟรช)")
        return
    q = gold_quote(primary)
    if q:
        mult = q["price"] / opt["spot"]
        st.markdown(f"**🪙 แปลงเป็นสเกลทอง ({primary}) • ตัวคูณ ×{mult:.2f}**")
        r2 = st.columns(4)
        r2[0].metric("ทองอ้างอิง", f"{q['price']:,.2f}")
        r2[1].metric("Call Wall → ทอง", f"{opt['callWall']*mult:,.0f}")
        r2[2].metric("Put Wall → ทอง", f"{opt['putWall']*mult:,.0f}")
        r2[3].metric("Max Pain → ทอง", f"{opt['maxPain']*mult:,.0f}" if opt["maxPain"] else "n/a")
        st.caption("แปลงจาก strike GLD × (ราคาทอง ÷ ราคา GLD) • เป็นค่าประมาณ ใช้เป็นโซนอ้างอิง")


def render_pinescript():
    st.header("📋 PineScript — เส้น + แจ้งเตือน บนกราฟทอง (ข้อมูลจริง)")
    opt = gld_snapshot()
    q = gold_quote(primary)
    if not opt or not q:
        st.info("ยังไม่มีข้อมูล options ในรอบนี้ — ลองรีเฟรช"); return
    if opt["anomalous"]:
        st.warning("⚠️ ข้อมูล Options งวดนี้เพี้ยน — ยังเจนเส้นไม่ได้ (รอค่ากระจายปกติแล้วลองใหม่)"); return
    mult = q["price"] / opt["spot"]
    dte = _dte_gold(opt["expiry"])
    stamp = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M UTC")
    walls = [(opt["callWall"] * mult, "Call Wall", "color.red", "hline.style_dashed", 2),
             (opt["putWall"] * mult, "Put Wall", "color.green", "hline.style_dashed", 2)]
    if opt["maxPain"]:
        walls.append((opt["maxPain"] * mult, "Max Pain", "color.yellow", "hline.style_dotted", 2))
    rh = gold_pivot_ref(primary)
    piv = C.classic_pivot(rh["high"], rh["low"], rh["close"]) if rh else None

    lines = ["//@version=5",
             f'indicator("Gold Levels [{primary}]", overlay=true)',
             f"// GLD options (Yahoo) แปลงสเกลทอง ×{mult:.2f} • งวด {opt['expiry']} • proxy • {stamp}", ""]
    for v, t, c, s, w in walls:
        title = f"{t} {opt['expiry']} ({dte}d)" if t == "Max Pain" and dte is not None else t
        lines.append(f'plot({v:.0f}, "{title}", color={c}, linewidth={w})')
    lines.append("")
    alert_levels = [(t, v) for v, t, c, s, w in walls]
    if piv:
        lines.append('showPivots = input.bool(true, "แสดง Pivot รายวัน (เรดาร์โซน)")')
        for name, col in [("R2", "color.gray"), ("R1", "color.gray"), ("PP", "color.blue"),
                          ("S1", "color.gray"), ("S2", "color.gray")]:
            lines.append(f'plot(showPivots ? {piv[name]:.0f} : na, "Pivot {name}", '
                         f'color=color.new({col}, 10), linewidth=1)')
            alert_levels.append((f"Pivot {name}", piv[name]))
        lines.append("")
    lines += C.pine_alerts(alert_levels)
    st.code("\n".join(lines), language="pine")
    st.caption(f"ค่าแปลงสเกลทองแล้ว (×{mult:.2f}) พล็อตบนกราฟ {primary} • ชื่อเส้นดูที่ legend (มุมซ้ายบน) "
               "ค่าโชว์เป็นแท็บสีที่ scale ขวา • ตั้งเตือน: คลิกขวากราฟ → Add alert → "
               "เลือกอินดิเคเตอร์นี้ → 'Any alert() function call' → Create • ราคาขยับมากให้ก๊อปใหม่ (snapshot)")


def _safe(fn, label):
    try:
        fn()
    except Exception:
        st.warning(f"⚠️ ส่วน «{label}» ขัดข้องชั่วคราว (แหล่งข้อมูลอาจติด rate limit) — "
                   "ส่วนอื่นยังใช้ได้ เดี๋ยวรอบถัดไปจะกลับมาเอง")


@st.fragment(run_every=REFRESH_SECONDS)
def body():
    st.title("เลขาตลาด • ทองคำ (Gold Focus)")
    st.caption(f"อัปเดตล่าสุด {datetime.now().strftime('%H:%M:%S')} • โหมดดูอย่างเดียว • "
               f"รีเฟรชอัตโนมัติทุก 30 นาที • อ้างอิง {primary}")
    _safe(render_confluence, "สรุปทองคำ")
    st.divider(); _safe(render_zone_radar, "เรดาร์โซน")
    st.divider(); _safe(render_compare, "GC vs XAU")
    st.divider(); _safe(render_macro, "มาโคร")
    st.divider(); _safe(render_pivots, "Pivot")
    st.divider(); _safe(render_options, "Options")
    st.divider(); _safe(render_pinescript, "PineScript")
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • เป็นข้อมูลดีเลย์ ไม่ใช่ราคาสดของโบรกเกอร์ • ไม่ใช่คำแนะนำการลงทุน")


body()
