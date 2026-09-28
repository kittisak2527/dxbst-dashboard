"""🧩 Pine 3-in-1 — รวม BTC / ทอง / ยูโร เป็นอินดี้ตัวเดียว (สลับชุดค่าตามสัญลักษณ์เอง)

- กดปุ่ม = ล้างแคช options แล้วดึงใหม่ "จริง" ทั้ง 3 ตัว (ต่างจากรีเฟรชที่อาจได้ของในแคช)
- ตัวไหนดึงไม่มา -> ใช้ค่าดีล่าสุด (carry-forward) พร้อมบอกว่าเก่าแค่ไหน — BTC ไม่ต้องรอใคร
"""
import time
from datetime import datetime, timezone, timedelta

import streamlit as st

import common as C
import levels_store as S
import pine3 as P
import btc_page as B
import gold_page as G
import euro_page as E

TH = timezone(timedelta(hours=7))
NAMES = {"BTC": "₿ BTCUSD", "XAU": "🥇 ทองคำ", "EUR": "💶 EUR/USD"}
SRC = {"BTC": "Deribit", "XAU": "GLD/IAU→GC", "EUR": "FXE→EUR"}


def _now_ms():
    return int(time.time() * 1000)


def _fmt_ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=TH).strftime("%d/%m %H:%M")


def _age(ms):
    h = (time.time() * 1000 - ms) / 3_600_000
    return f"{h:.0f} ชม." if h < 48 else f"{h / 24:.1f} วัน"


YAHOO_FUT_DELAY_MS = 10 * 60 * 1000   # ราคา futures ของ Yahoo ดีเลย์ ~10 นาที


def _ref(price, delay_ms=0):
    """ราคาสินทรัพย์อ้างอิงที่ใช้สเกลเส้น + เวลาของราคานั้น → Pine ใช้หา basis ณ เวลาเดียวกัน"""
    if not price:
        return {"refPrice": None, "ref_ts_ms": 0}
    return {"refPrice": float(price), "ref_ts_ms": _now_ms() - delay_ms}


def _gex_part(gx, prev, mult=1.0):
    """GEX ใหม่ -> ใช้ • GEX พลาดแต่ walls มา -> ยืม GEX ชุดเก่า (บอกในหมายเหตุ)"""
    if gx:
        flip = gx.get("flip")
        return {"gexCall": gx["call_wall"] * mult, "gexPut": gx["put_wall"] * mult,
                "flip": flip * mult if flip else None,
                "gexSign": 1 if gx.get("total", 0) >= 0 else -1,
                "gex_ts_ms": _now_ms()}, ""
    if prev and prev.get("gex_ts_ms"):
        keep = {k: prev.get(k) for k in ("gexCall", "gexPut", "flip", "gexSign", "gex_ts_ms")}
        return keep, f"GEX ดึงไม่ได้ ใช้ชุดเก่าเมื่อ {_fmt_ts(prev['gex_ts_ms'])}"
    return {"gexCall": None, "gexPut": None, "flip": None, "gexSign": 0, "gex_ts_ms": None}, \
        "GEX ดึงไม่ได้ (ไม่มีโหมด)"


# ---------- ดึงสดต่อสินทรัพย์: คืน (snapshot | None, เหตุผล) ----------
def fetch_btc(prev):
    opt, gx = B.deribit_options(), B.deribit_gex(0.20)
    if not opt or opt.get("anomalous"):
        return None, "ดึง Deribit ไม่ได้ / ข้อมูลงวดนี้เพี้ยน"
    g, note = _gex_part(gx, prev)
    snap = {"ts_ms": _now_ms(), "source": "Deribit", "expiry": opt["expiry"],
            "dte": B._dte_deribit(opt["expiry"]),
            "callWall": opt["callWall"], "putWall": opt["putWall"], "maxPain": opt["maxPain"], **g}
    return snap, note


def fetch_gold(prev):
    """ลองทุกแหล่งใน G.GOLD_OPTION_SOURCES (GLD, IAU) • ผ่านเกณฑ์หลายแหล่ง -> เลือก OI รวมสูงสุด
    ไม่เฉลี่ย wall: wall คือ strike ที่ OI กองจริง ค่าเฉลี่ยของสอง strike คือราคาที่ไม่มี OI อยู่เลย"""
    good, fails = [], []
    for tk in G.GOLD_OPTION_SOURCES:
        opt = G.gld_snapshot(tk)
        if not opt:
            fails.append(f"{tk}: ดึงไม่ได้")
            continue
        if opt["anomalous"]:
            fails.append(f"{tk}: เพี้ยน ({opt.get('anom_reason') or 'ผิดรูป'})")
            continue
        am = G.gold_mult(tk)
        if not am:
            fails.append(f"{tk}: ไม่มีราคาปิดวันเดียวกันกับ GC")
            continue
        good.append((opt, am["mult"]))
    if not good:
        return None, " • ".join(fails) or "ดึง options ทองไม่ได้"
    good.sort(key=lambda x: x[0].get("total_oi", 0), reverse=True)
    opt, m = good[0]
    tk = opt["ticker"]
    notes = []
    if len(good) > 1:
        notes.append(f"เลือก {tk} (OI {opt['total_oi']:,.0f} > {good[1][0]['ticker']} {good[1][0]['total_oi']:,.0f})")
    elif fails:
        notes.append("สำรอง: " + " • ".join(fails))
    if opt.get("concentrated"):
        notes.append("OI กองที่ strike เดียว")
    # GEX: ใช้แหล่งเดียวกับ walls ก่อน คำนวณไม่ได้ค่อยลองแหล่งอื่น (ไม่เฉลี่ย เพราะ IV คนละกอง)
    gx = None
    for o, _ in good:
        gx = G.gld_gex(0.20, o["ticker"])
        if gx:
            if o["ticker"] != tk:
                notes.append(f"GEX จาก {o['ticker']}")
            break
    g, gnote = _gex_part(gx, prev)
    if gnote:
        notes.append(gnote)
    q = G.gold_quote(G.primary)                          # ราคา GC ที่ใช้สเกลเส้น (Yahoo GC=F)
    snap = {"ts_ms": _now_ms(), "source": f"{tk}→GC", "expiry": opt["expiry"],
            "dte": G._dte_gold(opt["expiry"]),
            "callWall": opt["callWall"] * m, "putWall": opt["putWall"] * m,
            "maxPain": opt["maxPain"] * m if opt["maxPain"] else None, **g,
            **_ref(q["price"] if q else None, YAHOO_FUT_DELAY_MS)}
    return snap, " • ".join(notes)


def fetch_eur(prev):
    opt = E.fxe_snapshot()
    if not opt:
        return None, "ดึง options FXE ไม่ได้ (Yahoo บล็อก/rate limit หรือตลาดปิด)"
    if opt["anomalous"]:
        return None, f"FXE เพี้ยน ({opt.get('anom_reason') or 'ผิดรูป'}) — FXE ลิควิดน้อย เป็นปกติ"
    am = E.eur_mult()
    if not am:
        return None, "หาตัวคูณ FXE→EUR ไม่ได้ (ไม่มีราคาปิดวันเดียวกัน)"
    m = am["mult"]
    g, note = _gex_part(E.fxe_gex(0.20), prev)          # fxe_gex คืนสเกล EUR มาแล้ว
    q = E.eur_quote()                                    # ราคา EUR spot ที่ใช้สเกลเส้น
    snap = {"ts_ms": _now_ms(), "source": "FXE→EUR", "expiry": opt["expiry"],
            "dte": E._dte_eur(opt["expiry"]),
            "callWall": opt["callWall"] * m, "putWall": opt["putWall"] * m,
            "maxPain": opt["maxPain"] * m if opt["maxPain"] else None, **g,
            **_ref(q["price"] if q else None)}
    return snap, note


FETCHERS = {"BTC": fetch_btc, "XAU": fetch_gold, "EUR": fetch_eur}


def force_clear_caches():
    """ปุ่ม = ดึงใหม่จริง: ล้างแคช options/ราคา + ลืมประวัติพลาด"""
    for fn in (B.deribit_options, B.deribit_gex, B.deribit_index,
               G._opt_expiries_raw, G._opt_chain_raw, E._opt_expiries_raw, E._opt_chain_raw,
               C._yf_daily_raw, C._yf_hourly_raw):
        try:
            fn.clear()
        except Exception:
            pass
    C.reset_failures()


def run_generate():
    force_clear_caches()
    snaps = S.load()
    result = {}
    for a in S.ASSETS:
        with st.spinner(f"กำลังดึง {NAMES[a]} …"):
            try:
                snap, note = FETCHERS[a](snaps.get(a))
            except Exception as ex:
                snap, note = None, f"ขัดข้อง: {type(ex).__name__}"
        if snap:
            snaps[a] = snap
            result[a] = ("fresh", note)
        elif snaps.get(a):
            result[a] = ("stale", note)
        else:
            result[a] = ("none", note)
    saved = S.save(snaps)
    st.session_state["pine3_result"] = {"at_ms": _now_ms(), "items": result, "saved": saved}


# ---------- การ์ดสถานะ ----------
def status_cards(snaps, result):
    items = []
    for a in S.ASSETS:
        snap = snaps.get(a)
        state, note = (result or {}).get(a, (None, ""))
        if state == "fresh":
            big, color = "✅ อัปเดตใหม่", "#38c172"
            sub = f"ดึงเมื่อ {_fmt_ts(snap['ts_ms'])}" + (f" • {note}" if note else "")
        elif state == "stale":
            big, color = "🟡 ใช้ค่าเก่า", "#e8c565"
            sub = f"ดึงเมื่อ {_fmt_ts(snap['ts_ms'])} ({_age(snap['ts_ms'])}) • {note}"
        elif state == "none":
            big, color = "⛔ ยังไม่มีข้อมูล", "#e3506a"
            sub = note or "ยังไม่เคยดึงสำเร็จ"
        elif snap:
            big, color = "📦 ค่าที่เก็บไว้", "#9fb0c8"
            sub = f"ดึงเมื่อ {_fmt_ts(snap['ts_ms'])} ({_age(snap['ts_ms'])}) • กดปุ่มเพื่อดึงใหม่"
        else:
            big, color = "— ว่าง", "#9fb0c8"
            sub = "กดปุ่มเพื่อดึงครั้งแรก"
        items.append((f"{NAMES[a]} · {SRC[a]}", big, sub, color))
    C.hero_cards(items)


def body():
    C.apply_theme()
    st.title("🧩 Pine 3-in-1 • BTC / ทอง / ยูโร")
    st.caption("ก็อปครั้งเดียว ใช้ได้ทุกชาร์ต — อินดี้เลือกชุดค่าตามสัญลักษณ์เอง • "
               "ตัวไหนดึงไม่มา ใช้ค่าดีล่าสุดพร้อมบอกอายุ (BTC ไม่ต้องรอใคร)")

    if st.button("⚡ ดึงข้อมูลใหม่ + เจนโค้ด", type="primary", use_container_width=True):
        run_generate()

    snaps = S.load()
    res = st.session_state.get("pine3_result")
    status_cards(snaps, res["items"] if res else None)

    if res:
        fresh = [NAMES[a] for a, (s, _) in res["items"].items() if s == "fresh"]
        stale = [NAMES[a] for a, (s, _) in res["items"].items() if s != "fresh"]
        msg = f"รอบ {_fmt_ts(res['at_ms'])}: อัปเดต {', '.join(fresh) or '—'}"
        if stale:
            msg += f" • ยังไม่มา {', '.join(stale)} (โค้ดใส่ค่าเก่า/ว่างไว้ให้แล้ว)"
        (st.success if not stale else st.warning)(msg)
        if not res.get("saved"):
            st.caption("⚠️ บันทึกค่าลงเซิร์ฟเวอร์ไม่ได้ — โค้ดรอบนี้ยังใช้ได้ แต่ครั้งหน้าอาจจำค่าเก่าไม่ได้")
    if datetime.now(TH).weekday() >= 5:
        st.info("📅 วันหยุดสุดสัปดาห์ — options ทอง/ยูโร (ตลาด US) ไม่อัปเดต ใช้ค่าวันศุกร์เป็นเรื่องปกติ")

    if not any(snaps.values()):
        st.info("ยังไม่มีข้อมูลเก็บไว้ — กดปุ่มด้านบนเพื่อดึงครั้งแรก"); return

    code = P.build_pine(snaps, _now_ms())
    st.code(code, language="javascript")
    st.download_button("⬇️ ดาวน์โหลด .pine", code, file_name="positioning_levels_3in1.pine",
                       mime="text/plain")
    st.caption("วางทับอินดี้ตัวเดิมใน Pine Editor → Save • ตาราง/สีบอกอายุข้อมูลต่อสินทรัพย์บนกราฟเอง "
               "(เทา=สด • เหลือง=เก่า • แดง=เก่ามาก) • โหมดหน่วง/เร่ง คำนวณสดจากราคาเทียบ Gamma Flip")

    with st.expander("🛟 กู้ค่าเก่าจากโค้ดที่เคยก็อป (กรณีแอปหลับ/รีบูตแล้วลืมค่า)"):
        st.caption("โค้ดทุกชุดมีบรรทัด `// SNAPSHOT_JSON:` ซ่อนค่าไว้ — วางโค้ดเก่าทั้งก้อน แล้วกดกู้ "
                   "(รับเฉพาะสินทรัพย์ที่ใหม่กว่าค่าที่เก็บอยู่)")
        old = st.text_area("วางโค้ด Pine เก่า", height=120, label_visibility="collapsed")
        if st.button("กู้ค่า"):
            got = S.parse_from_code(old)
            if not got:
                st.error("ไม่พบบรรทัด SNAPSHOT_JSON ในโค้ดนี้")
            else:
                S.save(S.merge_newer(S.load(), got))
                st.success("กู้แล้ว — " + ", ".join(NAMES[a] for a in S.ASSETS if got.get(a)))
                st.rerun()

    st.caption("⚠️ ค่าที่จำไว้เก็บในเซิร์ฟเวอร์ Streamlit — ถ้าแอปหลับ/รีบูตจะหาย ใช้ช่องกู้ด้านบนได้ • "
               "ข้อมูลเพื่อการศึกษา ไม่ใช่คำแนะนำการลงทุน")


body()
