---
name: Trade_Booking
description: ใช้สำหรับโปรเจค Python สำหรับวิเคราะห์และ backtest หุ้น ใช้เมื่อต้องการแก้ไขหรือเพิ่มเติม RSI/MA strategy, การดึงข้อมูลด้วย yfinance, การคำนวณ indicator, กราฟ mplfinance, รายงาน Backtesting.py หรือระบบแจ้งเตือนหุ้นผ่าน Telegram ใน workspace Trade_Booking
---

# Trade Booking

ใช้ skill นี้สำหรับโปรเจค `Trade_Booking` ในเครื่อง โปรเจคนี้เป็น Python trading lab ขนาดเล็ก สำหรับดึงข้อมูลจาก Yahoo Finance, คำนวณ indicator, รัน backtest ด้วย RSI/MA, วาดกราฟ และส่งแจ้งเตือนผ่าน Telegram

## แผนผังโปรเจค

- `fetch_data.py`: ตัวอย่างการดึงข้อมูลหุ้นจาก Yahoo Finance
- `indicators.py`: ฟังก์ชัน indicator ที่ใช้ร่วมกัน ควรนำ `compute_ma`, `compute_rsi`, `calculate_indicators` และ `normalize_yfinance_columns` กลับมาใช้ซ้ำ
- `backtest_rsi.py`: backtest RSI strategy ด้วย Backtesting.py
- `backtest_ma.py`: backtest MA crossover strategy ด้วย Backtesting.py
- `backtest_combined.py`: backtest Combined Strategy (RSI + MA) ด้วย Backtesting.py
- `ml_predict.py`: โมเดล AI/ML เบื้องต้นสำหรับทำนายทิศทางราคาวันถัดไป
- `automation.py`: ระบบ automation ครบวงจร รวม indicator, ML summary, รายงาน และส่ง Telegram
- `chart.py`: กราฟ candlestick พร้อม volume และเส้น MA ด้วย mplfinance
- `alert.py`: ระบบแจ้งเตือนผ่าน Telegram สำหรับสัญญาณ RSI และ MA
- `RsiStrategy.html`: รายงาน Backtesting.py แบบ interactive
- `.env`: ค่า secret สำหรับ Telegram ในเครื่อง ห้ามแสดงหรือ commit ค่าจริงเด็ดขาด
- `.env.example`: template ที่ปลอดภัยสำหรับการตั้งค่า Telegram

## สภาพแวดล้อม

ใช้ virtual environment ของโปรเจคเสมอ:

```bash
.venv/bin/python <script.py>
```

หลีกเลี่ยงการใช้ `python3` ตรงๆ เพราะ Python ของระบบอาจไม่มี dependency ที่โปรเจคต้องการ เช่น `pandas`, `yfinance`, `backtesting`, `mplfinance`, `requests` หรือ `schedule`

ต้องการเครือข่ายสำหรับ:
- ดาวน์โหลดข้อมูลด้วย `yfinance`
- ส่งข้อความผ่าน Telegram API

ถ้ารันแล้วเกิด error เรื่อง DNS, host resolution หรือดาวน์โหลดไม่ได้ ให้ลองรันใหม่โดยอนุญาต network ก่อน ไม่ต้องแก้โค้ด

## กฎการแก้ไขโค้ด

- นำ `indicators.py` กลับมาใช้ซ้ำสำหรับ logic MA/RSI แทนการเขียนสูตรซ้ำในไฟล์ strategy หรือ alert
- ใช้ `normalize_yfinance_columns(df)` เพื่อจัดการ column ของ yfinance ก่อนเลือกคอลัมน์ OHLCV เสมอ
- เก็บรายชื่อหุ้นและ parameter ของ strategy ไว้ใกล้ส่วนเริ่มต้นของ script ให้มองเห็นชัดเจน
- ถือว่าผล backtest เป็นสัญญาณเพื่อการศึกษาเท่านั้น ห้ามนำเสนอเป็นคำแนะนำทางการเงิน
- ห้าม hardcode Telegram token หรือ chat id ให้อ่านจาก `.env` หรือ environment variable เท่านั้น

## คำสั่งที่ใช้บ่อย

ตรวจสอบ syntax:

```bash
.venv/bin/python -m py_compile backtest_rsi.py backtest_ma.py ml_predict.py automation.py indicators.py alert.py chart.py fetch_data.py
```

รัน RSI backtest:

```bash
.venv/bin/python backtest_rsi.py
```

รัน MA crossover backtest:

```bash
.venv/bin/python backtest_ma.py
```

รัน Combined Strategy backtest:

```bash
.venv/bin/python backtest_combined.py
```

รัน AI/ML prediction:

```bash
.venv/bin/python ml_predict.py
```

รัน automation ครั้งเดียว:

```bash
.venv/bin/python automation.py --once
```

รัน automation ครั้งเดียวพร้อมเลือกหุ้น:

```bash
.venv/bin/python automation.py --once --tickers AAPL,MSFT --ml-period 1y
```

รัน automation พร้อมกรองสัญญาณ Telegram:

```bash
.venv/bin/python automation.py --once --send-telegram --min-ml-probability 0.55 --min-ml-edge 0.00
```

รัน automation แบบต่อเนื่อง:

```bash
.venv/bin/python automation.py
```

รันกราฟ:

```bash
.venv/bin/python chart.py
```

รันระบบแจ้งเตือน Telegram:

```bash
.venv/bin/python alert.py
```

## การตั้งค่า Telegram

script แจ้งเตือนต้องการค่าเหล่านี้ใน `.env`:

```env
TELEGRAM_TOKEN=token_ใหม่ของคุณ
TELEGRAM_CHAT_ID=chat_id_ของคุณ
AUTOMATION_WATCHLIST=AAPL,MSFT,TSLA,NVDA,AMD,INTC
AUTOMATION_INTERVAL_MINUTES=30
AUTOMATION_ML_PERIOD=5y
AUTOMATION_SEND_TELEGRAM=false
AUTOMATION_MIN_ML_PROBABILITY=0.55
AUTOMATION_MIN_ML_EDGE=0.00
```

ให้ตั้ง `AUTOMATION_SEND_TELEGRAM=false` ไว้ก่อนระหว่างทดสอบ ใช้ `--send-telegram` หรือตั้งเป็น `true` เฉพาะเมื่อต้องการส่งจริงเท่านั้น การส่ง Telegram จะกรองเฉพาะสัญญาณ RSI extreme หรือ ML ที่ผ่านเกณฑ์ probability และ baseline-edge ที่กำหนด รายงานเต็มจะบันทึกไว้ที่ `reports/` เสมอ

ถ้า token เคยถูก commit, วางในแชท หรือเปิดเผยออกไป ให้บอกผู้ใช้ให้ revoke และสร้าง token ใหม่ผ่าน Telegram BotFather ก่อนรัน alert ใหม่

## Checklist หลังแก้โค้ด

1. รัน `py_compile` ด้วย `.venv/bin/python` เสมอ
2. import module ที่แก้ไขด้วย `.venv/bin/python -c "import ..."` เพื่อตรวจสอบเพิ่มเติมเมื่อจำเป็น
3. สำหรับการเปลี่ยน strategy ให้รัน backtest ที่เกี่ยวข้องถ้ามี network
4. สำหรับการเปลี่ยน alert ห้ามส่ง Telegram จริงนอกจากผู้ใช้จะขอทดสอบการส่งโดยตรง
5. สรุปว่า script ไหนที่ตรวจสอบแล้ว และมีการข้ามการตรวจสอบที่ต้องใช้ network หรือไม่
