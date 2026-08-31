#!/usr/bin/env python3
"""Check whether Palantir (PLTR) has reached the $160 threshold and notify.

Reports the day's close either way, and flags an actionable signal when the
price reaches the threshold from above (close <= 160, or the session low
touching 160). See notify.py for how the result is delivered.
"""

from __future__ import annotations

import os

import pandas as pd
import yfinance as yf

import notify

TICKER = "PLTR"
DEFAULT_THRESHOLD = 160.0
TRACKING_MARKER = "<!-- pltr-threshold-monitor -->"
DESCRIPTION = "PLTRの株価を毎日チェックし、結果をこのIssueにコメントします。"


def resolve_threshold() -> float:
    """The $160 target, overridable via PLTR_THRESHOLD.

    The workflow exposes this as a dispatch input so a manual run can force
    the reached branch and verify that the alert actually gets delivered.
    """
    raw = os.environ.get("PLTR_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_THRESHOLD
    return float(raw)


def fetch_recent_prices(ticker: str, period: str = "1mo") -> pd.DataFrame:
    data = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False)
    if data.empty:
        raise RuntimeError(f"No price data returned for {ticker}")
    # yfinance returns column MultiIndex when several tickers are requested;
    # flatten to the single-ticker case.
    if isinstance(data.columns, pd.MultiIndex):
        data = data.xs(ticker, axis=1, level=1)
    return data.dropna(subset=["Close"])


def evaluate(close: float, low: float, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """Return True when the price has come down to the threshold.

    PLTR trades above $160, so the meaningful event is the price falling to
    it: either the close lands at or below the threshold, or the session dips
    through it intraday.
    """
    return close <= threshold or low <= threshold


def build_title(close: float, reached: bool, threshold: float) -> str:
    """A self-contained one-liner; it becomes the notification subject."""
    if reached:
        return f"[PLTR] ${close:,.2f} — ${threshold:,.0f} 到達"
    diff = close - threshold
    pct = diff / threshold * 100
    return f"[PLTR] ${close:,.2f} — ${threshold:,.0f} 未到達 (あと ${diff:,.2f} / {pct:.1f}%)"


def build_message(
    date: pd.Timestamp,
    close: float,
    low: float,
    high: float,
    reached: bool,
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    date_str = date.strftime("%Y-%m-%d")
    lines = [
        f"PLTR ${threshold:,.0f} チェック",
        f"日付: {date_str}",
        f"終値: {close:,.2f}",
        f"高値: {high:,.2f} / 安値: {low:,.2f}",
    ]

    if reached:
        lines.append(f"判定: 到達(${threshold:,.0f}以下) -> アクション検討")
    else:
        diff = close - threshold
        pct = diff / threshold * 100
        lines.append(f"判定: 未到達 (あと ${diff:,.2f} / {pct:.1f}%)")

    return "\n".join(lines)


def main() -> int:
    threshold = resolve_threshold()
    data = fetch_recent_prices(TICKER)

    latest = data.iloc[-1]
    latest_date = data.index[-1]
    close = float(latest["Close"])
    low = float(latest["Low"])
    high = float(latest["High"])

    reached = evaluate(close, low, threshold)
    notify.notify(
        marker=TRACKING_MARKER,
        heading=f"PLTR ${threshold:,.0f} チェック",
        title=build_title(close, reached, threshold),
        message=build_message(latest_date, close, low, high, reached, threshold),
        description=DESCRIPTION,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
