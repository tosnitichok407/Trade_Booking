import mplfinance as mpf
import yfinance as yf
import pandas as pd


def load_price_data(ticker: str = "AAPL", period: str = "3mo") -> pd.DataFrame:
    """ดึงข้อมูลราคาจาก Yahoo Finance"""
    df = yf.download(ticker, period=period, progress=False)
    if df.empty:
        raise ValueError(f"ไม่สามารถดึงข้อมูลสำหรับ {ticker} ได้")
    return df


if __name__ == "__main__":
    ticker = "AAPL"
    df = load_price_data(ticker)

    # วาด candlestick + Volume
    mpf.plot(
        df.tail(60),    # 60 วันล่าสุด
        type="candle",  # แบบกราฟแท่งเทียน
        volume=True,   # แสดงกราฟปริมาณการซื้อขาย
        mav=(20, 50),   # แสดงค่าเฉลี่ยเคลื่อนที่ 20 วันและ 50 วัน
        style="yahoo",  # ใช้สไตล์กราฟแบบ Yahoo Finance
        title=f"{ticker} - 60 Days"
    )