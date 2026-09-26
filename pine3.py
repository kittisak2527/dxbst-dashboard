"""ประกอบ PineScript 3-in-1 (BTC / ทอง / ยูโร) — อินดี้ตัวเดียว สลับชุดค่าตามสัญลักษณ์บนชาร์ตเอง

snapshot ต่อสินทรัพย์ (dict หรือ None):
  ts_ms, source, expiry, dte, callWall, putWall, maxPain, gexCall, gexPut, flip, gexSign(+1/-1/0)
"""
from datetime import datetime, timezone

import levels_store as S

DEC = {"BTC": 0, "XAU": 1, "EUR": 5}
PFX = {"BTC": "btc", "XAU": "xau", "EUR": "eur"}
LABEL = {"BTC": "BTCUSD", "XAU": "XAUUSD", "EUR": "EURUSD"}
FIELDS = [("callWall", "call"), ("putWall", "put"), ("maxPain", "mp"),
          ("gexCall", "gexC"), ("gexPut", "gexP"), ("flip", "flip")]


def _num(v, dec):
    try:
        return "na" if v is None else f"{float(v):.{dec}f}"
    except Exception:
        return "na"


def _q(s):
    return '"' + str(s or "").replace('"', "'") + '"'


def _block(asset, snap):
    p, dec = PFX[asset], DEC[asset]
    has = bool(snap)
    snap = snap or {}
    stamp = (datetime.fromtimestamp(snap["ts_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
             if has else "ยังไม่มีข้อมูล")
    out = [f"// ── {LABEL[asset]} · {snap.get('source', '-')} · ข้อมูลเมื่อ {stamp}"]
    out.append(f"bool   {p}_has   = {'true' if has else 'false'}")
    for key, short in FIELDS:
        out.append(f"float  {p}_{short:<5}= {_num(snap.get(key), dec)}")
    try:
        gs = int(snap.get("gexSign") or 0)
    except Exception:
        gs = 0
    out.append(f"float  {p}_gsign = {gs}")
    out.append(f"int    {p}_ts    = {int(snap.get('ts_ms', 0))}")
    exp = snap.get("expiry") or ""
    if exp and snap.get("dte") is not None:
        exp = f"{exp} ({snap['dte']}d)"
    out.append(f"string {p}_src   = {_q(snap.get('source', ''))}")
    out.append(f"string {p}_exp   = {_q(exp)}")
    return out


def build_pine(snaps, gen_ts_ms):
    gen_txt = datetime.fromtimestamp(gen_ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = ["//@version=5",
         'indicator("Positioning Levels [3-in-1]", overlay=true, max_lines_count=50, '
         'max_labels_count=50, max_boxes_count=50)',
         "",
         f"// ═══ ค่าจากแดชบอร์ด • เจนเมื่อ {gen_txt} • อย่าแก้มือ (กดเจนใหม่ในแดชบอร์ดแทน) ═══"]
    for a in S.ASSETS:
        L += _block(a, snaps.get(a))
        L.append("")
    L.append(S.dump_line(snaps))
    L.append(PINE_BODY)
    return "\n".join(L)


PINE_BODY = r'''
// ═══════════════════════ ตั้งค่า ═══════════════════════
grpL     = "เส้น"
adjBasis = input.bool(true,  "ปรับสเกล basis อัตโนมัติ (GC→XAU spot • spot→6E)", group=grpL)
showLbl  = input.bool(true,  "แสดงป้ายราคา", group=grpL)
grpS     = "อายุข้อมูล"
warnH    = input.float(30, "เหลือง เมื่อเก่ากว่า (ชม.)", minval=1, group=grpS)
redH     = input.float(80, "แดง เมื่อเก่ากว่า (ชม.)  • 80 = ข้ามเสาร์-อาทิตย์ได้", minval=1, group=grpS)
grpF       = "FVG / Imbalance"
fvgOn      = input.bool(true,  "แสดงโซน FVG", group=grpF)
fvgLvlOnly = input.bool(true,  "แสดงเฉพาะโซนที่ทับเส้น positioning", group=grpF)
fvgKeep    = input.int(8, "เก็บโซนล่าสุด (จำนวน)", minval=1, maxval=20, group=grpF)
fvgMinPct  = input.float(0.03, "ขนาดโซนขั้นต่ำ %", minval=0.0, step=0.01, group=grpF) / 100
lvlTolPct  = input.float(0.15, "ระยะนับว่าทับเส้น %", minval=0.01, step=0.05, group=grpF) / 100
grpA     = "แจ้งเตือน"
alertsOn = input.bool(true, "เปิดแจ้งเตือน (Any alert() function call)", group=grpA)
nearPct  = input.float(0.25, "ระยะเตือนใกล้เส้น %", minval=0.05, step=0.05, group=grpA) / 100

// ═══════════════════════ เลือกชุดค่าตามสัญลักษณ์ ═══════════════════════
sym   = str.upper(syminfo.ticker)
root  = str.upper(syminfo.root)
isXAU = str.contains(sym, "XAU") or str.contains(sym, "GOLD") or root == "GC" or root == "MGC"
isEUR = not isXAU and ((str.contains(sym, "EUR") and str.contains(sym, "USD")) or root == "6E" or root == "M6E")
isBTC = not isXAU and not isEUR and (str.contains(sym, "BTC") or str.contains(sym, "XBT"))
matched = isXAU or isEUR or isBTC

hasD  = isXAU ? xau_has : isEUR ? eur_has : isBTC ? btc_has : false
tsSel = isXAU ? xau_ts  : isEUR ? eur_ts  : isBTC ? btc_ts  : 0
srcS  = isXAU ? xau_src : isEUR ? eur_src : isBTC ? btc_src : ""
expS  = isXAU ? xau_exp : isEUR ? eur_exp : isBTC ? btc_exp : ""
gsign = isXAU ? xau_gsign : isEUR ? eur_gsign : isBTC ? btc_gsign : 0.0
assetLbl = isXAU ? "XAUUSD" : isEUR ? "EURUSD" : isBTC ? "BTCUSD" : "—"

// ค่าทองอยู่ในสเกล GC (futures) • ยูโรอยู่ในสเกล spot → ปรับด้วยอัตราส่วนสดกับสัญลักษณ์อ้างอิง
refSym   = isXAU ? "COMEX:GC1!" : isEUR ? "FX:EURUSD" : syminfo.tickerid
refClose = request.security(refSym, timeframe.period, close, ignore_invalid_symbol=true)
rawRatio = (adjBasis and not isBTC and not na(refClose) and refClose > 0) ? close / refClose : 1.0
ratio    = math.abs(rawRatio - 1.0) > 0.05 ? 1.0 : rawRatio      // กันข้อมูลเพี้ยน

f_adj(v) => na(v) ? na : v * ratio

callL = f_adj(isXAU ? xau_call : isEUR ? eur_call : isBTC ? btc_call : na)
putL  = f_adj(isXAU ? xau_put  : isEUR ? eur_put  : isBTC ? btc_put  : na)
mpL   = f_adj(isXAU ? xau_mp   : isEUR ? eur_mp   : isBTC ? btc_mp   : na)
gexCL = f_adj(isXAU ? xau_gexC : isEUR ? eur_gexC : isBTC ? btc_gexC : na)
gexPL = f_adj(isXAU ? xau_gexP : isEUR ? eur_gexP : isBTC ? btc_gexP : na)
flipL = f_adj(isXAU ? xau_flip : isEUR ? eur_flip : isBTC ? btc_flip : na)

// ═══════════════════════ โหมด (คำนวณสดจากราคาเทียบ Gamma Flip) ═══════════════════════
modeKnown = matched and hasD and (not na(flipL) or gsign != 0)
dampen    = not na(flipL) ? close >= flipL : gsign > 0
modeTh    = dampen ? "หน่วง (มักเด้ง)" : "เร่ง (มักทะลุ)"

// ═══════════════════════ รวมเส้นเป็น array ═══════════════════════
f_push(float[] P, string[] N, color[] K, int[] W, float v, string n, color c, int w) =>
    if not na(v)
        array.push(P, v)
        array.push(N, n)
        array.push(K, c)
        array.push(W, w)
    0

keyP = array.new_float()
keyN = array.new_string()
keyK = array.new_color()
keyW = array.new_int()
if matched and hasD
    f_push(keyP, keyN, keyK, keyW, callL, "Call Wall",     color.red,     2)
    f_push(keyP, keyN, keyK, keyW, putL,  "Put Wall",      color.green,   2)
    f_push(keyP, keyN, keyK, keyW, mpL,   "Max Pain",      color.yellow,  2)
    f_push(keyP, keyN, keyK, keyW, gexCL, "GEX Call Wall", color.orange,  1)
    f_push(keyP, keyN, keyK, keyW, gexPL, "GEX Put Wall",  color.aqua,    1)
    f_push(keyP, keyN, keyK, keyW, flipL, "Gamma Flip",    color.fuchsia, 2)
nKeys = array.size(keyP)

// ═══════════════════════ วาดเส้น + ป้าย (แท่งล่าสุด) ═══════════════════════
var line[]  lns = array.new_line()
var label[] lbs = array.new_label()
if barstate.islast
    while array.size(lns) > 0
        line.delete(array.pop(lns))
    while array.size(lbs) > 0
        label.delete(array.pop(lbs))
    if nKeys > 0
        for i = 0 to nKeys - 1
            v  = array.get(keyP, i)
            n  = array.get(keyN, i)
            c  = array.get(keyK, i)
            st = n == "Max Pain" ? line.style_dotted : (n == "Call Wall" or n == "Put Wall") ? line.style_dashed : line.style_solid
            array.push(lns, line.new(bar_index - 1, v, bar_index, v, extend=extend.both, color=c, width=array.get(keyW, i), style=st))
            if showLbl
                array.push(lbs, label.new(bar_index + 3, v, n + " " + str.tostring(v, format.mintick), style=label.style_label_left, color=color.new(c, 65), textcolor=color.white, size=size.small))

// ═══════════════════════ ตารางสถานะ ═══════════════════════
ageH   = tsSel > 0 ? (timenow - tsSel) / 3600000.0 : 0.0
ageTxt = ageH < 48 ? str.tostring(math.round(ageH)) + " ชม." : str.tostring(math.round(ageH / 24)) + " วัน"

var table tb = table.new(position.top_right, 1, 4, border_width=1)
if barstate.islast
    string mTxt = ""
    color  mBg  = color.new(color.gray, 20)
    if not matched
        mTxt := "สัญลักษณ์นี้ไม่มีชุดข้อมูล (รองรับ XAU / EUR / BTC)"
    else if not hasD
        mTxt := "ยังไม่มีข้อมูล " + assetLbl + " — กดเจนในแดชบอร์ด"
    else if not modeKnown
        mTxt := "โหมด: ไม่ทราบ (ไม่มี GEX / Flip)"
    else if dampen
        mTxt := "โหมด: หน่วง → FADE"
        mBg  := color.new(color.green, 15)
    else
        mTxt := "โหมด: เร่ง → BREAK-RETEST"
        mBg  := color.new(color.orange, 10)
    table.cell(tb, 0, 0, mTxt, bgcolor=mBg, text_color=color.white, text_size=size.normal)
    if matched and hasD
        table.cell(tb, 0, 1, assetLbl + " • " + srcS + (expS != "" ? " • " + expS : ""), bgcolor=color.new(color.gray, 30), text_color=color.white, text_size=size.small)
        stale = ageH >= warnH
        ageBg = ageH >= redH ? color.new(color.red, 10) : stale ? color.new(color.orange, 20) : color.new(color.gray, 30)
        table.cell(tb, 0, 2, "ข้อมูลเมื่อ " + str.format_time(tsSel, "dd/MM HH:mm", "Asia/Bangkok") + " • " + ageTxt + (stale ? " • ค่าเก่า" : ""), bgcolor=ageBg, text_color=color.white, text_size=size.small)
        if math.abs(ratio - 1.0) > 0.0005
            table.cell(tb, 0, 3, "ปรับ basis ×" + str.tostring(ratio, "#.####"), bgcolor=color.new(color.gray, 45), text_color=color.white, text_size=size.tiny)

// ═══════════════════════ แจ้งเตือนใกล้ / เบรกเส้น ═══════════════════════
if alertsOn and nKeys > 0
    for i = 0 to nKeys - 1
        v = array.get(keyP, i)
        n = array.get(keyN, i) + " " + str.tostring(v, format.mintick)
        nearNow  = math.abs(close - v) / v <= nearPct
        nearPrev = math.abs(close[1] - v) / v <= nearPct
        if nearNow and not nearPrev
            alert("⚡ " + assetLbl + " เข้าใกล้ " + n + " • โหมด" + modeTh, alert.freq_once_per_bar)
        if close > v and close[1] <= v
            alert("⬆️ " + assetLbl + " เบรกขึ้น " + n + " • โหมด" + modeTh, alert.freq_once_per_bar)
        if close < v and close[1] >= v
            alert("⬇️ " + assetLbl + " เบรกลง " + n + " • โหมด" + modeTh, alert.freq_once_per_bar)

// ═══════════════════════ FVG ที่ทับเส้น positioning ═══════════════════════
var box[]    fBox  = array.new_box()
var float[]  fTop  = array.new_float()
var float[]  fBot  = array.new_float()
var bool[]   fBull = array.new_bool()
var bool[]   fIn   = array.new_bool()
var string[] fName = array.new_string()

f_lvlHit(float[] P, string[] N, float t, float b) =>
    string nm = ""
    if array.size(P) > 0
        for i = 0 to array.size(P) - 1
            v = array.get(P, i)
            if v >= b - v * lvlTolPct and v <= t + v * lvlTolPct
                nm := array.get(N, i)
                break
    nm

newBull = barstate.isconfirmed and low > high[2] and (low - high[2]) / high[2] >= fvgMinPct
newBear = barstate.isconfirmed and high < low[2] and (low[2] - high) / high >= fvgMinPct
if fvgOn and (newBull or newBear)
    t   = newBull ? low : low[2]
    b   = newBull ? high[2] : high
    nm  = f_lvlHit(keyP, keyN, t, b)
    atL = nm != ""
    if (not fvgLvlOnly) or atL
        bg = atL ? color.new(color.yellow, 80) : (newBull ? color.new(color.green, 90) : color.new(color.red, 90))
        bc = atL ? color.new(color.yellow, 30) : color.new(color.gray, 60)
        bx = box.new(bar_index - 2, t, bar_index + 3, b, border_color=bc, bgcolor=bg)
        if atL
            box.set_text(bx, "⭐ FVG @ " + nm)
            box.set_text_color(bx, color.white)
            box.set_text_size(bx, size.tiny)
            box.set_text_halign(bx, text.align_left)
        array.push(fBox, bx)
        array.push(fTop, t)
        array.push(fBot, b)
        array.push(fBull, newBull)
        array.push(fIn, false)
        array.push(fName, nm)
        while array.size(fBox) > fvgKeep
            box.delete(array.shift(fBox))
            array.shift(fTop)
            array.shift(fBot)
            array.shift(fBull)
            array.shift(fIn)
            array.shift(fName)

if barstate.isconfirmed and array.size(fBox) > 0
    for i = array.size(fBox) - 1 to 0
        t  = array.get(fTop, i)
        b  = array.get(fBot, i)
        bx = array.get(fBox, i)
        box.set_right(bx, bar_index + 3)
        inside = low <= t and high >= b
        if inside and not array.get(fIn, i)
            array.set(fIn, i, true)
            if alertsOn
                dir = array.get(fBull, i) ? "ขาขึ้น" : "ขาลง"
                tag = array.get(fName, i) != "" ? " ⭐ ที่ " + array.get(fName, i) : ""
                alert("🎯 " + assetLbl + " เข้าโซน FVG " + dir + tag + " • โหมด" + modeTh, alert.freq_once_per_bar_close)
        mit = array.get(fBull, i) ? close < b : close > t
        if mit
            box.delete(bx)
            array.remove(fBox, i)
            array.remove(fTop, i)
            array.remove(fBot, i)
            array.remove(fBull, i)
            array.remove(fIn, i)
            array.remove(fName, i)
'''
