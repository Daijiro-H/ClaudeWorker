#!/usr/bin/env python3
"""Shared notification for the daily market-check tools.

Both tools report the same way: a single long-lived GitHub issue per tool is
retitled with the day's verdict and gets one comment per run, so the result
arrives by email whatever the outcome. Notification subjects carry the
issue's current title, so the retitle puts the verdict in the subject line.

Notification channels, in order of reliability:

- GitHub issue (no setup required). Works out of the box through GITHUB_TOKEN.
- LINE Messaging API (optional). Skipped with a warning when its secrets are
  not configured, so a missing LINE setup never fails the run or suppresses
  the GitHub notification.

Exactly one notifying action per run: editing a title notifies nobody, so the
daily comment is the only one. A run that has to create the tracking issue
writes the result straight into the body rather than adding a comment, to
avoid notifying twice for the same result.
"""

from __future__ import annotations

import os
import sys

import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
GITHUB_API_URL = "https://api.github.com"


def write_job_summary(heading: str, message: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(f"## {heading}\n\n```\n{message}\n```\n")


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


def find_tracking_issue(marker: str, token: str, repository: str) -> int | None:
    issues = _github_request(
        "GET",
        f"{GITHUB_API_URL}/repos/{repository}/issues?state=open&per_page=100",
        token,
    )
    for issue in issues:
        # The issues endpoint also returns pull requests; skip those.
        if "pull_request" in issue:
            continue
        if marker in (issue.get("body") or ""):
            return issue["number"]
    return None


def create_tracking_issue(
    marker: str,
    title: str,
    message: str,
    description: str,
    token: str,
    repository: str,
    assignee: str,
) -> int:
    body = (
        f"{marker}\n"
        f"@{assignee}\n\n"
        f"```\n{message}\n```\n\n"
        f"---\n\n"
        f"{description}\n"
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


def notify_github(marker: str, title: str, message: str, description: str) -> None:
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

    number = find_tracking_issue(marker, token, repository)
    if number is None:
        number = create_tracking_issue(
            marker, title, message, description, token, repository, assignee
        )
        print(f"Tracking issue #{number} created with today's result in the body.")
        return

    # Retitle first: a comment notification carries the issue's title as it
    # stands when the comment is posted, so this puts today's verdict in the
    # subject line. Editing a title notifies nobody, so the comment below
    # stays the run's only notification.
    set_issue_title(number, title, token, repository)
    url = add_issue_comment(
        number, f"@{assignee}\n\n```\n{message}\n```", token, repository
    )
    print(f"Commented on tracking issue #{number}: {url}")


def notify(marker: str, heading: str, title: str, message: str, description: str) -> None:
    """Report one run's result through every configured channel."""
    print(title)
    print(message)
    write_job_summary(heading, message)
    notify_line(message)
    notify_github(marker, title, message, description)
