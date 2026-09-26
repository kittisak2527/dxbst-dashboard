"""เก็บ snapshot ล่าสุดที่ "ดึงสำเร็จ" ของแต่ละสินทรัพย์ (carry-forward)

หลักคิด: ทอง/ยูโร (Yahoo) บางรอบดึงไม่มา -> ไม่ทิ้ง BTC รอ แต่ใช้ค่าเก่าที่ดีล่าสุด พร้อมเวลากำกับ
- เก็บเป็นไฟล์ JSON ในเซิร์ฟเวอร์ (อยู่ได้ตราบที่แอปยังไม่หลับ/รีบูต)
- สำรองถาวร: ทุกโค้ด Pine ที่เจนจะฝังบรรทัด `// SNAPSHOT_JSON:` ไว้
  ถ้าเซิร์ฟเวอร์ลืม -> วางโค้ดเก่าที่เคยก็อปกลับมา กู้ค่าได้
"""
import json
import os
from pathlib import Path

STORE = Path(__file__).parent / ".cache" / "levels_snapshot.json"
ASSETS = ("BTC", "XAU", "EUR")
MARK = "// SNAPSHOT_JSON:"


def empty():
    return {k: None for k in ASSETS}


def load():
    try:
        d = json.loads(STORE.read_text("utf-8"))
        return {k: d.get(k) for k in ASSETS}
    except Exception:
        return empty()


def save(snaps):
    try:
        STORE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STORE.with_suffix(".tmp")
        tmp.write_text(json.dumps(snaps, ensure_ascii=False), "utf-8")
        os.replace(tmp, STORE)
        return True
    except Exception:
        return False


def merge_newer(base, incoming):
    """รวมเฉพาะสินทรัพย์ที่ incoming ใหม่กว่า (ไม่เอาของเก่าไปทับของใหม่)"""
    out = dict(base)
    for k in ASSETS:
        s = (incoming or {}).get(k)
        if s and (not out.get(k) or s.get("ts_ms", 0) > out[k].get("ts_ms", 0)):
            out[k] = s
    return out


def dump_line(snaps):
    return MARK + json.dumps(snaps, ensure_ascii=False, separators=(",", ":"))


def parse_from_code(code):
    for line in (code or "").splitlines():
        line = line.strip()
        if line.startswith(MARK):
            try:
                d = json.loads(line[len(MARK):])
                return {k: d.get(k) for k in ASSETS}
            except Exception:
                return None
    return None
