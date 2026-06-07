"""
ml_predict.py
AI/ML พื้นฐานสำหรับการพยากรณ์ทิศทางราคาหุ้น

เป้าหมาย:
- ทำนายว่าราคาปิดของวันถัดไปจะสูงกว่าราคาปิดวันนี้หรือไม่
- ใช้คุณลักษณะทางเทคนิคง่าย ๆ จากราคา ปริมาณการซื้อขาย MA และ RSI
- รักษาการพึ่งพาให้น้อยที่สุด: pandas, numpy, yfinance เท่านั้น
"""

import numpy as np
import pandas as pd
import yfinance as yf

from indicators import compute_ma, compute_rsi, normalize_yfinance_columns


FEATURE_COLUMNS = [
    "Return_1D",
    "Return_5D",
    "Volume_Change",
    "MA20_Distance",
    "MA50_Distance",
    "RSI",
]


def sigmoid(values: np.ndarray) -> np.ndarray:
    """ฟังก์ชันซิกมอยด์ที่มีความเสถียรทางตัวเลข."""
    values = np.clip(values, -500, 500)
    return 1 / (1 + np.exp(-values))


def prepare_dataset(ticker: str = "AAPL", period: str = "5y") -> pd.DataFrame:
    """ดาวน์โหลดข้อมูลราคาและสร้างคุณลักษณะสำหรับ ML."""
    df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
    if df.empty:
        raise ValueError(f"Cannot download data for {ticker}")

    df = normalize_yfinance_columns(df)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()

    df["MA20"] = compute_ma(df["Close"], 20)
    df["MA50"] = compute_ma(df["Close"], 50)
    df["RSI"] = compute_rsi(df["Close"], 14)
    df["Return_1D"] = df["Close"].pct_change()
    df["Return_5D"] = df["Close"].pct_change(5)
    df["Volume_Change"] = df["Volume"].pct_change()
    df["MA20_Distance"] = (df["Close"] - df["MA20"]) / df["MA20"]
    df["MA50_Distance"] = (df["Close"] - df["MA50"]) / df["MA50"]

    df["Next_Close"] = df["Close"].shift(-1)
    df["Target"] = (df["Next_Close"] > df["Close"]).astype(int)
    df = df.replace([np.inf, -np.inf], np.nan)
    return df.dropna()


def standardize_train_test(
    x_train: np.ndarray,
    x_test: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """ปรับสเกลคุณลักษณะโดยใช้สถิติจากชุดเทรนเท่านั้น."""
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std == 0] = 1
    return (x_train - mean) / std, (x_test - mean) / std


def train_logistic_regression(
    x_train: np.ndarray,
    y_train: np.ndarray,
    learning_rate: float = 0.05,
    epochs: int = 2_000,
) -> tuple[np.ndarray, float]:
    """ฝึกโมเดลโลจิสติกรีเกรสชันขนาดเล็กด้วย gradient descent."""
    weights = np.zeros(x_train.shape[1])
    bias = 0.0

    for _ in range(epochs):
        probabilities = sigmoid(x_train @ weights + bias)
        error = probabilities - y_train
        weights -= learning_rate * (x_train.T @ error) / len(x_train)
        bias -= learning_rate * error.mean()

    return weights, bias


def evaluate_predictions(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """คืนค่าตัวชี้วัดการจำแนกสำหรับการพยากรณ์ขึ้น/ลง."""
    accuracy = (y_true == y_pred).mean()
    true_positive = ((y_true == 1) & (y_pred == 1)).sum()
    false_positive = ((y_true == 0) & (y_pred == 1)).sum()
    false_negative = ((y_true == 1) & (y_pred == 0)).sum()

    precision = true_positive / max(true_positive + false_positive, 1)
    recall = true_positive / max(true_positive + false_negative, 1)
    return {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
    }


def run_ml_prediction(ticker: str = "AAPL", period: str = "5y") -> dict[str, object]:
    """เทรน/ทดสอบโมเดล ML และคืนค่าผลสรุป."""
    df = prepare_dataset(ticker=ticker, period=period)
    split_index = int(len(df) * 0.7)

    train = df.iloc[:split_index]
    test = df.iloc[split_index:]

    x_train = train[FEATURE_COLUMNS].to_numpy(dtype=float)
    y_train = train["Target"].to_numpy(dtype=float)
    x_test = test[FEATURE_COLUMNS].to_numpy(dtype=float)
    y_test = test["Target"].to_numpy(dtype=int)

    x_train, x_test = standardize_train_test(x_train, x_test)
    weights, bias = train_logistic_regression(x_train, y_train)

    probabilities = sigmoid(x_test @ weights + bias)
    predictions = (probabilities >= 0.5).astype(int)
    metrics = evaluate_predictions(y_test, predictions)

    baseline = max(y_test.mean(), 1 - y_test.mean())
    latest_probability = float(probabilities[-1])

    return {
        "ticker": ticker,
        "rows": len(df),
        "train_rows": len(train),
        "test_rows": len(test),
        "metrics": metrics,
        "baseline_accuracy": float(baseline),
        "latest_probability_up": latest_probability,
        "latest_signal": "UP" if latest_probability >= 0.5 else "DOWN",
    }


if __name__ == "__main__":
    tickers = ["AAPL", "MSFT", "PTT.BK"]

    print("\n" + "=" * 72)
    print("AI/ML Baseline: Next-Day Direction Prediction")
    print("=" * 72)

    for ticker in tickers:
        try:
            result = run_ml_prediction(ticker)
        except ValueError as error:
            print(f"{ticker}: {error}")
            continue

        metrics = result["metrics"]
        print(
            f"{ticker:6} | "
            f"Rows: {result['rows']:4} | "
            f"Accuracy: {metrics['accuracy'] * 100:6.2f}% | "
            f"Baseline: {result['baseline_accuracy'] * 100:6.2f}% | "
            f"Precision: {metrics['precision'] * 100:6.2f}% | "
            f"Recall: {metrics['recall'] * 100:6.2f}% | "
            f"Latest: {result['latest_signal']} "
            f"({result['latest_probability_up'] * 100:5.2f}% up)"
        )

    print("\nNote: This is an educational ML baseline, not financial advice.")
