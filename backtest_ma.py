"""
backtest_ma.py
ทดสอบ MA Crossover Strategy ย้อนหลัง
ซื้อเมื่อ MA20 ตัด MA50 ขึ้น, ขายเมื่อ MA20 ตัด MA50 ลง
เปรียบเทียบกับ RSI Strategy
"""

import yfinance as yf
import pandas as pd
from backtesting import Backtest, Strategy
from backtesting.lib import crossover


def compute_ma(close, period):
    """คำนวณ Moving Average"""
    return pd.Series(close).rolling(period).mean()


class MaCrossStrategy(Strategy):
    """
    MA Crossover Strategy
    - ซื้อเมื่อ MA20 ตัด MA50 ขึ้น (แนวโน้มขาขึ้น)
    - ขายเมื่อ MA20 ตัด MA50 ลง (แนวโน้มขาลง)
    """
    ma_fast = 20    # MA ระยะสั้น
    ma_slow = 50    # MA ระยะยาว

    def init(self):
        self.ma20 = self.I(compute_ma, self.data.Close, self.ma_fast)
        self.ma50 = self.I(compute_ma, self.data.Close, self.ma_slow)

    def next(self):
        # MA20 ตัด MA50 ขึ้น → ซื้อ
        if crossover(self.ma20, self.ma50):
            self.buy()

        # MA20 ตัด MA50 ลง → ขาย
        elif crossover(self.ma50, self.ma20):
            self.position.close()


if __name__ == "__main__":
    # หุ้นที่จะทดสอบ (เหมือนกับ RSI เพื่อเปรียบเทียบ)
    tickers = ["AAPL", "MSFT", "PTT.BK"]

    # MA combinations ที่จะทดสอบ
    combinations = [
        {"ma_fast": 20, "ma_slow": 50,  "label": "MA20/50  (เดิม)    "},
        {"ma_fast": 10, "ma_slow": 30,  "label": "MA10/30  (เร็วขึ้น) "},
        {"ma_fast": 50, "ma_slow": 200, "label": "MA50/200 (ช้าลง)   "},
    ]

    print("\n" + "="*70)
    print("เปรียบเทียบ MA Crossover Strategy หลาย combination และหลายหุ้น")
    print("="*70)

    for ticker in tickers:
        print(f"\n📊 หุ้น: {ticker}")
        print("-"*70)

        df = yf.download(ticker, period="2y", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

        if df.empty:
            print(f"ดึงข้อมูล {ticker} ไม่ได้")
            continue

        for c in combinations:
            bt = Backtest(df, MaCrossStrategy, cash=100_000, commission=0.002)
            results = bt.run(ma_fast=c["ma_fast"], ma_slow=c["ma_slow"])

            print(
                f"{c['label']} | "
                f"Return: {results['Return [%]']:>7.2f}% | "
                f"Trades: {int(results['# Trades']):>3} | "
                f"Win: {results['Win Rate [%]']:>6.2f}% | "
                f"Drawdown: {results['Max. Drawdown [%]']:>7.2f}%"
            )

    print("\n" + "="*70)
    print("เปรียบเทียบกับ RSI Strategy (แบบที่ 2 ที่ดีที่สุด)")
    print("="*70)
    print("AAPL   RSI 35/65  | Return:   63.45% | Trades:  11 | Win:  90.91% | Drawdown:  -11.45%")
    print("MSFT   RSI 35/65  | Return:  -13.15% | Trades:   7 | Win:  57.14% | Drawdown:  -31.10%")
    print("PTT.BK RSI 35/65  | Return:   42.87% | Trades:   8 | Win:  87.50% | Drawdown:  -11.11%")
    print("\nหมายเหตุ: ผลในอดีตไม่ได้การันตีอนาคต")
