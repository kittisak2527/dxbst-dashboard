# -*- coding: utf-8 -*-
# =============================================================
# gold_fund_page.py  —  หน้า "พื้นฐานทองคำ" (Fundamental)
# แสดง 4 องค์ประกอบ: สรุป Bias / แผงมาโคร / ข่าว+sentiment / ปฏิทินเศรษฐกิจ
# เรียกใช้ common (ธีม/การ์ด) + fundamental_common (ข้อมูล)
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


# ---------- 1) สรุป Bias (หัวเรื่อง) ----------
def render_bias(data):
    st.header("🧭 ทิศทางพื้นฐานทองคำ (Fundamental Bias)")
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
    st.caption("Bias มาจากการโหวตของแต่ละปัจจัยรวมกัน — เป็น 'บริบทพื้นฐาน' ไว้จับทิศลม "
               "ไม่ใช่สัญญาณเข้า/ออกระยะสั้น (นั่นคือหน้าที่ของสาย Technical)")


# ---------- 2) แผงมาโคร ----------
def render_macro(data):
    st.header("📊 แผงมาโคร (ตัวขับเคลื่อนทองคำ)")
    real, dxy, be, ff = data["real"], data["dxy"], data["be"], data["ff"]
    if not any([real, dxy, be, ff]):
        st.info("ยังดึงมาโครไม่ได้ — ต้องตั้ง FRED_API_KEY ใน Streamlit Secrets ก่อน "
                "(ที่มา: FRED / ธนาคารกลางสหรัฐฯ)")
        return
    c = st.columns(4)
    if real:
        c[0].metric("Real Yield 10Y (TIPS)", f"{real['value']:.2f}%",
                    f"{real['change']:+.2f}", delta_color="off")
    if dxy:
        c[1].metric("ดัชนีดอลลาร์ (broad)", f"{dxy['value']:.2f}",
                    f"{dxy['change']:+.2f}", delta_color="off")
    if be:
        c[2].metric("Breakeven Inflation 10Y", f"{be['value']:.2f}%",
                    f"{be['change']:+.2f}", delta_color="off")
    if ff:
        c[3].metric("Fed Funds (effective)", f"{ff['value']:.2f}%",
                    f"{ff['change']:+.2f}", delta_color="off")
    st.caption("🔑 กติกาทองคำ: Real Yield ลง = บวกต่อทอง (ต้นทุนถือทองต่ำลง) • ดอลลาร์อ่อน = บวก • "
               "เงินเฟ้อคาดการณ์ขึ้น = บวก (ทองเป็นสินทรัพย์กันเงินเฟ้อ)")


# ---------- 3) ข่าว + sentiment ----------
def render_news(data):
    st.header("📰 ข่าว + ทิศทาง (Sentiment)")
    news = data["news"]
    if news is None:
        st.info("ยังดึงข่าวไม่ได้ — ต้องตั้ง ALPHAVANTAGE_API_KEY ใน Secrets "
                "(หรืออาจใช้โควตาครบ 25 ครั้ง/วันแล้ว เดี๋ยวรีเซ็ตพรุ่งนี้)")
        return
    if not news:
        st.info("รอบนี้ยังไม่มีข่าวเข้ามา — ลองรีเฟรชอีกครั้ง")
        return
    avg = data.get("news_avg")
    if avg is not None:
        tone = "🟢 เอียงบวก" if avg >= 0.15 else ("🔴 เอียงลบ" if avg <= -0.15 else "⚪ เป็นกลาง")
        st.caption(f"อารมณ์ข่าวรวม: {tone} (คะแนนเฉลี่ย {avg:+.2f})")
    for a in news[:8]:
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
    st.header("🗓️ ปฏิทินเศรษฐกิจ (USD • สัปดาห์นี้)")
    cal = data["calendar"]
    if cal is None:
        st.info("ยังดึงปฏิทินไม่ได้ — ลองรีเฟรชอีกครั้ง (ที่มา: Forex Factory)")
        return
    upcoming = [e for e in cal if e["datetime"] and
                F.countdown_str(e["datetime"]) != "ผ่านไปแล้ว"]
    if not upcoming:
        st.info("สัปดาห์นี้ไม่มี event ระดับกลาง–สูงของ USD ที่ยังไม่เกิด")
        return
    rows = []
    for e in upcoming[:12]:
        imp = {"High": "🔴 สูง", "Medium": "🟠 กลาง"}.get(e["impact"], e["impact"])
        rows.append({
            "เวลา (เหลือ)": F.countdown_str(e["datetime"]),
            "Event": e["title"],
            "แรง": imp,
            "คาด": e["forecast"] or "—",
            "ครั้งก่อน": e["previous"] or "—",
        })
    st.table(C.pd.DataFrame(rows))
    st.caption("event สีแดง (FOMC/CPI/NFP) มักทำให้ทองผันผวนแรง — เลี่ยงเปิดสถานะใหม่ช่วงก่อน/หลังประกาศ")


# ---------- page-level safe wrapper (ล้อของสาย technical) ----------
def _safe(fn, data, label):
    try:
        fn(data)
    except Exception:
        st.warning(f"⚠️ ส่วน «{label}» ขัดข้องชั่วคราว — ส่วนอื่นยังใช้ได้ เดี๋ยวรอบถัดไปกลับมาเอง")


@st.fragment(run_every=REFRESH_SECONDS)
def body():
    st.title("พื้นฐานทองคำ • Gold Fundamental")
    st.caption(f"อัปเดต {datetime.now().strftime('%H:%M:%S')} • สรุปข่าว + มาโคร + ทิศทางพื้นฐาน • "
               "รีเฟรชอัตโนมัติทุก 30 นาที")

    if not F.FRED_KEY or not F.AV_KEY:
        miss = []
        if not F.FRED_KEY:
            miss.append("FRED_API_KEY (มาโคร)")
        if not F.AV_KEY:
            miss.append("ALPHAVANTAGE_API_KEY (ข่าว)")
        st.info("ℹ️ ยังไม่ได้ตั้ง key: " + " • ".join(miss) +
                " — ส่วนที่ไม่ต้องใช้ key (ปฏิทินเศรษฐกิจ) ยังทำงานปกติ "
                "ตั้ง key ได้ที่ Streamlit → Settings → Secrets")

    data = F.gold_fundamental()
    _safe(render_bias, data, "สรุป Bias")
    st.divider(); _safe(render_macro, data, "แผงมาโคร")
    st.divider(); _safe(render_news, data, "ข่าว")
    st.divider(); _safe(render_calendar, data, "ปฏิทินเศรษฐกิจ")
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • เป็นบริบทพื้นฐาน ไม่ใช่คำแนะนำการลงทุน • "
               "ใช้คู่กับสาย Technical เพื่อจับทั้ง 'ทิศลม' และ 'จังหวะ'")


body()
