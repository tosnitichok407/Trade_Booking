"""
ืทดสอบการใช้งาน RSI Strategy ย้อนหลัง
ซื้อเมื่อ RSI ต่ำกว่า 30 และขายเมื่อ RSI สูงกว่า 70
"""
import yfinance as yf
from backtesting import Backtest, Strategy

from indicators import compute_rsi, normalize_yfinance_columns


class RsiStrategy(Strategy):
    """
    RSI Strategy
    - ซื้อเมื่อ RSI ต่ำกว่า oversold
    - ขายเมื่อ RSI สูงกว่า overbought
    """
    rsi_period = 14
    oversold = 30
    overbought = 70

    def init(self):
        self.rsi = self.I(compute_rsi, self.data.Close, self.rsi_period)

    def next(self):
        if self.rsi[-1] < self.oversold and not self.position:
            self.buy()
        elif self.rsi[-1] > self.overbought and self.position:
            self.position.close()


if __name__ == "__main__":
    # หุ้นที่จะทดสอบ
    tickers = ["AAPL", "MSFT", "PTT.BK"]

    # RSI threshold ที่จะทดสอบ
    combinations = [
        {"oversold": 30, "overbought": 70, "label": "RSI 30/70 (มาตรฐาน)"},
        {"oversold": 35, "overbought": 65, "label": "RSI 35/65 (เร็วขึ้น)"},
        {"oversold": 25, "overbought": 75, "label": "RSI 25/75 (เข้มขึ้น)"},
    ]

    print("\n" + "="*70)
    print("เปรียบเทียบ RSI Strategy หลาย threshold และหลายหุ้น")
    print("="*70)

    for ticker in tickers:
        print(f"\n📊 หุ้น: {ticker}")
        print("-"*70)

        df = yf.download(ticker, period="2y", progress=False, auto_adjust=True)
        df = normalize_yfinance_columns(df)
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

        if df.empty:
            print(f"ดึงข้อมูล {ticker} ไม่ได้")
            continue

        for c in combinations:
            bt = Backtest(df, RsiStrategy, cash=100_000, commission=0.002)
            results = bt.run(oversold=c["oversold"], overbought=c["overbought"])

            print(
                f"{c['label']} | "
                f"Return: {results['Return [%]']:>7.2f}% | "
                f"Trades: {int(results['# Trades']):>3} | "
                f"Win: {results['Win Rate [%]']:>6.2f}% | "
                f"Drawdown: {results['Max. Drawdown [%]']:>7.2f}%"
            )

    print("หมายเหตุ: ผลในอดีตไม่ได้การันตีอนาคต")
