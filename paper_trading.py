"""
paper_trading.py — Paper Trading System (Combined RSI + MA Strategy)
- เงินทุนเริ่มต้น: $100,000
- กลยุทธ์: Combined RSI + MA Crossover
- บันทึก trade แต่ละครั้ง (เข้า/ออก)
- สรุปกำไร-ขาดทุนรายหุ้น
- แจ้งเตือนผ่าน Telegram (ถ้าเปิดใช้)
- แสดงกราฟผลลัพธ์

Usage:
    .venv/bin/python paper_trading.py
    .venv/bin/python paper_trading.py --tickers AAPL,MSFT,TSLA --period 6mo
    .venv/bin/python paper_trading.py --send-telegram
    .venv/bin/python paper_trading.py --reset   # ล้าง portfolio แล้วเริ่มใหม่
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

from indicators import (
    calculate_indicators,
    normalize_yfinance_columns,
)

# ─────────────────────────────────────────────
# CONFIG — แก้ไขได้ที่นี่
# ─────────────────────────────────────────────
INITIAL_CAPITAL = 100_000.0          # เงินทุนเริ่มต้น USD
POSITION_SIZE_PCT = 0.10             # ลงทุนต่อหุ้น 10% ของ portfolio
DEFAULT_TICKERS = ["AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
DEFAULT_PERIOD = "6mo"               # ช่วงเวลาดึงข้อมูล yfinance

# RSI thresholds
RSI_BUY = 35     # RSI ต่ำกว่า = zone ซื้อ
RSI_SELL = 65       # RSI สูงกว่า = zone ขาย

# MA periods
MA_SHORT = 20
MA_LONG = 50

# ไฟล์เก็บสถานะ
STATE_FILE = Path("paper_trading_state.json")
REPORT_DIR = Path("reports")

load_dotenv()

# ─────────────────────────────────────────────
# STATE MANAGEMENT
# ─────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "cash": INITIAL_CAPITAL,
        "positions": {},      # ticker -> {shares, avg_cost, entry_date}
        "trade_log": [],      # list of trade records
        "created_at": datetime.now().isoformat(),
    }


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def reset_state():
    if STATE_FILE.exists():
        STATE_FILE.unlink()
    print("✅ Portfolio ถูก reset แล้ว เริ่มต้นด้วยเงิน $100,000")


# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────

def send_telegram(message: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️  Telegram ไม่ได้ตั้งค่า (TELEGRAM_TOKEN / TELEGRAM_CHAT_ID)")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
        if resp.status_code == 200:
            print("📨 ส่ง Telegram แล้ว")
        else:
            print(f"⚠️  Telegram error: {resp.text}")
    except Exception as e:
        print(f"⚠️  Telegram exception: {e}")


# ─────────────────────────────────────────────
# SIGNAL GENERATION (Combined RSI + MA)
# ─────────────────────────────────────────────

def get_signal(df: pd.DataFrame) -> str:
    """
    BUY  = MA_SHORT ตัด MA_LONG ขึ้น (golden cross) AND RSI < RSI_BUY
    SELL = MA_SHORT ตัด MA_LONG ลง (death cross)  OR  RSI > RSI_SELL
    HOLD = อื่นๆ
    """
    if len(df) < MA_LONG + 2:
        return "HOLD"

    row = df.iloc[-1]
    prev = df.iloc[-2]

    ma_short_col = f"MA_{MA_SHORT}"
    ma_long_col = f"MA_{MA_LONG}"

    if ma_short_col not in df.columns or ma_long_col not in df.columns or "RSI" not in df.columns:
        return "HOLD"

    golden_cross = (prev[ma_short_col] <= prev[ma_long_col]) and (row[ma_short_col] > row[ma_long_col])
    death_cross = (prev[ma_short_col] >= prev[ma_long_col]) and (row[ma_short_col] < row[ma_long_col])
    rsi_oversold = row["RSI"] < RSI_BUY
    rsi_overbought = row["RSI"] > RSI_SELL

    if golden_cross and rsi_oversold:
        return "BUY"
    if death_cross or rsi_overbought:
        return "SELL"
    return "HOLD"


# ─────────────────────────────────────────────
# CORE TRADING LOGIC
# ─────────────────────────────────────────────

def run_paper_trading(tickers: list[str], period: str, send_tg: bool, state: dict) -> dict:
    summary_lines = []
    trades_this_run = []

    for ticker in tickers:
        print(f"\n📈 กำลังวิเคราะห์ {ticker} ...")
        try:
            raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
            if raw.empty:
                print(f"  ⚠️  ไม่มีข้อมูล {ticker}")
                continue

            df = normalize_yfinance_columns(raw)
            df = calculate_indicators(df, ma_periods=[MA_SHORT, MA_LONG], rsi_period=14)
            df.dropna(inplace=True)

            price = float(df["Close"].iloc[-1])
            signal = get_signal(df)
            date_str = str(df.index[-1].date())
            rsi_val = float(df["RSI"].iloc[-1])
            ma_s = float(df[f"MA_{MA_SHORT}"].iloc[-1])
            ma_l = float(df[f"MA_{MA_LONG}"].iloc[-1])

            position = state["positions"].get(ticker)
            action_taken = None

            # ─── BUY ───
            if signal == "BUY" and position is None:
                portfolio_value = state["cash"] + sum(
                    state["positions"][t]["shares"] * float(yf.download(t, period="1d", progress=False)["Close"].iloc[-1])
                    for t in state["positions"]
                    if state["positions"][t]
                ) if state["positions"] else state["cash"]
                invest_amount = portfolio_value * POSITION_SIZE_PCT
                shares = int(invest_amount / price)

                if shares > 0 and state["cash"] >= shares * price:
                    cost = shares * price
                    state["cash"] -= cost
                    state["positions"][ticker] = {
                        "shares": shares,
                        "avg_cost": price,
                        "entry_date": date_str,
                    }
                    trade = {
                        "date": date_str,
                        "ticker": ticker,
                        "action": "BUY",
                        "price": price,
                        "shares": shares,
                        "value": cost,
                        "rsi": rsi_val,
                        "ma_short": ma_s,
                        "ma_long": ma_l,
                        "pnl": None,
                    }
                    state["trade_log"].append(trade)
                    trades_this_run.append(trade)
                    action_taken = f"🟢 BUY  {ticker}: {shares} หุ้น @ ${price:.2f} (รวม ${cost:,.2f})"
                    print(f"  {action_taken}")

            # ─── SELL ───
            elif signal == "SELL" and position is not None:
                shares = position["shares"]
                revenue = shares * price
                pnl = revenue - (shares * position["avg_cost"])
                pnl_pct = (pnl / (shares * position["avg_cost"])) * 100

                state["cash"] += revenue
                del state["positions"][ticker]

                trade = {
                    "date": date_str,
                    "ticker": ticker,
                    "action": "SELL",
                    "price": price,
                    "shares": shares,
                    "value": revenue,
                    "rsi": rsi_val,
                    "ma_short": ma_s,
                    "ma_long": ma_l,
                    "pnl": pnl,
                    "pnl_pct": pnl_pct,
                }
                state["trade_log"].append(trade)
                trades_this_run.append(trade)
                emoji = "🔴" if pnl < 0 else "🟡"
                action_taken = (
                    f"{emoji} SELL {ticker}: {shares} หุ้น @ ${price:.2f} "
                    f"| P&L: ${pnl:+,.2f} ({pnl_pct:+.1f}%)"
                )
                print(f"  {action_taken}")

            else:
                status = f"ถือ {position['shares']} หุ้น" if position else "ไม่มี position"
                print(f"  ⏸  HOLD — RSI={rsi_val:.1f} | MA{MA_SHORT}={ma_s:.2f} | MA{MA_LONG}={ma_l:.2f} | {status}")

            if action_taken:
                summary_lines.append(action_taken)

        except Exception as e:
            print(f"  ❌ Error {ticker}: {e}")

    return trades_this_run


# ─────────────────────────────────────────────
# REPORT & CHART
# ─────────────────────────────────────────────

def print_summary(state: dict):
    print("\n" + "═" * 55)
    print("  📋 PAPER TRADING SUMMARY")
    print("═" * 55)

    # คำนวณ unrealized P&L
    total_unrealized = 0.0
    if state["positions"]:
        print("\n📦 Positions ที่ถืออยู่:")
        for ticker, pos in state["positions"].items():
            try:
                cur_price = float(
                    yf.download(ticker, period="1d", progress=False)["Close"].iloc[-1]
                )
                unreal = (cur_price - pos["avg_cost"]) * pos["shares"]
                total_unrealized += unreal
                emoji = "🟢" if unreal >= 0 else "🔴"
                print(
                    f"  {emoji} {ticker}: {pos['shares']} หุ้น | ซื้อที่ ${pos['avg_cost']:.2f} | "
                    f"ราคาปัจจุบัน ${cur_price:.2f} | Unrealized P&L: ${unreal:+,.2f}"
                )
            except Exception:
                print(f"  ⚠️  {ticker}: ดึงราคาปัจจุบันไม่ได้")
    else:
        print("\n  (ไม่มี open position)")

    # Realized P&L
    realized_trades = [t for t in state["trade_log"] if t["action"] == "SELL"]
    total_realized = sum(t.get("pnl", 0) or 0 for t in realized_trades)

    portfolio_value = state["cash"] + total_unrealized
    total_return = portfolio_value - INITIAL_CAPITAL
    total_return_pct = (total_return / INITIAL_CAPITAL) * 100

    print(f"\n💵 Cash คงเหลือ   : ${state['cash']:>12,.2f}")
    print(f"📈 Unrealized P&L : ${total_unrealized:>+12,.2f}")
    print(f"✅ Realized P&L   : ${total_realized:>+12,.2f}")
    print(f"💼 Portfolio รวม  : ${portfolio_value:>12,.2f}")
    print(f"📊 ผลตอบแทนรวม   : ${total_return:>+12,.2f}  ({total_return_pct:+.2f}%)")
    print("═" * 55)

    # รายหุ้น
    if realized_trades:
        print("\n📑 P&L รายหุ้น (Realized):")
        by_ticker = {}
        for t in realized_trades:
            by_ticker.setdefault(t["ticker"], []).append(t.get("pnl", 0) or 0)
        for tk, pnls in sorted(by_ticker.items()):
            total = sum(pnls)
            emoji = "🟢" if total >= 0 else "🔴"
            print(f"  {emoji} {tk}: ${total:+,.2f}  ({len(pnls)} trades)")

    print(f"\n📝 Trade ทั้งหมด: {len(state['trade_log'])} รายการ")
    print(f"📅 เริ่มต้นระบบ: {state.get('created_at', '-')}")


def plot_results(state: dict):
    """วาดกราฟ P&L สะสมจาก trade log"""
    trades = state["trade_log"]
    if not trades:
        print("⚠️  ยังไม่มี trade log สำหรับวาดกราฟ")
        return

    df = pd.DataFrame(trades)
    df["date"] = pd.to_datetime(df["date"])
    df_sell = df[df["action"] == "SELL"].copy()
    if df_sell.empty:
        print("⚠️  ยังไม่มี SELL trade สำหรับวาดกราฟ P&L")
        return

    df_sell = df_sell.sort_values("date")
    df_sell["cumulative_pnl"] = df_sell["pnl"].cumsum()

    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle("Paper Trading — P&L Report (Combined RSI + MA)", fontsize=14, fontweight="bold")

    # กราฟ P&L สะสม
    ax1 = axes[0]
    colors = ["green" if v >= 0 else "red" for v in df_sell["cumulative_pnl"]]
    ax1.plot(df_sell["date"], df_sell["cumulative_pnl"], color="steelblue", linewidth=2, marker="o", markersize=4)
    ax1.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax1.fill_between(df_sell["date"], df_sell["cumulative_pnl"], 0,
                     where=df_sell["cumulative_pnl"] >= 0, alpha=0.2, color="green")
    ax1.fill_between(df_sell["date"], df_sell["cumulative_pnl"], 0,
                     where=df_sell["cumulative_pnl"] < 0, alpha=0.2, color="red")
    ax1.set_title("Cumulative P&L ($)")
    ax1.set_ylabel("USD")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.grid(True, alpha=0.3)

    # กราฟ P&L แต่ละ trade
    ax2 = axes[1]
    bar_colors = ["green" if v >= 0 else "red" for v in df_sell["pnl"]]
    ax2.bar(range(len(df_sell)), df_sell["pnl"], color=bar_colors, alpha=0.75, edgecolor="white")
    ax2.axhline(0, color="gray", linestyle="--", linewidth=0.8)
    ax2.set_xticks(range(len(df_sell)))
    ax2.set_xticklabels(
        [f"{row['ticker']}\n{row['date'].strftime('%m/%d')}" for _, row in df_sell.iterrows()],
        fontsize=8,
    )
    ax2.set_title("P&L แต่ละ Trade ($)")
    ax2.set_ylabel("USD")
    ax2.grid(True, alpha=0.3, axis="y")

    plt.tight_layout()
    REPORT_DIR.mkdir(exist_ok=True)
    chart_path = REPORT_DIR / f"paper_trading_pnl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"\n💾 บันทึกกราฟที่: {chart_path}")


def build_telegram_message(state: dict, trades_this_run: list) -> str | None:
    if not trades_this_run:
        return None

    lines = ["<b>📊 Paper Trading Update</b>", ""]
    for t in trades_this_run:
        if t["action"] == "BUY":
            lines.append(
                f"🟢 <b>BUY</b> {t['ticker']} — {t['shares']} หุ้น @ ${t['price']:.2f}\n"
                f"   RSI: {t['rsi']:.1f} | MA{MA_SHORT}/{MA_LONG}: {t['ma_short']:.2f}/{t['ma_long']:.2f}"
            )
        else:
            emoji = "🟢" if (t.get("pnl") or 0) >= 0 else "🔴"
            lines.append(
                f"{emoji} <b>SELL</b> {t['ticker']} — {t['shares']} หุ้น @ ${t['price']:.2f}\n"
                f"   P&L: ${t.get('pnl', 0):+,.2f} ({t.get('pnl_pct', 0):+.1f}%)"
            )

    # portfolio snapshot
    realized = sum(tr.get("pnl", 0) or 0 for tr in state["trade_log"] if tr["action"] == "SELL")
    lines += [
        "",
        f"💵 Cash: ${state['cash']:,.2f}",
        f"✅ Realized P&L: ${realized:+,.2f}",
        f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Paper Trading — Combined RSI + MA")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS),
                        help="รายชื่อหุ้น คั่นด้วย comma (default: AAPL,MSFT,TSLA,NVDA,AMD)")
    parser.add_argument("--period", default=DEFAULT_PERIOD,
                        help="ช่วงเวลา yfinance เช่น 3mo, 6mo, 1y (default: 6mo)")
    parser.add_argument("--send-telegram", action="store_true",
                        help="ส่งสรุปผ่าน Telegram")
    parser.add_argument("--chart", action="store_true",
                        help="แสดงกราฟผล P&L")
    parser.add_argument("--reset", action="store_true",
                        help="ล้าง portfolio และเริ่มนับใหม่")
    parser.add_argument("--summary-only", action="store_true",
                        help="แสดงสรุป portfolio โดยไม่รันสัญญาณใหม่")
    args = parser.parse_args()

    if args.reset:
        reset_state()
        return

    state = load_state()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    if not args.summary_only:
        trades_this_run = run_paper_trading(tickers, args.period, args.send_telegram, state)
        save_state(state)

        if args.send_telegram:
            msg = build_telegram_message(state, trades_this_run)
            if msg:
                send_telegram(msg)
            else:
                print("ℹ️  ไม่มี trade ใหม่ในรอบนี้ — ไม่ส่ง Telegram")
    else:
        trades_this_run = []

    print_summary(state)

    if args.chart or not args.summary_only:
        plot_results(state)


if __name__ == "__main__":
    main()
