#!/usr/bin/env python3
"""Composite contrarian-stress score for the US market, checked daily.

Three readings are each normalised to 0-100 in the direction "the more
contrarian stress, the higher", then blended:

    Fear & Greed  40%   inverted: index 100 (Extreme Greed) -> 0,
                        index 0 (Extreme Fear) -> 100
    VIX           30%   calm -> 0, panic -> 100
    S&P500 vs MA200  30%   above the 200-day line -> 0, below it -> 100

All three are centred so that a neutral market scores about 50: Fear & Greed
50, the VIX band's midpoint, and price sitting exactly on its 200-day line.
The blend crossing 65 is the signal, i.e. stress well past neutral on the
weighted average rather than one component spiking on its own.

The three inputs come from two independent sources (CNN and Yahoo), so one
can be down while the others are fine. A missing component is never treated
as zero stress: it is dropped, the remaining weights are renormalised, and
the notification says which one is missing and what the score would be
weighted on. See notify.py for how the result is delivered.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import fear_greed
import market
import notify

SP500_TICKER = "^GSPC"
VIX_TICKER = "^VIX"
MA_PERIOD = 200
DEFAULT_THRESHOLD = 65.0

WEIGHT_FNG = 0.40
WEIGHT_VIX = 0.30
WEIGHT_DEVIATION = 0.30

# VIX band. Linear between the two, clamped outside them: a decade of daily
# closes sits mostly between them, with the midpoint (26) near the level at
# which a drawdown stops being routine.
VIX_CALM = 12.0  # and below -> 0
VIX_PANIC = 40.0  # and above -> 100

# Distance from the 200-day line, as a fraction. Symmetric around the line
# itself, so sitting on the MA200 scores 50.
DEVIATION_CALM = 0.10  # +10% and above -> 0
DEVIATION_STRESSED = -0.10  # -10% and below -> 100

TRACKING_MARKER = "<!-- market-stress-composite-monitor -->"
DESCRIPTION = (
    "Fear & Greed 40% + VIX 30% + S&P500の200日線乖離 30% の合成ストレス指数を"
    "毎営業日チェックし、結果をこのIssueにコメントします。"
)


@dataclass
class Component:
    """One normalised input to the blend."""

    label: str
    weight: float
    stress: float | None  # 0-100, or None when the source was unreachable
    detail: str  # the raw reading, shown as-is in the notification

    @property
    def contribution(self) -> float | None:
        return None if self.stress is None else self.stress * self.weight


def resolve_threshold() -> float:
    """The 65 threshold, overridable via STRESS_THRESHOLD.

    The workflow exposes this as a dispatch input so a manual run can force
    the exceeded branch and verify that the alert actually gets delivered.
    """
    raw = os.environ.get("STRESS_THRESHOLD", "").strip()
    return float(raw) if raw else DEFAULT_THRESHOLD


def normalize(value: float, zero_at: float, hundred_at: float) -> float:
    """Map value onto 0-100 linearly, clamped at both ends."""
    scaled = (value - zero_at) / (hundred_at - zero_at) * 100.0
    return max(0.0, min(100.0, scaled))


def fng_stress(score: float) -> float:
    """Fear & Greed is already 0-100; stress is its mirror image."""
    return normalize(score, 100.0, 0.0)


def vix_stress(vix: float) -> float:
    return normalize(vix, VIX_CALM, VIX_PANIC)


def deviation_stress(deviation: float) -> float:
    return normalize(deviation, DEVIATION_CALM, DEVIATION_STRESSED)


def composite(components: list[Component]) -> tuple[float | None, float]:
    """Return (score, covered weight) over the components that are available.

    Renormalising by the covered weight keeps a partial score on the same
    0-100 scale as a complete one, so the threshold still means the same
    thing; the caller reports how much weight it actually rests on.
    """
    available = [item for item in components if item.stress is not None]
    covered = sum(item.weight for item in available)
    if not available or covered == 0:
        return None, 0.0
    return sum(item.contribution for item in available) / covered, covered


def read_fear_greed() -> Component:
    reading = fear_greed.fetch()
    if reading is None:
        return Component("Fear & Greed", WEIGHT_FNG, None, "取得失敗(CNNに接続できず)")

    rating = f" ({reading['rating']})" if reading["rating"] else ""
    session = reading["session"].isoformat() if reading["session"] else "日付不明"
    return Component(
        "Fear & Greed",
        WEIGHT_FNG,
        fng_stress(reading["score"]),
        f"指数 {reading['score']:.0f}{rating} / {session}",
    )


def read_vix() -> Component:
    try:
        data, expected, stale = market.download_daily(VIX_TICKER, period="1mo")
    except Exception as exc:
        print(f"VIX: download failed: {exc}", file=sys.stderr)
        return Component("VIX", WEIGHT_VIX, None, "取得失敗(Yahooから取得できず)")

    close = market.close_series(data)
    vix = float(close.iloc[-1])
    suffix = f" ※{expected.isoformat()}未反映" if stale else ""
    return Component(
        "VIX",
        WEIGHT_VIX,
        vix_stress(vix),
        f"{vix:,.2f} / {market.last_session_date(data).isoformat()}{suffix}",
    )


def read_deviation() -> tuple[Component, dict]:
    """The S&P500's distance from its 200-day line, plus context for the body.

    The S&P500 close is reported whether or not the moving average can be
    computed, so the second return value carries it separately.
    """
    context: dict = {}
    try:
        # 2y leaves room for the 200-session window plus holidays and gaps.
        data, expected, stale = market.download_daily(SP500_TICKER, period="2y")
    except Exception as exc:
        print(f"{SP500_TICKER}: download failed: {exc}", file=sys.stderr)
        return (
            Component("S&P500 200日線乖離", WEIGHT_DEVIATION, None, "取得失敗"),
            context,
        )

    close = market.close_series(data)
    price = float(close.iloc[-1])
    session = market.last_session_date(data)
    context = {
        "date": session,
        "close": price,
        "previous": market.previous_session(data),
        "stale_note": market.staleness_note(session, expected) if stale else None,
    }

    if len(close) < MA_PERIOD:
        return (
            Component(
                "S&P500 200日線乖離",
                WEIGHT_DEVIATION,
                None,
                f"算出不可(日足{len(close)}本 < {MA_PERIOD}本)",
            ),
            context,
        )

    ma = float(close.rolling(MA_PERIOD).mean().iloc[-1])
    deviation = (price - ma) / ma
    context["ma"] = ma
    context["deviation"] = deviation
    return (
        Component(
            "S&P500 200日線乖離",
            WEIGHT_DEVIATION,
            deviation_stress(deviation),
            f"{price:,.2f} / MA200 {ma:,.2f} ({deviation * 100:+.2f}%)",
        ),
        context,
    )


def build_title(score: float | None, threshold: float, partial: bool) -> str:
    """A self-contained one-liner; it becomes the notification subject."""
    if score is None:
        return "[市場ストレス] 算出不可 — 全データ取得失敗"
    suffix = " ※一部データ欠損" if partial else ""
    if score > threshold:
        return f"[市場ストレス] {score:.1f} — {threshold:.0f}超 逆張り検討{suffix}"
    return (
        f"[市場ストレス] {score:.1f} — {threshold:.0f}以下 "
        f"(あと {threshold - score:.1f}){suffix}"
    )


def build_message(
    score: float | None,
    covered: float,
    components: list[Component],
    context: dict,
    threshold: float,
) -> str:
    lines = ["市場ストレス指数チェック"]
    if context.get("date"):
        lines.append(f"日付: {context['date'].isoformat()}")

    if score is None:
        lines.append("総合スコア: 算出不可(すべてのデータ取得に失敗しました)")
    else:
        lines.append(f"総合スコア: {score:.1f} / 100 (しきい値 {threshold:.0f})")
        if score > threshold:
            lines.append(
                f"判定: {threshold:.0f}超 -> 逆張り(買い)アクション検討"
            )
        else:
            lines.append(
                f"判定: 平常 (あと {threshold - score:.1f} でシグナル)"
            )

    lines.append("")
    lines.append("内訳:")
    for item in components:
        head = f"  {item.label} ({item.weight * 100:.0f}%): {item.detail}"
        if item.stress is None:
            lines.append(f"{head} -> 除外")
        else:
            lines.append(
                f"{head} -> ストレス {item.stress:.1f} -> 寄与 {item.contribution:.1f}"
            )

    if score is not None and covered < 1.0:
        lines.append(
            f"※取得できた {covered * 100:.0f}% 分の重みで再正規化したスコアです"
            "(欠損分は0点扱いにせず除外しています)"
        )

    if context.get("close") is not None:
        lines.append("")
        lines.append(f"S&P500終値: {context['close']:,.2f}")
        lines.extend(market.change_lines(context.get("previous"), context["close"]))

    lines.append("")
    lines.append("正規化の基準(いずれも高いほど逆張り的ストレスが強い):")
    lines.append("  Fear & Greed: 100 - 指数 (指数0=Extreme Fear / 100=Extreme Greed)")
    lines.append(
        f"  VIX: {VIX_CALM:.0f}以下=0 / {VIX_PANIC:.0f}以上=100 の線形"
    )
    lines.append(
        f"  200日線乖離: {DEVIATION_CALM * 100:+.0f}%以上=0 / 0%=50 / "
        f"{DEVIATION_STRESSED * 100:+.0f}%以下=100 の線形"
    )
    lines.append(
        f"判定基準: Fear&Greed {WEIGHT_FNG * 100:.0f}% + VIX {WEIGHT_VIX * 100:.0f}% + "
        f"200日線乖離 {WEIGHT_DEVIATION * 100:.0f}% の加重平均が {threshold:.0f} 超"
    )

    if context.get("stale_note"):
        lines.append(context["stale_note"])

    return "\n".join(lines)


def main() -> int:
    threshold = resolve_threshold()

    deviation_component, context = read_deviation()
    components = [read_fear_greed(), read_vix(), deviation_component]

    score, covered = composite(components)
    partial = score is not None and covered < 1.0

    notify.notify(
        marker=TRACKING_MARKER,
        heading="市場ストレス指数チェック",
        title=build_title(score, threshold, partial),
        message=build_message(score, covered, components, context, threshold),
        description=DESCRIPTION,
    )
    # Every source failing is a broken run, not a reading of "no stress".
    return 1 if score is None else 0


if __name__ == "__main__":
    raise SystemExit(main())
