#!/usr/bin/env python3
"""Daily bar retrieval with a freshness guarantee.

Yahoo publishes the newest session in two places that disagree for hours
after the close. The daily-bar array carries a row for the session with its
OHLC still null, while the quote metadata alongside it already holds the
settled close. Dropping the null row therefore silently falls back to the
previous session: on 2026-09-03 and 2026-09-04 the runs reported a price a
full session old, identical to the day before, while Yahoo's own site showed
the current one.

So the null row is completed from the quote metadata (regularMarketPrice and
the day's high/low, stamped with regularMarketTime) rather than discarded.
Only a session whose 16:00 ET close has passed is filled in, so an
in-progress session is never mistaken for a settled one. If neither source
has the expected session the download is retried, and anything still missing
is stated in the notification instead of being hidden.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

EASTERN = ZoneInfo("America/New_York")
MARKET_CLOSE_HOUR_ET = 16  # 16:00 ET regular-session close
DEFAULT_ATTEMPTS = 3
DEFAULT_DELAY_SECONDS = 45
CHART_HOSTS = ("query2", "query1")
CHART_URL = "https://{host}.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
# Yahoo rejects requests without a browser-ish agent.
USER_AGENT = "Mozilla/5.0 (compatible; ClaudeWorker/1.0)"


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


def latest_quote(ticker: str) -> dict | None:
    """The settled close from Yahoo's quote metadata, or None.

    Returns the session date in exchange-local terms alongside the price, so
    the caller can tell which session the quote actually belongs to.
    """
    for host in CHART_HOSTS:
        try:
            response = requests.get(
                CHART_URL.format(host=host, ticker=ticker),
                headers={"User-Agent": USER_AGENT},
                timeout=30,
            )
            response.raise_for_status()
            meta = response.json()["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            stamp = meta.get("regularMarketTime")
            if price is None or stamp is None:
                continue
            tz = ZoneInfo(meta.get("exchangeTimezoneName") or "America/New_York")
            moment = datetime.fromtimestamp(stamp, timezone.utc).astimezone(tz)
            return {
                "session": moment.date(),
                "close": float(price),
                "high": meta.get("regularMarketDayHigh"),
                "low": meta.get("regularMarketDayLow"),
            }
        except Exception as exc:  # any host may fail; try the next one
            print(f"{ticker}: quote metadata via {host} failed: {exc}", file=sys.stderr)
    return None


def fill_expected_session(
    data: pd.DataFrame, ticker: str, expected: date
) -> pd.DataFrame | None:
    """Append the expected session from the quote metadata, if it is there."""
    quote = latest_quote(ticker)
    if quote is None or quote["session"] != expected:
        return None

    close = quote["close"]
    row = {column: float("nan") for column in data.columns}
    row["Close"] = close
    if "High" in row:
        row["High"] = float(quote["high"]) if quote["high"] is not None else close
    if "Low" in row:
        row["Low"] = float(quote["low"]) if quote["low"] is not None else close
    if "Open" in row:
        row["Open"] = close
    if "Adj Close" in row:
        row["Adj Close"] = close

    stamp = pd.Timestamp(expected)
    if data.index.tz is not None:
        stamp = stamp.tz_localize(data.index.tz)
    completed = pd.concat([data, pd.DataFrame([row], index=[stamp])])
    print(
        f"{ticker}: daily bar for {expected.isoformat()} was empty; "
        f"completed it from the quote metadata (close={close})"
    )
    return completed


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

        # The bar exists but is not populated yet; the quote metadata has it.
        if not data.empty:
            completed = fill_expected_session(data, ticker, expected)
            if completed is not None:
                return completed, expected, False

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


def previous_session(data: pd.DataFrame) -> tuple[date, float] | None:
    """The session before the newest one, or None when there is only one."""
    if len(data) < 2:
        return None
    return pd.Timestamp(data.index[-2]).date(), float(data.iloc[-2]["Close"])


def change_lines(previous: tuple[date, float] | None, close: float) -> list[str]:
    """Previous close and the move from it, ready to drop into a message."""
    if previous is None:
        return ["前日終値: 取得できず"]
    prev_date, prev_close = previous
    lines = [f"前日終値: {prev_close:,.2f} ({prev_date.isoformat()})"]
    if prev_close:
        diff = close - prev_close
        lines.append(f"前日比: {diff:+,.2f} ({diff / prev_close * 100:+.2f}%)")
    return lines


def staleness_note(last: date, expected: date) -> str:
    return (
        f"※データ遅延: {expected.isoformat()} のセッションが未反映のため、"
        f"{last.isoformat()} 時点の値です(米国市場の休場日の場合もあります)"
    )
