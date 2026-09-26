"""Price history signals. Milestones 21 and 22, BRIEF section 3.4.

Pure functions over (date, price) lists. The app DB build feeds them from the
dev database; the phone re-derives anything that depends on today's date
(`cycle_hint`) itself, so a date ticking over doesn't rewrite rows.
"""

from __future__ import annotations

import statistics
from datetime import date, timedelta

INFLATION_WINDOW_DAYS = 28
# A rise smaller than this is rounding (2.99 -> 3.00), not a raised anchor.
INFLATION_MIN_RISE = 0.02
MIN_PROMOS_FOR_CYCLE = 3
# "Wait" only when the next promo is expected this close. Further out, the
# honest advice is to buy when you need it.
WAIT_WITHIN_DAYS = 14
SPARKLINE_WEEKS = 26


def reference_inflated(shelf: list[tuple[date, float]], promo_start: date,
                       promo_shelf: float | None) -> bool | None:
    """Did the shelf price go up in the 28 days before this promo started?

    A raised shelf price makes "25% korting" look better than it is. Needs a
    shelf price from before the window to compare with; without one the
    answer is unknown, not no.
    """
    if promo_shelf is None:
        return None
    window_start = promo_start - timedelta(days=INFLATION_WINDOW_DAYS)
    before = [p for d, p in sorted(shelf) if d <= window_start and p is not None]
    if not before:
        return None
    return promo_shelf > before[-1] * (1 + INFLATION_MIN_RISE)


def cycle_days(promo_starts: list[date]) -> int | None:
    """Median days between promo start dates, or None under three promos."""
    starts = sorted(set(promo_starts))
    if len(starts) < MIN_PROMOS_FOR_CYCLE:
        return None
    gaps = [(b - a).days for a, b in zip(starts, starts[1:])]
    return round(statistics.median(gaps))


def cycle_hint(cycle: int | None, last_start: date | None, *, on_promo: bool,
               today: date) -> str | None:
    """'buy' or 'wait', from the cycle and today's date.

    Mirrored in the app (`CycleHint.kt`); both are tested on the same cases.
    """
    if cycle is None or last_start is None:
        return None
    if on_promo:
        return "buy"
    until = (last_start + timedelta(days=cycle) - today).days
    if until > WAIT_WITHIN_DAYS:
        return "buy"
    if until > -cycle:
        # Due soon, or a little overdue: both mean it's likely close.
        return "wait"
    return None   # more than a whole cycle overdue; the pattern broke


def weekly_min(observations: list[tuple[date, float]],
               weeks: int = SPARKLINE_WEEKS) -> list[tuple[str, float]]:
    """Lowest price per ISO week (keyed by its Monday), last `weeks` weeks."""
    by_week: dict[str, float] = {}
    for day, price in observations:
        if price is None:
            continue
        monday = (day - timedelta(days=day.weekday())).isoformat()
        by_week[monday] = min(price, by_week.get(monday, price))
    return sorted(by_week.items())[-weeks:]
