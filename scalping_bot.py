"""
╔══════════════════════════════════════════════════════════════════╗
║  SCALPING BOT v2.0 — Paper Trade (Auto Execute)                 ║
║  ใช้ Logic จาก scalping_system.py โดยตรง                        ║
║  หุ้นสหรัฐ → Alpaca Paper API                                   ║
║  Crypto    → Binance Testnet                                    ║
╚══════════════════════════════════════════════════════════════════╝

วิธีใช้:
  1. วางไฟล์นี้ไว้โฟลเดอร์เดียวกับ scalping_system.py
  2. สร้างไฟล์ .env (ดูด้านล่าง)
  3. รัน: python scalping_bot.py

ติดตั้ง dependencies:
  pip install alpaca-trade-api python-binance python-dotenv colorama schedule

ไฟล์ .env:
  ALPACA_API_KEY=xxxx
  ALPACA_SECRET=xxxx
  BINANCE_API_KEY=xxxx
  BINANCE_SECRET=xxxx
"""

import os, sys, time, json, logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, Style, init

# ── Import ระบบ Signal จาก scalping_system.py เดิม ──────────────
sys.path.insert(0, str(Path(__file__).parent))
from scalping_system import (
    generate_signals,   # Wyckoff + Elliott + RSI Divergence
    load_real_data,
    CONFIG as SYS_CONFIG,
)

# ─────────────────────────────────────────────────────────────────
load_dotenv()
init(autoreset=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot_live.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
# BOT CONFIG  ← แก้ตรงนี้
# ══════════════════════════════════════════════════════════════════
BOT_CONFIG = {
    # สินทรัพย์ที่จะเทรด
    "stocks":  ["MSFT", "AAPL", "NVDA"],   # หุ้นสหรัฐ (Alpaca)
    "cryptos": ["BTCUSDT", "ETHUSDT"],      # Crypto (Binance Testnet)

    # Timeframe สำหรับดึงข้อมูล real-time
    "stock_interval":  "1h",   # 1m 5m 15m 30m 1h
    "crypto_interval": "1h",

    # Risk Management
    "capital":          10_000,   # เงินทุน paper trade
    "risk_pct":         2.0,      # % ต่อ trade
    "stop_loss_pct":    1.0,      # % SL จาก entry
    "take_profit_pct":  2.0,      # % TP จาก entry (RR 1:2)

    # รอบ scan (วินาที) — ไม่ควรน้อยกว่า 60 เพราะ yfinance rate limit
    "scan_interval": 60,

    # True = แสดง signal แต่ไม่ส่ง order จริง (ทดสอบก่อน)
    "dry_run": True,
}

# ดึง indicator config จาก scalping_system.py เดิม
SIGNAL_CFG = SYS_CONFIG.copy()


# ══════════════════════════════════════════════════════════════════
# BROKER CONNECTORS
# ══════════════════════════════════════════════════════════════════
class AlpacaConnector:
    """Alpaca Paper Trade API"""
    def __init__(self):
        self.api = None
        try:
            import alpaca_trade_api as tradeapi
        except ImportError:
            log.warning(f"{Fore.YELLOW}⚠ alpaca-trade-api ไม่ได้ติดตั้ง  →  pip install alpaca-trade-api")
            return

        key    = os.getenv("ALPACA_API_KEY", "") or os.getenv("ALPACA_KEY", "")
        secret = os.getenv("ALPACA_SECRET", "") or os.getenv("ALPACA_SECRET_KEY", "")
        base_url = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

        if not key or not secret:
            log.warning(
                f"{Fore.YELLOW}⚠ ไม่พบ ALPACA_API_KEY/ALPACA_SECRET ใน .env  →  ใช้ dry-run สำหรับหุ้น"
            )
            return
        try:
            self.api = tradeapi.REST(
                key_id=key,
                secret_key=secret,
                base_url=base_url,
            )
            acct = self.api.get_account()
            log.info(f"{Fore.GREEN}✓ Alpaca Paper  cash=${float(acct.cash):,.2f}")
        except Exception as e:
            log.error(f"Alpaca connect error: {e}")

    def submit(self, symbol: str, side: str, qty: int):
        if not self.api:
            return None
        try:
            order = self.api.submit_order(
                symbol=symbol,
                qty=max(1, qty),
                side=side,           # "buy" / "sell"
                type="market",
                time_in_force="day",
            )
            log.info(f"{Fore.CYAN}  [ALPACA] {side.upper()} {qty} {symbol}  id={order.id[:8]}")
            return order
        except Exception as e:
            log.error(f"  Alpaca order error: {e}")
            return None


class BinanceConnector:
    """Binance Testnet"""
    def __init__(self):
        self.client = None
        try:
            from binance.client import Client
        except ImportError:
            log.warning(f"{Fore.YELLOW}⚠ python-binance ไม่ได้ติดตั้ง  →  pip install python-binance")
            return

        key    = os.getenv("BINANCE_API_KEY", "") or os.getenv("BINANCE_KEY", "")
        secret = os.getenv("BINANCE_SECRET", "") or os.getenv("BINANCE_SECRET_KEY", "")

        if not key or not secret:
            log.warning(
                f"{Fore.YELLOW}⚠ ไม่พบ BINANCE_API_KEY/BINANCE_SECRET ใน .env  →  ใช้ dry-run สำหรับ crypto"
            )
            return
        try:
            from binance.client import Client
            self.client = Client(key, secret, testnet=True)
            bal = self.client.get_asset_balance(asset="USDT")
            log.info(f"{Fore.GREEN}✓ Binance Testnet  USDT={float(bal['free']):,.2f}")
        except Exception as e:
            log.error(f"Binance connect error: {e}")

    def get_price(self, symbol: str) -> float:
        """ดึงราคา real-time จาก Binance"""
        if not self.client:
            return None
        try:
            t = self.client.get_symbol_ticker(symbol=symbol)
            return float(t["price"])
        except Exception:
            return None

    def get_crypto_data(self, symbol: str, interval: str, limit: int = 100):
        """ดึง OHLCV สำหรับ generate_signals"""
        if not self.client:
            return None
        try:
            from binance.client import Client
            interval_map = {
                "1m": Client.KLINE_INTERVAL_1MINUTE,
                "5m": Client.KLINE_INTERVAL_5MINUTE,
                "15m": Client.KLINE_INTERVAL_15MINUTE,
                "1h": Client.KLINE_INTERVAL_1HOUR,
            }
            import pandas as pd
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval_map.get(interval, Client.KLINE_INTERVAL_1HOUR),
                limit=limit,
            )
            df = pd.DataFrame(klines, columns=[
                "timestamp","open","high","low","close","volume",
                "close_time","qav","trades","tbav","tqav","ignore"
            ])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")
            for col in ["open","high","low","close","volume"]:
                df[col] = df[col].astype(float)
            # rename ให้ตรงกับที่ generate_signals คาดหวัง
            df.rename(columns={"open":"Open","high":"High","low":"Low",
                                "close":"Close","volume":"Volume"}, inplace=True)
            return df
        except Exception as e:
            log.error(f"Binance get_data error {symbol}: {e}")
            return None

    def submit(self, symbol: str, side: str, qty: float):
        if not self.client:
            return None
        try:
            if side == "buy":
                order = self.client.order_market_buy(symbol=symbol, quantity=qty)
            else:
                order = self.client.order_market_sell(symbol=symbol, quantity=qty)
            log.info(f"{Fore.CYAN}  [BINANCE] {side.upper()} {qty} {symbol}  id={order['orderId']}")
            return order
        except Exception as e:
            log.error(f"  Binance order error: {e}")
            return None


# ══════════════════════════════════════════════════════════════════
# POSITION & RISK MANAGER
# ══════════════════════════════════════════════════════════════════
class PositionManager:
    def __init__(self, cfg: dict):
        self.cfg       = cfg
        self.equity    = cfg["capital"]
        self.positions = {}   # symbol → {side, qty, entry, sl, tp, opened_at}
        self.trade_log = []

    def calc_qty(self, price: float) -> float:
        risk_amt  = self.equity * (self.cfg["risk_pct"] / 100)
        stop_dist = price * (self.cfg["stop_loss_pct"] / 100)
        return round(risk_amt / max(stop_dist, 1e-9), 6)

    def open(self, symbol: str, price: float, side: int = 1):
        qty = self.calc_qty(price)
        sl  = round(price * (1 - self.cfg["stop_loss_pct"] / 100), 6)
        tp  = round(price * (1 + self.cfg["take_profit_pct"] / 100), 6)
        self.positions[symbol] = {
            "side": side, "qty": qty, "entry": price,
            "sl": sl, "tp": tp,
            "opened_at": datetime.now().strftime("%H:%M:%S"),
        }
        return qty, sl, tp

    def check_exit(self, symbol: str, price: float):
        pos = self.positions.get(symbol)
        if not pos:
            return None
        if price <= pos["sl"]:
            return "STOP_LOSS"
        if price >= pos["tp"]:
            return "TAKE_PROFIT"
        return None

    def close(self, symbol: str, price: float, reason: str):
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None
        pnl = round((price - pos["entry"]) * pos["qty"], 4)
        self.equity = round(self.equity + pnl, 2)
        record = {**pos, "symbol": symbol, "exit": price,
                  "pnl": pnl, "reason": reason,
                  "closed_at": datetime.now().strftime("%H:%M:%S")}
        self.trade_log.append(record)
        return record


# ══════════════════════════════════════════════════════════════════
# MAIN BOT
# ══════════════════════════════════════════════════════════════════
class ScalpingBot:
    def __init__(self):
        self.cfg     = BOT_CONFIG
        self.pm      = PositionManager(BOT_CONFIG)
        self.alpaca  = AlpacaConnector()
        self.binance = BinanceConnector()
        self.scan_no = 0

    # ── ดึงข้อมูล + สร้าง Signal ─────────────────────────────────
    def _get_signal(self, symbol: str, asset_type: str):
        """
        คืน (signal_int, price, indicators_dict)
        signal_int: +1=BUY / -1=SELL / 0=HOLD
        """
        try:
            if asset_type == "stock":
                df_raw = load_real_data(
                    symbol,
                    period="5d",
                    interval=self.cfg["stock_interval"],
                )
            else:
                df_raw = self.binance.get_crypto_data(
                    symbol,
                    interval=self.cfg["crypto_interval"],
                )
            if df_raw is None or len(df_raw) < 30:
                return 0, None, {}

            # ── ใช้ generate_signals จาก scalping_system.py ──────
            df_sig = generate_signals(df_raw, SIGNAL_CFG)

            latest = df_sig.iloc[-1]
            signal = int(latest.get("signal", 0))
            price  = float(latest["close"])
            ind    = {
                "ema_fast":    round(float(latest.get("ema_fast", 0)), 4),
                "ema_slow":    round(float(latest.get("ema_slow", 0)), 4),
                "rsi":         round(float(latest.get("rsi", 0)), 2),
                "wyckoff":     str(latest.get("wyckoff", "")),
                "wave3":       int(latest.get("wave3", 0)),
                "rsi_div":     int(latest.get("rsi_div", 0)),
                "long_score":  int(latest.get("long_score", 0)),
                "short_score": int(latest.get("short_score", 0)),
            }
            return signal, price, ind

        except Exception as e:
            log.error(f"  _get_signal error [{symbol}]: {e}")
            return 0, None, {}

    # ── Log สัญญาณสวยๆ ──────────────────────────────────────────
    def _log_signal(self, symbol, price, signal, ind):
        c = {1: Fore.GREEN, -1: Fore.RED, 0: Fore.YELLOW}.get(signal, Fore.WHITE)
        label = {1: "BUY ", -1: "SELL", 0: "HOLD"}.get(signal, "WAIT")
        wyck  = f" [{ind.get('wyckoff','')}]" if ind.get("wyckoff") else ""
        div   = " [div↑]" if ind.get("rsi_div") == 1 else " [div↓]" if ind.get("rsi_div") == -1 else ""
        log.info(
            f"{c}[{label}] {symbol:<10}  "
            f"${price:<10.4f}  "
            f"EMA9={ind.get('ema_fast','?'):<10}  "
            f"EMA21={ind.get('ema_slow','?'):<10}  "
            f"RSI={ind.get('rsi','?'):<7}"
            f"score={ind.get('long_score',0)}/{ind.get('short_score',0)}"
            f"{wyck}{div}"
        )

    # ── Execute Order ────────────────────────────────────────────
    def _execute(self, symbol: str, signal: int, price: float, asset_type: str):
        pm       = self.pm
        in_pos   = symbol in pm.positions
        dry      = self.cfg["dry_run"]

        # ตรวจ SL / TP ก่อนเสมอ
        exit_reason = pm.check_exit(symbol, price)
        if exit_reason and in_pos:
            rec = pm.close(symbol, price, exit_reason)
            c   = Fore.GREEN if rec["pnl"] >= 0 else Fore.RED
            log.info(f"{c}  ↳ CLOSE {symbol} @ ${price}  "
                     f"PnL={rec['pnl']:+.4f}  [{exit_reason}]  "
                     f"Equity=${pm.equity:,.2f}")
            if not dry:
                broker = self.alpaca if asset_type == "stock" else self.binance
                broker.submit(symbol, "sell", int(rec["qty"]) if asset_type == "stock" else rec["qty"])
            return

        # BUY signal → เปิด position ใหม่
        if signal == 1 and not in_pos:
            qty, sl, tp = pm.open(symbol, price)
            log.info(f"{Fore.GREEN}  ↳ OPEN BUY {symbol}  "
                     f"qty={qty}  entry=${price}  SL=${sl}  TP=${tp}")
            if not dry:
                broker = self.alpaca if asset_type == "stock" else self.binance
                broker.submit(symbol, "buy", int(qty) if asset_type == "stock" else qty)

        # SELL signal → ปิด position ที่เปิดอยู่
        elif signal == -1 and in_pos:
            rec = pm.close(symbol, price, "SIGNAL")
            c   = Fore.GREEN if rec["pnl"] >= 0 else Fore.RED
            log.info(f"{c}  ↳ CLOSE {symbol} @ ${price}  "
                     f"PnL={rec['pnl']:+.4f}  [SIGNAL]  "
                     f"Equity=${pm.equity:,.2f}")
            if not dry:
                broker = self.alpaca if asset_type == "stock" else self.binance
                broker.submit(symbol, "sell", int(rec["qty"]) if asset_type == "stock" else rec["qty"])

    # ── Scan รอบเดียว ────────────────────────────────────────────
    def scan(self):
        self.scan_no += 1
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_tag = f"{Fore.YELLOW}[DRY-RUN]" if self.cfg["dry_run"] else f"{Fore.GREEN}[PAPER]"
        print(f"\n{'═'*68}")
        print(f"  SCAN #{self.scan_no}  {now}  {mode_tag}  "
              f"Equity=${self.pm.equity:,.2f}  "
              f"Positions={len(self.pm.positions)}")
        print(f"{'═'*68}")

        # หุ้นสหรัฐ
        for sym in self.cfg["stocks"]:
            sig, price, ind = self._get_signal(sym, "stock")
            if price is None:
                continue
            self._log_signal(sym, price, sig, ind)
            self._execute(sym, sig, price, "stock")

        # Crypto
        if self.binance.client:
            for sym in self.cfg["cryptos"]:
                sig, price, ind = self._get_signal(sym, "crypto")
                if price is None:
                    continue
                self._log_signal(sym, price, sig, ind)
                self._execute(sym, sig, price, "crypto")
        else:
            log.info(f"{Fore.YELLOW}  [CRYPTO] ข้าม — Binance ไม่ได้เชื่อมต่อ")

    # ── Summary ──────────────────────────────────────────────────
    def print_summary(self):
        pm  = self.pm
        log = logging.getLogger(__name__)
        print(f"\n{'═'*68}")
        print(f"  SESSION SUMMARY")
        print(f"{'═'*68}")
        print(f"  Capital Start : ${self.cfg['capital']:,.2f}")
        print(f"  Capital End   : ${pm.equity:,.2f}")
        pnl = pm.equity - self.cfg["capital"]
        c = Fore.GREEN if pnl >= 0 else Fore.RED
        print(f"  Net PnL       : {c}{pnl:+,.2f}")
        print(f"  Total Trades  : {len(pm.trade_log)}")
        if pm.trade_log:
            wins = [t for t in pm.trade_log if t["pnl"] > 0]
            wr   = len(wins) / len(pm.trade_log) * 100
            print(f"  Win Rate      : {wr:.1f}%")
        print(f"{'═'*68}")

        # บันทึก trade log
        if pm.trade_log:
            out = Path("reports/trade_log_live.json")
            out.parent.mkdir(exist_ok=True)
            out.write_text(
                json.dumps(pm.trade_log, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
            print(f"  💾 บันทึก trade log → {out}")

    # ── Run Loop ─────────────────────────────────────────────────
    def run(self):
        mode = "DRY-RUN (ไม่ส่ง order จริง)" if self.cfg["dry_run"] else "PAPER TRADE"
        print(f"""
╔══════════════════════════════════════════════════════════════════╗
║  SCALPING BOT v2.0  —  {mode:<40}║
║                                                                  ║
║  Signal Logic  : Wyckoff + Elliott Wave + RSI Divergence         ║
║  Capital       : ${self.cfg['capital']:>10,.2f}                             ║
║  Risk/Trade    : {self.cfg['risk_pct']}%                                         ║
║  SL / TP       : {self.cfg['stop_loss_pct']}% / {self.cfg['take_profit_pct']}%  (RR 1:2)                      ║
║  Stocks        : {', '.join(self.cfg['stocks']):<46}║
║  Cryptos       : {', '.join(self.cfg['cryptos']):<46}║
║  Scan interval : {self.cfg['scan_interval']}s                                        ║
║                                                                  ║
║  กด Ctrl+C เพื่อหยุดและดู Summary                               ║
╚══════════════════════════════════════════════════════════════════╝
""")
        try:
            while True:
                self.scan()
                time.sleep(self.cfg["scan_interval"])
        except KeyboardInterrupt:
            print(f"\n{Fore.YELLOW}⏹  Bot หยุดทำงานโดยผู้ใช้")
            self.print_summary()


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    bot = ScalpingBot()
    bot.run()
