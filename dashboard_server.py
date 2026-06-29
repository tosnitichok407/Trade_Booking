"""
╔══════════════════════════════════════════════════════════════════╗
║  TRADING DASHBOARD SERVER                                        ║
║  - รัน Flask web server                                          ║
║  - อ่าน report จาก scalping_bot.py แบบ real-time               ║
║  - เข้าถึงได้จากทุกอุปกรณ์ผ่าน internet                        ║
╚══════════════════════════════════════════════════════════════════╝

ติดตั้ง: pip install flask flask-cors flask-sock yfinance python-binance
รัน:     python dashboard_server.py
เปิด:    http://localhost:8080
"""

from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from flask_sock import Sock
import json, threading, time, os
from pathlib import Path
from datetime import datetime

try:
    import yfinance as yf
    YF_OK = True
except ImportError:
    YF_OK = False

app  = Flask(__name__, static_folder="dashboard_static")
CORS(app)
sock = Sock(app)

REPORT_DIR = Path("reports/live")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── Shared state — Bot เขียน, Dashboard อ่าน ─────────────────────
_state = {
    "prices":      {},
    "snapshot":    None,
    "trades":      [],
    "server_time": "",
}
_state_lock   = threading.Lock()
_clients      = set()
_clients_lock = threading.Lock()

# ── ราคา cache ───────────────────────────────────────────────────
_price_cache = {}
_cache_time  = {}
CACHE_SEC    = 30


# ══════════════════════════════════════════════════════════════════
# PUBLIC API — Bot เรียกเพื่ออัปเดตข้อมูล real-time
# ══════════════════════════════════════════════════════════════════
def push_update(prices=None, snapshot=None, trades=None):
    with _state_lock:
        if prices   is not None: _state["prices"].update(prices)
        if snapshot is not None: _state["snapshot"] = snapshot
        if trades   is not None: _state["trades"]   = trades
        _state["server_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _broadcast(_state.copy())


def _broadcast(data):
    global _clients
    msg  = json.dumps(data, default=str)
    dead = set()
    with _clients_lock:
        current_clients = set(_clients)   # ← copy ก่อน iterate
    for client in current_clients:        # ← เปลี่ยนชื่อตัวแปรจาก ws เป็น client
        try:
            client.send(msg)
        except Exception:
            dead.add(client)
    with _clients_lock:
        _clients -= dead


# ══════════════════════════════════════════════════════════════════
# FILE HELPERS
# ══════════════════════════════════════════════════════════════════
def load_latest_snapshot():
    files = sorted(REPORT_DIR.glob("snapshot_*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except:
        return None


def load_trade_log():
    files = sorted(REPORT_DIR.glob("trades_*.json"))
    if not files:
        return []
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))
    except:
        return []


# ══════════════════════════════════════════════════════════════════
# WEBSOCKET ENDPOINT
# ══════════════════════════════════════════════════════════════════
@sock.route("/ws")
def websocket(ws):
    with _clients_lock:
        _clients.add(ws)
    try:
        with _state_lock:
            current = _state.copy()
        if current["snapshot"] is None:
            current["snapshot"] = load_latest_snapshot()
            current["trades"]   = load_trade_log()
        ws.send(json.dumps(current, default=str))
        while True:
            ws.receive(timeout=60)
    except Exception:
        pass
    finally:
        with _clients_lock:
            _clients.discard(ws)


# ══════════════════════════════════════════════════════════════════
# REST API
# ══════════════════════════════════════════════════════════════════
@app.route("/api/all")
def api_all():
    with _state_lock:
        prices = dict(_state.get("prices", {}))
        snap   = _state.get("snapshot") or load_latest_snapshot()
        trades = _state.get("trades")   or load_trade_log()

    return jsonify({
        "prices":      prices,   # ← อ่านจาก state ที่ Bot push มา ไม่ hardcode
        "snapshot":    snap,
        "trades":      trades,
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/snapshot")
def api_snapshot():
    with _state_lock:
        snap = _state.get("snapshot")
    if not snap:
        snap = load_latest_snapshot()
    if not snap:
        return jsonify({"error": "ยังไม่มี report — รัน scalping_bot.py ก่อน"})
    return jsonify(snap)


@app.route("/api/trades")
def api_trades():
    with _state_lock:
        trades = _state.get("trades", [])
    if not trades:
        trades = load_trade_log()
    return jsonify(trades)


@app.route("/")
def index():
    return send_from_directory("dashboard_static", "index.html")


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("╔══════════════════════════════════════════╗")
    print("║  TRADING DASHBOARD SERVER                ║")
    print("║  http://localhost:8080                   ║")
    print("║  WebSocket: ws://localhost:8080/ws       ║")
    print("╚══════════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=8080, debug=False)