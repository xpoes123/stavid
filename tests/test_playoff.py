"""Tests for individual-scoring playoff logic."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.cogs.playoff import (
    DEFAULT_PILLARS,
    WIN_THRESHOLD,
    build_user_week_lines,
    build_user_weekly_embed,
    finalize_user_status,
    format_user_weekly_summary,
    get_pillar_names,
    is_full_day_win,
    series_message,
    tally_user_week,
    week_start_for,
)
from src.db import PlayoffCheckin, WeeklyReview
from src.utils import DAVID_ID, STEPH_ID

GUILD_ID = 999_000_000_000_000_000
SUNDAY_APR_19 = date(2026, 4, 19)
SUNDAY_APR_12 = date(2026, 4, 12)


def _make_checkin(
    user_id: int,
    offset: int,
    *,
    p1: bool = True,
    p2: bool = True,
    p3: bool = True,
    week_start: date = SUNDAY_APR_19,
) -> PlayoffCheckin:
    """Create an unsaved PlayoffCheckin for testing."""
    now = datetime.now(timezone.utc)
    return PlayoffCheckin(
        guild_id=GUILD_ID,
        user_id=user_id,
        checkin_date=week_start + timedelta(days=offset),
        pillar1=p1,
        pillar2=p2,
        pillar3=p3,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# week_start_for
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("offset", range(7))
def test_week_start_for_all_days(offset):
    day = SUNDAY_APR_19 + timedelta(days=offset)
    assert week_start_for(day) == SUNDAY_APR_19


def test_week_start_for_sunday_is_itself():
    assert week_start_for(SUNDAY_APR_19) == SUNDAY_APR_19


def test_week_start_for_crosses_month():
    tue_mar_31 = date(2026, 3, 31)
    assert week_start_for(tue_mar_31) == date(2026, 3, 29)


# ---------------------------------------------------------------------------
# Pillar names
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
    assert get_pillar_names(0) == DEFAULT_PILLARS


# ---------------------------------------------------------------------------
# is_full_day_win — individual win condition
# ---------------------------------------------------------------------------


def test_full_day_win_requires_all_three_pillars():
    assert is_full_day_win(_make_checkin(DAVID_ID, 0, p1=True, p2=True, p3=True))
    assert not is_full_day_win(_make_checkin(DAVID_ID, 0, p1=True, p2=True, p3=False))
    assert not is_full_day_win(_make_checkin(DAVID_ID, 0, p1=False, p2=False, p3=False))


# ---------------------------------------------------------------------------
# tally_user_week — individual W/L
# ---------------------------------------------------------------------------


def test_tally_empty_week():
    assert tally_user_week([]) == (0, 0)


def test_tally_only_counts_logged_days():
    """Days without check-in rows are neither W nor L — only logged days count."""
    checkins = [
        _make_checkin(DAVID_ID, 0, p1=True, p2=True, p3=True),  # win
        _make_checkin(DAVID_ID, 1, p1=True, p2=False, p3=True),  # loss
    ]
    assert tally_user_week(checkins) == (1, 1)


def test_tally_full_week_all_wins():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(7)]
    assert tally_user_week(checkins) == (7, 0)


def test_tally_partner_independent():
    """David and Stephanie's tallies don't interfere — caller filters by user_id."""
    david_checkins = [_make_checkin(DAVID_ID, i) for i in range(5)]
    assert tally_user_week(david_checkins) == (5, 0)


# ---------------------------------------------------------------------------
# finalize_user_status
# ---------------------------------------------------------------------------


def test_status_won_at_threshold():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(WIN_THRESHOLD)]
    assert finalize_user_status(checkins) == "won"


def test_status_lost_below_threshold():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(WIN_THRESHOLD - 1)]
    assert finalize_user_status(checkins) == "lost"


def test_status_lost_on_empty():
    assert finalize_user_status([]) == "lost"


def test_status_won_with_extra_wins():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(7)]
    assert finalize_user_status(checkins) == "won"


def test_status_user_can_win_independently_of_partner():
    """David's status is computed only from David's check-ins."""
    david_checkins = [_make_checkin(DAVID_ID, i) for i in range(WIN_THRESHOLD)]
    # Steph data totally absent — David should still be 'won'
    assert finalize_user_status(david_checkins) == "won"


# ---------------------------------------------------------------------------
# series_message
# ---------------------------------------------------------------------------


def test_series_message_won():
    assert "Won" in series_message(WIN_THRESHOLD, 0)


def test_series_message_lost():
    assert "lost" in series_message(0, WIN_THRESHOLD).lower()


def test_series_message_fresh_week():
    msg = series_message(0, 0)
    assert "Fresh" in msg or "fresh" in msg


def test_series_message_close_still_alive():
    msg = series_message(0, 3)
    assert "alive" in msg.lower()


def test_series_message_ahead():
    msg = series_message(3, 1)
    assert "momentum" in msg.lower() or "keep" in msg.lower()


# ---------------------------------------------------------------------------
# DB persistence — PlayoffCheckin
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_checkin_is_persisted(db_session):
    today = SUNDAY_APR_19 + timedelta(days=2)
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
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    assert row is not None
    assert row.pillar1 is True
    assert row.pillar3 is False


@pytest.mark.asyncio
async def test_checkin_upsert_updates_values(db_session):
    today = SUNDAY_APR_19 + timedelta(days=2)
    now = datetime.now(timezone.utc)

    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID, checkin_date=today,
            pillar1=False, pillar2=False, pillar3=False,
            created_at=now, updated_at=now,
        )
    )
    await db_session.commit()

    existing = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    existing.pillar1 = True
    existing.pillar2 = True
    existing.pillar3 = True
    await db_session.commit()

    refreshed = await db_session.scalar(
        select(PlayoffCheckin).where(
            PlayoffCheckin.user_id == DAVID_ID,
            PlayoffCheckin.checkin_date == today,
        )
    )
    assert refreshed.pillar1 is True
    assert refreshed.pillar2 is True
    assert refreshed.pillar3 is True


@pytest.mark.asyncio
async def test_individual_tally_from_persisted_rows(db_session):
    """David's W/L computed from his own rows, ignoring Steph entirely."""
    week_start = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    # David: 4 wins, 1 loss
    for i in range(4):
        db_session.add(
            PlayoffCheckin(
                guild_id=GUILD_ID, user_id=DAVID_ID,
                checkin_date=week_start + timedelta(days=i),
                pillar1=True, pillar2=True, pillar3=True,
                created_at=now, updated_at=now,
            )
        )
    db_session.add(
        PlayoffCheckin(
            guild_id=GUILD_ID, user_id=DAVID_ID,
            checkin_date=week_start + timedelta(days=4),
            pillar1=True, pillar2=False, pillar3=True,
            created_at=now, updated_at=now,
        )
    )
    # Steph: only 2 wins — should NOT affect David's count
    for i in range(2):
        db_session.add(
            PlayoffCheckin(
                guild_id=GUILD_ID, user_id=STEPH_ID,
                checkin_date=week_start + timedelta(days=i),
                pillar1=True, pillar2=True, pillar3=True,
                created_at=now, updated_at=now,
            )
        )
    await db_session.commit()

    david_rows = (
        await db_session.scalars(
            select(PlayoffCheckin).where(
                PlayoffCheckin.guild_id == GUILD_ID,
                PlayoffCheckin.user_id == DAVID_ID,
                PlayoffCheckin.checkin_date >= week_start,
                PlayoffCheckin.checkin_date <= week_start + timedelta(days=6),
            )
        )
    ).all()
    steph_rows = (
        await db_session.scalars(
            select(PlayoffCheckin).where(
                PlayoffCheckin.guild_id == GUILD_ID,
                PlayoffCheckin.user_id == STEPH_ID,
                PlayoffCheckin.checkin_date >= week_start,
                PlayoffCheckin.checkin_date <= week_start + timedelta(days=6),
            )
        )
    ).all()

    assert tally_user_week(list(david_rows)) == (4, 1)
    assert tally_user_week(list(steph_rows)) == (2, 0)
    assert finalize_user_status(list(david_rows)) == "won"
    assert finalize_user_status(list(steph_rows)) == "lost"


# ---------------------------------------------------------------------------
# build_user_week_lines
# ---------------------------------------------------------------------------


def test_week_lines_dash_for_missing_days():
    checkins = [_make_checkin(DAVID_ID, 0)]  # only Sunday logged
    lines, seq = build_user_week_lines(checkins, SUNDAY_APR_19)
    assert len(lines) == 7
    assert "—" in lines[1]  # Mon is missing
    assert seq == [True, False, False, False, False, False, False]


def test_week_lines_show_misses_count():
    """A loss day should show how many pillars were missed."""
    checkins = [_make_checkin(DAVID_ID, 0, p1=True, p2=False, p3=False)]
    lines, _ = build_user_week_lines(checkins, SUNDAY_APR_19)
    assert "2 pillars missed" in lines[0]


def test_week_lines_full_week():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(7)]
    lines, seq = build_user_week_lines(checkins, SUNDAY_APR_19)
    assert all(s for s in seq)
    assert all("🏆" in line for line in lines)


# ---------------------------------------------------------------------------
# build_user_weekly_embed
# ---------------------------------------------------------------------------


def test_embed_won_is_green():
    import discord
    checkins = [_make_checkin(DAVID_ID, i) for i in range(WIN_THRESHOLD)]
    embed = build_user_weekly_embed(DAVID_ID, checkins, SUNDAY_APR_19)
    assert embed.color == discord.Color.green()


def test_embed_lost_is_red():
    import discord
    checkins = [_make_checkin(DAVID_ID, i, p3=False) for i in range(7)]
    embed = build_user_weekly_embed(DAVID_ID, checkins, SUNDAY_APR_19)
    assert embed.color == discord.Color.red()


def test_embed_empty_week_grey():
    import discord
    embed = build_user_weekly_embed(DAVID_ID, [], SUNDAY_APR_19)
    assert embed.color == discord.Color.greyple()
    assert "No check-ins" in (embed.description or "")


def test_embed_title_has_user_label():
    embed = build_user_weekly_embed(DAVID_ID, [], SUNDAY_APR_19)
    assert "David" in embed.title


def test_embed_title_has_week_dates():
    embed = build_user_weekly_embed(DAVID_ID, [], SUNDAY_APR_19)
    assert "Apr 19" in embed.title
    assert "Apr 25" in embed.title


def test_embed_per_pillar_breakdown():
    checkins = [
        _make_checkin(DAVID_ID, 0, p1=True, p2=True, p3=True),
        _make_checkin(DAVID_ID, 1, p1=True, p2=True, p3=True),
        _make_checkin(DAVID_ID, 2, p1=False, p2=True, p3=True),
    ]
    embed = build_user_weekly_embed(DAVID_ID, checkins, SUNDAY_APR_19)
    pillar_field = next((f for f in embed.fields if "Pillar" in f.name), None)
    assert pillar_field is not None
    assert "2/3" in pillar_field.value  # pillar1 hit 2/3 days
    assert "3/3" in pillar_field.value  # pillar2 and pillar3 hit 3/3


def test_embed_streak_field_when_two_or_more():
    checkins = [
        _make_checkin(DAVID_ID, 0),
        _make_checkin(DAVID_ID, 1),
        _make_checkin(DAVID_ID, 2, p1=False),
    ]
    embed = build_user_weekly_embed(DAVID_ID, checkins, SUNDAY_APR_19)
    field_names = [f.name for f in embed.fields]
    assert any("Streak" in n for n in field_names)


def test_embed_no_streak_for_single_win():
    checkins = [
        _make_checkin(DAVID_ID, 0),
        _make_checkin(DAVID_ID, 1, p1=False),
    ]
    embed = build_user_weekly_embed(DAVID_ID, checkins, SUNDAY_APR_19)
    field_names = [f.name for f in embed.fields]
    assert not any("Streak" in n for n in field_names)


def test_embed_streak_uses_longest_not_last():
    """Streak should be the longest run of wins, not just the trailing one."""
    checkins = [
        _make_checkin(DAVID_ID, 0),  # win
        _make_checkin(DAVID_ID, 1),  # win
        _make_checkin(DAVID_ID, 2),  # win — streak=3
        _make_checkin(DAVID_ID, 3, p1=False),  # loss
        _make_checkin(DAVID_ID, 4),  # win — streak=1
    ]
    embed = build_user_weekly_embed(DAVID_ID, checkins, SUNDAY_APR_19)
    streak_field = next((f for f in embed.fields if "Streak" in f.name), None)
    assert streak_field is not None
    assert "3" in streak_field.value


# ---------------------------------------------------------------------------
# format_user_weekly_summary (text)
# ---------------------------------------------------------------------------


def test_summary_no_data_shows_no_checkins():
    msg = format_user_weekly_summary(DAVID_ID, [], SUNDAY_APR_19)
    assert "No check-ins recorded" in msg


def test_summary_under_discord_limit():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(7)]
    msg = format_user_weekly_summary(DAVID_ID, checkins, SUNDAY_APR_19)
    assert len(msg) <= 2000


def test_summary_includes_user_label():
    msg = format_user_weekly_summary(DAVID_ID, [], SUNDAY_APR_19)
    assert "David" in msg


def test_summary_won_count_correct():
    checkins = [_make_checkin(DAVID_ID, i) for i in range(WIN_THRESHOLD)]
    msg = format_user_weekly_summary(DAVID_ID, checkins, SUNDAY_APR_19)
    assert f"{WIN_THRESHOLD}–0" in msg
    assert "won" in msg.lower()


# ---------------------------------------------------------------------------
# WeeklyReview persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_review_persists(db_session):
    week_of = SUNDAY_APR_19
    now = datetime.now(timezone.utc)
    text = "Great week — focus next week: maintain steps."

    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID, user_id=DAVID_ID, week_of=week_of,
            review_text=text, created_at=now,
        )
    )
    await db_session.commit()

    row = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.user_id == DAVID_ID,
            WeeklyReview.week_of == week_of,
        )
    )
    assert row is not None
    assert row.review_text == text


@pytest.mark.asyncio
async def test_weekly_review_per_user_independent(db_session):
    week_of = SUNDAY_APR_19
    now = datetime.now(timezone.utc)

    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID, user_id=DAVID_ID, week_of=week_of,
            review_text="david's", created_at=now,
        )
    )
    db_session.add(
        WeeklyReview(
            guild_id=GUILD_ID, user_id=STEPH_ID, week_of=week_of,
            review_text="steph's", created_at=now,
        )
    )
    await db_session.commit()

    david_row = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.user_id == DAVID_ID, WeeklyReview.week_of == week_of,
        )
    )
    steph_row = await db_session.scalar(
        select(WeeklyReview).where(
            WeeklyReview.user_id == STEPH_ID, WeeklyReview.week_of == week_of,
        )
    )
    assert david_row.review_text == "david's"
    assert steph_row.review_text == "steph's"
