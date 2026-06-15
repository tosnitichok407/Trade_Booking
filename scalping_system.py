"""
=============================================================
  SCALPING SYSTEM: Wyckoff + Elliott Wave + RSI Divergence
  สำหรับตลาดหุ้นไทย (SET) / Crypto / Forex
  Version 1.0
=============================================================
ฟีเจอร์:
  1. Signal Generator  — สัญญาณ Buy/Sell แบบ Real-time
  2. Backtester        — ทดสอบย้อนหลังพร้อม Trade Log
  3. Performance Report — Equity Curve + สถิติครบ
=============================================================
"""

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyArrowPatch
import warnings, sys
warnings.filterwarnings("ignore")
from pathlib import Path

# ─────────────────────────────────────────────
# 0. CONFIG  (แก้ค่าตรงนี้ได้เลย)
# ─────────────────────────────────────────────
CONFIG = {
    # ── Risk Management ──
    "risk_per_trade":   0.05,   # 5% ของพอร์ตต่อ trade
    "max_daily_loss":   0.10,   # หยุดวันนั้นถ้าขาดทุน 10%
    "max_trades_day":   50,      # ห้ามเกิน 50 trade/วัน

    # ── Entry/Exit ──
    "stop_loss_pct":    0.05,  # SL = 5% ต่ำกว่า entry
    "rr_ratio":         2.0,    # Target R:R = 1:2
    "trail_after_1r":   True,   # Trail stop หลังกำไร 1R

    # ── Indicators ──
    "rsi_period":       14,
    "rsi_oversold":     35,
    "rsi_overbought":   65,
    "ema_fast":         9,
    "ema_slow":         21,
    "volume_ma":        20,

    # ── Wyckoff ──
    "wyckoff_lookback": 20,     # แท่งที่ใช้หา Phase

    # ── Capital ──
    "initial_capital":  100_000,  # บาท / หน่วยเงินใดก็ได้
    "commission":       0.0015,   # 0.15% ต่อด้าน (SET broker)
}

# ─────────────────────────────────────────────
# REAL DATA CONFIG  (แก้ค่าตรงนี้)
# ─────────────────────────────────────────────
TICKER   = "MSFT"      # เปลี่ยนเป็นหุ้นที่ต้องการ เช่น "PTT.BK", "BTC-USD"
PERIOD   = "1y"       # ช่วงเวลา: 1mo / 3mo / 6mo / 1y
INTERVAL = "1h"        # timeframe: 1m / 5m / 15m / 1h / 1d
                       # หมายเหตุ: yfinance รองรับ intraday ย้อนหลังสูงสุด 60 วัน
                       #           ถ้าใช้ interval="5m" ให้ตั้ง period="1mo" หรือ "60d"


# ═════════════════════════════════════════════
# 1. INDICATOR LIBRARY
# ═════════════════════════════════════════════

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def rsi_divergence(close: pd.Series, rsi: pd.Series, window: int = 5) -> pd.Series:
    """
    Bullish Divergence: ราคาทำ Lower Low แต่ RSI ทำ Higher Low → +1
    Bearish Divergence: ราคาทำ Higher High แต่ RSI ทำ Lower High → -1
    """
    signal = pd.Series(0, index=close.index)
    for i in range(window * 2, len(close)):
        sl = slice(i - window * 2, i + 1)
        c, r = close.iloc[sl], rsi.iloc[sl]
        # Bullish
        if c.iloc[-1] < c.min() * 1.002 and r.iloc[-1] > r.iloc[:-1].min() * 1.05:
            signal.iloc[i] = 1
        # Bearish
        elif c.iloc[-1] > c.max() * 0.998 and r.iloc[-1] < r.iloc[:-1].max() * 0.95:
            signal.iloc[i] = -1
    return signal


# ═════════════════════════════════════════════
# 2. WYCKOFF PHASE DETECTOR
# ═════════════════════════════════════════════

def detect_wyckoff_phase(df: pd.DataFrame, lookback: int = 20) -> pd.Series:
    """
    ตรวจ Wyckoff Phase แบบ simplified:
        'C_spring'  = Phase C: Spring (โอกาส Long)
        'C_upthrust'= Phase C: Upthrust (โอกาส Short)
        'D_markup'  = Phase D: Markup (ยืนยัน Long)
        'D_markdown'= Phase D: Markdown (ยืนยัน Short)
        ''          = ไม่ชัด
    """
    phase = pd.Series("", index=df.index)
    c, v = df["close"], df["volume"]

    for i in range(lookback * 2, len(df)):
        window_c = c.iloc[i - lookback: i]
        window_v = v.iloc[i - lookback: i]

        support    = window_c.min()
        resistance = window_c.max()
        avg_vol    = window_v.mean()
        cur_c      = c.iloc[i]
        cur_v      = v.iloc[i]
        prev_c     = c.iloc[i - 1]

        # Spring: ราคาหลุด support แต่ volume หดแล้วกลับขึ้น
        if cur_c < support * 1.003 and cur_v < avg_vol * 0.85 and cur_c > prev_c:
            phase.iloc[i] = "C_spring"

        # Upthrust: ราคาทะลุ resistance แต่ volume ต่ำแล้วดิ่งลง
        elif cur_c > resistance * 0.997 and cur_v < avg_vol * 0.85 and cur_c < prev_c:
            phase.iloc[i] = "C_upthrust"

        # Markup: ราคาเหนือ resistance + volume พุ่ง
        elif cur_c > resistance and cur_v > avg_vol * 1.3:
            phase.iloc[i] = "D_markup"

        # Markdown: ราคาต่ำกว่า support + volume พุ่ง
        elif cur_c < support and cur_v > avg_vol * 1.3:
            phase.iloc[i] = "D_markdown"

    return phase


# ═════════════════════════════════════════════
# 3. ELLIOTT WAVE MICRO-COUNTER (Simplified)
# ═════════════════════════════════════════════

def detect_wave3_start(close: pd.Series, window: int = 10) -> pd.Series:
    """
    ตรวจจุดเริ่ม Wave 3 แบบ Simplified:
    - หา Swing Low (Wave 2 End) → ราคาเริ่มทะลุ Wave 1 High → Wave 3 เริ่ม
    คืนค่า: +1 = Wave 3 ขาขึ้น, -1 = Wave 3 ขาลง, 0 = ไม่มี
    """
    signal = pd.Series(0, index=close.index)

    for i in range(window * 3, len(close)):
        seg = close.iloc[i - window * 3: i + 1]

        # หา Wave 1: impulse ขึ้น
        w1_low  = seg.iloc[:window].min()
        w1_high = seg.iloc[:window].max()
        # หา Wave 2: ย่อลงมา (retracement > 38.2%)
        w2_low  = seg.iloc[window: window * 2].min()
        retracement = (w1_high - w2_low) / (w1_high - w1_low + 1e-9)

        # Wave 3 เริ่ม: ราคาปัจจุบันทะลุ Wave 1 High หลัง retracement 38-78%
        if (0.38 <= retracement <= 0.786
                and seg.iloc[-1] > w1_high
                and seg.iloc[-2] <= w1_high):
            signal.iloc[i] = 1

        # Wave 3 ขาลง (Inverted)
        w1_high2 = seg.iloc[:window].max()
        w1_low2  = seg.iloc[:window].min()
        w2_high  = seg.iloc[window: window * 2].max()
        ret2     = (w2_high - w1_low2) / (w1_high2 - w1_low2 + 1e-9)
        if (0.38 <= ret2 <= 0.786
                and seg.iloc[-1] < w1_low2
                and seg.iloc[-2] >= w1_low2):
            signal.iloc[i] = -1

    return signal


# ═════════════════════════════════════════════
# 4. SIGNAL GENERATOR (รวม 3 ระบบ)
# ═════════════════════════════════════════════

def generate_signals(df: pd.DataFrame, cfg: dict = CONFIG) -> pd.DataFrame:
    """
    รวม Wyckoff + Elliott Wave + RSI Divergence
    คืน DataFrame ที่มีคอลัมน์ signal: +1=Buy, -1=Sell, 0=Hold
    """
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    # ── Indicators ──
    df["rsi"]       = calc_rsi(df["close"], cfg["rsi_period"])
    df["ema_fast"]  = calc_ema(df["close"], cfg["ema_fast"])
    df["ema_slow"]  = calc_ema(df["close"], cfg["ema_slow"])
    df["atr"]       = calc_atr(df["high"], df["low"], df["close"])
    df["vol_ma"]    = df["volume"].rolling(cfg["volume_ma"]).mean()

    # ── Sub-signals ──
    df["wyckoff"]   = detect_wyckoff_phase(df, cfg["wyckoff_lookback"])
    df["wave3"]     = detect_wave3_start(df["close"])
    df["rsi_div"]   = rsi_divergence(df["close"], df["rsi"])

    # ── LONG Signal (ต้องผ่านอย่างน้อย 2 ใน 3) ──
    long_conditions = pd.DataFrame({
        "wyckoff_bull": df["wyckoff"].isin(["C_spring", "D_markup"]),
        "wave3_up":     df["wave3"] == 1,
        "rsi_bull":     (df["rsi_div"] == 1) | (df["rsi"] < cfg["rsi_oversold"]),
        "ema_trend":    df["ema_fast"] > df["ema_slow"],
    })
    df["long_score"] = long_conditions.sum(axis=1)

    # ── SHORT Signal ──
    short_conditions = pd.DataFrame({
        "wyckoff_bear": df["wyckoff"].isin(["C_upthrust", "D_markdown"]),
        "wave3_down":   df["wave3"] == -1,
        "rsi_bear":     (df["rsi_div"] == -1) | (df["rsi"] > cfg["rsi_overbought"]),
        "ema_trend":    df["ema_fast"] < df["ema_slow"],
    })
    df["short_score"] = short_conditions.sum(axis=1)

    # ── Final Signal (ต้องผ่าน ≥ 2 เงื่อนไข) ──
    df["signal"] = 0
    df.loc[df["long_score"]  >= 2, "signal"] =  1
    df.loc[df["short_score"] >= 2, "signal"] = -1

    # ─ กันสัญญาณซ้ำ ─
    df["signal"] = df["signal"].where(df["signal"] != df["signal"].shift(), 0)

    return df


# ═════════════════════════════════════════════
# 5. BACKTESTER
# ═════════════════════════════════════════════

def run_backtest(df: pd.DataFrame, cfg: dict = CONFIG) -> dict:
    """
    Backtest แบบ Event-driven พร้อม:
    - Risk-based position sizing
    - Trailing stop หลัง 1R
    - Daily loss limit
    - Max trades/day limit
    """
    capital   = cfg["initial_capital"]
    equity    = [capital]
    trades    = []
    position  = None       # dict: {side, entry, sl, tp, size, date}

    daily_pnl   = {}
    daily_count = {}

    for i, row in df.iterrows():
        date_key = str(i)[:10]
        daily_pnl.setdefault(date_key,   0)
        daily_count.setdefault(date_key, 0)

        # ── ปิด Position ──
        if position:
            hit_sl = (position["side"] ==  1 and row["low"]  <= position["sl"]) or \
                     (position["side"] == -1 and row["high"] >= position["sl"])
            hit_tp = (position["side"] ==  1 and row["high"] >= position["tp"]) or \
                     (position["side"] == -1 and row["low"]  <= position["tp"])

            exit_price = None
            exit_reason = ""

            if hit_tp:
                exit_price  = position["tp"]
                exit_reason = "TP"
            elif hit_sl:
                exit_price  = position["sl"]
                exit_reason = "SL"

            if exit_price:
                raw_pnl  = position["side"] * (exit_price - position["entry"]) * position["size"]
                comm     = exit_price * position["size"] * cfg["commission"]
                net_pnl  = raw_pnl - comm
                capital += net_pnl
                daily_pnl[date_key] += net_pnl

                trades.append({
                    "entry_date":  position["date"],
                    "exit_date":   str(i),
                    "side":        "LONG" if position["side"] == 1 else "SHORT",
                    "entry_price": round(position["entry"], 4),
                    "exit_price":  round(exit_price, 4),
                    "exit_reason": exit_reason,
                    "size":        round(position["size"], 4),
                    "pnl":         round(net_pnl, 2),
                    "pnl_pct":     round(net_pnl / (position["entry"] * position["size"]) * 100, 3),
                })
                position = None

            # Trailing Stop หลัง 1R
            elif cfg["trail_after_1r"] and position:
                r = abs(position["entry"] - position["sl"])
                if position["side"] == 1 and row["close"] > position["entry"] + r:
                    position["sl"] = max(position["sl"], row["close"] - r)
                elif position["side"] == -1 and row["close"] < position["entry"] - r:
                    position["sl"] = min(position["sl"], row["close"] + r)

        # ── เปิด Position ──
        if not position and row.get("signal", 0) != 0:
            # ตรวจ Daily Limit
            dd_pct = daily_pnl[date_key] / cfg["initial_capital"]
            if dd_pct <= -cfg["max_daily_loss"]:
                equity.append(capital)
                continue
            if daily_count[date_key] >= cfg["max_trades_day"]:
                equity.append(capital)
                continue

            side       = int(row["signal"])
            entry      = row["close"]
            sl_dist    = entry * cfg["stop_loss_pct"]
            sl         = entry - side * sl_dist
            tp         = entry + side * sl_dist * cfg["rr_ratio"]
            risk_amt   = capital * cfg["risk_per_trade"]
            size       = risk_amt / sl_dist
            comm       = entry * size * cfg["commission"]

            if size > 0 and capital > comm:
                capital -= comm
                position = {
                    "side":  side,
                    "entry": entry,
                    "sl":    sl,
                    "tp":    tp,
                    "size":  size,
                    "date":  str(i),
                }
                daily_count[date_key] += 1

        equity.append(capital)

    return {
        "trades":       pd.DataFrame(trades),
        "equity_curve": pd.Series(equity[:len(df)], index=df.index),
        "final_capital": capital,
    }


# ═════════════════════════════════════════════
# 6. PERFORMANCE REPORT
# ═════════════════════════════════════════════

def calc_performance(result: dict, cfg: dict = CONFIG) -> dict:
    trades = result["trades"]
    eq     = result["equity_curve"]
    init   = cfg["initial_capital"]

    if trades.empty:
        return {"error": "No trades found — ลอง adjust parameters หรือดาต้า"}

    wins  = trades[trades["pnl"] > 0]
    loss  = trades[trades["pnl"] <= 0]

    # Drawdown
    roll_max = eq.cummax()
    dd       = (eq - roll_max) / roll_max
    max_dd   = dd.min()

    # Sharpe (annualized, assume 252 trading days)
    daily_ret = eq.pct_change().dropna()
    sharpe    = (daily_ret.mean() / daily_ret.std()) * np.sqrt(252) if daily_ret.std() > 0 else 0

    # Profit Factor
    gross_profit = wins["pnl"].sum()
    gross_loss   = abs(loss["pnl"].sum())
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "total_trades":       len(trades),
        "win_rate":           round(len(wins) / len(trades) * 100, 1),
        "profit_factor":      round(pf, 2),
        "sharpe_ratio":       round(sharpe, 2),
        "max_drawdown_pct":   round(max_dd * 100, 2),
        "net_profit":         round(result["final_capital"] - init, 2),
        "net_profit_pct":     round((result["final_capital"] - init) / init * 100, 2),
        "avg_win":            round(wins["pnl"].mean(), 2) if not wins.empty else 0,
        "avg_loss":           round(loss["pnl"].mean(), 2) if not loss.empty else 0,
        "best_trade":         round(trades["pnl"].max(), 2),
        "worst_trade":        round(trades["pnl"].min(), 2),
        "long_trades":        len(trades[trades["side"] == "LONG"]),
        "short_trades":       len(trades[trades["side"] == "SHORT"]),
        "avg_pnl_pct":        round(trades["pnl_pct"].mean(), 3),
    }


# ═════════════════════════════════════════════
# 7. DASHBOARD PLOTTER
# ═════════════════════════════════════════════

def plot_dashboard(df: pd.DataFrame, result: dict, perf: dict):
    trades = result["trades"]
    eq     = result["equity_curve"]

    fig = plt.figure(figsize=(18, 14), facecolor="#0d1117")
    fig.suptitle("⚡ SCALPING SYSTEM REPORT — Wyckoff + Elliott + RSI Divergence",
                 fontsize=16, color="white", fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(4, 3, figure=fig,
                           hspace=0.45, wspace=0.35,
                           top=0.93, bottom=0.06,
                           left=0.07, right=0.97)

    # ── สี ──
    bg, fg = "#0d1117", "white"
    green, red, blue, amber = "#26a641", "#f85149", "#58a6ff", "#e3b341"

    def style_ax(ax, title=""):
        ax.set_facecolor("#161b22")
        ax.tick_params(colors=fg, labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#30363d")
        if title:
            ax.set_title(title, color=amber, fontsize=9, fontweight="bold", pad=6)
        ax.yaxis.label.set_color(fg)
        ax.xaxis.label.set_color(fg)

    # ─────────────────────────────────
    # Panel 1: Price + EMA + Signals
    # ─────────────────────────────────
    ax1 = fig.add_subplot(gs[0, :2])
    style_ax(ax1, "Price + EMA + Signals")
    x  = range(len(df))
    ax1.plot(x, df["close"], color="#8b949e", lw=0.8, alpha=0.9, label="Close")
    ax1.plot(x, df["ema_fast"], color=blue,  lw=1.2, alpha=0.8, label=f"EMA{CONFIG['ema_fast']}")
    ax1.plot(x, df["ema_slow"], color=amber, lw=1.2, alpha=0.8, label=f"EMA{CONFIG['ema_slow']}")

    if not trades.empty:
        for _, t in trades.iterrows():
            try:
                ei = df.index.get_loc(pd.Timestamp(t["entry_date"]))
                color = green if t["side"] == "LONG" else red
                marker = "^" if t["side"] == "LONG" else "v"
                ax1.scatter(ei, t["entry_price"], color=color, marker=marker, s=60, zorder=5)
            except Exception:
                pass

    ax1.legend(fontsize=7, facecolor="#161b22", labelcolor=fg, loc="upper left")

    # ─────────────────────────────────
    # Panel 2: Equity Curve
    # ─────────────────────────────────
    ax2 = fig.add_subplot(gs[0, 2])
    style_ax(ax2, "Equity Curve")
    eq_vals = eq.values
    colors_eq = [green if eq_vals[i] >= eq_vals[i-1] else red
                 for i in range(1, len(eq_vals))]
    for i in range(1, len(eq_vals)):
        ax2.plot([i-1, i], [eq_vals[i-1], eq_vals[i]], color=colors_eq[i-1], lw=1.5)
    ax2.axhline(CONFIG["initial_capital"], color=amber, lw=0.8, ls="--", alpha=0.6)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1000:.0f}K"))

    # ─────────────────────────────────
    # Panel 3: RSI
    # ─────────────────────────────────
    ax3 = fig.add_subplot(gs[1, :2])
    style_ax(ax3, "RSI + Divergence")
    ax3.plot(x, df["rsi"], color=blue, lw=1, label="RSI")
    ax3.axhline(CONFIG["rsi_oversold"],   color=green, lw=0.8, ls="--", alpha=0.7)
    ax3.axhline(CONFIG["rsi_overbought"], color=red,   lw=0.8, ls="--", alpha=0.7)
    ax3.axhline(50, color="#30363d", lw=0.6, ls="-")
    ax3.fill_between(x, df["rsi"], CONFIG["rsi_oversold"],
                     where=df["rsi"] < CONFIG["rsi_oversold"],
                     alpha=0.2, color=green)
    ax3.fill_between(x, df["rsi"], CONFIG["rsi_overbought"],
                     where=df["rsi"] > CONFIG["rsi_overbought"],
                     alpha=0.2, color=red)
    div_bull = df[df["rsi_div"] ==  1].index
    div_bear = df[df["rsi_div"] == -1].index
    if len(div_bull):
        idx = [df.index.get_loc(i) for i in div_bull]
        ax3.scatter(idx, df.loc[div_bull, "rsi"], color=green, s=40, zorder=5, marker="D")
    if len(div_bear):
        idx = [df.index.get_loc(i) for i in div_bear]
        ax3.scatter(idx, df.loc[div_bear, "rsi"], color=red, s=40, zorder=5, marker="D")
    ax3.set_ylim(0, 100)
    ax3.legend(fontsize=7, facecolor="#161b22", labelcolor=fg)

    # ─────────────────────────────────
    # Panel 4: Volume + Wyckoff Phase
    # ─────────────────────────────────
    ax4 = fig.add_subplot(gs[1, 2])
    style_ax(ax4, "Volume + Wyckoff")
    vol = df["volume"].values
    vol_colors = [green if df["close"].iloc[i] >= df["close"].iloc[i-1] else red
                  for i in range(len(df))]
    ax4.bar(x, vol, color=vol_colors, alpha=0.6, width=0.8)
    ax4.plot(x, df["vol_ma"], color=amber, lw=1.2, label="Vol MA")
    # Wyckoff markers
    phase_map = {"C_spring": (green, "S"), "C_upthrust": (red, "U"),
                 "D_markup": (blue, "M"),  "D_markdown": (red, "Md")}
    for phase, (pc, pm) in phase_map.items():
        idx = df[df["wyckoff"] == phase].index
        if len(idx):
            pos = [df.index.get_loc(i) for i in idx]
            ax4.scatter(pos, df.loc[idx, "volume"],
                        color=pc, s=50, zorder=5, marker="*", label=phase)
    ax4.legend(fontsize=6, facecolor="#161b22", labelcolor=fg)
    ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M" if v >= 1e6 else f"{v/1000:.0f}K"))

    # ─────────────────────────────────
    # Panel 5: Drawdown
    # ─────────────────────────────────
    ax5 = fig.add_subplot(gs[2, :2])
    style_ax(ax5, "Drawdown")
    roll_max = eq.cummax()
    dd = ((eq - roll_max) / roll_max * 100)
    ax5.fill_between(range(len(dd)), dd.values, 0, color=red, alpha=0.4)
    ax5.plot(range(len(dd)), dd.values, color=red, lw=1)
    ax5.axhline(0, color="#30363d", lw=0.6)
    ax5.set_ylabel("DD %", color=fg, fontsize=8)

    # ─────────────────────────────────
    # Panel 6: PnL Distribution
    # ─────────────────────────────────
    ax6 = fig.add_subplot(gs[2, 2])
    style_ax(ax6, "PnL Distribution")
    if not trades.empty:
        win_pnl  = trades[trades["pnl"] > 0]["pnl"]
        loss_pnl = trades[trades["pnl"] <= 0]["pnl"]
        if len(win_pnl):
            ax6.hist(win_pnl,  bins=15, color=green, alpha=0.7, label="Win")
        if len(loss_pnl):
            ax6.hist(loss_pnl, bins=15, color=red,   alpha=0.7, label="Loss")
        ax6.axvline(0, color=amber, lw=1)
        ax6.legend(fontsize=7, facecolor="#161b22", labelcolor=fg)

    # ─────────────────────────────────
    # Panel 7: Performance Stats
    # ─────────────────────────────────
    ax7 = fig.add_subplot(gs[3, :])
    ax7.set_facecolor("#161b22")
    ax7.axis("off")

    if "error" not in perf:
        stats = [
            ("Total Trades",     f"{perf['total_trades']}"),
            ("Win Rate",         f"{perf['win_rate']}%"),
            ("Profit Factor",    f"{perf['profit_factor']}"),
            ("Sharpe Ratio",     f"{perf['sharpe_ratio']}"),
            ("Max Drawdown",     f"{perf['max_drawdown_pct']}%"),
            ("Net Profit",       f"{perf['net_profit']:,.0f}"),
            ("Net Profit %",     f"{perf['net_profit_pct']}%"),
            ("Avg Win",          f"{perf['avg_win']:,.0f}"),
            ("Avg Loss",         f"{perf['avg_loss']:,.0f}"),
            ("Best Trade",       f"{perf['best_trade']:,.0f}"),
            ("Worst Trade",      f"{perf['worst_trade']:,.0f}"),
            ("Long / Short",     f"{perf['long_trades']} / {perf['short_trades']}"),
        ]
        cols = 6
        rows_ = [stats[i:i+cols] for i in range(0, len(stats), cols)]
        for r_idx, row_stats in enumerate(rows_):
            for c_idx, (label, val) in enumerate(row_stats):
                xpos = 0.01 + c_idx * 0.165
                ypos = 0.85 - r_idx * 0.42
                ax7.text(xpos, ypos + 0.12, label,
                         transform=ax7.transAxes,
                         color="#8b949e", fontsize=8)
                color = fg
                if label in ("Net Profit", "Net Profit %", "Avg Win", "Best Trade"):
                    color = green if float(val.replace(",","").replace("%","")) > 0 else red
                elif label in ("Avg Loss", "Worst Trade", "Max Drawdown"):
                    color = red
                elif label == "Win Rate":
                    color = green if float(val.replace("%","")) >= 50 else amber
                ax7.text(xpos, ypos - 0.05, val,
                         transform=ax7.transAxes,
                         color=color, fontsize=11, fontweight="bold")

    Path("reports").mkdir(exist_ok=True)
    plt.savefig("reports/scalping_dashboard.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("✅ บันทึก Dashboard → scalping_dashboard.png")


# ═════════════════════════════════════════════
# 8. REAL DATA LOADER
# ═════════════════════════════════════════════

def load_real_data(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """
    ดึงข้อมูลจริงจาก Yahoo Finance ด้วย yfinance
    หมายเหตุ: intraday (1m/5m/15m) ย้อนหลังได้สูงสุด 60 วัน
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("ติดตั้ง yfinance ก่อน: pip install yfinance")

    print(f"📡 ดึงข้อมูล {ticker} | period={period} | interval={interval} ...")
    raw = yf.download(ticker, period=period, interval=interval,
                      auto_adjust=True, progress=False)

    if raw.empty:
        raise ValueError(f"ไม่พบข้อมูลสำหรับ {ticker} — ตรวจสอบ ticker และ period/interval")

    # Flatten MultiIndex columns (yfinance บางเวอร์ชันคืน MultiIndex)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # เลือกเฉพาะ OHLCV และ rename เป็น lowercase
    col_map = {}
    for col in raw.columns:
        col_lower = col.lower()
        if col_lower in ("open", "high", "low", "close", "volume"):
            col_map[col] = col_lower

    df = raw[list(col_map.keys())].rename(columns=col_map).copy()
    df.dropna(inplace=True)

    print(f"✅ โหลดข้อมูลสำเร็จ: {len(df):,} แท่ง "
          f"({str(df.index[0])[:16]} → {str(df.index[-1])[:16]})")
    return df


# ═════════════════════════════════════════════
# 9. MAIN
# ═════════════════════════════════════════════

def main(df: pd.DataFrame = None):
    print("=" * 60)
    print("  SCALPING SYSTEM v1.0 — Wyckoff + Elliott + RSI Div")
    print("=" * 60)

    if df is None:
        # ── ดึงข้อมูลจริงจาก Yahoo Finance ──
        df = load_real_data(TICKER, PERIOD, INTERVAL)

    print(f"\n🔍 สร้าง Signals...")
    df_sig = generate_signals(df, CONFIG)

    n_long  = (df_sig["signal"] ==  1).sum()
    n_short = (df_sig["signal"] == -1).sum()
    print(f"   Long signals:  {n_long}")
    print(f"   Short signals: {n_short}")

    print(f"\n🧪 รัน Backtest...")
    result = run_backtest(df_sig, CONFIG)
    perf   = calc_performance(result, CONFIG)

    if "error" in perf:
        print(f"⚠️  {perf['error']}")
        return

    print(f"\n{'─'*40}")
    print(f"  📊 PERFORMANCE SUMMARY")
    print(f"{'─'*40}")
    for k, v in perf.items():
        print(f"  {k:<22} {v}")
    print(f"{'─'*40}")

    print(f"\n📈 สร้าง Dashboard...")
    plot_dashboard(df_sig, result, perf)

    # บันทึก Trade Log
    if not result["trades"].empty:
        log_path = "reports/trade_log.csv"
        result["trades"].to_csv(log_path, index=False)
        print(f"✅ บันทึก Trade Log → trade_log.csv")

    print(f"\n✅ เสร็จสิ้น! Capital: {CONFIG['initial_capital']:,.0f} → {result['final_capital']:,.2f}")


# ─────────────────────────────────────────────
# HOW TO USE WITH CUSTOM DATA:
#
# import yfinance as yf
# df = yf.download("PTT.BK", period="3mo", interval="5m")
# main(df=df)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    main()
