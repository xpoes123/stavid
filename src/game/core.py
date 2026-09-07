"""Pure game logic: money-type gating, pace, streak. Cents in, cents out.

Only Variable spend counts (§2 of the spec). Fixed bills and Sinking-fund
draws (travel, gifts) are tracked but never break a streak.
"""
from __future__ import annotations
from dataclasses import dataclass
import calendar
import datetime as dt

VARIABLE = "Variable"
MONEY_TYPES = (VARIABLE, "Fixed", "Sinking")


@dataclass
class SpendItem:
    """One in-scope contribution to a user's day. cents>0 spends, cents<0 offsets."""
    date: dt.date
    cents: int
    money_type: str        # Variable | Fixed | Sinking
    category: str          # for the brief's bars; free-form otherwise


def variable_by_day(items: list[SpendItem]) -> dict[dt.date, int]:
    by: dict[dt.date, int] = {}
    for it in items:
        if it.money_type == VARIABLE:
            by[it.date] = by.get(it.date, 0) + it.cents
    return by


def cumulative_to(day: dt.date, by_day: dict[dt.date, int]) -> int:
    return sum(c for d, c in by_day.items()
               if d.year == day.year and d.month == day.month and d <= day)


def allowance_cents(day: dt.date, cap_cents: int) -> int:
    """Prorated month-to-date allowance (§7). Round to the cent."""
    dim = calendar.monthrange(day.year, day.month)[1]
    return round(cap_cents * day.day / dim)


@dataclass
class Score:
    day: dt.date
    spent_cents: int
    allowed_cents: int
    on_pace: bool
    froze: bool
    streak: int
    freezes_remaining: int


def score_day(day: dt.date, by_day: dict[dt.date, int], *, cap_cents: int,
              streak: int, freezes_remaining: int, freeze_month: str | None,
              last_scored: str | None, freezes_per_month: int,
              shadow: bool) -> tuple[Score, dict]:
    """Advance a player's streak for `day`. Returns (Score, mutated player fields).

    Idempotent per date. Shadow mode reports but accrues nothing.
    """
    spent = cumulative_to(day, by_day)
    allowed = allowance_cents(day, cap_cents)
    on_pace = spent <= allowed

    month = day.strftime("%Y-%m")
    if freeze_month != month:                    # monthly freeze allotment resets
        freeze_month = month
        freezes_remaining = freezes_per_month

    froze = False
    if not shadow and last_scored != day.isoformat():
        if on_pace:
            streak += 1
        elif freezes_remaining > 0:
            freezes_remaining -= 1
            streak += 1
            froze = True
        else:
            streak = 0
        last_scored = day.isoformat()

    fields = {"streak": streak, "freezes_remaining": freezes_remaining,
              "freeze_month": freeze_month, "last_scored": last_scored}
    return Score(day, spent, allowed, on_pace, froze, streak, freezes_remaining), fields
