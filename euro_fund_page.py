# -*- coding: utf-8 -*-
# =============================================================
# euro_fund_page.py  —  หน้า "พื้นฐาน EUR/USD" (Fundamental)
# โครงเดียวกับ gold/btc แต่แกนหลักคือ "ส่วนต่างดอกเบี้ย Fed vs ECB"
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
    st.header("🧭 ทิศทางพื้นฐาน EUR/USD (Fundamental Bias)")
    bias = data["bias"]
    net = bias["net"]
    C.hero_cards([
        ("ทิศทางรวม", f"{bias['emoji']} {bias['label']}", f"จากปัจจัย {len(bias['votes'])} ตัว", _bias_color(net)),
        ("คะแนน Bias (0–100)", f"{bias['score']}", "50 = เป็นกลาง", _bias_color(net)),
        ("โหวตสุทธิ", f"{net:+d}", "บวก = หนุน EUR • ลบ = กด EUR", _bias_color(net)),
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
    st.caption("⚠️ อ่านอย่างเข้าใจ: EUR มีน้ำหนักราว 57% ในตะกร้า DXY — แถว DXY จึงเป็น "
               "'เงาสะท้อน' ของ EUR/USD มากกว่าตัวขับเคลื่อนอิสระ • ตัวที่บอกอะไรใหม่จริง ๆ คือ "
               "**ส่วนต่างดอกเบี้ย Fed − ECB** • เป็นบริบทพื้นฐาน ไม่ใช่สัญญาณเข้า/ออก")


# ---------- 2) แผงมาโคร ----------
def render_macro(data):
    st.header("📊 แผงมาโคร (ตัวขับเคลื่อน EUR/USD)")
    ff, ecb, diff, dxy, real = data["ff"], data["ecb"], data["diff"], data["dxy"], data["real"]
    if not any([ff, ecb, dxy, real]):
        st.info("ยังดึงมาโครไม่ได้ — ต้องตั้ง FRED_API_KEY ใน Streamlit Secrets ก่อน")
        return
    c = st.columns(4)
    if ff:
        c[0].metric("Fed Funds (effective)", f"{ff['value']:.2f}%",
                    f"{ff['change']:+.2f} (1ด.)", delta_color="off")
    if ecb:
        c[1].metric("ECB Deposit Rate", f"{ecb['value']:.2f}%",
                    f"{ecb['change']:+.2f} (1ด.)", delta_color="off")
    if diff is not None:
        c[2].metric("ส่วนต่าง Fed − ECB", f"{diff:+.2f}%",
                    f"{data['diff_chg']:+.2f} (1ด.)", delta_color="off")
    if dxy:
        c[3].metric("ดัชนีดอลลาร์ (DXY)", f"{dxy['value']:.2f}",
                    f"{dxy['change']:+.2f}", delta_color="off")
    if real:
        st.caption(f"Real Yield 10Y (US): {real['value']:.2f}% (Δ {real['change']:+.2f})")
    st.caption("🔑 กติกา EUR/USD: ส่วนต่างดอกเบี้ยกว้างขึ้น (Fed สูงกว่า/ECB ลด) = เงินไหลเข้า USD = EUR ลง • "
               "แคบลง = EUR ขึ้น • ดอลลาร์อ่อน = EUR ขึ้น • "
               "ดอกเบี้ยนโยบายขยับเฉพาะวันประชุม จึงเทียบย้อน ~1 เดือน")


# ---------- 3) ข่าว + sentiment ----------
def render_news(data):
    st.header("📰 ข่าวยูโร + ทิศทาง (Sentiment)")
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
    st.caption("ข่าวจาก FXE (ETF ค่าเงินยูโร) • คะแนน sentiment จาก Alpha Vantage (NLP)")


# ---------- 4) ปฏิทินเศรษฐกิจ ----------
def render_calendar(data):
    st.header("🗓️ ปฏิทินเศรษฐกิจ (USD + EUR)")
    cal = data["calendar"]
    if cal is None:
        st.info("ยังดึงปฏิทินไม่ได้ (feed ไม่ตอบ) — ลองรีเฟรชอีกครั้ง (ที่มา: Forex Factory)")
        return
    if not cal:
        st.info("feed โหลดได้ แต่ยังไม่มี event ระดับกลาง–สูงในกรอบเวลานี้")
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
            "สกุล": e["currency"],
            "Event": e["title"],
            "แรง": imp,
            "คาด": e["forecast"] or "—",
            "ครั้งก่อน": e["previous"] or "—",
        })
    st.table(C.pd.DataFrame(rows))
    st.caption("EUR/USD ไหวทั้งจากข่าวสหรัฐฯ (FOMC/CPI/NFP) และข่าวยุโรป (ECB/HICP) — "
               "เลี่ยงเปิดสถานะใหม่ช่วงก่อน/หลังประกาศ")


# ---------- page-level safe wrapper ----------
def _safe(fn, data, label):
    try:
        fn(data)
    except Exception:
        st.warning(f"⚠️ ส่วน «{label}» ขัดข้องชั่วคราว — ส่วนอื่นยังใช้ได้ เดี๋ยวรอบถัดไปกลับมาเอง")


@st.fragment(run_every=REFRESH_SECONDS)
def body():
    st.title("พื้นฐาน EUR/USD • Euro Fundamental")
    st.caption(f"อัปเดต {datetime.now().strftime('%H:%M:%S')} • ส่วนต่างดอกเบี้ย + ข่าว + ทิศทางพื้นฐาน • "
               "รีเฟรชอัตโนมัติทุก 30 นาที")

    if not F.FRED_KEY or not F.AV_KEY:
        miss = []
        if not F.FRED_KEY:
            miss.append("FRED_API_KEY (มาโคร)")
        if not F.AV_KEY:
            miss.append("ALPHAVANTAGE_API_KEY (ข่าว)")
        st.info("ℹ️ ยังไม่ได้ตั้ง key: " + " • ".join(miss) +
                " — ส่วนที่ไม่ต้องใช้ key (ปฏิทินเศรษฐกิจ) ยังทำงานปกติ")

    data = F.eur_fundamental()
    _safe(render_bias, data, "สรุป Bias")
    st.divider(); _safe(render_macro, data, "แผงมาโคร")
    st.divider(); _safe(render_news, data, "ข่าว")
    st.divider(); _safe(render_calendar, data, "ปฏิทินเศรษฐกิจ")
    st.divider()
    st.caption("⚠️ ข้อมูลเพื่อการศึกษา • เป็นบริบทพื้นฐาน ไม่ใช่คำแนะนำการลงทุน • "
               "ใช้คู่กับสาย Technical เพื่อจับทั้ง 'ทิศลม' และ 'จังหวะ'")


body()
