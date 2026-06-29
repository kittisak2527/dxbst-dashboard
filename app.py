import time
import threading
import json
import os
from datetime import datetime

import streamlit as st

# ============================================================
#  CONFIG
# ============================================================
STATUS_FILE = "bot_status.json"   # เขียนโดย "ปุ่มควบคุม" เท่านั้น  (control plane)
LOG_FILE = "bot_log.jsonl"        # เขียนโดย "worker" เท่านั้น       (data plane)
LOOP_INTERVAL = 5                 # รัน strategy ทุกๆ X วินาที
MAX_LOG_LINES = 200               # กันไฟล์ log โตไม่จบ
THREAD_NAME = "TradingBotThread"


# ============================================================
#  STATUS  (control plane: UI -> worker)
# ============================================================
def load_bot_status() -> bool:
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("is_running", False)
    except (FileNotFoundError, json.JSONDecodeError):
        return False


def save_bot_status(is_running: bool) -> None:
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump({"is_running": is_running}, f)


# ============================================================
#  LOGGING  (data plane: worker -> UI)
# ============================================================
def write_log(message: str) -> None:
    record = {"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "msg": message}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_logs(limit: int = 15):
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []

    # ตัด log เก่าทิ้งถ้ายาวเกิน
    if len(lines) > MAX_LOG_LINES:
        lines = lines[-MAX_LOG_LINES:]
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.writelines(lines)

    out = []
    for ln in lines[-limit:]:
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


# ============================================================
#  TRADING WORKER  (background thread)
# ============================================================
def run_strategy() -> str:
    """
    >>> ใส่ logic การเทรดจริงของคุณที่นี่ <<<
    เช่น: ดึงราคา -> คำนวณ indicator -> ตัดสินใจ -> ส่งคำสั่งผ่าน API โบรกเกอร์
    คืนค่าเป็นข้อความสรุปของรอบนี้ เพื่อบันทึกลง log
    """
    return "executing strategy... (placeholder)"


def trading_bot_worker() -> None:
    write_log("✅ Bot started")
    while load_bot_status():
        try:
            write_log(run_strategy())
        except Exception as e:                       # กัน thread ตายเงียบ
            write_log(f"⚠️ error: {e}")

        # sleep แบบหั่นย่อย -> กด "ปิดบอท" แล้วหยุดไว ไม่ต้องรอครบ interval
        for _ in range(LOOP_INTERVAL * 2):
            if not load_bot_status():
                break
            time.sleep(0.5)
    write_log("🛑 Bot stopped")


def ensure_worker_running() -> None:
    """สร้าง thread ใหม่เฉพาะเมื่อยังไม่มีตัวที่รันอยู่ (กัน thread ซ้อน)"""
    if THREAD_NAME not in [t.name for t in threading.enumerate()]:
        threading.Thread(
            target=trading_bot_worker, name=THREAD_NAME, daemon=True
        ).start()


# ============================================================
#  SESSION INIT
# ============================================================
if "bot_running" not in st.session_state:
    st.session_state.bot_running = load_bot_status()

# ถ้าไฟล์บอกว่า "เปิดอยู่" แต่ thread หาย (เช่น เซิร์ฟเวอร์เพิ่ง restart) -> ปลุกกลับ
if st.session_state.bot_running:
    ensure_worker_running()


# ============================================================
#  UI
# ============================================================
st.title("🤖 Trading Bot Control Panel")

status_text = "🟢 กำลังรัน" if st.session_state.bot_running else "🔴 ปิดทำงาน"
st.subheader(f"สถานะปัจจุบัน: {status_text}")

col1, col2 = st.columns(2)
with col1:
    if st.button("▶️ เปิดบอท", disabled=st.session_state.bot_running,
                 use_container_width=True):
        save_bot_status(True)
        st.session_state.bot_running = True
        ensure_worker_running()
        st.rerun()
with col2:
    if st.button("⏹️ ปิดบอท", disabled=not st.session_state.bot_running,
                 use_container_width=True):
        save_bot_status(False)
        st.session_state.bot_running = False
        st.rerun()

st.divider()


# ---- LIVE LOG: อัปเดตเองทุก 2 วิ โดยไม่รีเฟรชทั้งหน้า (ต้องใช้ Streamlit >= 1.37) ----
@st.fragment(run_every="2s")
def live_panel():
    logs = read_logs(limit=15)
    if logs:
        st.caption(f"💓 heartbeat ล่าสุด: {logs[-1]['ts']}")
        body = "\n".join(f"[{x['ts']}] {x['msg']}" for x in reversed(logs))
        st.code(body, language=None)
    else:
        st.caption("ยังไม่มี log")


live_panel()
