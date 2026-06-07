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


def calculate_indicators(ticker: str = "AAPL", period: str = "3mo") -> pd.DataFrame:
    """ดึงข้อมูลราคาจาก Yahoo Finance แล้วคำนวณ MA และ RSI"""
    df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"ไม่สามารถดึงข้อมูลสำหรับ {ticker} ได้")

    df = normalize_yfinance_columns(df)
    df["MA20"] = compute_ma(df["Close"], 20)
    df["MA50"] = compute_ma(df["Close"], 50)
    df["RSI"] = compute_rsi(df["Close"], 14)

    return df


if __name__ == "__main__":
    ticker = "AAPL"
    df = calculate_indicators(ticker)
    print(df[["Close", "MA20", "MA50"]].tail(10))
    print(df["RSI"].tail(5))
