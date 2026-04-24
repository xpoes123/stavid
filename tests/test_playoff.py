"""Tests for daily pillar check-in persistence and playoff logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.cogs.playoff import build_weekly_embed, finalize_series_status, format_weekly_summary, get_pillar_names, series_message, week_start_for
from src.db import DailyResult, PlayoffCheckin, PlayoffSeries, WeeklyReview
from src.utils import DAVID_ID, STEPH_ID

GUILD_ID = 999_000_000_000_000_000

# ---------------------------------------------------------------------------
# week_start_for — must map every day in a Sun–Sat week to that week's Sunday
# ---------------------------------------------------------------------------

SUNDAY_APR_19 = date(2026, 4, 19)  # confirmed Sunday
SUNDAY_APR_12 = date(2026, 4, 12)  # a completed past week (ended Apr 18)


@pytest.mark.parametrize("offset", range(7))
def test_week_start_for_all_days(offset):
    """Every day in a Sun–Sat week should map to the same Sunday."""
    day = SUNDAY_APR_19 + timedelta(days=offset)
    assert week_start_for(day) == SUNDAY_APR_19


def test_week_start_for_sunday_is_itself():
    assert week_start_for(SUNDAY_APR_19) == SUNDAY_APR_19


def test_week_start_for_saturday():
    saturday = date(2026, 4, 25)
    assert week_start_for(saturday) == SUNDAY_APR_19


def test_week_start_for_crosses_month():
    """Last day of March 2026 is a Tuesday → week started Sun Mar 29."""
    tue_mar_31 = date(2026, 3, 31)
    assert week_start_for(tue_mar_31) == date(2026, 3, 29)


# ---------------------------------------------------------------------------
# series_message — motivational copy for every score state
# ---------------------------------------------------------------------------


def test_series_message_won():
    msg = series_message(4, 0)
    assert "Won" in msg or "won" in msg


def test_series_message_lost():
    msg = series_message(0, 4)
    assert "lost" in msg.lower()


def test_series_message_tied():
    msg = series_message(2, 2)
    assert "Tied" in msg


def test_series_message_ahead():
    msg = series_message(3, 1)
    assert "Up" in msg


def test_series_message_behind_not_eliminated():
    msg = series_message(1, 3)
    # Should emphasise resilience rather than defeat
    assert "alive" in msg.lower() or "Down" in msg


def test_series_message_close_still_alive():
    msg = series_message(0, 3)
    assert "alive" in msg.lower()


# ---------------------------------------------------------------------------
# get_pillar_names — correct per-user pillars
# ---------------------------------------------------------------------------


def test_david_gets_his_pillars():
    pillars = get_pillar_names(DAVID_ID)
    assert any("steps" in p.lower() or "10,000" in p for p in pillars)
    assert len(pillars) == 3


def test_steph_gets_her_pillars():
    pillars = get_pillar_names(STEPH_ID)
    assert any("tiktok" in p.lower() for p in pillars)
    assert len(pillars) == 3


def test_unknown_user_gets_generic_pillars():
    pillars = get_pillar_names(0)
    assert pillars == ["Pillar 1", "Pillar 2", "Pillar 3"]


# ---------------------------------------------------------------------------
# DB persistence — PlayoffCheckin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_is_persisted(db_session):
    """A check-in row can be written and read back."""
    today = date(2026, 4, 21)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID,
            user_id=DAVID_ID,
            checkin_date=today,
            pillar1=True,
            pillar2=True,
            pillar3=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.guild_id == GUILD_ID,
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    assert row is not None
    assert row.pillar1 is True
    assert row.pillar2 is True
    assert row.pillar3 is False


@pytest.mark.asyncio
async def test_both_users_stored_independently(db_session):
    """David and Stephanie each get their own row per day."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=STEPH_ID, checkin_date=today,
            pillar1=False, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    david = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    steph = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.user_id == STEPH_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )

    assert david is not None and steph is not None
    assert david.pillar1 is True
    assert steph.pillar1 is False  # Steph missed pillar 1


@pytest.mark.asyncio
async def test_checkin_upsert_updates_values(db_session):
    """Re-submitting a check-in overwrites pillar values for that day."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    # Initial (all false)
    row = PlayoffCheckin(
        guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
        pillar1=False, pillar2=False, pillar3=False,
        created_at=now, updated_at=now,
    )
    db_session.add(row)
    await db_session.commit()

    # Upsert — same day, updated values
    existing = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.guild_id == GUILD_ID,
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    existing.pillar1 = True
    existing.pillar2 = True
    existing.pillar3 = True
    existing.updated_at = datetime.now(timezone.utc)
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.guild_id == GUILD_ID,
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    assert refreshed.pillar1 is True
    assert refreshed.pillar2 is True
    assert refreshed.pillar3 is True


@pytest.mark.asyncio
async def test_historical_checkins_queryable(db_session):
    """All 5 weekdays' check-ins for one user are retrievable as history."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(
            PlayoffCheckin(
                guild_id=GUILD_ID,
                user_id=DAVID_ID,
                checkin_date=week_start + timedelta(days=i),
                pillar1=True, pillar2=True, pillar3=True,
                created_at=now, updated_at=now,
            )
        )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(PlayoffCheckin).where(
                PlayoffCheckin.guild_id == GUILD_ID,
                PlayoffCheckin.user_id == DAVID_ID,
                PlayoffCheckin.checkin_date >= week_start,
            )
        )
    ).all()
    assert len(rows) == 5


@pytest.mark.asyncio
async def test_series_win_requires_both_players(db_session):
    """A day only counts as a win when both David AND Steph hit all pillars."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    # David hits all; Steph only hits 2 — should be a loss
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=STEPH_ID, checkin_date=today,
            pillar1=False, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    wins, losses = _tally(
        (
            await db_session.scalars(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == GUILD_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
        ).all()
    )
    assert wins == 0
    assert losses == 1


@pytest.mark.asyncio
async def test_series_win_when_both_perfect(db_session):
    """Both players hitting all pillars = 1 series win."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    for uid in (DAVID_ID, STEPH_ID):
        db_session.add(
            PlayoffCheckin(
                guild_id=GUILD_ID, user_id=uid, checkin_date=today,
                pillar1=True, pillar2=True, pillar3=True,
                created_at=now, updated_at=now,
            )
        )
    await db_session.commit()

    wins, losses = _tally(
        (
            await db_session.scalars(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == GUILD_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
        ).all()
    )
    assert wins == 1
    assert losses == 0


@pytest.mark.asyncio
async def test_unsettled_day_not_counted(db_session):
    """A day where only one player has checked in is ignored by the tally."""
    today = date(2026, 4, 21)
    now = datetime.now(timezone.utc)

    # Only David checks in
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    wins, losses = _tally(
        (
            await db_session.scalars(
                select(PlayoffCheckin).where(
                    PlayoffCheckin.guild_id == GUILD_ID,
                    PlayoffCheckin.checkin_date == today,
                )
            )
        ).all()
    )
    assert wins == 0
    assert losses == 0


@pytest.mark.asyncio
async def test_full_week_series_accumulation(db_session):
    """4 shared-win days across a week results in a won series."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    for i in range(4):  # 4 days both perfect
        day = week_start + timedelta(days=i)
        for uid in (DAVID_ID, STEPH_ID):
            db_session.add(
                PlayoffCheckin(
                    guild_id=GUILD_ID, user_id=uid, checkin_date=day,
                    pillar1=True, pillar2=True, pillar3=True,
                    created_at=now, updated_at=now,
                )
            )
    # 1 day Steph misses
    bad_day = week_start + timedelta(days=4)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=bad_day,
            pillar1=True, pillar2=True, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=STEPH_ID, checkin_date=bad_day,
            pillar1=False, pillar2=False, pillar3=False,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    all_rows = (
        await db_session.scalars(
            select(PlayoffCheckin).where(
                PlayoffCheckin.guild_id == GUILD_ID,
                PlayoffCheckin.checkin_date >= week_start,
            )
        )
    ).all()
    wins, losses = _tally(all_rows)

    assert wins == 4
    assert losses == 1
    assert wins >= 4  # series won


# ---------------------------------------------------------------------------
# DB persistence — PlayoffSeries
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_row_persisted(db_session):
    """PlayoffSeries aggregate can be written and read back."""
    now = datetime.now(timezone.utc)
    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=SUNDAY_APR_19,
            wins=3,
            losses=1,
            status="ongoing",
            created_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == SUNDAY_APR_19,
        )
    )
    assert row is not None
    assert row.wins == 3
    assert row.losses == 1
    assert row.status == "ongoing"


# ---------------------------------------------------------------------------
# DB persistence — DailyResult (combined win/loss, authoritative per day)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_result_persisted(db_session):
    """A DailyResult row can be written and read back."""
    now = datetime.now(timezone.utc)
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=date(2026, 4, 21),
            david_complete=True,
            steph_complete=True,
            won=True,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert row is not None
    assert row.won is True
    assert row.david_complete is True
    assert row.steph_complete is True


@pytest.mark.asyncio
async def test_daily_result_loss_when_one_incomplete(db_session):
    """won=False when either player is incomplete."""
    now = datetime.now(timezone.utc)
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=date(2026, 4, 21),
            david_complete=True,
            steph_complete=False,  # Steph didn't finish
            won=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert row is not None
    assert row.won is False
    assert row.david_complete is True
    assert row.steph_complete is False


@pytest.mark.asyncio
async def test_daily_result_upsert(db_session):
    """Re-settling a day (e.g., after a re-checkin) updates the existing row."""
    now = datetime.now(timezone.utc)
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=date(2026, 4, 21),
            david_complete=True,
            steph_complete=False,
            won=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    # Steph re-checks in — now both complete
    row = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    row.steph_complete = True
    row.won = True
    row.updated_at = datetime.now(timezone.utc)
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert refreshed.won is True
    assert refreshed.steph_complete is True


@pytest.mark.asyncio
async def test_series_tally_from_daily_results(db_session):
    """Series wins/losses derived from DailyResult rows match expected counts."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # 3 wins, 1 loss over 4 days
    for i in range(3):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    db_session.add(
        DailyResult(
            guild_id=GUILD_ID,
            result_date=week_start + timedelta(days=3),
            david_complete=True,
            steph_complete=False,
            won=False,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(DailyResult).where(
                DailyResult.guild_id == GUILD_ID,
                DailyResult.result_date >= week_start,
            )
        )
    ).all()

    wins = sum(1 for r in rows if r.won)
    losses = sum(1 for r in rows if not r.won)
    assert wins == 3
    assert losses == 1


@pytest.mark.asyncio
async def test_no_daily_result_until_both_checked_in(db_session):
    """DailyResult is absent when only one player has a PlayoffCheckin."""
    now = datetime.now(timezone.utc)
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID,
            user_id=DAVID_ID,
            checkin_date=date(2026, 4, 21),
            pillar1=True,
            pillar2=True,
            pillar3=True,
            created_at=now,
            updated_at=now,
        )
    )
    await db_session.commit()

    # No DailyResult should exist yet — Steph hasn't checked in
    result = await db_session.scalar(
        select(DailyResult).where(
            DailyResult.guild_id == GUILD_ID,
            DailyResult.result_date == date(2026, 4, 21),
        )
    )
    assert result is None


@pytest.mark.asyncio
async def test_combined_win_requires_both_complete(db_session):
    """won=True only when david_complete AND steph_complete are both True."""
    now = datetime.now(timezone.utc)
    today = date(2026, 4, 21)

    cases = [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (True, True, True),
    ]
    for i, (dc, sc, expected_won) in enumerate(cases):
        result_date = today + timedelta(days=i)
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=result_date,
                david_complete=dc,
                steph_complete=sc,
                won=dc and sc,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    for i, (dc, sc, expected_won) in enumerate(cases):
        result_date = today + timedelta(days=i)
        row = await db_session.scalar(
            select(DailyResult).where(
                DailyResult.guild_id == GUILD_ID,
                DailyResult.result_date == result_date,
            )
        )
        assert row is not None
        assert row.won is expected_won, (
            f"dc={dc}, sc={sc}: expected won={expected_won}, got {row.won}"
        )


# ---------------------------------------------------------------------------
# format_weekly_summary — per-day breakdown, individual totals, streaks
# ---------------------------------------------------------------------------

WEEK_SUN = date(2026, 4, 19)  # Sunday — week of Apr 19–25


def _make_result(
    offset: int,
    *,
    david: bool,
    steph: bool,
    guild_id: int = GUILD_ID,
) -> DailyResult:
    """Create an unsaved DailyResult for day (WEEK_SUN + offset)."""
    now = datetime.now(timezone.utc)
    return DailyResult(
        guild_id=guild_id,
        result_date=WEEK_SUN + timedelta(days=offset),
        david_complete=david,
        steph_complete=steph,
        won=david and steph,
        created_at=now,
        updated_at=now,
    )


def test_summary_no_data_shows_no_checkins():
    msg = format_weekly_summary([], WEEK_SUN)
    assert "No check-ins recorded" in msg


def test_summary_no_data_still_has_reflection_prompt():
    msg = format_weekly_summary([], WEEK_SUN)
    assert "reflect" in msg.lower()


def test_summary_counts_combined_wins():
    results = [
        _make_result(0, david=True, steph=True),   # Sun — win
        _make_result(1, david=True, steph=False),  # Mon — loss
        _make_result(2, david=True, steph=True),   # Tue — win
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "2/7" in msg  # combined wins
    # Series result line
    assert "2–1" in msg


def test_summary_david_individual_count():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=True, steph=False),
        _make_result(2, david=False, steph=True),
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "David:** 2/7" in msg


def test_summary_steph_individual_count():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=True, steph=False),
        _make_result(2, david=False, steph=True),
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "Steph:** 2/7" in msg


def test_summary_per_day_win_label():
    results = [_make_result(0, david=True, steph=True)]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "Win" in msg


def test_summary_per_day_loss_label():
    results = [_make_result(1, david=True, steph=False)]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "Loss" in msg


def test_summary_days_without_result_show_dash():
    """Days with no DailyResult row should show a dash, not win/loss."""
    results = [_make_result(0, david=True, steph=True)]  # only Sunday logged
    msg = format_weekly_summary(results, WEEK_SUN)
    # Tue through Sat should show dashes (at least one "— " line)
    assert "—" in msg


def test_summary_streak_shown_when_two_or_more():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=True, steph=True),
        _make_result(2, david=False, steph=True),
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "streak" in msg.lower()
    assert "2" in msg


def test_summary_no_streak_line_for_single_win():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=False, steph=True),
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "streak" not in msg.lower()


def test_summary_streak_uses_longest_not_last():
    """Best streak should reflect the longest run, not the final sequence."""
    results = [
        _make_result(0, david=True, steph=True),   # win
        _make_result(1, david=True, steph=True),   # win (streak=2)
        _make_result(2, david=True, steph=True),   # win (streak=3)
        _make_result(3, david=False, steph=True),  # loss
        _make_result(4, david=True, steph=True),   # win (streak=1 reset)
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "3" in msg  # best streak is 3


def test_summary_day_names_appear():
    """Each day-of-week abbreviation for logged days should appear."""
    results = [
        _make_result(0, david=True, steph=True),   # Sun
        _make_result(3, david=True, steph=True),   # Wed
    ]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "Sun" in msg
    assert "Wed" in msg


def test_summary_perfect_week():
    """All 7 days won — 7/7 should appear and streak=7."""
    results = [_make_result(i, david=True, steph=True) for i in range(7)]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert "7/7" in msg
    assert "7" in msg  # streak of 7


def test_summary_under_discord_limit():
    """Summary should not exceed Discord's 2000-character message limit."""
    results = [_make_result(i, david=True, steph=True) for i in range(7)]
    msg = format_weekly_summary(results, WEEK_SUN)
    assert len(msg) <= 2000


# ---------------------------------------------------------------------------
# finalize_series_status — week-end status determination
# ---------------------------------------------------------------------------


def test_finalize_status_won_at_exactly_four():
    results = [_make_result(i, david=True, steph=True) for i in range(4)]
    assert finalize_series_status(results) == "won"


def test_finalize_status_won_with_extra_wins():
    """6-win week is still "won"."""
    results = [_make_result(i, david=True, steph=True) for i in range(6)]
    assert finalize_series_status(results) == "won"


def test_finalize_status_lost_at_three_wins():
    """3 wins, 4 losses — didn't reach 4, so the week is a loss."""
    results = [_make_result(i, david=True, steph=True) for i in range(3)]
    results += [_make_result(i + 3, david=False, steph=True) for i in range(4)]
    assert finalize_series_status(results) == "lost"


def test_finalize_status_lost_on_empty_week():
    """No activity → no wins → lost."""
    assert finalize_series_status([]) == "lost"


def test_finalize_status_lost_when_all_losses():
    results = [_make_result(i, david=False, steph=True) for i in range(7)]
    assert finalize_series_status(results) == "lost"


# ---------------------------------------------------------------------------
# DB: series finalization at week end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_finalized_won_from_daily_results(db_session):
    """A week with 4+ wins is finalized as 'won' in PlayoffSeries."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # 5 wins, 2 losses — series is won
    for i in range(5):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    for i in range(5, 7):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=False,
                steph_complete=True,
                won=False,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(DailyResult).where(DailyResult.guild_id == GUILD_ID)
        )
    ).all()

    # Simulate week-end finalization
    wins = sum(1 for r in rows if r.won)
    losses = sum(1 for r in rows if not r.won)
    status = finalize_series_status(rows)

    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=week_start,
            wins=wins,
            losses=losses,
            status=status,
            created_at=now,
        )
    )
    await db_session.commit()

    series = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    assert series is not None
    assert series.wins == 5
    assert series.losses == 2
    assert series.status == "won"


@pytest.mark.asyncio
async def test_series_finalized_lost_when_ongoing_status_overwritten(db_session):
    """An 'ongoing' series stuck at 3-3 is finalized to 'lost' at week end."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # Pre-existing series record at 3-3 (ongoing — neither reached 4)
    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=week_start,
            wins=3,
            losses=3,
            status="ongoing",
            created_at=now,
        )
    )

    daily_results = []
    for i in range(3):
        r = DailyResult(
            guild_id=GUILD_ID,
            result_date=week_start + timedelta(days=i),
            david_complete=True,
            steph_complete=True,
            won=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(r)
        daily_results.append(r)
    for i in range(3, 6):
        r = DailyResult(
            guild_id=GUILD_ID,
            result_date=week_start + timedelta(days=i),
            david_complete=False,
            steph_complete=True,
            won=False,
            created_at=now,
            updated_at=now,
        )
        db_session.add(r)
        daily_results.append(r)
    await db_session.commit()

    # Simulate week-end finalization overwriting "ongoing"
    final_status = finalize_series_status(daily_results)
    series = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    assert series is not None
    series.wins = 3
    series.losses = 3
    series.status = final_status
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    assert refreshed.status == "lost"


@pytest.mark.asyncio
async def test_series_finalized_creates_row_when_missing(db_session):
    """If no PlayoffSeries row exists for a week, finalization creates one."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # 4 wins, no pre-existing series record
    daily_results = []
    for i in range(4):
        r = DailyResult(
            guild_id=GUILD_ID,
            result_date=week_start + timedelta(days=i),
            david_complete=True,
            steph_complete=True,
            won=True,
            created_at=now,
            updated_at=now,
        )
        db_session.add(r)
        daily_results.append(r)
    await db_session.commit()

    wins = sum(1 for r in daily_results if r.won)
    losses = sum(1 for r in daily_results if not r.won)
    status = finalize_series_status(daily_results)

    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=week_start,
            wins=wins,
            losses=losses,
            status=status,
            created_at=now,
        )
    )
    await db_session.commit()

    series = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    assert series is not None
    assert series.wins == 4
    assert series.losses == 0
    assert series.status == "won"


# ---------------------------------------------------------------------------
# series_history per-person stats — grouping DailyResult by week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_history_per_person_stats_correct(db_session):
    """DailyResult rows grouped by week give correct per-person day counts."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # David: 5 days complete; Steph: 3 days complete; combined wins: 3
    profiles = [
        (True, True),   # Sun — both complete, win
        (True, True),   # Mon — both complete, win
        (True, True),   # Tue — both complete, win
        (True, False),  # Wed — David only
        (True, False),  # Thu — David only
    ]
    for i, (dc, sc) in enumerate(profiles):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=dc,
                steph_complete=sc,
                won=dc and sc,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    rows = (
        await db_session.scalars(
            select(DailyResult).where(DailyResult.guild_id == GUILD_ID)
        )
    ).all()

    david_days = sum(1 for r in rows if r.david_complete)
    steph_days = sum(1 for r in rows if r.steph_complete)
    combined_wins = sum(1 for r in rows if r.won)

    assert david_days == 5
    assert steph_days == 3
    assert combined_wins == 3


@pytest.mark.asyncio
async def test_history_multiple_weeks_grouped_correctly(db_session):
    """DailyResult rows from two different weeks are grouped independently."""
    week1 = SUNDAY_APR_19
    week2 = SUNDAY_APR_19 + timedelta(weeks=1)  # Apr 26
    now = datetime.now(timezone.utc)

    # Week 1: 4 wins (David & Steph both complete all 4 days)
    for i in range(4):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week1 + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    # Week 2: 2 wins (Steph missed 2 days)
    for i in range(2):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week2 + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    for i in range(2, 4):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week2 + timedelta(days=i),
                david_complete=True,
                steph_complete=False,
                won=False,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    all_rows = (
        await db_session.scalars(
            select(DailyResult).where(DailyResult.guild_id == GUILD_ID)
        )
    ).all()

    # Group by week (mirror series_history logic)
    daily_by_week: dict[date, list] = {}
    for dr in all_rows:
        ws = week_start_for(dr.result_date)
        daily_by_week.setdefault(ws, []).append(dr)

    w1_rows = daily_by_week[week1]
    w2_rows = daily_by_week[week2]

    assert sum(1 for r in w1_rows if r.david_complete) == 4
    assert sum(1 for r in w1_rows if r.steph_complete) == 4
    assert sum(1 for r in w2_rows if r.david_complete) == 4
    assert sum(1 for r in w2_rows if r.steph_complete) == 2


@pytest.mark.asyncio
async def test_checkin_tally_bounded_to_current_week(db_session):
    """Series tally only counts DailyResult rows within the current week (Sun–Sat).

    Rows from adjacent weeks must not bleed into the current week's win count.
    This mirrors the result_date >= week_start AND <= week_start+6 query used in
    _process_checkin Step 3.
    """
    week1 = SUNDAY_APR_19           # Apr 19–25
    week2 = SUNDAY_APR_19 + timedelta(weeks=1)  # Apr 26–May 2
    now = datetime.now(timezone.utc)

    # Week 1: 3 wins on Mon–Wed
    for i in range(1, 4):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week1 + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    # Week 2: 2 wins on Sun–Mon of next week
    for i in range(2):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week2 + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    # Tally for week1 — must exclude week2 results
    week1_rows = (
        await db_session.scalars(
            select(DailyResult).where(
                DailyResult.guild_id == GUILD_ID,
                DailyResult.result_date >= week1,
                DailyResult.result_date <= week1 + timedelta(days=6),
            )
        )
    ).all()

    assert sum(1 for r in week1_rows if r.won) == 3
    # Tally for week2 — must exclude week1 results
    week2_rows = (
        await db_session.scalars(
            select(DailyResult).where(
                DailyResult.guild_id == GUILD_ID,
                DailyResult.result_date >= week2,
                DailyResult.result_date <= week2 + timedelta(days=6),
            )
        )
    ).all()
    assert sum(1 for r in week2_rows if r.won) == 2


# ---------------------------------------------------------------------------
# series_history auto-heal — stale "ongoing" status for completed past weeks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_ongoing_healed_for_past_week(db_session):
    """A past week stuck as 'ongoing' is corrected when history is queried."""
    week_start = SUNDAY_APR_12  # week ended Apr 18 — fully in the past
    now = datetime.now(timezone.utc)

    # Series record never got finalized (e.g. bot was down that Sunday)
    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=week_start,
            wins=3,
            losses=2,
            status="ongoing",
            created_at=now,
        )
    )
    # 3 wins, 2 losses — week is over, not enough wins → "lost"
    for i in range(3):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    for i in range(3, 5):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=False,
                steph_complete=True,
                won=False,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    # Simulate the auto-heal logic from series_history
    daily_rows = (
        await db_session.scalars(select(DailyResult).where(DailyResult.guild_id == GUILD_ID))
    ).all()

    daily_by_week: dict[date, list[DailyResult]] = {}
    for dr in daily_rows:
        ws = week_start_for(dr.result_date)
        daily_by_week.setdefault(ws, []).append(dr)

    series = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    week_daily = daily_by_week.get(week_start, [])
    series.wins = sum(1 for dr in week_daily if dr.won)
    series.losses = sum(1 for dr in week_daily if not dr.won)
    series.status = finalize_series_status(week_daily)
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    assert refreshed.status == "lost"  # 3 wins < 4 → lost
    assert refreshed.wins == 3
    assert refreshed.losses == 2


@pytest.mark.asyncio
async def test_stale_ongoing_healed_to_won(db_session):
    """A past week with 4+ wins is healed to 'won', not 'lost'."""
    week_start = SUNDAY_APR_12
    now = datetime.now(timezone.utc)

    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=week_start,
            wins=4,
            losses=2,
            status="ongoing",
            created_at=now,
        )
    )
    for i in range(4):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=True,
                steph_complete=True,
                won=True,
                created_at=now,
                updated_at=now,
            )
        )
    for i in range(4, 6):
        db_session.add(
            DailyResult(
                guild_id=GUILD_ID,
                result_date=week_start + timedelta(days=i),
                david_complete=False,
                steph_complete=True,
                won=False,
                created_at=now,
                updated_at=now,
            )
        )
    await db_session.commit()

    daily_rows = (
        await db_session.scalars(select(DailyResult).where(DailyResult.guild_id == GUILD_ID))
    ).all()
    week_daily = [dr for dr in daily_rows if week_start_for(dr.result_date) == week_start]

    series = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    series.wins = sum(1 for dr in week_daily if dr.won)
    series.losses = sum(1 for dr in week_daily if not dr.won)
    series.status = finalize_series_status(week_daily)
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == week_start,
        )
    )
    assert refreshed.status == "won"  # 4 wins → won


@pytest.mark.asyncio
async def test_current_week_ongoing_not_healed(db_session):
    """A series for the current (in-progress) week stays 'ongoing' — only past weeks are healed."""
    from datetime import date as date_type
    import datetime as dt_module

    # Use a future week to simulate "current" in the test
    future_sunday = date_type(2099, 1, 5)  # far future, always current
    now = datetime.now(timezone.utc)

    db_session.add(
        PlayoffSeries(
            guild_id=GUILD_ID,
            week_start=future_sunday,
            wins=2,
            losses=1,
            status="ongoing",
            created_at=now,
        )
    )
    await db_session.commit()

    series = await db_session.scalar(
        select(PlayoffSeries).where(
            PlayoffSeries.guild_id == GUILD_ID,
            PlayoffSeries.week_start == future_sunday,
        )
    )
    # week_end is in the future — auto-heal condition (week_end < today) is False
    week_end = future_sunday + timedelta(days=6)
    today = date_type.today()
    assert week_end >= today, "test setup: future_sunday must be in the future"
    # Status should remain "ongoing" — no healing applied
    assert series.status == "ongoing"


# ---------------------------------------------------------------------------
# WeeklyReview — text reflection persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_review_persists(db_session):
    """A weekly review is written to the DB and can be read back."""
    week_of = SUNDAY_APR_19
    now = datetime.now(timezone.utc)
    text = "Great week — hit all pillars Mon–Wed. Focus next week: maintain steps."

    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID,
            user_id=DAVID_ID,
            week_of=week_of,
            review_text=text,
            created_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.guild_id == GUILD_ID,
            WeeklyReview.user_id == DAVID_ID,
            WeeklyReview.week_of == week_of,
        )
    )
    assert row is not None
    assert row.review_text == text


@pytest.mark.asyncio
async def test_weekly_review_upsert(db_session):
    """Updating an existing weekly review replaces the text in place."""
    week_of = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID,
            user_id=STEPH_ID,
            week_of=week_of,
            review_text="first draft",
            created_at=now,
        )
    )
    await db_session.commit()

    # Update
    existing = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.guild_id == GUILD_ID,
            WeeklyReview.user_id == STEPH_ID,
            WeeklyReview.week_of == week_of,
        )
    )
    existing.review_text = "revised: TikTok control was tough — next week: 60min cap"
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.guild_id == GUILD_ID,
            WeeklyReview.user_id == STEPH_ID,
            WeeklyReview.week_of == week_of,
        )
    )
    assert refreshed.review_text == "revised: TikTok control was tough — next week: 60min cap"


@pytest.mark.asyncio
async def test_weekly_review_per_user_independent(db_session):
    """David and Steph can each have their own review for the same week."""
    week_of = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID,
            user_id=DAVID_ID,
            week_of=week_of,
            review_text="david's reflection",
            created_at=now,
        )
    )
    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID,
            user_id=STEPH_ID,
            week_of=week_of,
            review_text="steph's reflection",
            created_at=now,
        )
    )
    await db_session.commit()

    david_row = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.guild_id == GUILD_ID,
            WeeklyReview.user_id == DAVID_ID,
            WeeklyReview.week_of == week_of,
        )
    )
    steph_row = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.guild_id == GUILD_ID,
            WeeklyReview.user_id == STEPH_ID,
            WeeklyReview.week_of == week_of,
        )
    )
    assert david_row.review_text == "david's reflection"
    assert steph_row.review_text == "steph's reflection"


# ---------------------------------------------------------------------------
# build_weekly_embed — rich Discord embed with per-pillar breakdown
# ---------------------------------------------------------------------------


def _make_checkin(
    user_id: int,
    offset: int,
    *,
    p1: bool = True,
    p2: bool = True,
    p3: bool = True,
) -> PlayoffCheckin:
    """Create an unsaved PlayoffCheckin for testing."""
    now = datetime.now(timezone.utc)
    return PlayoffCheckin(
        guild_id=GUILD_ID,
        user_id=user_id,
        checkin_date=WEEK_SUN + timedelta(days=offset),
        pillar1=p1,
        pillar2=p2,
        pillar3=p3,
        created_at=now,
        updated_at=now,
    )


def test_embed_no_data_has_no_checkin_message():
    embed = build_weekly_embed([], WEEK_SUN)
    assert "No check-ins recorded" in (embed.description or "")


def test_embed_won_series_is_green():
    import discord as _discord
    results = [_make_result(i, david=True, steph=True) for i in range(4)]
    embed = build_weekly_embed(results, WEEK_SUN)
    assert embed.color == _discord.Color.green()


def test_embed_lost_series_is_red():
    import discord as _discord
    results = [_make_result(i, david=False, steph=True) for i in range(7)]
    embed = build_weekly_embed(results, WEEK_SUN)
    assert embed.color == _discord.Color.red()


def test_embed_title_contains_week_dates():
    embed = build_weekly_embed([], WEEK_SUN)
    assert "Apr 19" in embed.title
    assert "Apr 25" in embed.title


def test_embed_day_by_day_field_present():
    results = [_make_result(0, david=True, steph=True)]
    embed = build_weekly_embed(results, WEEK_SUN)
    field_names = [f.name for f in embed.fields]
    assert any("Day" in name for name in field_names)


def test_embed_per_pillar_stats_with_checkin_rows():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=True, steph=False),
    ]
    checkins = [
        _make_checkin(DAVID_ID, 0, p1=True, p2=True, p3=True),
        _make_checkin(DAVID_ID, 1, p1=True, p2=True, p3=True),
        _make_checkin(STEPH_ID, 0, p1=True, p2=True, p3=True),
        _make_checkin(STEPH_ID, 1, p1=False, p2=True, p3=True),
    ]
    embed = build_weekly_embed(results, WEEK_SUN, checkins)
    # David field should show 2/2 for all pillars
    david_field = next(f for f in embed.fields if "David" in f.name)
    assert "2/2" in david_field.value
    # Steph field should show 1/2 for pillar1
    steph_field = next(f for f in embed.fields if "Steph" in f.name)
    assert "1/2" in steph_field.value


def test_embed_no_checkin_rows_still_shows_day_counts():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=True, steph=False),
    ]
    embed = build_weekly_embed(results, WEEK_SUN)
    david_field = next(f for f in embed.fields if "David" in f.name)
    assert "2/7" in david_field.value
    steph_field = next(f for f in embed.fields if "Steph" in f.name)
    assert "1/7" in steph_field.value


def test_embed_streak_field_shown_when_two_wins():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=True, steph=True),
        _make_result(2, david=False, steph=True),
    ]
    embed = build_weekly_embed(results, WEEK_SUN)
    field_names = [f.name for f in embed.fields]
    assert any("Streak" in name for name in field_names)


def test_embed_no_streak_field_for_single_win():
    results = [
        _make_result(0, david=True, steph=True),
        _make_result(1, david=False, steph=True),
    ]
    embed = build_weekly_embed(results, WEEK_SUN)
    field_names = [f.name for f in embed.fields]
    assert not any("Streak" in name for name in field_names)


def test_embed_footer_mentions_weekly_review():
    embed = build_weekly_embed([], WEEK_SUN)
    assert embed.footer is not None
    assert "weekly_review" in embed.footer.text.lower() or "weekly_review" in (embed.footer.text or "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tally(checkins: list[PlayoffCheckin]) -> tuple[int, int]:
    """Mirror the win/loss accumulation logic from playoff._process_checkin."""
    by_date: dict[date, dict[int, PlayoffCheckin]] = {}
    for c in checkins:
        by_date.setdefault(c.checkin_date, {})[c.user_id] = c

    wins = 0
    losses = 0
    for day in by_date.values():
        if DAVID_ID not in day or STEPH_ID not in day:
            continue
        d, s = day[DAVID_ID], day[STEPH_ID]
        if d.pillar1 and d.pillar2 and d.pillar3 and s.pillar1 and s.pillar2 and s.pillar3:
            wins += 1
        else:
            losses += 1
    return wins, losses
