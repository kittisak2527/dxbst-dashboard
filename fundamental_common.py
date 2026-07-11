# -*- coding: utf-8 -*-
# =============================================================
# fundamental_common.py
# โมดูลกลางของแดชบอร์ดสาย FUNDAMENTAL (ทองคำ + BTC)
# ล้อกับ common.py ของสาย Technical:
#   - ทุก fetcher ห่อด้วย _safe() -> พังที่เดียวไม่ทำให้ทั้งหน้าเพจล่ม (คืน None)
#   - cache ด้วย st.cache_data เพื่อคุมโควตา API (โดยเฉพาะ Alpha Vantage 25 req/วัน)
# แหล่งข้อมูล:
#   FRED (key ฟรี)         -> มาโครสหรัฐ: real yield, dollar, breakeven, fed funds
#   Alpha Vantage (key ฟรี) -> ข่าว + คะแนน sentiment
#   Forex Factory (ไม่ต้อง key) -> ปฏิทินเศรษฐกิจ
#   alternative.me (ไม่ต้อง key) -> Fear & Greed (คริปโต)
#   CoinGecko (ไม่ต้อง key)      -> BTC dominance
# =============================================================

import functools
import requests
import streamlit as st
from datetime import datetime

# ---------- config / keys ----------
def _secret(name, default=""):
    """อ่านค่าจาก Streamlit secrets แบบปลอดภัย (ไม่ตั้งค่าก็ไม่พัง)"""
    try:
        return st.secrets[name]
    except Exception:
        return default

FRED_KEY = _secret("FRED_API_KEY")
AV_KEY   = _secret("ALPHAVANTAGE_API_KEY")

UA      = {"User-Agent": "Mozilla/5.0 (dxbst-dashboard/fundamental)"}
TIMEOUT = 12


# ---------- safe wrapper (ล้อ _safe ของสาย technical) ----------
def _safe(fn):
    """ครอบ fetcher ทุกตัว: error ที่เดียวไม่ทำให้ทั้งหน้าเพจล่ม -> คืน None
    วางไว้ 'นอกสุด' ของ st.cache_data เพื่อไม่ให้ cache เก็บผลที่ error ไว้"""
    @functools.wraps(fn)
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            return None
    return wrap


# =============================================================
# 1) มาโคร — FRED (ตัวขับเคลื่อนพื้นฐานของทองคำ/ดอลลาร์/ดอกเบี้ย)
# =============================================================
@_safe
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def fred_latest(series_id, n=10):
    """ดึงค่าล่าสุด + ค่าก่อนหน้าของ FRED series หนึ่งตัว
    คืน dict: value, prev, change, date  (คืน None ถ้าไม่มี key หรือดึงไม่ได้)"""
    if not FRED_KEY:
        return None
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id, "api_key": FRED_KEY, "file_type": "json",
        "sort_order": "desc", "limit": n,
    }
    r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
    obs = r.json().get("observations", [])
    vals = [(o["date"], float(o["value"])) for o in obs if o.get("value") not in (".", "", None)]
    if len(vals) < 2:
        return None
    (d0, v0), (_, v1) = vals[0], vals[1]
    return {"value": v0, "prev": v1, "change": v0 - v1, "date": d0, "series": series_id}


# =============================================================
# 2) ข่าว + sentiment — Alpha Vantage NEWS_SENTIMENT
#    NOTE: free tier = 25 req/วัน -> ตั้ง cache 3 ชม. (สูงสุด ~8 รอบ/วัน/คิวรี)
# =============================================================
@st.cache_data(ttl=3 * 3600, show_spinner=False)
def _av_news_cached(tickers, topics, limit):
    """เรียก Alpha Vantage จริง — คืน dict {items, note} เสมอ (ไม่คืน None)
    note = เหตุผลจริงถ้าไม่มีข่าว (เช่น ข้อความ rate limit) เพื่อ debug ได้"""
    try:
        params = {"function": "NEWS_SENTIMENT", "apikey": AV_KEY, "limit": limit, "sort": "LATEST"}
        if tickers:
            params["tickers"] = tickers
        if topics:
            params["topics"] = topics
        r = requests.get("https://www.alphavantage.co/query", params=params,
                         headers=UA, timeout=TIMEOUT)
        j = r.json()
    except Exception as e:
        return {"items": [], "note": f"เชื่อมต่อ Alpha Vantage ไม่ได้ ({type(e).__name__})"}

    feed = j.get("feed")
    if not feed:
        # ไม่มี feed = มักได้ข้อความ Information/Note/Error แทน -> ดึงมาโชว์
        note = (j.get("Information") or j.get("Note")
                or j.get("Error Message") or "Alpha Vantage ไม่ส่งข่าวกลับมาในรอบนี้")
        return {"items": [], "note": str(note)[:240]}

    items = []
    for a in feed[:limit]:
        items.append({
            "title":  a.get("title", ""),
            "url":    a.get("url", ""),
            "source": a.get("source", ""),
            "time":   a.get("time_published", ""),
            "score":  float(a.get("overall_sentiment_score", 0) or 0),
            "label":  a.get("overall_sentiment_label", "Neutral"),
        })
    return {"items": items, "note": None}


def av_news(tickers=None, topics=None, limit=12):
    """คืน dict {items: [...], note: str|None}
    tickers เช่น 'CRYPTO:BTC' | topics เช่น 'economy_monetary,financial_markets'"""
    if not AV_KEY:
        return {"items": [], "note": "ยังไม่ได้ตั้ง ALPHAVANTAGE_API_KEY"}
    return _av_news_cached(tickers, topics, limit)


def news_vote(items):
    """เฉลี่ย sentiment ของข่าวทั้งหมด -> (vote, avg)
    เกณฑ์ Alpha Vantage: >= +0.15 = บวก, <= -0.15 = ลบ"""
    if not items:
        return 0, None
    avg = sum(i["score"] for i in items) / len(items)
    if avg >= 0.15:
        return 1, avg
    if avg <= -0.15:
        return -1, avg
    return 0, avg


def fmt_news_time(t):
    """'20260711T133000' -> '11/07 13:30'"""
    try:
        return datetime.strptime(t, "%Y%m%dT%H%M%S").strftime("%d/%m %H:%M")
    except Exception:
        return t


# =============================================================
# 3) ปฏิทินเศรษฐกิจ — Forex Factory (ฟรี ไม่ต้อง key)
# =============================================================
@_safe
@st.cache_data(ttl=3600, show_spinner=False)
def econ_calendar(currencies=("USD", "EUR"), min_impact="Medium"):
    """คืน list event (สัปดาห์นี้ + สัปดาห์หน้า) เรียงตามเวลา:
    [{title, currency, impact, datetime, forecast, previous}, ...]"""
    urls = [
        "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
        "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
    ]
    rank  = {"Low": 0, "Medium": 1, "High": 2, "Holiday": 0}
    floor = rank.get(min_impact, 1)
    out, seen = [], set()
    for url in urls:
        try:
            data = requests.get(url, headers=UA, timeout=TIMEOUT).json()
        except Exception:
            continue                          # สัปดาห์หน้าอาจยังไม่มี feed -> ข้ามไป
        if not isinstance(data, list):
            continue                          # กัน feed คืน error page/dict แทน list
        for e in data:
            cur = e.get("country", "")        # ff ใช้ field 'country' เป็นสกุลเงิน เช่น USD/EUR
            if cur not in currencies:
                continue
            imp = str(e.get("impact", "")).strip().capitalize()   # กันตัวพิมพ์เล็ก/ใหญ่ไม่ตรง
            if rank.get(imp, 0) < floor:
                continue
            try:
                dt = datetime.fromisoformat(e.get("date"))   # เช่น 2026-07-14T12:30:00-04:00
            except Exception:
                continue
            key = (e.get("title", ""), e.get("date", ""))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "title": e.get("title", ""), "currency": cur, "impact": imp,
                "datetime": dt, "forecast": e.get("forecast", ""), "previous": e.get("previous", ""),
            })
    out.sort(key=lambda x: x["datetime"])
    return out


def countdown_str(dt):
    """คืนข้อความนับถอยหลังภาษาไทย"""
    if dt is None:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    diff = dt - now
    secs = diff.total_seconds()
    if secs < 0:
        return "ผ่านไปแล้ว"
    days = diff.days
    hrs  = (int(secs) % 86400) // 3600
    mins = (int(secs) % 3600) // 60
    if days > 0:
        return f"อีก {days} วัน {hrs} ชม."
    if hrs > 0:
        return f"อีก {hrs} ชม. {mins} นาที"
    return f"อีก {mins} นาที"


# =============================================================
# 4) คริปโต — Fear & Greed + BTC dominance (ฟรี ไม่ต้อง key)
# =============================================================
@_safe
@st.cache_data(ttl=1800, show_spinner=False)
def fear_greed():
    """คืน {value, prev, class} ของดัชนี Fear & Greed คริปโต (0-100)"""
    r = requests.get("https://api.alternative.me/fng/?limit=2", headers=UA, timeout=TIMEOUT)
    d = r.json().get("data", [])
    if not d:
        return None
    now  = int(d[0]["value"])
    prev = int(d[1]["value"]) if len(d) > 1 else now
    return {"value": now, "prev": prev, "class": d[0].get("value_classification", "")}


@_safe
@st.cache_data(ttl=1800, show_spinner=False)
def btc_dominance():
    """คืน {dominance} = % market cap ของ BTC เทียบตลาดคริปโตทั้งหมด"""
    r = requests.get("https://api.coingecko.com/api/v3/global", headers=UA, timeout=TIMEOUT)
    dom = r.json().get("data", {}).get("market_cap_percentage", {}).get("btc")
    return {"dominance": dom} if dom is not None else None


# =============================================================
# 5) เครื่องมือให้คะแนน Bias (ล้อ grade_from_votes ของสาย technical)
# =============================================================
def _vote(cond_bull, cond_bear):
    """helper: คืน +1 ถ้า bull, -1 ถ้า bear, 0 ถ้าไม่เข้าเงื่อนไข"""
    if cond_bull:
        return 1
    if cond_bear:
        return -1
    return 0


def bias_from_votes(votes):
    """votes: list ของ dict {name, vote(-1/0/+1), detail}
    คืน dict สรุปทิศทางรวม: net, score(0-100), label(TH), emoji, votes"""
    net = sum(v["vote"] for v in votes)
    if net >= 2:
        label, emoji = "ขาขึ้นชัดเจน (Bullish)", "🟢"
    elif net == 1:
        label, emoji = "เอียงขึ้น (Mild Bullish)", "🟢"
    elif net <= -2:
        label, emoji = "ขาลงชัดเจน (Bearish)", "🔴"
    elif net == -1:
        label, emoji = "เอียงลง (Mild Bearish)", "🔴"
    else:
        label, emoji = "เป็นกลาง (Neutral)", "⚪"
    maxv  = max(1, len(votes))
    score = round(50 + (net / maxv) * 50)     # 50 = กลาง, 0-100
    return {"net": net, "score": score, "label": label, "emoji": emoji, "votes": votes}


# =============================================================
# 6) ตัวรวม — หน้าเพจเรียกใช้แค่ 2 ฟังก์ชันนี้
# =============================================================
def gold_fundamental():
    """รวมทุกอย่างของทองคำ: macro + news + bias
    คืน dict: {real, dxy, be, ff, news, news_avg, bias, calendar}"""
    real = fred_latest("DFII10")     # 10Y real yield (TIPS) — ตัวขับเคลื่อนหลัก (ผกผันกับทอง)
    dxy  = fred_latest("DTWEXBGS")   # ดัชนีดอลลาร์ broad (proxy ทิศทาง DXY)
    be   = fred_latest("T10YIE")     # breakeven inflation 10Y
    ff   = fred_latest("DFF")        # fed funds effective
    news = av_news(topics="economy_monetary,financial_markets")
    items = news.get("items", [])
    nv, navg = news_vote(items)

    votes = []
    if real:
        votes.append({"name": "Real Yield 10Y (TIPS)",
                      "vote": _vote(real["change"] < 0, real["change"] > 0),
                      "detail": f"{real['value']:.2f}% (Δ {real['change']:+.2f}) — ลง=บวกต่อทอง"})
    if dxy:
        votes.append({"name": "ดัชนีดอลลาร์ (DXY)",
                      "vote": _vote(dxy["change"] < 0, dxy["change"] > 0),
                      "detail": f"{dxy['value']:.2f} (Δ {dxy['change']:+.2f}) — ลง=บวกต่อทอง"})
    if be:
        votes.append({"name": "Breakeven Inflation 10Y",
                      "vote": _vote(be["change"] > 0, be["change"] < 0),
                      "detail": f"{be['value']:.2f}% (Δ {be['change']:+.2f}) — ขึ้น=บวกต่อทอง"})
    if items:
        votes.append({"name": "Sentiment ข่าว", "vote": nv,
                      "detail": f"เฉลี่ย {navg:+.2f} จาก {len(items)} ข่าว"})

    return {"real": real, "dxy": dxy, "be": be, "ff": ff,
            "news": news, "news_avg": navg,
            "bias": bias_from_votes(votes),
            "calendar": econ_calendar(currencies=("USD",))}


def btc_fundamental():
    """รวมทุกอย่างของ BTC: macro (risk-on) + fear&greed + news + bias
    คืน dict: {dxy, real, fg, dom, news, news_avg, bias, calendar}"""
    dxy  = fred_latest("DTWEXBGS")
    real = fred_latest("DFII10")     # ดอกเบี้ยจริง: ขึ้น=ลบต่อสินทรัพย์เสี่ยง
    fg   = fear_greed()
    dom  = btc_dominance()
    news = av_news(tickers="CRYPTO:BTC")
    items = news.get("items", [])
    nv, navg = news_vote(items)

    votes = []
    if dxy:
        votes.append({"name": "ดัชนีดอลลาร์ (DXY)",
                      "vote": _vote(dxy["change"] < 0, dxy["change"] > 0),
                      "detail": f"{dxy['value']:.2f} (Δ {dxy['change']:+.2f}) — ลง=risk-on=บวก"})
    if real:
        votes.append({"name": "Real Yield 10Y",
                      "vote": _vote(real["change"] < 0, real["change"] > 0),
                      "detail": f"{real['value']:.2f}% (Δ {real['change']:+.2f}) — ลง=บวกต่อสินทรัพย์เสี่ยง"})
    if fg:
        votes.append({"name": "Fear & Greed",
                      "vote": _vote(fg["value"] > 55, fg["value"] < 45),
                      "detail": f"{fg['value']} ({fg['class']}) — >55 โลภ=บวก, <45 กลัว=ลบ"})
    if items:
        votes.append({"name": "Sentiment ข่าว", "vote": nv,
                      "detail": f"เฉลี่ย {navg:+.2f} จาก {len(items)} ข่าว"})

    return {"dxy": dxy, "real": real, "fg": fg, "dom": dom,
            "news": news, "news_avg": navg,
            "bias": bias_from_votes(votes),
            "calendar": econ_calendar(currencies=("USD",))}
