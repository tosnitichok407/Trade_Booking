"""
automation.py
สคริปต์หลักสำหรับรันระบบอัตโนมัติทั้งหมดของโปรเจกต์ Trade_Booking
หน้าที่การทำงาน:
- อ่านการตั้งค่าจากไฟล์ .env หรือตัวแปรสภาพแวดล้อม (Environment Variables)
- สร้างสรุปผลจาก Indicators และโมเดล ML สำหรับหุ้นแต่ละตัว
- บันทึกรายงานข้อความพร้อมวันและเวลาไว้ในโฟลเดอร์ reports/
- สามารถส่งรายงานไปยัง Telegram ได้ หากเปิดใช้งานฟังก์ชันนี้อย่างชัดเจน
"""

import argparse
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import schedule

from alert import load_env_file, send_telegram
from indicators import calculate_indicators
from ml_predict import run_ml_prediction


DEFAULT_WATCHLIST = ["AAPL", "MSFT", "TSLA", "NVDA", "AMD", "INTC"]
REPORT_DIR = Path("reports")
DEFAULT_MIN_ML_PROBABILITY = 0.55
DEFAULT_MIN_ML_EDGE = 0.0


def parse_bool(value: str | None, default: bool = False) -> bool:
    """แปลงค่าตัวแปรสภาพแวดล้อมทั่วไปที่เป็น true/false."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def parse_watchlist(value: str | None) -> list[str]:
    """อ่านรายชื่อหุ้นคั่นด้วยเครื่องหมายจุลภาคจาก env."""
    if not value:
        return DEFAULT_WATCHLIST
    tickers = [ticker.strip().upper() for ticker in value.split(",")]
    return [ticker for ticker in tickers if ticker]


def build_indicator_summary(ticker: str) -> dict[str, object]:
    """คืนค่าสัญญาณและค่าตัวชี้วัดล่าสุด."""
    df = calculate_indicators(ticker=ticker, period="6mo")
    latest = df.iloc[-1]

    if not all(key in latest.index for key in ("Close", "RSI", "MA20", "MA50")):
        raise ValueError("DataFrame ไม่มีคอลัมน์ MA20/MA50/RSI ที่ต้องการ")

    price = float(latest["Close"])
    rsi = float(latest["RSI"])
    ma20 = float(latest["MA20"])
    ma50 = float(latest["MA50"])

    if any(not pd.notna(value) for value in (price, rsi, ma20, ma50)):
        raise ValueError("ข้อมูลมีค่า NaN/ไม่สมบูรณ์")

    signals = []
    if rsi < 30:
        signals.append("RSI oversold")
    elif rsi > 70:
        signals.append("RSI overbought")

    if ma20 > ma50:
        signals.append("MA20 above MA50")
    else:
        signals.append("MA20 below MA50")

    return {
        "price": price,
        "rsi": rsi,
        "ma20": ma20,
        "ma50": ma50,
        "signals": signals,
    }


def build_ticker_analysis(
    ticker: str,
    ml_period: str,
    min_ml_probability: float,
    min_ml_edge: float,
) -> dict[str, object]:
    """สร้างบรรทัดรายงานสำหรับหุ้นแต่ละตัวและแจ้งเตือนที่น่าสนใจ."""
    try:
        indicator = build_indicator_summary(ticker)
    except Exception as error:
        return {
            "report_line": f"{ticker}: indicator error: {error}",
            "alert_line": None,
        }

    ml_result = None
    try:
        ml_result = run_ml_prediction(ticker=ticker, period=ml_period)
        metrics = ml_result["metrics"]
        ml_line = (
            f"ML {ml_result['latest_signal']} "
            f"({ml_result['latest_probability_up'] * 100:.2f}% up), "
            f"accuracy {metrics['accuracy'] * 100:.2f}% "
            f"vs baseline {ml_result['baseline_accuracy'] * 100:.2f}%"
        )
    except Exception as error:
        ml_line = f"ML error: {error}"

    signals = ", ".join(indicator["signals"])
    report_line = (
        f"{ticker}: price {indicator['price']:.2f}, "
        f"RSI {indicator['rsi']:.2f}, "
        f"MA20 {indicator['ma20']:.2f}, "
        f"MA50 {indicator['ma50']:.2f}, "
        f"signals [{signals}], "
        f"{ml_line}"
    )

    alert_reasons = []
    alert_type = None

    if indicator["rsi"] < 30:
        alert_type = "BUY WATCH"
        alert_reasons.append(f"RSI oversold {indicator['rsi']:.2f}")
    elif indicator["rsi"] > 70:
        alert_type = "SELL WATCH"
        alert_reasons.append(f"RSI overbought {indicator['rsi']:.2f}")

    if ml_result is not None:
        metrics = ml_result["metrics"]
        accuracy = float(metrics["accuracy"])
        baseline = float(ml_result["baseline_accuracy"])
        probability_up = float(ml_result["latest_probability_up"])
        probability_down = 1 - probability_up
        beats_baseline = accuracy >= baseline + min_ml_edge

        if (
            beats_baseline
            and probability_up >= min_ml_probability
            and indicator["ma20"] > indicator["ma50"]
        ):
            alert_type = alert_type or "BUY WATCH"
            alert_reasons.append(
                f"ML UP {probability_up * 100:.2f}% "
                f"and accuracy {accuracy * 100:.2f}% > baseline {baseline * 100:.2f}%"
            )
        elif (
            beats_baseline
            and probability_down >= min_ml_probability
            and indicator["ma20"] < indicator["ma50"]
        ):
            alert_type = alert_type or "SELL WATCH"
            alert_reasons.append(
                f"ML DOWN {probability_down * 100:.2f}% "
                f"and accuracy {accuracy * 100:.2f}% > baseline {baseline * 100:.2f}%"
            )

    alert_line = None
    if alert_type and alert_reasons:
        alert_line = (
            f"{alert_type}: {ticker} | "
            f"price {indicator['price']:.2f} | "
            f"RSI {indicator['rsi']:.2f} | "
            f"MA20 {indicator['ma20']:.2f} / MA50 {indicator['ma50']:.2f} | "
            f"{'; '.join(alert_reasons)}"
        )

    return {
        "report_line": report_line,
        "alert_line": alert_line,
    }


def build_reports(
    tickers: list[str],
    ml_period: str,
    min_ml_probability: float,
    min_ml_edge: float,
) -> tuple[str, str | None]:
    """สร้างรายงานเต็มรูปแบบและรายงานสัญญาณที่กรองสำหรับ Telegram."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "Trade Booking Automation Report",
        f"Generated: {timestamp}",
        "",
    ]
    alert_lines = [
        "Trade Booking Signals",
        f"Generated: {timestamp}",
        "",
    ]

    for ticker in tickers:
        analysis = build_ticker_analysis(
            ticker=ticker,
            ml_period=ml_period,
            min_ml_probability=min_ml_probability,
            min_ml_edge=min_ml_edge,
        )
        lines.append(str(analysis["report_line"]))
        if analysis["alert_line"]:
            alert_lines.append(str(analysis["alert_line"]))

    lines.extend(
        [
            "",
            "Note: Educational automation only. This is not financial advice.",
        ]
    )

    if len(alert_lines) == 3:
        return "\n".join(lines), None

    alert_lines.extend(
        [
            "",
            "Note: Filtered signals only. This is not financial advice.",
        ]
    )
    return "\n".join(lines), "\n".join(alert_lines)


def save_report(report: str) -> Path:
    """บันทึกรายงานลงโฟลเดอร์ reports/ พร้อมชื่อไฟล์มี timestamp."""
    REPORT_DIR.mkdir(exist_ok=True)
    filename = datetime.now().strftime("automation_%Y%m%d_%H%M%S.txt")
    path = REPORT_DIR / filename
    path.write_text(report, encoding="utf-8")
    return path


def run_once(
    tickers: list[str],
    ml_period: str,
    send_report: bool,
    min_ml_probability: float = DEFAULT_MIN_ML_PROBABILITY,
    min_ml_edge: float = DEFAULT_MIN_ML_EDGE,
) -> Path:
    """รันหนึ่งรอบของระบบอัตโนมัติ."""
    report, signal_report = build_reports(
        tickers=tickers,
        ml_period=ml_period,
        min_ml_probability=min_ml_probability,
        min_ml_edge=min_ml_edge,
    )
    report_path = save_report(report)

    print(report)
    print(f"\nSaved report: {report_path}")

    if send_report:
        if signal_report:
            print("\nTelegram signal report:")
            print(signal_report)
            send_telegram(f"<pre>{signal_report}</pre>")
        else:
            print("\nNo high-interest signals. Telegram message skipped.")

    return report_path


def main():
    load_env_file()

    parser = argparse.ArgumentParser(description="Run Trade_Booking automation.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument(
        "--tickers",
        help="Comma-separated ticker override, e.g. AAPL,MSFT,PTT.BK.",
    )
    parser.add_argument("--ml-period", help="Override ML data period, e.g. 1y or 5y.")
    parser.add_argument("--interval-minutes", type=int, help="Override schedule interval.")
    parser.add_argument(
        "--min-ml-probability",
        type=float,
        help="Minimum ML probability for filtered Telegram signals, e.g. 0.55.",
    )
    parser.add_argument(
        "--min-ml-edge",
        type=float,
        help="Minimum accuracy edge over baseline for ML signals, e.g. 0.02.",
    )
    parser.add_argument(
        "--send-telegram",
        action="store_true",
        help="Send the generated report to Telegram.",
    )
    args = parser.parse_args()

    tickers = parse_watchlist(args.tickers or os.getenv("AUTOMATION_WATCHLIST"))
    ml_period = args.ml_period or os.getenv("AUTOMATION_ML_PERIOD", "5y")
    interval_minutes = args.interval_minutes or int(os.getenv("AUTOMATION_INTERVAL_MINUTES", "30"))
    send_report = args.send_telegram or parse_bool(os.getenv("AUTOMATION_SEND_TELEGRAM"))
    min_ml_probability = args.min_ml_probability or float(
        os.getenv("AUTOMATION_MIN_ML_PROBABILITY", str(DEFAULT_MIN_ML_PROBABILITY))
    )
    min_ml_edge = args.min_ml_edge or float(
        os.getenv("AUTOMATION_MIN_ML_EDGE", str(DEFAULT_MIN_ML_EDGE))
    )

    if args.once:
        run_once(
            tickers=tickers,
            ml_period=ml_period,
            send_report=send_report,
            min_ml_probability=min_ml_probability,
            min_ml_edge=min_ml_edge,
        )
        return

    print("=== Trade Booking Automation ===")
    print(f"Watchlist: {', '.join(tickers)}")
    print(f"Interval: {interval_minutes} minutes")
    print(f"Telegram: {'enabled' if send_report else 'disabled'}")
    print(f"Min ML probability: {min_ml_probability:.2f}")
    print(f"Min ML edge: {min_ml_edge:.2f}")

    run_once(
        tickers=tickers,
        ml_period=ml_period,
        send_report=send_report,
        min_ml_probability=min_ml_probability,
        min_ml_edge=min_ml_edge,
    )
    schedule.every(interval_minutes).minutes.do(
        run_once,
        tickers=tickers,
        ml_period=ml_period,
        send_report=send_report,
        min_ml_probability=min_ml_probability,
        min_ml_edge=min_ml_edge,
    )

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
