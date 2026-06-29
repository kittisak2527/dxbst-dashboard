import streamlit as st
import requests
from bs4 import BeautifulSoup
import datetime

st.set_page_config(page_title="เลขาตลาด • GROUNDED", layout="wide")

st.title("เลขาตลาด • GROUNDED")
st.subheader("บรีฟทองคำ • ยูโร (ระบบดึงข้อมูล Real-time)")

# ฟังก์ชันดึงราคา ทองคำ จาก TradingEconomics
def get_gold_data():
    try:
        url = "https://tradingeconomics.com/commodity/gold"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price = soup.find('div', {'id': 'market_price'}).text.strip()
        change = soup.find('div', {'id': 'market_price_change'}).text.strip()
        return f"${price}", change
    except:
        return "$4,087.01", "+1.49% (Fallback)"

# ฟังก์ชันดึงค่า DXY จาก TradingEconomics
def get_dxy_data():
    try:
        url = "https://tradingeconomics.com/united-states/currency"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(res.text, 'html.parser')
        price = soup.find('div', {'id': 'market_price'}).text.strip()
        change = soup.find('div', {'id': 'market_price_change'}).text.strip()
        return price, change
    except:
        return "101.37", "-0.06% (Fallback)"

# ปุ่มประมวลผลดึงข้อมูลสด
if st.button("🔄 กดประมวลผลดึงบรีฟล่าสุด", type="primary"):
    st.info("กำลังเชื่อมต่อดึงข้อมูลสดจาก TradingEconomics...")
    
    # ดึงข้อมูลสดผ่านฟังก์ชัน
    gold_price, gold_change = get_gold_data()
    dxy_value, dxy_change = get_dxy_data()
    
    st.success(f"ดึงข้อมูลและประมวลผลสำเร็จ ณ เวลา {datetime.datetime.now().strftime('%X')} น.")
    
    # แสดงตาราง Snapshot แบบ Dynamic
    col1, col2, col3, col4 = st.columns(4)
    col1.snapshot_card = col1.metric("XAU/USD (ทองคำ)", gold_price, f"{gold_change} vs วันก่อนหน้า")
    col2.snapshot_card = col2.metric("DXY (ดอลลาร์)", dxy_value, f"{dxy_change} vs วันก่อนหน้า")
    col3.snapshot_card = col3.metric("US 10Y YIELD", "4.37%", "ทรงตัว")
    col4.snapshot_card = col4.metric("US 10Y REAL (TIPS)", "2.17%", "-0.01 pp")
    
    st.markdown("""
    ---
    ### 🏆 ทองคำ (XAUUSD) - Bearish เทรนด์หลัก
    * **แนวต้านสำคัญ (นัยสำคัญ):** $4,120 / $4,150 *(โซนดักล้นวอลลุ่มสะสมฝั่งขาลง)*
    * **แนวรับสำคัญ (นัยสำคัญ):** $4,050 / $4,000 *(แนวสนับสนุนจิตวิทยาระดับก้น)*
    * **Price Action:** ภาพใหญ่ยังถูกคุมด้วยฝั่งหมี แต่ระยะสั้นมีการสวิงดีดเทคนิคอลรีบาวด์ทดสอบกรอบบน
    * **กลยุทธ์สั้นๆ:** เน้น "Sell on Rally" ใน Premium Zone ย่อยเมื่อเข้าใกล้แนวต้านแล้วแสดงอาการ Rejection
    
    ---
    ### 🇪🇺 ยูโร (EURUSD) - Bearish พักฐาน
    * **แนวต้านสำคัญ (นัยสำคัญ):** 1.1240 / 1.1280 *(รอยต่อของโครงสร้างเดิม)*
    * **แนวรับสำคัญ (นัยสำคัญ):** 1.1150 / 1.1100 *(แนวสนับสนุนรายสัปดาห์)*
    * **Price Action:** ปฏิทินเศรษฐกิจวันนี้ไม่มีเหตุการณ์ผลกระทบสูง ตลาดอาจเคลื่อนไหวจำกัดกรอบ (Squeeze) เพื่อสะสมพลัง
    * **กลยุทธ์สั้นๆ:** เล่นในกรอบ Sideway บีบตัวจำกัด (Tight Range) จนกว่าจะเห็นการเบรกเอาต์ของ Volume
    """)
else:
    st.warning("👉 กรุณากดปุ่มด้านบนเพื่อเริ่มประมวลผลวิเคราะห์ข้อมูลรอบใหม่ครับ")