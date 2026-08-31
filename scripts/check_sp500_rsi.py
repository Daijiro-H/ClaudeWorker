#!/usr/bin/env python3
"""Check the S&P 500 RSI(14) and notify.

Reports the current RSI every run, and flags an actionable signal when RSI
reaches the overbought (>=70) or oversold (<=30) threshold. See notify.py for
how the result is delivered.
"""

from __future__ import annotations

import sys

import pandas as pd
import yfinance as yf

import notify

TICKER = "^GSPC"
RSI_PERIOD = 14
OVERBOUGHT = 70
OVERSOLD = 30
TRACKING_MARKER = "<!-- sp500-rsi-monitor -->"
DESCRIPTION = "S&P500のRSI(14)を毎営業日チェックし、結果をこのIssueにコメントします。"


def fetch_close_prices(ticker: str, period: str = "6mo") -> pd.Series:
    data = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False)
    if data.empty:
        raise RuntimeError(f"No price data returned for {ticker}")
    close = data["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def calculate_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    # Wilder's smoothing (equivalent to an EMA with alpha = 1/period).
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.where(avg_loss != 0, 100)  # no losses at all -> RSI 100
    return rsi


def build_title(price: float, rsi: float) -> str:
    """A self-contained one-liner; it becomes the notification subject."""
    if rsi >= OVERBOUGHT:
        verdict = "買われすぎ -> 売り検討"
    elif rsi <= OVERSOLD:
        verdict = "売られすぎ -> 買い検討"
    else:
        verdict = "中立"
    return f"[S&P500] {price:,.2f} / RSI {rsi:.1f} — {verdict}"


def build_message(date: pd.Timestamp, price: float, rsi: float) -> str:
    date_str = date.strftime("%Y-%m-%d")
    lines = [
        "S&P500 RSIチェック",
        f"日付: {date_str}",
        f"終値: {price:,.2f}",
        f"RSI(14): {rsi:.1f}",
    ]

    if rsi >= OVERBOUGHT:
        lines.append(f"シグナル: 買われすぎ(RSI >= {OVERBOUGHT}) -> 売りアクション検討")
    elif rsi <= OVERSOLD:
        lines.append(f"シグナル: 売られすぎ(RSI <= {OVERSOLD}) -> 買いアクション検討")
    else:
        lines.append("シグナル: 中立(70/30到達なし)")

    return "\n".join(lines)


def main() -> int:
    close = fetch_close_prices(TICKER)
    rsi = calculate_rsi(close)

    latest_date = close.index[-1]
    latest_price = float(close.iloc[-1])
    latest_rsi = float(rsi.iloc[-1])

    if pd.isna(latest_rsi):
        print("Error: not enough data to calculate RSI yet.", file=sys.stderr)
        return 1

    notify.notify(
        marker=TRACKING_MARKER,
        heading="S&P500 RSIチェック",
        title=build_title(latest_price, latest_rsi),
        message=build_message(latest_date, latest_price, latest_rsi),
        description=DESCRIPTION,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
