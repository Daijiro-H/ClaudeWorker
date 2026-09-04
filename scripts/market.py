#!/usr/bin/env python3
"""Daily bar retrieval with a freshness guarantee.

Yahoo does not always have the day's daily bar published by the time the
morning run fires: on 2026-09-03 the run reported the 2026-09-01 session,
byte-for-byte identical to the previous day's notification, because the code
took whatever the last row happened to be. Silently reporting a stale price
as if it were current is worse than reporting nothing, so the download is
retried until the expected session shows up, and what is still missing
afterwards is stated in the notification instead of being hidden.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

EASTERN = ZoneInfo("America/New_York")
MARKET_CLOSE_HOUR_ET = 16  # 16:00 ET regular-session close
DEFAULT_ATTEMPTS = 3
DEFAULT_DELAY_SECONDS = 45


def latest_expected_session(now_utc: datetime | None = None) -> date:
    """The most recent weekday whose 16:00 ET close has already passed.

    Weekday-based, so a US market holiday looks like a missing session. That
    is deliberate: it makes the run say the data may be behind rather than
    quietly presenting an older bar as today's.
    """
    now = (now_utc or datetime.now(timezone.utc)).astimezone(EASTERN)
    day = now.date()
    if now.hour < MARKET_CLOSE_HOUR_ET:
        day -= timedelta(days=1)
    while day.weekday() >= 5:  # Saturday, Sunday
        day -= timedelta(days=1)
    return day


def _flatten(data: pd.DataFrame) -> pd.DataFrame:
    # yfinance returns (field, ticker) columns; collapse to field names.
    if isinstance(data.columns, pd.MultiIndex):
        data = data.copy()
        data.columns = data.columns.get_level_values(0)
    return data


def last_session_date(data: pd.DataFrame) -> date:
    return pd.Timestamp(data.index[-1]).date()


def download_daily(
    ticker: str,
    period: str = "1mo",
    attempts: int = DEFAULT_ATTEMPTS,
    delay_seconds: int = DEFAULT_DELAY_SECONDS,
    now_utc: datetime | None = None,
) -> tuple[pd.DataFrame, date, bool]:
    """Return (bars, expected_session, stale).

    Retries while the newest bar predates the expected session, since the
    usual cause is Yahoo not having published it yet.
    """
    expected = latest_expected_session(now_utc)
    data = pd.DataFrame()

    for attempt in range(1, attempts + 1):
        data = _flatten(
            yf.download(
                ticker, period=period, interval="1d", progress=False, auto_adjust=False
            )
        )
        data = data.dropna(subset=["Close"]) if not data.empty else data
        if not data.empty and last_session_date(data) >= expected:
            return data, expected, False
        if attempt < attempts:
            have = last_session_date(data).isoformat() if not data.empty else "none"
            print(
                f"{ticker}: newest bar is {have}, expected {expected.isoformat()}; "
                f"retrying in {delay_seconds}s ({attempt}/{attempts - 1})",
                file=sys.stderr,
            )
            time.sleep(delay_seconds)

    if data.empty:
        raise RuntimeError(f"No price data returned for {ticker}")

    print(
        f"{ticker}: giving up after {attempts} attempts; newest bar is "
        f"{last_session_date(data).isoformat()}, expected {expected.isoformat()}",
        file=sys.stderr,
    )
    return data, expected, True


def staleness_note(last: date, expected: date) -> str:
    return (
        f"※データ遅延: {expected.isoformat()} のセッションが未反映のため、"
        f"{last.isoformat()} 時点の値です(米国市場の休場日の場合もあります)"
    )
