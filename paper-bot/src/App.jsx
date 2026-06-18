import { useState, useEffect, useCallback } from "react";

// ─── REAL PRICE FETCHER via Anthropic API + Web Search ───────────────────────
// ดึงราคาจริงจาก web search ทุก 30 วินาที
// Crypto fallback → Binance public API (ไม่ต้อง key)

async function fetchRealPrice(symbol, type) {
  try {
    if (type === "crypto") {
      // Binance public REST — ไม่ต้อง API key
      const pair = symbol.replace("/", ""); // BTC/USDT → BTCUSDT
      const res = await fetch(`https://api.binance.com/api/v3/ticker/price?symbol=${pair}`);
      if (!res.ok) throw new Error("binance fail");
      const data = await res.json();
      return parseFloat(data.price);
    } else {
      // หุ้นสหรัฐ → ใช้ Anthropic API + web_search
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-6",
          max_tokens: 100,
          tools: [{ type: "web_search_20250305", name: "web_search" }],
          system: `You are a price data extractor. 
Return ONLY a JSON object like: {"price": 123.45}
No explanation, no markdown, no extra text.`,
          messages: [{
            role: "user",
            content: `Current stock price of ${symbol} in USD. Return JSON only: {"price": <number>}`
          }]
        })
      });
      const data = await res.json();
      // รวม text blocks ทั้งหมด
      const text = (data.content || [])
        .filter(b => b.type === "text")
        .map(b => b.text).join("");
      const clean = text.replace(/```json|```/g, "").trim();
      const parsed = JSON.parse(clean);
      return parseFloat(parsed.price);
    }
  } catch {
    return null; // คืน null ถ้า fetch ไม่ได้ → UI จะแสดง "—"
  }
}

// Hook: ดึงราคาจริง refresh ทุก 30 วินาที
// Crypto เร็วกว่า (15 วินาที) เพราะ Binance public API ไม่มี rate limit
function usePriceFeed(symbol, type, onPrice) {
  const [price, setPrice] = useState(null);
  const [loading, setLoading] = useState(true);
  const interval = type === "crypto" ? 15000 : 30000;

  useEffect(() => {
    let cancelled = false;
    const fetch_ = async () => {
      setLoading(true);
      const p = await fetchRealPrice(symbol, type);
      if (!cancelled && p !== null) {
        setPrice(p);
        onPrice?.(p);
      }
      setLoading(false);
    };
    fetch_();
    const id = setInterval(fetch_, interval);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, type, interval, onPrice]);

  return { price, loading };
}

// ─── INDICATOR ENGINE ────────────────────────────────────────────────────────
function calcEMA(prices, period) {
  if (prices.length < period) return null;
  const k = 2 / (period + 1);
  let ema = prices.slice(0, period).reduce((a, b) => a + b, 0) / period;
  for (let i = period; i < prices.length; i++) ema = prices[i] * k + ema * (1 - k);
  return +ema.toFixed(4);
}

function calcRSI(prices, period = 14) {
  if (prices.length < period + 1) return null;
  let gains = 0, losses = 0;
  for (let i = prices.length - period; i < prices.length; i++) {
    const d = prices[i] - prices[i - 1];
    if (d > 0) gains += d; else losses -= d;
  }
  const rs = gains / (losses || 0.0001);
  return +(100 - 100 / (1 + rs)).toFixed(2);
}

function generateSignal(prices) {
  if (prices.length < 25) return "WAIT";
  const ema9  = calcEMA(prices, 9);
  const ema21 = calcEMA(prices, 21);
  const rsi   = calcRSI(prices, 14);
  if (!ema9 || !ema21 || !rsi) return "WAIT";
  if (ema9 > ema21 && rsi < 65 && rsi > 45) return "BUY";
  if (ema9 < ema21 && rsi > 35 && rsi < 55) return "SELL";
  return "HOLD";
}

// ─── MINI LINE CHART ─────────────────────────────────────────────────────────
function SparkLine({ data, color = "#00e5ff", height = 48 }) {
  if (!data || data.length < 2) return <div style={{ height }} />;
  const w = 200, h = height;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) =>
    `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * (h - 4) - 2}`
  ).join(" ");
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

// ─── ASSET PANEL ─────────────────────────────────────────────────────────────
function AssetPanel({ symbol, type, capital, onTrade }) {
  const [history, setHistory] = useState([]);
  const [position, setPosition] = useState(null); // { side, qty, entry, time }
  const [trades, setTrades] = useState([]);
  const [pnl, setPnl] = useState(0);

  const handlePriceUpdate = useCallback((nextPrice) => {
    setHistory(prev => {
      const nextHistory = [...prev.slice(-59), nextPrice];
      const sig = generateSignal(nextHistory);

      if (sig === "BUY" && !position) {
        const entry = nextPrice;
        const riskAmt = capital * 0.02;
        const stopDist = nextPrice * 0.01;
        const qty = +(riskAmt / stopDist).toFixed(4);
        const trade = { id: Date.now(), side: "BUY", qty, entry, exit: null, pnl: null, time: new Date().toLocaleTimeString() };
        setPosition({ side: "BUY", qty, entry, time: trade.time });
        setTrades(t => [trade, ...t].slice(0, 20));
        onTrade?.({ symbol, ...trade });
      } else if (sig === "SELL" && position?.side === "BUY") {
        const tradePnl = +((nextPrice - position.entry) * position.qty).toFixed(2);
        setPnl(p => +(p + tradePnl).toFixed(2));
        setTrades(t => t.map((tr, i) => i === 0 ? { ...tr, exit: nextPrice, pnl: tradePnl } : tr));
        setPosition(null);
        onTrade?.({ symbol, side: "CLOSE", qty: position.qty, entry: position.entry, exit: nextPrice, pnl: tradePnl });
      }

      return nextHistory;
    });
  }, [capital, onTrade, position, symbol]);

  const { price, loading } = usePriceFeed(symbol, type, handlePriceUpdate);
  const historyForCalc = history.length > 0 ? history : (price !== null ? [price] : []);
  const spark = historyForCalc.slice(-30);
  const signal = generateSignal(historyForCalc);

  const sigColor = { BUY: "#00e676", SELL: "#ff1744", HOLD: "#ffd740", WAIT: "#546e7a" };
  const sigBg    = { BUY: "#00e67615", SELL: "#ff174415", HOLD: "#ffd74015", WAIT: "#546e7a15" };
  const typeTag  = type === "crypto" ? "CRYPTO" : "STOCK";
  const tagColor = type === "crypto" ? "#f7a600" : "#448aff";

  return (
    <div style={{
      background: "#0d1117", border: "1px solid #1e2a35", borderRadius: 12,
      padding: "16px 18px", display: "flex", flexDirection: "column", gap: 10
    }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontFamily: "monospace", fontWeight: 700, fontSize: 16, color: "#e0e6ef", letterSpacing: 1 }}>{symbol}</span>
          <span style={{ background: tagColor + "20", color: tagColor, fontSize: 9, fontWeight: 700, padding: "2px 7px", borderRadius: 4, letterSpacing: 1 }}>{typeTag}</span>
        </div>
        <span style={{
          background: sigBg[signal], color: sigColor[signal],
          fontFamily: "monospace", fontWeight: 800, fontSize: 11,
          padding: "3px 10px", borderRadius: 6, letterSpacing: 2,
          border: `1px solid ${sigColor[signal]}40`
        }}>{signal}</span>
      </div>

      {/* Price */}
      <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
        <span style={{ fontSize: 26, fontWeight: 700, fontFamily: "monospace", color: "#fff" }}>
          {loading && price === null
            ? <span style={{ fontSize: 13, color: "#546e7a" }}>fetching...</span>
            : price !== null
              ? `$${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
              : "—"
          }
        </span>
        {loading && price !== null && (
          <span style={{ fontSize: 9, color: "#546e7a", fontFamily: "monospace" }}>↻</span>
        )}
        <span style={{ fontSize: 11, color: pnl >= 0 ? "#00e676" : "#ff1744", fontFamily: "monospace" }}>
          PnL {pnl >= 0 ? "+" : ""}{pnl}
        </span>
      </div>
      <div style={{ fontSize: 9, color: "#37474f", fontFamily: "monospace" }}>
        {type === "crypto" ? "src: Binance · refresh 15s" : "src: Web Search · refresh 30s"}
      </div>

      {/* Sparkline */}
      <SparkLine data={spark} color={signal === "BUY" ? "#00e676" : signal === "SELL" ? "#ff1744" : "#00e5ff"} />

      {/* Position */}
      {position && (
        <div style={{
          background: "#00e67608", border: "1px solid #00e67630",
          borderRadius: 7, padding: "7px 10px", fontSize: 11, color: "#b0bec5", fontFamily: "monospace"
        }}>
          📌 OPEN {position.side} · {position.qty} @ ${position.entry} · since {position.time}
        </div>
      )}

      {/* Indicators */}
      <div style={{ display: "flex", gap: 8 }}>
        {[
          { label: "EMA9",  val: calcEMA(historyForCalc, 9) },
          { label: "EMA21", val: calcEMA(historyForCalc, 21) },
          { label: "RSI",   val: calcRSI(historyForCalc, 14) },
        ].map(({ label, val }) => (
          <div key={label} style={{
            flex: 1, background: "#131c24", borderRadius: 6, padding: "5px 8px", textAlign: "center"
          }}>
            <div style={{ fontSize: 9, color: "#546e7a", fontFamily: "monospace", marginBottom: 2 }}>{label}</div>
            <div style={{ fontSize: 12, color: "#90a4ae", fontFamily: "monospace" }}>{val ?? "—"}</div>
          </div>
        ))}
      </div>

      {/* Recent Trades */}
      {trades.length > 0 && (
        <div style={{ marginTop: 2 }}>
          <div style={{ fontSize: 9, color: "#546e7a", fontFamily: "monospace", marginBottom: 5, letterSpacing: 1 }}>TRADE LOG</div>
          <div style={{ maxHeight: 90, overflowY: "auto", display: "flex", flexDirection: "column", gap: 3 }}>
            {trades.slice(0, 5).map(tr => (
              <div key={tr.id} style={{
                display: "flex", justifyContent: "space-between",
                fontSize: 10, fontFamily: "monospace", color: "#607d8b",
                background: "#0a1520", borderRadius: 5, padding: "3px 8px"
              }}>
                <span style={{ color: tr.side === "BUY" ? "#00e676" : "#ff1744" }}>{tr.side}</span>
                <span>{tr.qty} @ ${tr.entry}</span>
                <span style={{ color: tr.pnl == null ? "#546e7a" : tr.pnl >= 0 ? "#00e676" : "#ff1744" }}>
                  {tr.pnl == null ? "open" : `${tr.pnl >= 0 ? "+" : ""}$${tr.pnl}`}
                </span>
                <span style={{ color: "#37474f" }}>{tr.time}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── GLOBAL TRADE FEED ───────────────────────────────────────────────────────
function TradeFeed({ events }) {
  return (
    <div style={{
      background: "#0d1117", border: "1px solid #1e2a35", borderRadius: 12,
      padding: "14px 16px", height: "100%", display: "flex", flexDirection: "column"
    }}>
      <div style={{ fontSize: 10, color: "#546e7a", fontFamily: "monospace", letterSpacing: 2, marginBottom: 10 }}>
        ⚡ LIVE ORDER FEED
      </div>
      <div style={{ flex: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
        {events.length === 0 && (
          <div style={{ color: "#37474f", fontFamily: "monospace", fontSize: 11, marginTop: 8 }}>
            Waiting for signals...
          </div>
        )}
        {events.map((e, i) => (
          <div key={i} style={{
            background: e.side === "BUY" ? "#00e67608" : e.side === "CLOSE" ? "#ffd74008" : "#ff174408",
            border: `1px solid ${e.side === "BUY" ? "#00e67625" : e.side === "CLOSE" ? "#ffd74025" : "#ff174425"}`,
            borderRadius: 7, padding: "7px 10px", fontFamily: "monospace", fontSize: 10
          }}>
            <div style={{ display: "flex", justifyContent: "space-between" }}>
              <span style={{ color: "#90a4ae", fontWeight: 700 }}>{e.symbol}</span>
              <span style={{ color: e.side === "BUY" ? "#00e676" : e.side === "CLOSE" ? "#ffd740" : "#ff1744", fontWeight: 800 }}>
                {e.side === "CLOSE" ? "✓ CLOSED" : e.side}
              </span>
            </div>
            <div style={{ color: "#546e7a", marginTop: 2 }}>
              {e.qty} @ ${e.entry}
              {e.pnl != null && (
                <span style={{ color: e.pnl >= 0 ? "#00e676" : "#ff1744", marginLeft: 8 }}>
                  {e.pnl >= 0 ? "▲" : "▼"} ${Math.abs(e.pnl)}
                </span>
              )}
            </div>
            <div style={{ color: "#263238", marginTop: 2 }}>{e.time}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── SETUP GUIDE ─────────────────────────────────────────────────────────────
function SetupGuide({ onClose }) {
  const steps = [
    {
      label: "Alpaca Paper Trade (หุ้นสหรัฐ)",
      color: "#448aff",
      steps: [
        "สมัครฟรีที่ alpaca.markets",
        "เลือก Paper Trading → Get API Keys",
        "ใส่ ALPACA_API_KEY และ ALPACA_SECRET ใน .env",
        "ใช้ endpoint: https://paper-api.alpaca.markets/v2"
      ]
    },
    {
      label: "Binance Testnet (Crypto)",
      color: "#f7a600",
      steps: [
        "ไปที่ testnet.binance.vision",
        "Login ด้วย GitHub → Generate HMAC Keys",
        "ใส่ BINANCE_API_KEY และ BINANCE_SECRET ใน .env",
        "ใช้ endpoint: https://testnet.binance.vision/api/v3"
      ]
    }
  ];

  return (
    <div style={{
      position: "fixed", inset: 0, background: "#000a",
      display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100
    }}>
      <div style={{
        background: "#0d1117", border: "1px solid #1e2a35", borderRadius: 16,
        padding: 28, maxWidth: 480, width: "90%"
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <span style={{ color: "#e0e6ef", fontWeight: 700, fontSize: 15, fontFamily: "monospace" }}>
            🔧 API Setup Guide
          </span>
          <button onClick={onClose} style={{
            background: "none", border: "1px solid #263238", color: "#546e7a",
            borderRadius: 6, padding: "4px 12px", cursor: "pointer", fontFamily: "monospace"
          }}>✕ Close</button>
        </div>
        {steps.map(section => (
          <div key={section.label} style={{ marginBottom: 18 }}>
            <div style={{
              color: section.color, fontFamily: "monospace", fontWeight: 700,
              fontSize: 11, letterSpacing: 1, marginBottom: 8
            }}>{section.label}</div>
            {section.steps.map((s, i) => (
              <div key={i} style={{
                display: "flex", gap: 10, marginBottom: 5,
                fontSize: 12, color: "#90a4ae", fontFamily: "monospace"
              }}>
                <span style={{ color: "#37474f", minWidth: 16 }}>{i + 1}.</span>
                <span>{s}</span>
              </div>
            ))}
          </div>
        ))}
        <div style={{
          background: "#131c24", borderRadius: 8, padding: "10px 14px",
          fontFamily: "monospace", fontSize: 11, color: "#546e7a", marginTop: 8
        }}>
          📌 Dashboard นี้จำลองการทำงาน — ผูก API จริงในโค้ด Python ของคุณ
        </div>
      </div>
    </div>
  );
}

// ─── APP ─────────────────────────────────────────────────────────────────────
const ASSETS = [
  { symbol: "MSFT",     type: "stock"  },
  { symbol: "AAPL",     type: "stock"  },
  { symbol: "BTC/USDT", type: "crypto" },
  { symbol: "ETH/USDT", type: "crypto" },
];

export default function App() {
  const [capital]     = useState(100000);
  const [events, setEvents]     = useState([]);
  const [showGuide, setShowGuide] = useState(false);
  const [botRunning, setBotRunning] = useState(true);
  const [elapsed, setElapsed]     = useState(0);
  const [snapshot, setSnapshot] = useState(null);

  useEffect(() => {
    if (!botRunning) return;
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, [botRunning]);

  useEffect(() => {
    let cancelled = false;

    const loadSnapshot = () => {
      fetch("/scalping_snapshot.json")
        .then(res => (res.ok ? res.json() : null))
        .then(data => {
          if (!cancelled) setSnapshot(data);
        })
        .catch(() => {
          if (!cancelled) setSnapshot(null);
        });
    };

    loadSnapshot();
    const id = setInterval(loadSnapshot, 10000);

    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const handleTrade = useCallback((event) => {
    setEvents(e => [{
      ...event,
      time: new Date().toLocaleTimeString()
    }, ...e].slice(0, 50));
  }, []);

  const fmt = s => `${String(Math.floor(s/3600)).padStart(2,"0")}:${String(Math.floor(s/60)%60).padStart(2,"0")}:${String(s%60).padStart(2,"0")}`;
  const totalPnl = events.filter(e => e.pnl != null).reduce((a, e) => a + e.pnl, 0);
  const snapshotLabel = snapshot?.signal_label || "WAIT";
  const snapshotColor = snapshot?.latest_signal === 1 ? "#00e676" : snapshot?.latest_signal === -1 ? "#ff1744" : "#ffd740";

  return (
    <div style={{
      background: "#060d14", minHeight: "100vh", padding: "20px 20px",
      fontFamily: "'JetBrains Mono', 'Fira Code', monospace",
      color: "#e0e6ef"
    }}>
      {showGuide && <SetupGuide onClose={() => setShowGuide(false)} />}

      {/* Header */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "center",
        marginBottom: 20, flexWrap: "wrap", gap: 10
      }}>
        <div>
          <div style={{
            fontSize: 11, color: "#546e7a", letterSpacing: 3, marginBottom: 4
          }}>PAPER TRADE · WYCKOFF + EMA + RSI</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: "#00e5ff", letterSpacing: 1 }}>
            ⚡ AUTO TRADING BOT
          </div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {/* Stats */}
          {[
            { label: "CAPITAL", val: `$${capital.toLocaleString()}`, color: "#e0e6ef" },
            { label: "SESSION PnL", val: `${totalPnl >= 0 ? "+" : ""}$${totalPnl.toFixed(2)}`, color: totalPnl >= 0 ? "#00e676" : "#ff1744" },
            { label: "UPTIME", val: fmt(elapsed), color: "#ffd740" },
          ].map(s => (
            <div key={s.label} style={{
              background: "#0d1117", border: "1px solid #1e2a35",
              borderRadius: 8, padding: "7px 14px", textAlign: "center", minWidth: 90
            }}>
              <div style={{ fontSize: 8, color: "#546e7a", letterSpacing: 2 }}>{s.label}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: s.color, marginTop: 2 }}>{s.val}</div>
            </div>
          ))}
          {/* Controls */}
          <button onClick={() => setBotRunning(r => !r)} style={{
            background: botRunning ? "#ff174415" : "#00e67615",
            border: `1px solid ${botRunning ? "#ff174440" : "#00e67640"}`,
            color: botRunning ? "#ff1744" : "#00e676",
            borderRadius: 8, padding: "8px 16px", cursor: "pointer",
            fontFamily: "monospace", fontWeight: 700, fontSize: 11, letterSpacing: 1
          }}>
            {botRunning ? "⏸ PAUSE" : "▶ START"}
          </button>
          <button onClick={() => setShowGuide(true)} style={{
            background: "#131c24", border: "1px solid #1e2a35",
            color: "#546e7a", borderRadius: 8, padding: "8px 14px",
            cursor: "pointer", fontFamily: "monospace", fontSize: 11
          }}>🔧 API Setup</button>
        </div>
      </div>

      {/* Status bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 8, marginBottom: 18,
        padding: "8px 14px", background: "#0d1117", borderRadius: 8,
        border: "1px solid #1e2a35", fontSize: 10, color: "#546e7a"
      }}>
        <span style={{
          width: 7, height: 7, borderRadius: "50%",
          background: botRunning ? "#00e676" : "#ff1744",
          display: "inline-block",
          boxShadow: botRunning ? "0 0 6px #00e676" : "none"
        }} />
        <span style={{ color: botRunning ? "#00e676" : "#ff1744", fontWeight: 700 }}>
          {botRunning ? "BOT RUNNING" : "BOT PAUSED"}
        </span>
        <span>·</span>
        <span>MODE: PAPER TRADE (จำลอง — ไม่ใช้เงินจริง)</span>
        <span>·</span>
        <span>RISK/TRADE: 2%</span>
        <span>·</span>
        <span>SIGNALS: EMA9/21 + RSI 14</span>
        <span>·</span>
        <span>ASSETS: {ASSETS.length} active</span>
      </div>

      {/* Automation snapshot summary */}
      {snapshot && (
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: 10,
          marginBottom: 14
        }}>
          <div style={{
            background: "#0d1117", border: "1px solid #1e2a35", borderRadius: 10,
            padding: "10px 12px"
          }}>
            <div style={{ fontSize: 9, color: "#546e7a", letterSpacing: 2 }}>AUTO SIGNAL</div>
            <div style={{ color: snapshotColor, fontSize: 16, fontWeight: 800, marginTop: 4 }}>{snapshotLabel}</div>
          </div>
          <div style={{
            background: "#0d1117", border: "1px solid #1e2a35", borderRadius: 10,
            padding: "10px 12px"
          }}>
            <div style={{ fontSize: 9, color: "#546e7a", letterSpacing: 2 }}>LAST PRICE</div>
            <div style={{ color: "#e0e6ef", fontSize: 16, fontWeight: 800, marginTop: 4 }}>
              {snapshot.latest_close != null ? `$${snapshot.latest_close}` : "—"}
            </div>
          </div>
          <div style={{
            background: "#0d1117", border: "1px solid #1e2a35", borderRadius: 10,
            padding: "10px 12px"
          }}>
            <div style={{ fontSize: 9, color: "#546e7a", letterSpacing: 2 }}>NET PROFIT</div>
            <div style={{ color: snapshot.net_profit >= 0 ? "#00e676" : "#ff1744", fontSize: 16, fontWeight: 800, marginTop: 4 }}>
              {snapshot.net_profit >= 0 ? "+" : ""}${snapshot.net_profit?.toFixed?.(2) || snapshot.net_profit}
            </div>
          </div>
        </div>
      )}

      {/* Main Grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
        gap: 14,
      }}>
        {ASSETS.map(a => (
          <AssetPanel
            key={a.symbol}
            symbol={a.symbol}
            type={a.type}
            capital={capital}
            onTrade={handleTrade}
          />
        ))}
      </div>

      {/* Trade Feed */}
      <div style={{ marginTop: 14, height: 220 }}>
        <TradeFeed events={events} />
      </div>

      {/* Footer note */}
      <div style={{
        marginTop: 14, textAlign: "center",
        fontSize: 9, color: "#263238", letterSpacing: 1
      }}>
        PAPER TRADE SIMULATION · สำหรับทดสอบระบบเท่านั้น ไม่ใช่คำแนะนำการลงทุน
      </div>
    </div>
  );
}
