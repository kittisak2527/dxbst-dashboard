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


def expiry_ts_ms(expiry):
    """Deribit '25DEC26' = 08:00 UTC • ETF options '2026-10-16' = ปิดตลาด US ~20:00 UTC"""
    for fmt, hour in (("%d%b%y", 8), ("%Y-%m-%d", 20)):
        try:
            d = datetime.strptime(str(expiry).upper() if fmt == "%d%b%y" else str(expiry), fmt)
            return int(d.replace(hour=hour, tzinfo=timezone.utc).timestamp() * 1000)
        except Exception:
            continue
    return 0


def _q(s):
    return '"' + str(s or "").replace('"', "'") + '"'


def _block(asset, snap):
    p, dec = PFX[asset], DEC[asset]
    has = bool(snap)
    snap = snap or {}
    stamp = (datetime.fromtimestamp(snap["ts_ms"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
             if has else "ยังไม่มีข้อมูล")
    out = [f"// ── {LABEL[asset]} · {snap.get('source', '-')} · ดึงเมื่อ {stamp}"]
    out.append(f"bool   {p}_has   = {'true' if has else 'false'}")
    for key, short in FIELDS:
        out.append(f"float  {p}_{short:<5}= {_num(snap.get(key), dec)}")
    try:
        gs = int(snap.get("gexSign") or 0)
    except Exception:
        gs = 0
    out.append(f"float  {p}_gsign = {gs}")
    out.append(f"int    {p}_ts    = {int(snap.get('ts_ms', 0))}")
    out.append(f"float  {p}_ref   = {_num(snap.get('refPrice'), max(dec, 2))}")
    out.append(f"int    {p}_refts = {int(snap.get('ref_ts_ms') or 0)}")
    exp = snap.get("expiry") or ""
    out.append(f"int    {p}_expts = {expiry_ts_ms(exp) if exp else 0}")
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
lblOff   = input.int(15, "ระยะป้ายจากแท่งล่าสุด (แท่ง) • เส้นจบตรงป้าย", minval=3, maxval=200, group=grpL)
mergePct = input.float(0.10, "รวมป้ายเมื่อเส้นห่างกันไม่เกิน %", minval=0.0, step=0.05, group=grpL) / 100
grpS     = "อายุข้อมูล"
warnH    = input.float(30, "เหลือง เมื่อเก่ากว่า (ชม.)", minval=1, group=grpS)
redH     = input.float(80, "แดง เมื่อเก่ากว่า (ชม.)  • 80 = ข้ามเสาร์-อาทิตย์ได้", minval=1, group=grpS)
grpF       = "FVG / Imbalance"
fvgOn      = input.bool(true,  "แสดงโซน FVG", group=grpF)
fvgLvlOnly = input.bool(true,  "แสดงเฉพาะโซนที่ทับเส้น positioning", group=grpF)
fvgKeep    = input.int(8, "เก็บโซนล่าสุด (จำนวน)", minval=1, maxval=20, group=grpF)
fvgDelMit  = input.bool(true,  "ลบโซนเมื่อแท่งปิดทะลุทั้งโซน", group=grpF)
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
expTs = isXAU ? xau_expts : isEUR ? eur_expts : isBTC ? btc_expts : 0

// ═══ นับถอยหลังงวด options (สด ทุกแท่ง) ═══
grpE    = "งวด options"
expWarn = input.float(3, "เตือนใกล้หมดอายุ (วัน)", minval=0.5, step=0.5, group=grpE)
cdOnMP  = input.bool(true, "ต่อท้ายป้าย Max Pain ด้วยเวลาที่เหลือ", group=grpE)
msLeft  = expTs > 0 ? float(expTs - timenow) : na
expired = not na(msLeft) and msLeft <= 0
expNear = not na(msLeft) and not expired and msLeft <= expWarn * 86400000
f_cd(ms) =>
    string r = ""
    if not na(ms)
        if ms <= 0
            r := "หมดอายุแล้ว"
        else if ms < 86400000
            r := str.tostring(math.floor(ms / 3600000)) + " ชม. " + str.tostring(math.floor(ms / 60000) % 60) + " น."
        else
            r := str.tostring(math.floor(ms / 86400000)) + " วัน " + str.tostring(math.floor(ms / 3600000) % 24) + " ชม."
    r
cdTxt = f_cd(msLeft)
assetLbl = isXAU ? "XAUUSD" : isEUR ? "EURUSD" : isBTC ? "BTCUSD" : "—"

// ค่าทองอยู่ในสเกล GC (futures) • ยูโรอยู่ในสเกล spot → ปรับด้วยอัตราส่วนสดกับสัญลักษณ์อ้างอิง
// ── basis วิธีหลัก: เทียบ ณ เวลาเจน ──
// แดชบอร์ดฝัง "ราคาอ้างอิงที่ใช้สเกลเส้น" + เวลาของราคานั้นมาให้
// → หาราคาชาร์ตนี้ ณ เวลาเดียวกัน (จากแท่ง 5 นาที ทุก TF ได้ค่าเดียวกัน) แล้วหารกัน
refPx = isXAU ? xau_ref   : isEUR ? eur_ref   : na
refTs = isXAU ? xau_refts : isEUR ? eur_refts : 0
f_pxAt(int ts) =>
    var float p = na
    if ts > 0 and time_close <= ts
        p := close
    p
pxAtRef = request.security(syminfo.tickerid, "5", f_pxAt(refTs))
// วิธีที่ 1 (แม่นสุด): เทียบกับสัญลักษณ์อ้างอิงบน TradingView เอง ณ เวลาเดียวกัน
//   ทอง → COMEX:GC1!  • ยูโร → FX:EURUSD   (ทั้งสองฝั่งมาจาก TV เวลาตรงกันแน่นอน ไม่พึ่งดีเลย์ของ Yahoo)
tvRefSym = isXAU ? "COMEX:GC1!" : isEUR ? "FX:EURUSD" : syminfo.tickerid
tvAtRef  = request.security(tvRefSym, "5", f_pxAt(refTs), ignore_invalid_symbol=true)
useTvBasis   = refTs > 0 and not na(pxAtRef) and not na(tvAtRef) and tvAtRef > 0
// วิธีที่ 2: เทียบกับราคา Yahoo ที่แดชบอร์ดฝังมา (สำรองเมื่อไม่มีข้อมูล GC1!/FX:EURUSD)
useSnapBasis = not na(refPx) and refPx > 0 and not na(pxAtRef)

// ── basis สำรอง: ราคาปิดวันก่อน (ใช้เมื่อ snapshot เก่ายังไม่มีราคาอ้างอิง) ──
refSym   = isXAU ? "COMEX:GC1!" : isEUR ? "FX:EURUSD" : syminfo.tickerid
refPrevD = request.security(refSym, "D", close[1], lookahead=barmerge.lookahead_on, ignore_invalid_symbol=true)
chPrevD  = request.security(syminfo.tickerid, "D", close[1], lookahead=barmerge.lookahead_on)
dailyOK  = not na(refPrevD) and refPrevD > 0 and not na(chPrevD)

rawRatio = (not adjBasis or isBTC) ? 1.0 : useTvBasis ? pxAtRef / tvAtRef : useSnapBasis ? pxAtRef / refPx : dailyOK ? chPrevD / refPrevD : 1.0
basisHow = useTvBasis ? "เทียบ " + (isXAU ? "GC1!" : "EURUSD") + " ณ เวลาเจน" : useSnapBasis ? "เทียบ Yahoo ณ เวลาเจน" : dailyOK ? "ปิดวันก่อน" : "ไม่ปรับ"
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

// ═══════════════════════ A/V Pivot (TF ใหญ่) — นิยามแท่งคู่ตาม DTX v2.3a ═══════════════════════
grpV      = "A/V Pivot (TF ใหญ่)"
avOn      = input.bool(true, "แสดงโซน A/V", group=grpV)
avTf      = input.timeframe("240", "TF ที่ใช้ตรวจ", group=grpV)
avLineMd  = input.string("zMid (ตาม DTX)", "เส้นตัดสินในโซน", options=["zMid (ตาม DTX)", "ขอบที่บรรจบ", "จุดที่ถูกทดสอบ"], group=grpV)
avShowN   = input.int(2, "แสดงโซนด้านบน / ล่าง อย่างละ", minval=1, maxval=4, group=grpV)
avBodyPct = input.float(0.25, "② เนื้อเทียน ≥ สัดส่วนของ range", step=0.05, group=grpV)
avBodyAtr = input.float(0.30, "② เนื้อเทียน ≥ × ATR(14)", step=0.05, group=grpV)
avExtLen  = input.int(6, "③ ต้องเป็นยอด/ฐานของ (แท่ง)", minval=2, group=grpV)
avMaxH    = input.float(2.0, "④ ความสูงโซนสูงสุด × ATR", step=0.1, group=grpV)
avKill    = input.float(0.6, "⑥ โซนตายเมื่อปิดเลยขอบ × ATR", step=0.1, group=grpV)
avReqExt  = input.bool(false, "⑤ กรองเพิ่ม: EXT (ชิดสุดของ 100 แท่ง)", group=grpV)
avReqSwp  = input.bool(false, "⑤ กรองเพิ่ม: SWEEP (แหย่เลยสวิงเก่าแล้วปิดกลับ)", group=grpV)
avReqPos  = input.bool(false, "⑤ กรองเพิ่ม: POS (ซ้อนเส้น positioning)", group=grpV)
avPadAtr  = 0.35
avMaxZ    = 12

// คำนวณบนแท่ง TF ใหญ่ แล้วส่ง "แท่งที่ปิดแล้ว" ([1] + lookahead_on = ไม่ repaint)
f_avHTF() =>
    a     = ta.atr(14)
    b0    = math.abs(close - open)
    b1    = math.abs(close[1] - open[1])
    r0    = high - low
    r1    = high[1] - low[1]
    solid = b0 >= avBodyPct * r0 and b0 >= avBodyAtr * a and b1 >= avBodyPct * r1 and b1 >= avBodyAtr * a
    hhN   = ta.highest(high, avExtLen)
    llN   = ta.lowest(low, avExtLen)
    isA   = close[1] > open[1] and close < open and solid and math.max(high, high[1]) >= hhN
    isV   = close[1] < open[1] and close > open and solid and math.min(low, low[1]) <= llN
    zT    = math.max(math.max(open, close), math.max(open[1], close[1]))
    zB    = math.min(math.min(open, close), math.min(open[1], close[1]))
    okH   = zT - zB <= avMaxH * a
    hh100 = ta.highest(high, 100)
    ll100 = ta.lowest(low, 100)
    oldH  = ta.highest(high[4], 17)
    oldL  = ta.lowest(low[4], 17)
    ext   = isA ? hh100 - zT <= avPadAtr * a : isV ? zB - ll100 <= avPadAtr * a : false
    swp   = isA ? (math.max(high, high[1]) > oldH and close < oldH) : isV ? (math.min(low, low[1]) < oldL and close > oldL) : false
    kind  = okH ? (isA ? 1 : isV ? -1 : 0) : 0
    [kind[1], zT[1], zB[1], a[1], ext[1], swp[1], high[1], low[1], close[1]]

avSec    = timeframe.in_seconds(avTf)
avActive = avOn and timeframe.in_seconds() <= avSec
avTfName = avSec >= 604800 ? "W" : avSec >= 86400 ? "D" : avSec >= 3600 ? "H" + str.tostring(math.round(avSec / 3600)) : "M" + str.tostring(math.round(avSec / 60))
[hK, hT, hB, hAtr, hExt, hSwp, hH, hL, hC] = request.security(syminfo.tickerid, avTf, f_avHTF(), lookahead=barmerge.lookahead_on)
newHtf = ta.change(time(avTf)) != 0

var int[]    zK   = array.new_int()
var float[]  zTp  = array.new_float()
var float[]  zBt  = array.new_float()
var float[]  zAt  = array.new_float()
var int[]    zTc  = array.new_int()
var int[]    zId  = array.new_int()
var int[]    zBi  = array.new_int()
var float[]  tVal = array.new_float()
var int[]    tId  = array.new_int()
var int      zNext = 0

f_posHit(float t, float b, float pad) =>
    bool hit = false
    for v in array.from(flipL, callL, putL, mpL, gexCL, gexPL)
        if not na(v) and v >= b - pad and v <= t + pad
            hit := true
    hit

f_zDel(int i) =>
    array.remove(zK, i)
    array.remove(zTp, i)
    array.remove(zBt, i)
    array.remove(zAt, i)
    array.remove(zTc, i)
    array.remove(zId, i)
    array.remove(zBi, i)
    0

if avActive and newHtf
    // 1) อัปเดตโซนเดิมด้วยแท่ง TF ใหญ่ที่เพิ่งปิด: ตาย / ถูกทดสอบ
    if array.size(zK) > 0
        for i = array.size(zK) - 1 to 0
            k = array.get(zK, i)
            t = array.get(zTp, i)
            b = array.get(zBt, i)
            a = array.get(zAt, i)
            dead = k == 1 ? hC > t + avKill * a : hC < b - avKill * a
            if dead
                f_zDel(i)
            else
                touch = k == 1 ? (hH >= b and hC <= t) : (hL <= t and hC >= b)
                if touch
                    array.set(zTc, i, array.get(zTc, i) + 1)
                    array.push(tVal, k == 1 ? math.min(hH, t) : math.max(hL, b))
                    array.push(tId, array.get(zId, i))
                    while array.size(tVal) > 300
                        array.shift(tVal)
                        array.shift(tId)
    // 2) โซนใหม่ (①–④ ผ่านแล้วจากฝั่ง TF ใหญ่ • ⑤ กรองเพิ่มเมื่อเปิด)
    if hK != 0 and not na(hT) and not na(hAtr)
        anyReq = avReqExt or avReqSwp or avReqPos
        why = (avReqExt and hExt) ? "EXT" : (avReqSwp and hSwp) ? "SWP" : (avReqPos and f_posHit(hT, hB, avPadAtr * hAtr)) ? "POS" : ""
        if not anyReq or why != ""
            array.push(zK, hK)
            array.push(zTp, hT)
            array.push(zBt, hB)
            array.push(zAt, hAtr)
            array.push(zTc, 0)
            array.push(zId, zNext)
            array.push(zBi, bar_index)
            zNext += 1
            while array.size(zK) > avMaxZ
                f_zDel(0)

// เส้นตัดสินในโซน
f_zLine(int i) =>
    k = array.get(zK, i)
    t = array.get(zTp, i)
    b = array.get(zBt, i)
    float r = (t + b) / 2
    if avLineMd == "ขอบที่บรรจบ"
        r := k == 1 ? t : b
    else if avLineMd == "จุดที่ถูกทดสอบ" and array.get(zTc, i) >= 2
        id   = array.get(zId, i)
        vals = array.new_float()
        if array.size(tId) > 0
            for j = 0 to array.size(tId) - 1
                if array.get(tId, j) == id
                    array.push(vals, array.get(tVal, j))
        if array.size(vals) >= 2
            r := array.median(vals)
    r

// เลือกโซนที่ใกล้ราคา ด้านบน/ล่าง อย่างละ avShowN
selI = array.new_int()
selV = array.new_float()
if avActive and array.size(zK) > 0
    upD = array.new_float()
    upI = array.new_int()
    dnD = array.new_float()
    dnI = array.new_int()
    for i = 0 to array.size(zK) - 1
        v = f_zLine(i)
        if v >= close
            array.push(upD, v - close)
            array.push(upI, i)
        else
            array.push(dnD, close - v)
            array.push(dnI, i)
    if array.size(upD) > 0
        o = array.sort_indices(upD, order.ascending)
        for j = 0 to math.min(avShowN, array.size(o)) - 1
            ii = array.get(upI, array.get(o, j))
            array.push(selI, ii)
            array.push(selV, f_zLine(ii))
    if array.size(dnD) > 0
        o = array.sort_indices(dnD, order.ascending)
        for j = 0 to math.min(avShowN, array.size(o)) - 1
            ii = array.get(dnI, array.get(o, j))
            array.push(selI, ii)
            array.push(selV, f_zLine(ii))
colA = color.rgb(239, 83, 80)
colV = color.rgb(38, 166, 154)

// ═══════════════════════ รวมเส้นเป็น array ═══════════════════════
f_push(float[] P, string[] N, color[] K, int[] W, bool[] D, float v, string n, color c, int w, bool d) =>
    if not na(v)
        array.push(P, v)
        array.push(N, n)
        array.push(K, c)
        array.push(W, w)
        array.push(D, d)
    0

keyP = array.new_float()
keyN = array.new_string()
keyK = array.new_color()
keyW = array.new_int()
keyD = array.new_bool()      // true = วาดเส้นเต็มแบบ positioning • false = A/V (วาดเป็นโซนแยก)
if matched and hasD
    f_push(keyP, keyN, keyK, keyW, keyD, flipL, "Gamma Flip",    color.fuchsia, 2, true)
    f_push(keyP, keyN, keyK, keyW, keyD, callL, "Call Wall",     color.red,     2, true)
    f_push(keyP, keyN, keyK, keyW, keyD, putL,  "Put Wall",      color.green,   2, true)
    f_push(keyP, keyN, keyK, keyW, keyD, mpL,   "Max Pain",      color.yellow,  2, true)
    f_push(keyP, keyN, keyK, keyW, keyD, gexCL, "GEX Call Wall", color.orange,  1, true)
    f_push(keyP, keyN, keyK, keyW, keyD, gexPL, "GEX Put Wall",  color.aqua,    1, true)
if array.size(selI) > 0
    for j = 0 to array.size(selI) - 1
        ii = array.get(selI, j)
        k  = array.get(zK, ii)
        tc = array.get(zTc, ii)
        f_push(keyP, keyN, keyK, keyW, keyD, array.get(selV, j), (k == 1 ? "A-" : "V-") + avTfName + (tc > 0 ? " ×" + str.tostring(tc) : ""), k == 1 ? colA : colV, 1, false)
nKeys = array.size(keyP)

// ═══════════════════════ วาดเส้น + ป้าย (แท่งล่าสุด) ═══════════════════════
var line[]  lns = array.new_line()
var label[] lbs = array.new_label()
var box[]   avb = array.new_box()
if barstate.islast
    while array.size(lns) > 0
        line.delete(array.pop(lns))
    while array.size(lbs) > 0
        label.delete(array.pop(lbs))
    while array.size(avb) > 0
        box.delete(array.pop(avb))
    // โซน A/V: กล่องเนื้อเทียน + เส้นตัดสิน (จางลงเมื่อถูกทดสอบแล้ว)
    if array.size(selI) > 0
        for j = 0 to array.size(selI) - 1
            ii = array.get(selI, j)
            c  = array.get(zK, ii) == 1 ? colA : colV
            tc = array.get(zTc, ii)
            x0 = math.max(array.get(zBi, ii), bar_index - 4900)   // กันวัตถุย้อนไกลเกินขีดจำกัดของ TradingView
            array.push(avb, box.new(x0, array.get(zTp, ii), bar_index + lblOff, array.get(zBt, ii), border_color=color.new(c, tc > 0 ? 80 : 60), bgcolor=color.new(c, tc > 0 ? 94 : 87)))
            array.push(lns, line.new(x0, array.get(selV, j), bar_index + lblOff, array.get(selV, j), color=color.new(c, tc > 0 ? 50 : 15), width=1, style=line.style_dashed))
    if nKeys > 0
        for i = 0 to nKeys - 1
            if not array.get(keyD, i)
                continue
            v  = array.get(keyP, i)
            n  = array.get(keyN, i)
            c  = array.get(keyK, i)
            st = n == "Max Pain" ? line.style_dotted : (n == "Call Wall" or n == "Put Wall") ? line.style_dashed : line.style_solid
            array.push(lns, line.new(bar_index - 1, v, bar_index + lblOff, v, extend=extend.left, color=c, width=array.get(keyW, i), style=st))
        if showLbl
            used = array.new_bool(nKeys, false)
            for i = 0 to nKeys - 1
                if not array.get(used, i)
                    v   = array.get(keyP, i)
                    c   = array.get(keyK, i)
                    txt = array.get(keyN, i)
                    if i < nKeys - 1
                        for j = i + 1 to nKeys - 1
                            if not array.get(used, j) and math.abs(array.get(keyP, j) - v) <= v * mergePct
                                txt := txt + " · " + array.get(keyN, j)
                                array.set(used, j, true)
                    txt := txt + " " + str.tostring(v, format.mintick)
                    if cdOnMP and cdTxt != "" and str.contains(txt, "Max Pain")
                        txt := txt + " • ⏳ " + cdTxt
                    array.push(lbs, label.new(bar_index + lblOff, v, txt, style=label.style_label_left, color=color.new(c, 65), textcolor=color.white, size=size.small))

// ═══════════════════════ ตารางสถานะ ═══════════════════════
ageH   = tsSel > 0 ? (timenow - tsSel) / 3600000.0 : 0.0
ageTxt = ageH < 48 ? str.tostring(math.round(ageH)) + " ชม." : str.tostring(math.round(ageH / 24)) + " วัน"

var table tb = table.new(position.top_right, 1, 5, border_width=1)
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
        table.cell(tb, 0, 1, assetLbl + " • " + srcS, bgcolor=color.new(color.gray, 30), text_color=color.white, text_size=size.small)
        if expS != ""
            expBg  = expired ? color.new(color.red, 10) : expNear ? color.new(color.orange, 20) : color.new(color.gray, 30)
            expTag = expired ? " • เจนใหม่ด่วน" : expNear ? " • ใกล้หมดอายุ Max Pain ดึงแรง" : ""
            table.cell(tb, 0, 4, "งวด " + expS + " • ⏳ " + cdTxt + expTag, bgcolor=expBg, text_color=color.white, text_size=size.small)
        stale = ageH >= warnH
        ageBg = ageH >= redH ? color.new(color.red, 10) : stale ? color.new(color.orange, 20) : color.new(color.gray, 30)
        table.cell(tb, 0, 2, "ดึงเมื่อ " + str.format_time(tsSel, "dd/MM HH:mm", "Asia/Bangkok") + " • " + ageTxt + (stale ? " • ค่าเก่า" : ""), bgcolor=ageBg, text_color=color.white, text_size=size.small)
        if math.abs(ratio - 1.0) > 0.0005
            table.cell(tb, 0, 3, "ปรับ basis ×" + str.tostring(ratio, "#.####") + " (" + basisHow + ")", bgcolor=color.new(color.gray, 45), text_color=color.white, text_size=size.tiny)

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
var int[]    fBar  = array.new_int()
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
            box.set_text_halign(bx, text.align_right)    // ข้อความชิดขอบขวาของกล่อง ไม่ล้นไปทับป้ายราคา
            box.set_text_valign(bx, text.align_bottom)
        array.push(fBox, bx)
        array.push(fTop, t)
        array.push(fBot, b)
        array.push(fBull, newBull)
        array.push(fIn, false)
        array.push(fName, nm)
        array.push(fBar, bar_index)
        while array.size(fBox) > fvgKeep
            box.delete(array.shift(fBox))
            array.shift(fTop)
            array.shift(fBot)
            array.shift(fBull)
            array.shift(fIn)
            array.shift(fName)
            array.shift(fBar)

if barstate.isconfirmed and array.size(fBox) > 0
    for i = array.size(fBox) - 1 to 0
        t  = array.get(fTop, i)
        b  = array.get(fBot, i)
        bx = array.get(fBox, i)
        box.set_right(bx, bar_index + 3)
        // แตะโซน = แท่งหลังสร้างโซนมี high/low เข้าไปในกล่อง (แค่สัมผัสก็นับ)
        inside = bar_index > array.get(fBar, i) and low <= t and high >= b
        if inside and not array.get(fIn, i)
            array.set(fIn, i, true)
            // ถูกใช้งานแล้ว → จางลง (ยังเห็นตำแหน่ง แต่ไม่แย่งสายตา)
            box.set_bgcolor(bx, color.new(color.gray, 92))
            box.set_border_color(bx, color.new(color.gray, 75))
            box.set_text_color(bx, color.new(color.white, 65))
            if alertsOn
                dir = array.get(fBull, i) ? "ขาขึ้น" : "ขาลง"
                tag = array.get(fName, i) != "" ? " ⭐ ที่ " + array.get(fName, i) : ""
                alert("🎯 " + assetLbl + " เข้าโซน FVG " + dir + tag + " • โหมด" + modeTh, alert.freq_once_per_bar_close)
        mit = bar_index > array.get(fBar, i) and (array.get(fBull, i) ? close < b : close > t)
        if fvgDelMit and mit
            box.delete(bx)
            array.remove(fBox, i)
            array.remove(fTop, i)
            array.remove(fBot, i)
            array.remove(fBull, i)
            array.remove(fIn, i)
            array.remove(fName, i)
            array.remove(fBar, i)
'''
