"""
╔══════════════════════════════════════════════════════════════════╗
║  SCALPING BOT v2.0 — Paper Trade (Auto Execute)                  ║
║  ใช้ Logic จาก scalping_system.py โดยตรง                          ║
║  หุ้นสหรัฐ → Alpaca Paper API                                       ║
║  Crypto    → Binance Testnet                                     ║
╚══════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, json, logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from colorama import Fore, init

sys.path.insert(0, str(Path(__file__).parent))
from scalping_system import (
    generate_signals,
    load_real_data,
    CONFIG as SYS_CONFIG,
)

# ── เชื่อม Dashboard (import push_update จาก dashboard_server) ───
try:
    from dashboard_server import push_update
    DASHBOARD_OK = True
except ImportError:
    DASHBOARD_OK = False
    def push_update(**kwargs): pass

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
# BOT CONFIG
# ══════════════════════════════════════════════════════════════════
BOT_CONFIG = {
    "stocks":  ["MSFT", "AAPL", "NVDA", "PTT.BK", "SCB.BK", "KBANK.BK"],
    "cryptos": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT"],
    "stock_interval":  "1h",
    "crypto_interval": "1h",
    "capital":         10_000,
    "risk_pct":        2.0,
    "stop_loss_pct":   1.0,
    "take_profit_pct": 2.0,
    "scan_interval":   60,
    "report_interval": 180,
    "report_keep":     3,
    "dry_run":         True,
}

SIGNAL_CFG = SYS_CONFIG.copy()
REPORT_DIR = Path("reports/live")


# ══════════════════════════════════════════════════════════════════
# AUTO REPORT MANAGER (เหมือนเดิมทุกอย่าง)
# ══════════════════════════════════════════════════════════════════
class ReportManager:
    def __init__(self, cfg: dict):
        self.interval  = cfg["report_interval"]
        self.keep      = cfg["report_keep"]
        self.last_time = 0
        REPORT_DIR.mkdir(parents=True, exist_ok=True)

    def should_report(self) -> bool:
        return (time.time() - self.last_time) >= self.interval

    def save(self, snapshot: dict, trade_log: list):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        snap_path = REPORT_DIR / f"snapshot_{ts}.json"
        snap_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8"
        )

        if trade_log:
            log_path = REPORT_DIR / f"trades_{ts}.json"
            log_path.write_text(
                json.dumps(trade_log, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8"
            )

        self._cleanup("snapshot_*.json")
        self._cleanup("trades_*.json")

        self.last_time = time.time()
        log.info(f"{Fore.CYAN}  📊 Report saved → {snap_path.name}  "
                 f"(เก็บล่าสุด {self.keep} ชุด)")

    def _cleanup(self, pattern: str):
        files = sorted(REPORT_DIR.glob(pattern))
        while len(files) > self.keep:
            files[0].unlink()
            log.info(f"{Fore.YELLOW}  🗑  ลบ report เก่า → {files[0].name}")
            files.pop(0)

    def print_report(self, snapshot: dict):
        eq  = snapshot["equity"]
        pnl = snapshot["session_pnl"]
        c   = Fore.GREEN if pnl >= 0 else Fore.RED
        print(f"\n{'─'*68}")
        print(f"  📊 AUTO REPORT  {snapshot['timestamp']}")
        print(f"{'─'*68}")
        print(f"  Equity       : ${eq:>12,.2f}")
        print(f"  Session PnL  : {c}{pnl:>+12,.4f}")
        print(f"  Total Trades : {snapshot['total_trades']}")
        print(f"  Win Rate     : {snapshot['win_rate']:.1f}%")
        print(f"  Open Pos     : {snapshot['open_positions']}")
        print(f"  Scans Done   : {snapshot['scan_count']}")
        print(f"{'─'*68}\n")


# ══════════════════════════════════════════════════════════════════
# BROKER CONNECTORS (เหมือนเดิมทุกอย่าง)
# ══════════════════════════════════════════════════════════════════
class AlpacaConnector:
    def __init__(self):
        self.api = None
        try:
            import alpaca_trade_api as tradeapi
        except ImportError:
            log.warning(f"{Fore.YELLOW}⚠ alpaca-trade-api ไม่ได้ติดตั้ง")
            return
        key    = os.getenv("ALPACA_API_KEY", "") or os.getenv("ALPACA_KEY", "")
        secret = os.getenv("ALPACA_SECRET", "") or os.getenv("ALPACA_SECRET_KEY", "")
        if not key or not secret:
            log.warning(f"{Fore.YELLOW}⚠ ไม่พบ ALPACA key ใน .env → dry-run หุ้น")
            return
        try:
            self.api = tradeapi.REST(key_id=key, secret_key=secret,
                                     base_url="https://paper-api.alpaca.markets")
            acct = self.api.get_account()
            log.info(f"{Fore.GREEN}✓ Alpaca Paper  cash=${float(acct.cash):,.2f}")
        except Exception as e:
            log.error(f"Alpaca connect error: {e}")

    def submit(self, symbol, side, qty):
        if not self.api: return None
        try:
            order = self.api.submit_order(symbol=symbol, qty=max(1, qty),
                                          side=side, type="market",
                                          time_in_force="day")
            log.info(f"{Fore.CYAN}  [ALPACA] {side.upper()} {qty} {symbol}  id={order.id[:8]}")
            return order
        except Exception as e:
            log.error(f"  Alpaca order error: {e}")


class BinanceConnector:
    def __init__(self):
        self.client = None
        try:
            from binance.client import Client
        except ImportError:
            log.warning(f"{Fore.YELLOW}⚠ python-binance ไม่ได้ติดตั้ง")
            return
        key    = os.getenv("BINANCE_API_KEY", "") or os.getenv("BINANCE_KEY", "")
        secret = os.getenv("BINANCE_SECRET", "") or os.getenv("BINANCE_SECRET_KEY", "")
        if not key or not secret:
            log.warning(f"{Fore.YELLOW}⚠ ไม่พบ BINANCE key ใน .env → dry-run crypto")
            return
        try:
            from binance.client import Client
            self.client = Client(key, secret, testnet=True)
            bal = self.client.get_asset_balance(asset="USDT")
            log.info(f"{Fore.GREEN}✓ Binance Testnet  USDT={float(bal['free']):,.2f}")
        except Exception as e:
            log.error(f"Binance connect error: {e}")

    def get_crypto_data(self, symbol, interval, limit=100):
        if not self.client: return None
        try:
            from binance.client import Client
            import pandas as pd
            imap = {"1m": Client.KLINE_INTERVAL_1MINUTE,
                    "5m": Client.KLINE_INTERVAL_5MINUTE,
                    "15m": Client.KLINE_INTERVAL_15MINUTE,
                    "1h": Client.KLINE_INTERVAL_1HOUR}
            klines = self.client.get_klines(symbol=symbol,
                                            interval=imap.get(interval, Client.KLINE_INTERVAL_1HOUR),
                                            limit=limit)
            df = pd.DataFrame(klines, columns=[
                "timestamp","open","high","low","close","volume",
                "close_time","qav","trades","tbav","tqav","ignore"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("timestamp")
            for col in ["open","high","low","close","volume"]:
                df[col] = df[col].astype(float)
            df.rename(columns={"open":"Open","high":"High","low":"Low",
                                "close":"Close","volume":"Volume"}, inplace=True)
            return df
        except Exception as e:
            log.error(f"Binance get_data error {symbol}: {e}")

    def submit(self, symbol, side, qty):
        if not self.client: return None
        try:
            order = (self.client.order_market_buy(symbol=symbol, quantity=qty)
                     if side == "buy"
                     else self.client.order_market_sell(symbol=symbol, quantity=qty))
            log.info(f"{Fore.CYAN}  [BINANCE] {side.upper()} {qty} {symbol}")
            return order
        except Exception as e:
            log.error(f"  Binance order error: {e}")


# ══════════════════════════════════════════════════════════════════
# POSITION MANAGER (เหมือนเดิมทุกอย่าง)
# ══════════════════════════════════════════════════════════════════
class PositionManager:
    def __init__(self, cfg):
        self.cfg       = cfg
        self.equity    = cfg["capital"]
        self.positions = {}
        self.trade_log = []

    def calc_qty(self, price):
        risk_amt  = self.equity * (self.cfg["risk_pct"] / 100)
        stop_dist = price * (self.cfg["stop_loss_pct"] / 100)
        return round(risk_amt / max(stop_dist, 1e-9), 6)

    def open(self, symbol, price, side=1):
        qty = self.calc_qty(price)
        sl  = round(price * (1 - self.cfg["stop_loss_pct"] / 100), 6)
        tp  = round(price * (1 + self.cfg["take_profit_pct"] / 100), 6)
        self.positions[symbol] = {"side": side, "qty": qty, "entry": price,
                                  "sl": sl, "tp": tp,
                                  "opened_at": datetime.now().strftime("%H:%M:%S")}
        return qty, sl, tp

    def check_exit(self, symbol, price):
        pos = self.positions.get(symbol)
        if not pos: return None
        if price <= pos["sl"]: return "STOP_LOSS"
        if price >= pos["tp"]: return "TAKE_PROFIT"
        return None

    def close(self, symbol, price, reason):
        pos = self.positions.pop(symbol, None)
        if not pos: return None
        pnl = round((price - pos["entry"]) * pos["qty"], 4)
        self.equity = round(self.equity + pnl, 2)
        rec = {**pos, "symbol": symbol, "exit": price, "pnl": pnl,
               "reason": reason, "closed_at": datetime.now().strftime("%H:%M:%S")}
        self.trade_log.append(rec)
        return rec

    def stats(self):
        trades = self.trade_log
        if not trades:
            return {"total": 0, "win_rate": 0.0}
        wins = [t for t in trades if t["pnl"] > 0]
        return {
            "total":     len(trades),
            "win_rate":  round(len(wins) / len(trades) * 100, 1),
            "total_pnl": round(sum(t["pnl"] for t in trades), 4),
        }


# ══════════════════════════════════════════════════════════════════
# MAIN BOT (เหมือนเดิม + เพิ่ม push_update หลัง scan)
# ══════════════════════════════════════════════════════════════════
class ScalpingBot:
    def __init__(self):
        self.cfg     = BOT_CONFIG
        self.pm      = PositionManager(BOT_CONFIG)
        self.alpaca  = AlpacaConnector()
        self.binance = BinanceConnector()
        self.report  = ReportManager(BOT_CONFIG)
        self.scan_no = 0

    def _get_signal(self, symbol, asset_type):
        try:
            if asset_type == "stock":
                df_raw = load_real_data(symbol, period="5d",
                                        interval=self.cfg["stock_interval"])
            else:
                df_raw = self.binance.get_crypto_data(
                    symbol, interval=self.cfg["crypto_interval"])
            if df_raw is None or len(df_raw) < 30:
                return 0, None, {}
            df_sig = generate_signals(df_raw, SIGNAL_CFG)
            latest = df_sig.iloc[-1]
            signal = int(latest.get("signal", 0))
            price  = float(latest["close"])
            ind    = {
                "ema_fast":    round(float(latest.get("ema_fast", 0)), 4),
                "ema_slow":    round(float(latest.get("ema_slow", 0)), 4),
                "rsi":         round(float(latest.get("rsi", 0)), 2),
                "wyckoff":     str(latest.get("wyckoff", "")),
                "rsi_div":     int(latest.get("rsi_div", 0)),
                "long_score":  int(latest.get("long_score", 0)),
                "short_score": int(latest.get("short_score", 0)),
            }
            return signal, price, ind
        except Exception as e:
            log.error(f"  _get_signal error [{symbol}]: {e}")
            return 0, None, {}

    def _log_signal(self, symbol, price, signal, ind):
        c     = {1: Fore.GREEN, -1: Fore.RED, 0: Fore.YELLOW}.get(signal, Fore.WHITE)
        label = {1: "BUY ", -1: "SELL", 0: "HOLD"}.get(signal, "WAIT")
        wyck  = f" [{ind.get('wyckoff','')}]" if ind.get("wyckoff") else ""
        div   = " [div↑]" if ind.get("rsi_div") == 1 else \
                " [div↓]" if ind.get("rsi_div") == -1 else ""
        log.info(f"{c}[{label}] {symbol:<10}  ${price:<10.4f}  "
                 f"EMA9={ind.get('ema_fast','?'):<10}  "
                 f"EMA21={ind.get('ema_slow','?'):<10}  "
                 f"RSI={ind.get('rsi','?'):<7}"
                 f"score={ind.get('long_score',0)}/{ind.get('short_score',0)}"
                 f"{wyck}{div}")

    def _execute(self, symbol, signal, price, asset_type):
        pm, dry = self.pm, self.cfg["dry_run"]
        in_pos  = symbol in pm.positions

        exit_reason = pm.check_exit(symbol, price)
        if exit_reason and in_pos:
            rec = pm.close(symbol, price, exit_reason)
            c   = Fore.GREEN if rec["pnl"] >= 0 else Fore.RED
            log.info(f"{c}  ↳ CLOSE {symbol} @ ${price}  "
                     f"PnL={rec['pnl']:+.4f}  [{exit_reason}]  "
                     f"Equity=${pm.equity:,.2f}")
            if not dry:
                b = self.alpaca if asset_type == "stock" else self.binance
                b.submit(symbol, "sell",
                         int(rec["qty"]) if asset_type == "stock" else rec["qty"])
            return

        if signal == 1 and not in_pos:
            qty, sl, tp = pm.open(symbol, price)
            log.info(f"{Fore.GREEN}  ↳ OPEN BUY {symbol}  "
                     f"qty={qty}  entry=${price}  SL=${sl}  TP=${tp}")
            if not dry:
                b = self.alpaca if asset_type == "stock" else self.binance
                b.submit(symbol, "buy",
                         int(qty) if asset_type == "stock" else qty)

        elif signal == -1 and in_pos:
            rec = pm.close(symbol, price, "SIGNAL")
            c   = Fore.GREEN if rec["pnl"] >= 0 else Fore.RED
            log.info(f"{c}  ↳ CLOSE {symbol} @ ${price}  "
                     f"PnL={rec['pnl']:+.4f}  [SIGNAL]  "
                     f"Equity=${pm.equity:,.2f}")
            if not dry:
                b = self.alpaca if asset_type == "stock" else self.binance
                b.submit(symbol, "sell",
                         int(rec["qty"]) if asset_type == "stock" else rec["qty"])

    def _build_snapshot(self) -> dict:
        stats = self.pm.stats()
        return {
            "timestamp":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "equity":         self.pm.equity,
            "session_pnl":    round(self.pm.equity - self.cfg["capital"], 4),
            "total_trades":   stats["total"],
            "win_rate":       stats["win_rate"],
            "open_positions": len(self.pm.positions),
            "positions":      dict(self.pm.positions),
            "scan_count":     self.scan_no,
            "dry_run":        self.cfg["dry_run"],
        }

    def scan(self):
        self.scan_no += 1
        now      = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_tag = f"{Fore.YELLOW}[DRY-RUN]" if self.cfg["dry_run"] else f"{Fore.GREEN}[PAPER]"
        print(f"\n{'═'*68}")
        print(f"  SCAN #{self.scan_no}  {now}  {mode_tag}  "
              f"Equity=${self.pm.equity:,.2f}  "
              f"Positions={len(self.pm.positions)}")
        print(f"{'═'*68}")

        scan_prices = {}

        for sym in self.cfg["stocks"]:
            sig, price, ind = self._get_signal(sym, "stock")
            if price is None: continue
            self._log_signal(sym, price, sig, ind)
            self._execute(sym, sig, price, "stock")
            scan_prices[sym] = {
                "price":  price, "type": "stock",
                "signal": {1:"BUY",-1:"SELL",0:"HOLD"}.get(sig,"HOLD"),
                **ind
            }

        if self.binance.client:
            for sym in self.cfg["cryptos"]:
                sig, price, ind = self._get_signal(sym, "crypto")
                if price is None: continue
                self._log_signal(sym, price, sig, ind)
                self._execute(sym, sig, price, "crypto")
                scan_prices[sym] = {
                    "price":  price, "type": "crypto",
                    "signal": {1:"BUY",-1:"SELL",0:"HOLD"}.get(sig,"HOLD"),
                    **ind
                }
        else:
            log.info(f"{Fore.YELLOW}  [CRYPTO] ข้าม — Binance ไม่ได้เชื่อมต่อ")

        # ── Auto Report ทุก 3 นาที (เหมือนเดิม) ─────────────────
        if self.report.should_report():
            snapshot = self._build_snapshot()
            self.report.save(snapshot, self.pm.trade_log)
            self.report.print_report(snapshot)

        # ── Push ไป Dashboard ผ่าน WebSocket ทันที ───────────────
        push_update(
            prices   = scan_prices,
            snapshot = self._build_snapshot(),
            trades   = self.pm.trade_log,
        )

    def print_summary(self):
        snapshot = self._build_snapshot()
        self.report.save(snapshot, self.pm.trade_log)
        push_update(snapshot=snapshot, trades=self.pm.trade_log)
        print(f"\n{'═'*68}")
        print(f"  SESSION SUMMARY")
        print(f"{'═'*68}")
        print(f"  Capital Start : ${self.cfg['capital']:,.2f}")
        print(f"  Capital End   : ${self.pm.equity:,.2f}")
        pnl = self.pm.equity - self.cfg["capital"]
        c = Fore.GREEN if pnl >= 0 else Fore.RED
        print(f"  Net PnL       : {c}{pnl:>+,.4f}")
        stats = self.pm.stats()
        print(f"  Total Trades  : {stats['total']}")
        print(f"  Win Rate      : {stats['win_rate']:.1f}%")
        print(f"{'═'*68}")

    def run(self):
        mode = "DRY-RUN (ไม่ส่ง order จริง)" if self.cfg["dry_run"] else "PAPER TRADE"
        dash = "เชื่อมต่อแล้ว ✓" if DASHBOARD_OK else "ไม่พบ dashboard_server.py"
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
║  Scan interval : {self.cfg['scan_interval']}s  │  Report : ทุก {self.cfg['report_interval']}s (เก็บ {self.cfg['report_keep']} ชุด)     ║
║  Dashboard     : {dash:<48}║
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