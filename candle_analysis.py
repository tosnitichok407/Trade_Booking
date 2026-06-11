"""
candle_analysis.py — วิเคราะห์แท่งเทียน + Support/Resistance
สัญญาณหลัก : Candlestick Patterns (Doji, Hammer, Engulfing, Shooting Star, Morning/Evening Star)
ตัวกรองเสริม: RSI + MA Crossover (ต้องผ่านทั้งคู่ถึงจะส่งสัญญาณ BUY/SELL จริง)

Logic:
  BUY  = แท่งเทียน Bullish Pattern  AND RSI < RSI_FILTER_BUY  AND ราคา > MA_LONG (อยู่เหนือแนวโน้ม)
  SELL = แท่งเทียน Bearish Pattern  AND RSI > RSI_FILTER_SELL AND ราคา < MA_LONG
  WATCH= แท่งเทียนมีสัญญาณ แต่ RSI/MA ยังไม่ยืนยัน (แจ้งเตือนให้เฝ้าดู)

Usage:
    .venv/bin/python candle_analysis.py
    .venv/bin/python candle_analysis.py --tickers AAPL,MSFT --period 3mo
    .venv/bin/python candle_analysis.py --send-telegram
    .venv/bin/python candle_analysis.py --chart AAPL
"""

import argparse
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

from indicators import calculate_indicators, normalize_yfinance_columns

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
DEFAULT_TICKERS = ["AAPL", "MSFT", "TSLA", "NVDA", "AMD"]
DEFAULT_PERIOD = "3mo"

# RSI filter thresholds
RSI_FILTER_BUY = 55    # RSI ต้องต่ำกว่านี้ ถึงยืนยัน BUY
RSI_FILTER_SELL = 45   # RSI ต้องสูงกว่านี้ ถึงยืนยัน SELL

# MA periods
MA_SHORT = 20
MA_LONG = 50

# Support/Resistance: ดูกี่แท่งย้อนหลัง
SR_LOOKBACK = 30
SR_TOLERANCE_PCT = 0.015   # ±1.5% ถือว่าอยู่ใน zone เดียวกัน

# แท่งเทียน: ขนาดขั้นต่ำ (% ของราคา) ถึงนับว่ามีนัยสำคัญ
MIN_BODY_PCT = 0.003   # 0.3%

load_dotenv()
REPORT_DIR = Path("reports")


# ─────────────────────────────────────────────
# DATA CLASSES
# ─────────────────────────────────────────────

@dataclass
class CandleSignal:
    pattern: str        # ชื่อ pattern
    direction: str      # "bullish" / "bearish" / "neutral"
    strength: int       # 1=อ่อน, 2=กลาง, 3=แรง
    description: str    # คำอธิบายภาษาไทย


@dataclass
class AnalysisResult:
    ticker: str
    date: str
    price: float
    candle_signals: list[CandleSignal] = field(default_factory=list)
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)
    near_support: bool = False
    near_resistance: bool = False
    rsi: float = 0.0
    ma_short: float = 0.0
    ma_long: float = 0.0
    final_signal: str = "HOLD"    # BUY / SELL / WATCH_BUY / WATCH_SELL / HOLD
    reason: str = ""


# ─────────────────────────────────────────────
# CANDLESTICK PATTERN DETECTION
# ─────────────────────────────────────────────

def detect_patterns(df: pd.DataFrame) -> list[CandleSignal]:
    """ตรวจจับ pattern จาก 3 แท่งล่าสุด"""
    signals = []

    if len(df) < 3:
        return signals

    # แท่งปัจจุบัน
    o, h, l, c = float(df["Open"].iloc[-1]), float(df["High"].iloc[-1]), \
                  float(df["Low"].iloc[-1]), float(df["Close"].iloc[-1])
    # แท่งก่อนหน้า
    o1, h1, l1, c1 = float(df["Open"].iloc[-2]), float(df["High"].iloc[-2]), \
                     float(df["Low"].iloc[-2]), float(df["Close"].iloc[-2])
    # สองแท่งก่อนหน้า
    o2, h2, l2, c2 = float(df["Open"].iloc[-3]), float(df["High"].iloc[-3]), \
                     float(df["Low"].iloc[-3]), float(df["Close"].iloc[-3])

    body = abs(c - o)
    body1 = abs(c1 - o1)
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    price_range = h - l if h != l else 0.0001
    avg_price = (o + c) / 2

    # ── DOJI ──────────────────────────────────
    # แท่งที่ open ≈ close = ความลังเล
    if body < avg_price * 0.001 and price_range > avg_price * MIN_BODY_PCT:
        signals.append(CandleSignal(
            pattern="Doji",
            direction="neutral",
            strength=2,
            description="แท่ง Doji: ตลาดลังเล ราคาเปิด-ปิดใกล้กัน รอดูทิศทาง",
        ))

    # ── HAMMER (Bullish) ──────────────────────
    # ไส้ล่างยาว ≥ 2× body, ไส้บนสั้น, เกิดหลังขาลง
    if (lower_shadow >= 2 * body and upper_shadow <= body * 0.3
            and body >= avg_price * MIN_BODY_PCT and c1 < o1):
        signals.append(CandleSignal(
            pattern="Hammer",
            direction="bullish",
            strength=2,
            description="Hammer: ไส้ล่างยาว แสดงว่าแรงขายถูก absorb กลับ อาจกลับตัวขึ้น",
        ))

    # ── SHOOTING STAR (Bearish) ───────────────
    # ไส้บนยาว ≥ 2× body, ไส้ล่างสั้น, เกิดหลังขาขึ้น
    if (upper_shadow >= 2 * body and lower_shadow <= body * 0.3
            and body >= avg_price * MIN_BODY_PCT and c1 > o1):
        signals.append(CandleSignal(
            pattern="Shooting Star",
            direction="bearish",
            strength=2,
            description="Shooting Star: ไส้บนยาว ราคาพุ่งขึ้นแล้วถูก reject ลง อาจกลับตัวลง",
        ))

    # ── BULLISH ENGULFING ─────────────────────
    # แท่งเขียวครอบแท่งแดงก่อนหน้าทั้งหมด
    if (c > o and c1 < o1               # ปัจจุบันเขียว, ก่อนหน้าแดง
            and o <= c1 and c >= o1     # ครอบ body ก่อนหน้า
            and body >= body1 * 0.9):
        signals.append(CandleSignal(
            pattern="Bullish Engulfing",
            direction="bullish",
            strength=3,
            description="Bullish Engulfing: แท่งเขียวครอบแดง แรงซื้อครอบงำแรงขาย สัญญาณกลับตัวแรง",
        ))

    # ── BEARISH ENGULFING ─────────────────────
    if (c < o and c1 > o1
            and o >= c1 and c <= o1
            and body >= body1 * 0.9):
        signals.append(CandleSignal(
            pattern="Bearish Engulfing",
            direction="bearish",
            strength=3,
            description="Bearish Engulfing: แท่งแดงครอบเขียว แรงขายครอบงำแรงซื้อ สัญญาณกลับตัวแรง",
        ))

    # ── MORNING STAR (Bullish) ────────────────
    # แดงใหญ่ → แท่งเล็ก (gap ลง) → เขียวใหญ่
    if (c2 < o2 and body2_val(o2, c2, avg_price) > MIN_BODY_PCT * 1.5  # แดงใหญ่
            and abs(c1 - o1) < avg_price * MIN_BODY_PCT * 0.5           # แท่งเล็ก
            and c > o and c > (o2 + c2) / 2):                           # เขียวขึ้นเกินกลาง
        signals.append(CandleSignal(
            pattern="Morning Star",
            direction="bullish",
            strength=3,
            description="Morning Star (3 แท่ง): สัญญาณกลับตัวขึ้นแบบ classic แรงมาก",
        ))

    # ── EVENING STAR (Bearish) ────────────────
    if (c2 > o2 and body2_val(o2, c2, avg_price) > MIN_BODY_PCT * 1.5
            and abs(c1 - o1) < avg_price * MIN_BODY_PCT * 0.5
            and c < o and c < (o2 + c2) / 2):
        signals.append(CandleSignal(
            pattern="Evening Star",
            direction="bearish",
            strength=3,
            description="Evening Star (3 แท่ง): สัญญาณกลับตัวลงแบบ classic แรงมาก",
        ))

    # ── MARUBOZU Bullish ──────────────────────
    # แท่งเขียวล้วน ไม่มีไส้เลย
    if (c > o and upper_shadow < body * 0.05 and lower_shadow < body * 0.05
            and body >= avg_price * 0.01):
        signals.append(CandleSignal(
            pattern="Bullish Marubozu",
            direction="bullish",
            strength=2,
            description="Bullish Marubozu: แท่งเขียวไม่มีไส้ แรงซื้อครองตลาดทั้งวัน",
        ))

    # ── MARUBOZU Bearish ──────────────────────
    if (c < o and upper_shadow < body * 0.05 and lower_shadow < body * 0.05
            and body >= avg_price * 0.01):
        signals.append(CandleSignal(
            pattern="Bearish Marubozu",
            direction="bearish",
            strength=2,
            description="Bearish Marubozu: แท่งแดงไม่มีไส้ แรงขายครองตลาดทั้งวัน",
        ))

    return signals


def body2_val(o, c, avg_price):
    """helper คำนวณ body % สำหรับแท่ง index -3"""
    return abs(c - o) / avg_price if avg_price else 0


# ─────────────────────────────────────────────
# SUPPORT & RESISTANCE
# ─────────────────────────────────────────────

def find_support_resistance(df: pd.DataFrame) -> tuple[list[float], list[float]]:
    """
    หา local high/low จาก SR_LOOKBACK แท่งล่าสุด
    คืนค่า (support_levels, resistance_levels)
    """
    window = df.tail(SR_LOOKBACK)
    highs = window["High"].values
    lows = window["Low"].values

    # หา local peaks (resistance) และ local troughs (support)
    resistance_raw, support_raw = [], []

    for i in range(2, len(highs) - 2):
        if highs[i] == max(highs[i-2:i+3]):
            resistance_raw.append(float(highs[i]))
        if lows[i] == min(lows[i-2:i+3]):
            support_raw.append(float(lows[i]))

    # รวม level ที่ใกล้กัน (cluster)
    def cluster(levels: list[float]) -> list[float]:
        if not levels:
            return []
        levels = sorted(levels)
        clustered = [levels[0]]
        for lv in levels[1:]:
            if abs(lv - clustered[-1]) / clustered[-1] > SR_TOLERANCE_PCT:
                clustered.append(lv)
            else:
                clustered[-1] = (clustered[-1] + lv) / 2  # เฉลี่ย
        return clustered

    return cluster(support_raw), cluster(resistance_raw)


def check_near_level(price: float, levels: list[float]) -> bool:
    """ตรวจว่าราคาอยู่ใกล้ level ใด level หนึ่งไหม"""
    return any(abs(price - lv) / lv <= SR_TOLERANCE_PCT for lv in levels)


# ─────────────────────────────────────────────
# SIGNAL DECISION
# ─────────────────────────────────────────────

def decide_signal(
    candle_signals: list[CandleSignal],
    near_support: bool,
    near_resistance: bool,
    rsi: float,
    price: float,
    ma_long: float,
) -> tuple[str, str]:
    """
    รวมสัญญาณทั้งหมด → final_signal + reason

    BUY       = Bullish candle + (near support หรือ strength≥3)
                AND RSI < RSI_FILTER_BUY AND price > ma_long
    SELL      = Bearish candle + (near resistance หรือ strength≥3)
                AND RSI > RSI_FILTER_SELL AND price < ma_long
    WATCH_BUY = Bullish candle แต่ RSI/MA ยังไม่ยืนยัน
    WATCH_SELL= Bearish candle แต่ RSI/MA ยังไม่ยืนยัน
    HOLD      = ไม่มีสัญญาณที่ชัดเจน
    """
    bullish = [s for s in candle_signals if s.direction == "bullish"]
    bearish = [s for s in candle_signals if s.direction == "bearish"]

    has_bull = bool(bullish) and (near_support or max((s.strength for s in bullish), default=0) >= 3)
    has_bear = bool(bearish) and (near_resistance or max((s.strength for s in bearish), default=0) >= 3)

    bull_names = ", ".join(s.pattern for s in bullish) if bullish else "-"
    bear_names = ", ".join(s.pattern for s in bearish) if bearish else "-"

    rsi_ok_buy = rsi < RSI_FILTER_BUY
    rsi_ok_sell = rsi > RSI_FILTER_SELL
    trend_up = price > ma_long
    trend_down = price < ma_long

    if has_bull:
        if rsi_ok_buy and trend_up:
            return "BUY", (
                f"แท่งเทียน Bullish ({bull_names}) ใกล้ Support={near_support} | "
                f"RSI={rsi:.1f}<{RSI_FILTER_BUY} ✅ | ราคาเหนือ MA{MA_LONG} ✅"
            )
        else:
            missing = []
            if not rsi_ok_buy:
                missing.append(f"RSI={rsi:.1f} ยังสูงเกิน {RSI_FILTER_BUY}")
            if not trend_up:
                missing.append(f"ราคาต่ำกว่า MA{MA_LONG}")
            return "WATCH_BUY", (
                f"แท่งเทียน Bullish ({bull_names}) แต่ยังไม่ผ่านกรอง: {', '.join(missing)}"
            )

    if has_bear:
        if rsi_ok_sell and trend_down:
            return "SELL", (
                f"แท่งเทียน Bearish ({bear_names}) ใกล้ Resistance={near_resistance} | "
                f"RSI={rsi:.1f}>{RSI_FILTER_SELL} ✅ | ราคาต่ำกว่า MA{MA_LONG} ✅"
            )
        else:
            missing = []
            if not rsi_ok_sell:
                missing.append(f"RSI={rsi:.1f} ยังต่ำเกิน {RSI_FILTER_SELL}")
            if not trend_down:
                missing.append(f"ราคาเหนือ MA{MA_LONG}")
            return "WATCH_SELL", (
                f"แท่งเทียน Bearish ({bear_names}) แต่ยังไม่ผ่านกรอง: {', '.join(missing)}"
            )

    return "HOLD", "ไม่พบ pattern ที่มีนัยสำคัญในแท่งล่าสุด"


# ─────────────────────────────────────────────
# MAIN ANALYSIS
# ─────────────────────────────────────────────

def analyze_ticker(ticker: str, period: str) -> AnalysisResult | None:
    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if raw.empty or len(raw) < MA_LONG + 5:
            print(f"  ⚠️  ข้อมูลไม่เพียงพอ {ticker}")
            return None

        df = normalize_yfinance_columns(raw)
        df = calculate_indicators(df, ma_periods=[MA_SHORT, MA_LONG], rsi_period=14)
        df.dropna(inplace=True)

        price = float(df["Close"].iloc[-1])
        rsi = float(df["RSI"].iloc[-1])
        ma_s = float(df[f"MA_{MA_SHORT}"].iloc[-1])
        ma_l = float(df[f"MA_{MA_LONG}"].iloc[-1])
        date_str = str(df.index[-1].date())

        candle_signals = detect_patterns(df)
        support_levels, resistance_levels = find_support_resistance(df)
        near_sup = check_near_level(price, support_levels)
        near_res = check_near_level(price, resistance_levels)

        final_signal, reason = decide_signal(
            candle_signals, near_sup, near_res, rsi, price, ma_l
        )

        return AnalysisResult(
            ticker=ticker,
            date=date_str,
            price=price,
            candle_signals=candle_signals,
            support_levels=support_levels,
            resistance_levels=resistance_levels,
            near_support=near_sup,
            near_resistance=near_res,
            rsi=rsi,
            ma_short=ma_s,
            ma_long=ma_l,
            final_signal=final_signal,
            reason=reason,
        )
    except Exception as e:
        print(f"  ❌ Error {ticker}: {e}")
        return None


# ─────────────────────────────────────────────
# CHART
# ─────────────────────────────────────────────

def plot_candle_chart(ticker: str, period: str):
    """วาด candlestick + MA + Support/Resistance + สัญญาณ"""
    try:
        import mplfinance as mpf
    except ImportError:
        print("⚠️  ต้องติดตั้ง mplfinance: pip install mplfinance")
        return

    raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if raw.empty:
        return

    df = normalize_yfinance_columns(raw)
    df = calculate_indicators(df, ma_periods=[MA_SHORT, MA_LONG], rsi_period=14)
    df.dropna(inplace=True)

    support_levels, resistance_levels = find_support_resistance(df)

    # เตรียม add_plot สำหรับ MA
    add_plots = [
        mpf.make_addplot(df[f"MA_{MA_SHORT}"], color="orange", width=1.2, label=f"MA{MA_SHORT}"),
        mpf.make_addplot(df[f"MA_{MA_LONG}"], color="blue", width=1.2, label=f"MA{MA_LONG}"),
        mpf.make_addplot(df["RSI"], panel=1, color="purple", width=1.2, ylabel="RSI"),
    ]

    # เส้น Support/Resistance เป็น hlines
    hlines_dict = {}
    if support_levels:
        hlines_dict["hlines"] = support_levels + resistance_levels
        hlines_dict["colors"] = ["green"] * len(support_levels) + ["red"] * len(resistance_levels)
        hlines_dict["linestyle"] = "--"
        hlines_dict["linewidths"] = 0.8

    REPORT_DIR.mkdir(exist_ok=True)
    save_path = REPORT_DIR / f"{ticker}_candle_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    mpf.plot(
        df,
        type="candle",
        style="charles",
        title=f"{ticker} — Candlestick + MA + Support/Resistance",
        addplot=add_plots,
        volume=True,
        savefig=str(save_path),
        **hlines_dict,
    )
    print(f"💾 บันทึกกราฟที่: {save_path}")


# ─────────────────────────────────────────────
# PRINT & TELEGRAM
# ─────────────────────────────────────────────

SIGNAL_EMOJI = {
    "BUY": "🟢",
    "SELL": "🔴",
    "WATCH_BUY": "👀🟢",
    "WATCH_SELL": "👀🔴",
    "HOLD": "⏸",
}


def print_result(r: AnalysisResult):
    emoji = SIGNAL_EMOJI.get(r.final_signal, "❓")
    print(f"\n{'─'*50}")
    print(f"  {emoji} {r.ticker}  |  ${r.price:.2f}  |  {r.date}")
    print(f"  RSI: {r.rsi:.1f}  |  MA{MA_SHORT}: {r.ma_short:.2f}  |  MA{MA_LONG}: {r.ma_long:.2f}")

    if r.candle_signals:
        print("  📊 Patterns พบ:")
        for s in r.candle_signals:
            strength_bar = "★" * s.strength + "☆" * (3 - s.strength)
            print(f"     [{strength_bar}] {s.description}")
    else:
        print("  📊 ไม่พบ pattern แท่งเทียนที่มีนัยสำคัญ")

    if r.support_levels:
        levels_str = ", ".join(f"${v:.2f}" for v in r.support_levels[-3:])
        print(f"  🟩 Support   : {levels_str}" + (" ← ราคาอยู่ใกล้!" if r.near_support else ""))
    if r.resistance_levels:
        levels_str = ", ".join(f"${v:.2f}" for v in r.resistance_levels[-3:])
        print(f"  🟥 Resistance: {levels_str}" + (" ← ราคาอยู่ใกล้!" if r.near_resistance else ""))

    print(f"  🎯 สัญญาณ: {r.final_signal}")
    print(f"  💬 เหตุผล: {r.reason}")


def build_telegram_message(results: list[AnalysisResult]) -> str:
    actionable = [r for r in results if r.final_signal in ("BUY", "SELL", "WATCH_BUY", "WATCH_SELL")]
    if not actionable:
        return ""

    lines = [f"<b>🕯 Candle Analysis — {datetime.now().strftime('%Y-%m-%d %H:%M')}</b>", ""]
    for r in actionable:
        emoji = SIGNAL_EMOJI.get(r.final_signal, "")
        pattern_names = ", ".join(s.pattern for s in r.candle_signals) or "—"
        lines.append(
            f"{emoji} <b>{r.ticker}</b> @ ${r.price:.2f}  →  <b>{r.final_signal}</b>\n"
            f"   Pattern: {pattern_names}\n"
            f"   RSI: {r.rsi:.1f} | MA{MA_SHORT}/{MA_LONG}: {r.ma_short:.2f}/{r.ma_long:.2f}\n"
            f"   {r.reason}"
        )
    return "\n\n".join(lines)


def send_telegram(message: str):
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("⚠️  ไม่พบ TELEGRAM_TOKEN / TELEGRAM_CHAT_ID ใน .env")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}, timeout=10)
        print("📨 ส่ง Telegram แล้ว" if resp.status_code == 200 else f"⚠️  Telegram error: {resp.text}")
    except Exception as e:
        print(f"⚠️  Telegram exception: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Candle Analysis — แท่งเทียน + RSI/MA filter")
    parser.add_argument("--tickers", default=",".join(DEFAULT_TICKERS))
    parser.add_argument("--period", default=DEFAULT_PERIOD,
                        help="ช่วงเวลา yfinance เช่น 1mo, 3mo, 6mo (default: 3mo)")
    parser.add_argument("--send-telegram", action="store_true")
    parser.add_argument("--chart", metavar="TICKER",
                        help="วาดกราฟแท่งเทียนของหุ้นที่ระบุ เช่น --chart AAPL")
    args = parser.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    # ─ วาดกราฟเดี่ยว ─
    if args.chart:
        print(f"📊 วาดกราฟ {args.chart} ...")
        plot_candle_chart(args.chart.upper(), args.period)
        return

    # ─ วิเคราะห์ทุกหุ้น ─
    print(f"\n🕯  Candle Analysis  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"   หุ้น: {', '.join(tickers)}  |  ช่วง: {args.period}\n")

    results = []
    for ticker in tickers:
        print(f"⏳ กำลังวิเคราะห์ {ticker} ...")
        result = analyze_ticker(ticker, args.period)
        if result:
            print_result(result)
            results.append(result)

    # ─ สรุปรวม ─
    print(f"\n{'═'*50}")
    print("  📋 สรุปสัญญาณทั้งหมด")
    print(f"{'═'*50}")
    for r in results:
        emoji = SIGNAL_EMOJI.get(r.final_signal, "")
        print(f"  {emoji}  {r.ticker:<6} {r.final_signal:<12} ${r.price:.2f}")

    # ─ Telegram ─
    if args.send_telegram:
        msg = build_telegram_message(results)
        if msg:
            send_telegram(msg)
        else:
            print("\nℹ️  ไม่มีสัญญาณ BUY/SELL/WATCH — ไม่ส่ง Telegram")


if __name__ == "__main__":
    main()
