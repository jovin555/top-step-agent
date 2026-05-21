import yfinance as yf
import pandas as pd
import numpy as np

SYMBOL_MAP = {
    "ES": "ES=F",
    "NQ": "NQ=F",
    "CL": "CL=F",
    "GC": "GC=F",
    "SI": "SI=F",
    "NG": "NG=F",
    "YM": "YM=F",
    "HG": "HG=F",
    "ZN": "ZN=F",
    "6E": "6E=F",
    "6J": "6J=F",
    "6B": "6B=F",
}

INTERVAL_PERIOD_MAP = {
    "1m":  ("1m",  "1d"),
    "5m":  ("5m",  "2d"),
    "15m": ("15m", "5d"),
    "1h":  ("60m", "30d"),
    "4h":  ("1h",  "60d"),
}


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=True).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=True).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))


def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(series, fast)
    ema_slow = _ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=True).mean()


def get_htf_ema200(symbol: str) -> tuple[float, float]:
    """Fetch 1H chart and return (current_price, ema200) for higher-timeframe trend filtering."""
    ticker = SYMBOL_MAP.get(symbol.upper(), symbol)
    df = yf.download(ticker, interval="60m", period="60d", progress=False, auto_adjust=True)
    if df.empty or len(df) < 50:
        raise ValueError(f"Not enough 1H data for {symbol}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close = df["Close"].squeeze().dropna()
    ema200 = _ema(close, 200)
    return float(close.iloc[-1]), float(ema200.iloc[-1])


def get_market_snapshot(symbol: str, timeframe: str = "15m") -> dict:
    ticker = SYMBOL_MAP.get(symbol.upper(), symbol)
    interval, period = INTERVAL_PERIOD_MAP.get(timeframe, ("15m", "5d"))

    df = yf.download(ticker, interval=interval, period=period, progress=False, auto_adjust=True)
    if df.empty or len(df) < 30:
        raise ValueError(f"Not enough data for {symbol} ({ticker})")

    # Flatten MultiIndex columns if present
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    close = df["Close"].squeeze().dropna()
    high  = df["High"].squeeze().dropna()
    low   = df["Low"].squeeze().dropna()
    open_ = df["Open"].squeeze().dropna()
    volume = df["Volume"].squeeze().dropna()

    rsi = _rsi(close)
    ema20  = _ema(close, 20)
    ema50  = _ema(close, 50)
    ema200 = _ema(close, 200)
    macd_line, signal_line, histogram = _macd(close)
    atr = _atr(high, low, close)

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    bb_upper = sma20 + 2 * std20
    bb_lower = sma20 - 2 * std20

    last_close  = float(close.iloc[-1])
    last_high   = float(high.iloc[-1])
    last_low    = float(low.iloc[-1])
    last_volume = int(volume.iloc[-1])
    avg_volume  = int(volume.tail(20).mean())

    # Recent swing highs/lows over last 50 bars for S/R
    resistance = round(float(high.tail(50).max()), 2)
    support    = round(float(low.tail(50).min()), 2)

    candles = []
    for i in range(5, 0, -1):
        idx = -i
        candles.append({
            "open":  round(float(open_.iloc[idx]), 2),
            "high":  round(float(high.iloc[idx]), 2),
            "low":   round(float(low.iloc[idx]), 2),
            "close": round(float(close.iloc[idx]), 2),
        })

    return {
        "symbol":        symbol,
        "ticker":        ticker,
        "timeframe":     timeframe,
        "current_price": round(last_close, 2),
        "current_high":  round(last_high, 2),
        "current_low":   round(last_low, 2),
        "rsi_14":        round(float(rsi.iloc[-1]), 2),
        "ema_20":        round(float(ema20.iloc[-1]), 2),
        "ema_50":        round(float(ema50.iloc[-1]), 2),
        "ema_200":       round(float(ema200.iloc[-1]), 2),
        "macd_line":     round(float(macd_line.iloc[-1]), 4),
        "macd_signal":   round(float(signal_line.iloc[-1]), 4),
        "macd_histogram":round(float(histogram.iloc[-1]), 4),
        "atr_14":        round(float(atr.iloc[-1]), 4),
        "bb_upper":      round(float(bb_upper.iloc[-1]), 2),
        "bb_lower":      round(float(bb_lower.iloc[-1]), 2),
        "volume_last":   last_volume,
        "volume_avg_20": avg_volume,
        "resistance":    resistance,
        "support":       support,
        "candles_last_5": candles,
    }
