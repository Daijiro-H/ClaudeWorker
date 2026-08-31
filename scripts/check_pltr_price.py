#!/usr/bin/env python3
"""Check whether Palantir (PLTR) has reached the $160 threshold and notify.

Sends a daily notification with the latest close, and flags an actionable
signal when the price reaches the threshold from above (close <= 160, or the
session low touching 160).

Notification channels, in order of reliability:

- GitHub issue (no setup required): opened when the threshold is reached, so
  GitHub emails the repository owner. This is the channel that works out of
  the box.
- LINE Messaging API (optional): a daily push, matching the S&P500 RSI tool.
  Skipped with a warning when its secrets are not configured, so a missing
  LINE setup never fails the run or suppresses the GitHub issue.
"""

from __future__ import annotations

import json
import os
import sys

import pandas as pd
import requests
import yfinance as yf

TICKER = "PLTR"
DEFAULT_THRESHOLD = 160.0
LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
GITHUB_API_URL = "https://api.github.com"


def fetch_recent_prices(ticker: str, period: str = "1mo") -> pd.DataFrame:
    data = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False)
    if data.empty:
        raise RuntimeError(f"No price data returned for {ticker}")
    # yfinance returns column MultiIndex when several tickers are requested;
    # flatten to the single-ticker case.
    if isinstance(data.columns, pd.MultiIndex):
        data = data.xs(ticker, axis=1, level=1)
    return data.dropna(subset=["Close"])


def resolve_threshold() -> float:
    """The $160 target, overridable via PLTR_THRESHOLD.

    The workflow exposes this as a dispatch input so a manual run can force
    the reached branch and verify that the alert actually gets delivered.
    """
    raw = os.environ.get("PLTR_THRESHOLD", "").strip()
    if not raw:
        return DEFAULT_THRESHOLD
    return float(raw)


def evaluate(close: float, low: float, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """Return True when the price has come down to the threshold.

    PLTR trades above $160, so the meaningful event is the price falling to
    it: either the close lands at or below the threshold, or the session dips
    through it intraday.
    """
    return close <= threshold or low <= threshold


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


def send_line_push_message(message: str, channel_access_token: str, to: str) -> None:
    response = requests.post(
        LINE_PUSH_URL,
        headers={
            "Authorization": f"Bearer {channel_access_token}",
            "Content-Type": "application/json",
        },
        json={"to": to, "messages": [{"type": "text", "text": message}]},
        timeout=30,
    )
    response.raise_for_status()


def create_github_issue(title: str, body: str, token: str, repository: str) -> str:
    response = requests.post(
        f"{GITHUB_API_URL}/repos/{repository}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"title": title, "body": body},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["html_url"]


def write_job_summary(message: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(f"## PLTR $160 チェック\n\n```\n{message}\n```\n")


def notify_line(message: str) -> None:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    if not token or not user_id:
        print(
            "Note: LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID are not set, "
            "skipping the LINE push.",
            file=sys.stderr,
        )
        return
    send_line_push_message(message, token, user_id)
    print("LINE push sent.")


def notify_github_issue(message: str, date_str: str, threshold: float) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        print(
            "Note: GITHUB_TOKEN / GITHUB_REPOSITORY are not set, "
            "skipping the issue.",
            file=sys.stderr,
        )
        return
    url = create_github_issue(
        title=f"[PLTR] ${threshold:,.0f} に到達しました ({date_str})",
        body=f"```\n{message}\n```\n\nこのIssueは日次チェックワークフローが自動で作成しました。",
        token=token,
        repository=repository,
    )
    print(f"GitHub issue created: {url}")


def main() -> int:
    threshold = resolve_threshold()
    data = fetch_recent_prices(TICKER)

    latest = data.iloc[-1]
    latest_date = data.index[-1]
    close = float(latest["Close"])
    low = float(latest["Low"])
    high = float(latest["High"])

    reached = evaluate(close, low, threshold)
    message = build_message(latest_date, close, low, high, reached, threshold)
    print(message)

    write_job_summary(message)
    notify_line(message)
    if reached:
        notify_github_issue(message, latest_date.strftime("%Y-%m-%d"), threshold)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
