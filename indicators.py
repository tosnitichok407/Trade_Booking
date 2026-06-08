import pandas as pd
import yfinance as yf


def normalize_yfinance_columns(df: pd.DataFrame) -> pd.DataFrame:
    """แปลงคอลัมน์ MultiIndex จาก yfinance ให้เป็นคอลัมน์ชั้นเดียว"""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def compute_ma(close, period: int) -> pd.Series:
    """คำนวณ Moving Average"""
    return pd.Series(close).rolling(window=period).mean()


def compute_rsi(close, period: int = 14) -> pd.Series:
    """คำนวณ RSI แบบ rolling average"""
    close = pd.Series(close)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


from typing import Sequence, Union

def calculate_indicators(
    data: Union[pd.DataFrame, str] = "AAPL",
    period: str = "3mo",
    ma_periods: Sequence[int] = (20, 50),
    rsi_period: int = 14,
) -> pd.DataFrame:
    """ดึงข้อมูลราคาจาก Yahoo Finance แล้วคำนวณ MA และ RSI.

    Args:
        data: ข้อมูลราคาที่ส่งมาเป็น DataFrame หรือ ticker string.
        period: เมื่อ data เป็น ticker จะใช้ period นี้ในการดึงข้อมูล.
        ma_periods: รายการช่วงเวลา MA ที่จะคำนวณ.
        rsi_period: ช่วงเวลา RSI ที่จะคำนวณ.
    """
    if isinstance(data, pd.DataFrame):
        df = data.copy()
        df = normalize_yfinance_columns(df)
    else:
        df = yf.download(data, period=period, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"ไม่สามารถดึงข้อมูลสำหรับ {data} ได้")
        df = normalize_yfinance_columns(df)

    for period_value in ma_periods:
        df[f"MA_{period_value}"] = compute_ma(df["Close"], period_value)
    df["RSI"] = compute_rsi(df["Close"], rsi_period)

    return df


if __name__ == "__main__":
    ticker = "AAPL"
    df = calculate_indicators(ticker)
    print(df[["Close", "MA_20", "MA_50"]].tail(10))
    print(df["RSI"].tail(5))
