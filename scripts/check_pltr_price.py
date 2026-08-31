#!/usr/bin/env python3
"""Check whether Palantir (PLTR) has reached the $160 threshold and notify.

Sends a daily notification with the latest close, and flags an actionable
signal when the price reaches the threshold from above (close <= 160, or the
session low touching 160).

Notification channels, in order of reliability:

- GitHub issue (no setup required): a single tracking issue is retitled with
  the day's verdict and gets a comment on every run, reached or not, so
  GitHub emails the repository owner daily. Notification subjects carry the
  issue's current title, so the retitle puts the price and the verdict in the
  subject line. This is the channel that works out of the box.
- LINE Messaging API (optional): a daily push, matching the S&P500 RSI tool.
  Skipped with a warning when its secrets are not configured, so a missing
  LINE setup never fails the run or suppresses the GitHub notification.
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
# Marks the one long-lived issue this tool retitles and comments on, so the
# run can find it again without storing state anywhere.
TRACKING_MARKER = "<!-- pltr-threshold-monitor -->"


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


def _github_request(method: str, url: str, token: str, payload: dict | None = None):
    response = requests.request(
        method,
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def find_tracking_issue(token: str, repository: str) -> int | None:
    issues = _github_request(
        "GET",
        f"{GITHUB_API_URL}/repos/{repository}/issues?state=open&per_page=100",
        token,
    )
    for issue in issues:
        # The issues endpoint also returns pull requests; skip those.
        if "pull_request" in issue:
            continue
        if TRACKING_MARKER in (issue.get("body") or ""):
            return issue["number"]
    return None


def create_tracking_issue(
    title: str, message: str, token: str, repository: str, assignee: str
) -> int:
    # The first run's result goes straight into the body rather than into a
    # follow-up comment: each notifying action costs the recipient a separate
    # email, so the creation run posts once instead of twice.
    body = (
        f"{TRACKING_MARKER}\n"
        f"@{assignee}\n\n"
        f"```\n{message}\n```\n\n"
        f"---\n\n"
        f"PLTRの株価を毎日チェックし、結果をこのIssueにコメントします。\n"
        f"タイトルは常に最新の判定に更新されるため、通知メールの件名だけで結果が分かります。\n\n"
        f"このIssueは閉じないでください。閉じると次回の実行で新しいIssueが作成されます。"
    )
    issue = _github_request(
        "POST",
        f"{GITHUB_API_URL}/repos/{repository}/issues",
        token,
        {"title": title, "body": body, "assignees": [assignee]},
    )
    return issue["number"]


def set_issue_title(number: int, title: str, token: str, repository: str) -> None:
    _github_request(
        "PATCH",
        f"{GITHUB_API_URL}/repos/{repository}/issues/{number}",
        token,
        {"title": title},
    )


def add_issue_comment(number: int, body: str, token: str, repository: str) -> str:
    comment = _github_request(
        "POST",
        f"{GITHUB_API_URL}/repos/{repository}/issues/{number}/comments",
        token,
        {"body": body},
    )
    return comment["html_url"]


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


def notify_github(message: str, title: str, threshold: float) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repository = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repository:
        print(
            "Note: GITHUB_TOKEN / GITHUB_REPOSITORY are not set, "
            "skipping the GitHub notification.",
            file=sys.stderr,
        )
        return

    # Assign and @mention the recipient. A repository's default watch setting
    # is "Participating and @mentions", under which activity from
    # github-actions[bot] that does not involve you generates no notification
    # at all; being assigned and mentioned counts as participating, so the
    # daily update reaches the inbox without switching to "All Activity".
    assignee = os.environ.get("ISSUE_ASSIGNEE", "").strip() or repository.split("/")[0]

    number = find_tracking_issue(token, repository)
    if number is None:
        number = create_tracking_issue(title, message, token, repository, assignee)
        print(f"Tracking issue #{number} created with today's result in the body.")
        return

    # Retitle first: a comment notification carries the issue's title as it
    # stands when the comment is posted, so this puts today's verdict in the
    # subject line. Editing a title notifies nobody, so the comment below
    # stays the run's only notification.
    set_issue_title(number, title, token, repository)
    url = add_issue_comment(
        number,
        f"@{assignee}\n\n```\n{message}\n```",
        token,
        repository,
    )
    print(f"Commented on tracking issue #{number}: {url}")


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
    title = build_title(close, reached, threshold)
    print(title)
    print(message)

    write_job_summary(message)
    notify_line(message)
    notify_github(message, title, threshold)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
