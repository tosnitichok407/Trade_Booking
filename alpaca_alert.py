"""
alpaca_bot.py
ระบบเทรดอัตโนมัติด้วย Alpaca Paper Trading
- ซื้อเมื่อ RSI < 35 (Oversold)
- ขายเมื่อ RSI > 65 (Overbought)
- ครั้งละ 1 หุ้น
- ส่งแจ้งเตือนผ่าน Telegram ทุกครั้งที่ซื้อ/ขาย
- รันอัตโนมัติทุก 30 นาที เฉพาะวันจันทร์-ศุกร์
"""

import os
import io
import time
import schedule
import requests
import yfinance as yf
import pandas as pd
import mplfinance as mpf
from datetime import datetime
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

# โหลดค่าจาก .env
load_dotenv()

ALPACA_API_KEY    = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
TELEGRAM_TOKEN    = os.getenv("TELEGRAM_TOKEN")
CHAT_ID           = os.getenv("TELEGRAM_CHAT_ID")

# รายชื่อหุ้นที่ต้องการติดตาม
WATCHLIST = ["AAPL", "MSFT", "TSLA", "NVDA"]

# เงื่อนไขซื้อขาย
RSI_BUY   = 35   # ซื้อเมื่อ RSI ต่ำกว่านี้
RSI_SELL  = 65   # ขายเมื่อ RSI สูงกว่านี้
QTY       = 1    # จำนวนหุ้นต่อออเดอร์


def get_client() -> TradingClient:
    """สร้าง Alpaca Trading Client"""
    return TradingClient(
        api_key=ALPACA_API_KEY,
        secret_key=ALPACA_SECRET_KEY,
        paper=True,  # Paper Trading เสมอ
    )


def get_account_info(client: TradingClient) -> dict:
    """ดึงข้อมูลบัญชี"""
    account = client.get_account()
    return {
        "portfolio_value": float(account.portfolio_value),
        "cash":            float(account.cash),
        "buying_power":    float(account.buying_power),
    }


def get_position(client: TradingClient, ticker: str) -> float:
    """ดูว่าถือหุ้นตัวนี้อยู่กี่หุ้น (0 = ไม่ถือ)"""
    try:
        position = client.get_open_position(ticker)
        return float(position.qty)
    except Exception:
        return 0.0


def place_order(client: TradingClient, ticker: str, side: OrderSide) -> dict:
    """ส่งคำสั่งซื้อหรือขาย"""
    order = MarketOrderRequest(
        symbol=ticker,
        qty=QTY,
        side=side,
        time_in_force=TimeInForce.DAY,
    )
    result = client.submit_order(order)
    return {
        "id":     str(result.id),
        "symbol": result.symbol,
        "side":   result.side,
        "qty":    result.qty,
        "status": result.status,
    }


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """คำนวณ RSI"""
    delta    = close.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs       = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def analyze(ticker: str) -> dict:
    """ดึงข้อมูลและคำนวณ indicator"""
    df = yf.download(ticker, period="3mo", progress=False, auto_adjust=True)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df["MA20"] = df["Close"].rolling(20).mean()
    df["MA50"] = df["Close"].rolling(50).mean()
    df["RSI"]  = compute_rsi(df["Close"])

    latest = df.iloc[-1]
    return {
        "ticker": ticker,
        "price":  round(float(latest["Close"]), 2),
        "rsi":    round(float(latest["RSI"]),   2),
        "ma20":   round(float(latest["MA20"]),  2),
        "ma50":   round(float(latest["MA50"]),  2),
        "df":     df,
    }


def build_chart(df: pd.DataFrame, ticker: str) -> bytes:
    """วาดกราฟ candlestick คืนค่าเป็น bytes"""
    buf = io.BytesIO()
    mpf.plot(
        df.tail(60),
        type="candle",
        volume=True,
        mav=(20, 50),
        style="yahoo",
        title=f"{ticker} — 60 Days",
        savefig=dict(fname=buf, dpi=100, bbox_inches="tight"),
    )
    buf.seek(0)
    return buf.read()


def build_links(ticker: str) -> str:
    """สร้างลิ้งค์ Yahoo Finance และ TradingView"""
    yahoo       = f"https://finance.yahoo.com/quote/{ticker}"
    tradingview = f"https://www.tradingview.com/chart/?symbol={ticker}"
    return (
        f'📊 <a href="{yahoo}">Yahoo Finance</a>  |  '
        f'📈 <a href="{tradingview}">TradingView</a>'
    )


def send_telegram_photo(image_bytes: bytes, caption: str):
    """ส่งรูปกราฟพร้อม caption ไปยัง Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        response = requests.post(
            url,
            data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
            files={"photo": ("chart.png", image_bytes, "image/png")},
        )
        if response.status_code == 200:
            print("ส่ง Telegram สำเร็จ")
        else:
            print(f"ส่ง Telegram ไม่สำเร็จ: {response.text}")
    except Exception as error:
        print(f"Telegram error: {error}")


def run():
    """รันระบบเทรดอัตโนมัติหนึ่งรอบ"""
    client  = get_client()
    account = get_account_info(client)
    print(f"Portfolio: ${account['portfolio_value']:,.2f} | Cash: ${account['cash']:,.2f}")

    for ticker in WATCHLIST:
        print(f"กำลังวิเคราะห์ {ticker}...")
        try:
            data     = analyze(ticker)
            position = get_position(client, ticker)
            rsi      = data["rsi"]
            price    = data["price"]

            print(f"{ticker} | ราคา: ${price} | RSI: {rsi} | ถือ: {position} หุ้น")

            action  = None
            emoji   = ""
            caption = ""

            # สัญญาณซื้อ — RSI ต่ำกว่า 35 และยังไม่ได้ถือหุ้นอยู่
            if rsi < RSI_BUY and position == 0:
                order  = place_order(client, ticker, OrderSide.BUY)
                action = "ซื้อ"
                emoji  = "🟢"
                print(f"✅ สั่งซื้อ {ticker} {QTY} หุ้น | Order ID: {order['id']}")

            # สัญญาณขาย — RSI สูงกว่า 65 และถือหุ้นอยู่
            elif rsi > RSI_SELL and position > 0:
                order  = place_order(client, ticker, OrderSide.SELL)
                action = "ขาย"
                emoji  = "🔴"
                print(f"✅ สั่งขาย {ticker} {QTY} หุ้น | Order ID: {order['id']}")

            else:
                print(f"{ticker}: ไม่มีสัญญาณ")
                continue

            # ส่ง Telegram พร้อมกราฟและลิ้งค์
            chart   = build_chart(data["df"], ticker)
            links   = build_links(ticker)
            caption = (
                f"<b>{emoji} Bot {action}: {ticker}</b>\n"
                f"💰 ราคา: ${price}\n"
                f"📊 RSI: {rsi}\n"
                f"📈 MA20: {data['ma20']} | MA50: {data['ma50']}\n"
                f"🔢 จำนวน: {QTY} หุ้น\n\n"
                f"<b>💼 Portfolio: ${account['portfolio_value']:,.2f}</b>\n"
                + links
            )
            send_telegram_photo(chart, caption)

        except Exception as error:
            print(f"{ticker}: error — {error}")


def run_scheduler():
    """รันเฉพาะวันจันทร์-ศุกร์"""
    now = datetime.now()
    print(f"\n[{now.strftime('%Y-%m-%d %H:%M:%S')}] กำลังเช็คสัญญาณ...")

    if now.weekday() < 5:
        run()
    else:
        print("ตลาดปิด (เสาร์-อาทิตย์) ข้ามไป")


if __name__ == "__main__":
    print("=== Alpaca Auto Trading Bot ===")
    print(f"หุ้นที่ติดตาม: {', '.join(WATCHLIST)}")
    print(f"ซื้อเมื่อ RSI < {RSI_BUY} | ขายเมื่อ RSI > {RSI_SELL}")
    print(f"จำนวนต่อออเดอร์: {QTY} หุ้น")
    print("รันทุก 30 นาที เฉพาะวันจันทร์-ศุกร์")
    print("กด Ctrl+C เพื่อหยุด\n")

    # รันทันทีตอนเริ่ม
    run_scheduler()

    # ตั้ง schedule ทุก 30 นาที
    schedule.every(30).minutes.do(run_scheduler)

    while True:
        schedule.run_pending()
        time.sleep(1)
