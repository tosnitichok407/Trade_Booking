"""
alert.py
ระบบแจ้งเตือนหุ้นผ่าน Telegram
เช็ค RSI และ MA แล้วส่งแจ้งเตือนอัตโนมัติ
"""

import os
import requests
import schedule
import time

from indicators import calculate_indicators as build_indicators

# ==========================================
# ตั้งค่าตรงนี้
# ==========================================
# หุ้นที่ต้องการติดตาม
WATCHLIST = ["AAPL", "MSFT", "TSLA", "NVDA", "AMD", "INTC"]

# เงื่อนไขแจ้งเตือน
RSI_OVERSOLD = 30       # RSI ต่ำกว่านี้ = แจ้งเตือน "อาจขึ้น"
RSI_OVERBOUGHT = 70     # RSI สูงกว่านี้ = แจ้งเตือน "อาจลง"
# ==========================================

def load_env_file(path: str = ".env"):
    """โหลดค่า KEY=VALUE จากไฟล์ .env แบบง่าย ๆ โดยไม่ต้องติดตั้ง library เพิ่ม"""
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def get_telegram_config() -> tuple[str, str]:
    """อ่านค่า Telegram token และ chat id จาก environment"""
    load_env_file()
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "กรุณาตั้งค่า TELEGRAM_TOKEN และ TELEGRAM_CHAT_ID ใน environment หรือไฟล์ .env"
        )
    return token, chat_id


def send_telegram(message: str):
    """ส่งข้อความไปยัง Telegram"""
    token, chat_id = get_telegram_config()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print(f"ส่งแจ้งเตือนสำเร็จ")
        else:
            print(f"ส่งไม่สำเร็จ: {response.text}")
    except Exception as e:
        print(f"Error: {e}")


def calculate_indicators(ticker: str) -> dict:
    """ดึงข้อมูลและคำนวณ indicators"""
    try:
        df = build_indicators(ticker, period="3mo")
    except ValueError:
        return None

    # ดึงค่าล่าสุด
    latest = df.iloc[-1]

    return {
        "ticker": ticker,
        "price": round(float(latest["Close"]), 2),
        "rsi": round(float(latest["RSI"]), 2),
        "ma20": round(float(latest["MA20"]), 2),
        "ma50": round(float(latest["MA50"]), 2),
    }


def check_alerts():
    """เช็คทุกหุ้นใน Watchlist และส่งแจ้งเตือนถ้าเข้าเงื่อนไข"""
    print(f"\nกำลังเช็คหุ้น...")

    for ticker in WATCHLIST:
        data = calculate_indicators(ticker)

        if data is None:
            print(f"{ticker}: ดึงข้อมูลไม่ได้")
            continue

        print(f"{ticker} | ราคา: {data['price']} | RSI: {data['rsi']}")

        alerts = []

        # เช็ค RSI Oversold
        if data["rsi"] < RSI_OVERSOLD:
            alerts.append(f"🟢 RSI = {data['rsi']} (Oversold — อาจขึ้น)")

        # เช็ค RSI Overbought
        if data["rsi"] > RSI_OVERBOUGHT:
            alerts.append(f"🔴 RSI = {data['rsi']} (Overbought — อาจลง)")

        # เช็ค MA Crossover (MA20 ตัด MA50 ขึ้น)
        if data["ma20"] > data["ma50"]:
            alerts.append(f"📈 MA20 ({data['ma20']}) อยู่เหนือ MA50 ({data['ma50']}) — แนวโน้มขาขึ้น")

        # ถ้ามี alert ให้ส่ง Telegram
        if alerts:
            message = (
                f"<b>🔔 Stock Alert: {ticker}</b>\n"
                f"💰 ราคา: {data['price']}\n\n"
                + "\n".join(alerts)
            )
            send_telegram(message)
        else:
            print(f"{ticker}: ไม่มีสัญญาณ")


def test_connection():
    """ทดสอบการเชื่อมต่อ Telegram"""
    send_telegram("✅ ระบบ Stock Alert เริ่มทำงานแล้ว!")


if __name__ == "__main__":
    load_env_file()
    print("=== Stock Alert System ===")

    # ทดสอบการเชื่อมต่อก่อน
    test_connection()

    # เช็คทันทีตอนเริ่มรัน
    check_alerts()

    # ตั้งให้เช็คซ้ำทุก 30 นาที
    schedule.every(30).minutes.do(check_alerts)

    print("\nระบบทำงานแล้ว เช็คทุก 30 นาที (กด Ctrl+C เพื่อหยุด)")

    while True:
        schedule.run_pending()
        time.sleep(1)
