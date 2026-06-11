import numpy as np
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
    """คำนวณ RSI แบบ rolling average และป้องกันค่า NaN เมื่อ avg_loss = 0"""
    close = pd.Series(close, dtype=float)
    delta = close.diff().fillna(0.0)
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    rs = rs.fillna(np.inf)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.where(rsi.notna(), 50.0)


from typing import Sequence, Union


def calculate_indicators(
    data: Union[pd.DataFrame, str, None] = None,
    period: str = "3mo",
    ma_periods: Sequence[int] = (20, 50),
    rsi_period: int = 14,
    ticker: str | None = None,
) -> pd.DataFrame:
    """ดึงข้อมูลราคาจาก Yahoo Finance แล้วคำนวณ MA และ RSI.

    Args:
        data: ข้อมูลราคาที่ส่งมาเป็น DataFrame หรือ ticker string.
        period: เมื่อ data เป็น ticker จะใช้ period นี้ในการดึงข้อมูล.
        ma_periods: รายการช่วงเวลา MA ที่จะคำนวณ.
        rsi_period: ช่วงเวลา RSI ที่จะคำนวณ.
    """
    source = data if data is not None else ticker or "AAPL"

    if isinstance(source, pd.DataFrame):
        df = source.copy()
        df = normalize_yfinance_columns(df)
    else:
        df = yf.download(source, period=period, progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError(f"ไม่สามารถดึงข้อมูลสำหรับ {source} ได้")
        df = normalize_yfinance_columns(df)

    df = df.copy()
    df["Close"] = pd.to_numeric(df.get("Close", pd.Series(dtype=float)), errors="coerce")
    df = df.dropna(subset=["Close"])
    if df.empty:
        raise ValueError(f"ข้อมูลราคาไม่ถูกต้องสำหรับ {source} (Close เป็น NaN)")

    for period_value in ma_periods:
        df[f"MA_{period_value}"] = compute_ma(df["Close"], period_value)
    df["RSI"] = compute_rsi(df["Close"], rsi_period)

    # Backward-compatible aliases for older callers that expect MA20 / MA50
    if 20 in ma_periods:
        df["MA20"] = df["MA_20"]
    if 50 in ma_periods:
        df["MA50"] = df["MA_50"]

    return df


if __name__ == "__main__":
    ticker = "AAPL"
    df = calculate_indicators(ticker)
    print(df[["Close", "MA_20", "MA_50"]].tail(10))
    print(df["RSI"].tail(5))
