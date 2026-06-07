import pandas as pd
import yfinance as yf
import mplfinance as mpf
# yfinnance เป็นไลบรารีที่ใช้สำหรับดึงข้อมูลหุ้นจาก Yahoo Finance 
# mplfinance เป็นไลบรารีที่ใช้สำหรับสร้างกราฟแท่งเทียน (candlestick chart) ของหุ้น

# ดึงข้อมูลหุ้น Apple (AAPL) ในช่วง 6 เดือนที่ผ่านมา
df = yf.download('AAPL', period="6mo")

if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

# ดูข้อมูลที่ดึงมา
print(df.head()) # แสดงข้อมูล 5 แถวแรกของ DataFrame
print(df.shape) # แสดงจำนวนแถวและคอลัมน์ของ DataFrame
# df เป็น DataFrame ที่เก็บข้อมูลหุ้น Apple ซึ่งมีคอลัมน์ต่าง ๆ เช่น Open, High, Low, Close, Volume และ Adj Close
