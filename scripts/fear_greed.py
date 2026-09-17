#!/usr/bin/env python3
"""CNN Fear & Greed Index retrieval.

CNN publishes the index through the JSON feed that backs its own dashboard.
There is no documented API, so two things are worth knowing: the endpoint
rejects requests that do not look like a browser, and the undated URL
occasionally 404s while the dated one keeps serving. Both are handled here.

The score is 0-100 with 0 = Extreme Fear and 100 = Extreme Greed, i.e. the
opposite orientation from a stress gauge; the caller inverts it.
"""

from __future__ import annotations

import sys
import time
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import requests

EASTERN = ZoneInfo("America/New_York")
BASE_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
DEFAULT_ATTEMPTS = 3
DEFAULT_DELAY_SECONDS = 20
# CNN serves the feed only to requests that carry a browser-ish agent and an
# origin of its own site.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://edition.cnn.com",
    "Referer": "https://edition.cnn.com/",
}


def _session_date(stamp: str | None) -> date | None:
    """The US-market session a feed timestamp belongs to."""
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(EASTERN).date()


def _parse(payload: dict) -> dict | None:
    current = payload.get("fear_and_greed") or {}
    score = current.get("score")
    session = _session_date(current.get("timestamp"))

    if score is None:
        # The dated URL sometimes omits the summary block and carries only the
        # series; its last point is the same reading.
        history = (payload.get("fear_and_greed_historical") or {}).get("data") or []
        if not history:
            return None
        last = history[-1]
        score = last.get("y")
        if score is None:
            return None
        stamp = last.get("x")
        if session is None and stamp is not None:
            session = datetime.fromtimestamp(
                float(stamp) / 1000, timezone.utc
            ).astimezone(EASTERN).date()
        rating = last.get("rating")
    else:
        rating = current.get("rating")

    return {
        "score": float(score),
        "rating": (rating or "").replace("_", " ") or None,
        "session": session,
        "previous_close": (
            float(current["previous_close"])
            if current.get("previous_close") is not None
            else None
        ),
    }


def fetch(
    attempts: int = DEFAULT_ATTEMPTS, delay_seconds: int = DEFAULT_DELAY_SECONDS
) -> dict | None:
    """The latest index reading, or None when the feed cannot be reached."""
    # The dated URL is the fallback: same payload, different route, and it has
    # stayed up on days the undated one returned 404.
    urls = (BASE_URL, f"{BASE_URL}/{date.today().isoformat()}")

    for attempt in range(1, attempts + 1):
        for url in urls:
            try:
                response = requests.get(url, headers=HEADERS, timeout=30)
                response.raise_for_status()
                reading = _parse(response.json())
                if reading is not None:
                    return reading
                print(f"Fear & Greed: {url} returned no score", file=sys.stderr)
            except Exception as exc:
                print(f"Fear & Greed: {url} failed: {exc}", file=sys.stderr)
        if attempt < attempts:
            time.sleep(delay_seconds)
    return None
