# -*- coding: utf-8 -*-
# =============================================================
# btc_fund_page.py  —  หน้า "พื้นฐาน BTC" (Fundamental)
# โครงเดียวกับ gold_fund_page แต่ปัจจัยเป็นสาย risk-on:
#   DXY / Real Yield / Fear & Greed / BTC Dominance + ข่าวคริปโต
# =============================================================
from datetime import datetime

import streamlit as st

import common as C
import fundamental_common as F

C.apply_theme()

REFRESH_SECONDS = 1800
GREEN, RED, GOLD, MUTE = "#38c172", "#e3506a", "#e8c565", "#9fb0c8"


def _bias_color(net):
    return GREEN if net > 0 else (RED if net < 0 else GOLD)


# ---------- 1) สรุป Bias ----------
def render_bias(data):
    st.header("🧭 ทิศทางพื้นฐาน BTC (Fundamental Bias)")
    bias = data["bias"]
    net = bias["net"]
    n = len(bias["votes"])
    C.hero_cards([
        ("ทิศทางรวม", f"{bias['emoji']} {bias['label']}", f"จากปัจจัย {n} ตัว", _bias_color(net)),
        ("คะแนน Bias (0–100)", f"{bias['score']}", "50 = เป็นกลาง", _bias_color(net)),
        ("โหวตสุทธิ", f"{net:+d}", "บวก = หนุนขึ้น • ลบ = กดลง", _bias_color(net)),
    ])
    if not bias["votes"]:
        st.warning("ยังไม่มีปัจจัยให้คำนวณ — ตรวจว่าตั้ง FRED_API_KEY / ALPHAVANTAGE_API_KEY "
                   "ใน Streamlit Secrets แล้วหรือยัง")
        return
    rows = []
    for v in bias["votes"]:
        sig = "🟢 หนุน" if v["vote"] > 0 else ("🔴 กด" if v["vote"] < 0 else "⚪ กลาง")
        rows.append({"ปัจจัย": v["name"], "สัญญาณ": sig, "รายละเอียด": v["detail"]})
    st.table(C.pd.DataFrame(rows))
    st.caption("BTC เป็นสินทรัพย์เสี่ยง (risk-on) — ดอลลาร์อ่อน/ดอกเบี้ยลด/ตลาดโลภ = หนุน • "
               "เป็นบริบทพื้นฐาน ไม่ใช่สัญญาณเข้า/ออก (นั่นคือหน้าที่ของสาย Technical)")


# ---------- 2) แผงมาโคร ----------
def render_macro(data):
    st.header("📊 แผงมาโคร (ตัวขับเคลื่อน BTC)")
    dxy, real, fg, dom = data["dxy"], data["real"], data["fg"], data["dom"]
    if not any([dxy, real, fg, dom]):
        st.info("ยังดึงมาโครไม่ได้ — ตรวจ FRED_API_KEY ใน Secrets (Fear & Greed / Dominance ไม่ต้องใช้ key)")
        return
    c = st.columns(4)
    if dxy:
        c[0].metric("ดัชนีดอลลาร์ (DXY)", f"{dxy['value']:.2f}",
                    f"{dxy['change']:+.2f}", delta_color="off")
    if real:
        c[1].metric("Real Yield 10Y", f"{real['value']:.2f}%",
                    f"{real['change']:+.2f}", delta_color="off")
    if fg:
        c[2].metric("Fear & Greed", f"{fg['value']} · {fg['class']}",
                    f"{fg['value'] - fg['prev']:+d}", delta_color="off")
    if dom:
        c[3].metric("BTC Dominance", f"{dom['dominance']:.1f}%")
    st.caption("🔑 กติกา BTC: ดอลลาร์อ่อน = risk-on = บวก • ดอกเบี้ยจริงลด = บวก • "
               "Fear & Greed >55 (โลภ) = โมเมนตัมบวก, <45 (กลัว) = ลบ • Dominance สูง = เงินไหลเข้า BTC มากกว่า alt")


# ---------- 3) ข่าว + sentiment ----------
def render_news(data):
    st.header("📰 ข่าวคริปโต + ทิศทาง (Sentiment)")
    news = data["news"] or {}
    items = news.get("items", [])
    note = news.get("note")
    if not items:
        st.info(f"ยังไม่มีข่าวในรอบนี้ — เหตุผลจาก Alpha Vantage: {note}"
                if note else "รอบนี้ยังไม่มีข่าว — ลองรีเฟรชอีกครั้ง")
        return
    avg = data.get("news_avg")
    if avg is not None:
        tone = "🟢 เอียงบวก" if avg >= 0.15 else ("🔴 เอียงลบ" if avg <= -0.15 else "⚪ เป็นกลาง")
        st.caption(f"อารมณ์ข่าวรวม: {tone} (คะแนนเฉลี่ย {avg:+.2f})")
    for a in items[:8]:
        lab = a["label"]
        dot = "🟢" if "Bull" in lab else ("🔴" if "Bear" in lab else "⚪")
        t = F.fmt_news_time(a["time"])
        title = a["title"] or "(ไม่มีหัวข้อ)"
        link = f"[{title}]({a['url']})" if a["url"] else title
        st.markdown(f"{dot} **{link}**  \n"
                    f"<span style='color:{MUTE};font-size:.82rem;'>{a['source']} • {t} • "
                    f"sentiment {a['score']:+.2f} ({lab})</span>", unsafe_allow_html=True)
    st.caption("คะแนน sentiment จาก Alpha Vantage (NLP วิเคราะห์ข่าว) • + = โทนบวก, − = โทนลบ")


# ---------- 4) ปฏิทินเศรษฐกิจ ----------
def render_calendar(data):
    st.header("🗓️ ปฏิทินเศรษฐกิจ (USD • มีผลต่อ BTC ผ่าน risk sentiment)")
    cal = data["calendar"]
    if cal is None:
        st.info("ยังดึงปฏิทินไม่ได้ (feed ไม่ตอบ) — ลองรีเฟรชอีกครั้ง (ที่มา: Forex Factory)")
        return
    if not cal:
        st.info("feed โหลดได้ แต่ยังไม่มี event USD ระดับกลาง–สูงในกรอบเวลานี้")
        return
    upcoming = [e for e in cal if F.countdown_str(e["datetime"]) != "ผ่านไปแล้ว"]
    show = upcoming if upcoming else cal[-6:]
    if not upcoming:
        st.caption(f"ยังไม่มี event ล่วงหน้าในกรอบนี้ — แสดง {len(show)} รายการล่าสุดที่ผ่านมาแทน "
                   f"(feed มีทั้งหมด {len(cal)} รายการ)")
    rows = []
    for e in show[:12]:
        imp = {"High": "🔴 สูง", "Medium": "🟠 กลาง"}.get(e["impact"], e["impact"])
        cd = F.countdown_str(e["datetime"])
        rows.append({
            "เวลา": cd if cd != "ผ่านไปแล้ว" else e["datetime"].strftime("%d/%m %H:%M"),
            "Event": e["title"],
            "แรง": imp,
            "คาด": e["forecast"] or "—",
            "ครั้งก่อน": e["previous"] or "—",
        })
    st.table(C.pd.DataFrame(rows))
    st.caption("FOMC/CPI แรงๆ ทำตลาด risk ผันผวน กระทบ BTC โดยตรง — เลี่ยงเปิดสถานะช่วงก่อน/หลังประกาศ")


# ---------- page-level safe wrapper ----------
def _safe(fn, data, label):
    try:
        fn(data)
    except Exception:
        st.warning(f"⚠️ ส่วน «{label}» ขัดข้องชั่วคราว — ส่วนอื่นยังใช้ได้ เดี๋ยวรอบถัดไปกลับมาเอง")


@st.fragment(run_every=REFRESH_SECONDS)
def body():
    st.title("พื้นฐาน BTC • Bitcoin Fundamental")
    st.caption(f"อัปเดต {datetime.now().strftime('%H:%M:%S')} • สรุปข่าว + มาโคร + ทิศทางพื้นฐาน • "
               "รีเฟรชอัตโนมัติทุก 30 นาที")

    if not F.FRED_KEY or not F.AV_KEY:
        miss = []
        if not F.FRED_KEY:
            miss.append("FRED_API_KEY (มาโคร)")
        if not F.AV_KEY:
            miss.append("ALPHAVANTAGE_API_KEY (ข่าว)")
        st.info("ℹ️ ยังไม่ได้ตั้ง key: " + " • ".join(miss) +
                " — ส่วนที่ไม่ต้องใช้ key (Fear & Greed / Dominance / ปฏิทิน) ยังทำงานปกติ")

    data = F.btc_fundamental()
    _safe(render_bias, data, "สรุป Bias")
    st.divider(); _safe(render_macro, data, "แผงมาโคร")
    st.divider(); _safe(render_news, data, "ข่าว")
    st.divider(); _safe(render_calendar, data, "ปฏิทินเศรษฐกิจ")
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • เป็นบริบทพื้นฐาน ไม่ใช่คำแนะนำการลงทุน • "
               "ใช้คู่กับสาย Technical เพื่อจับทั้ง 'ทิศลม' และ 'จังหวะ'")


body()
