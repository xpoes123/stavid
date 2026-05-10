"""Shared helpers for inbox cogs."""
from __future__ import annotations

import datetime as _dt
import logging
import re
from datetime import datetime, timezone

import discord

# David + Stephanie's apartment guild — only routes messages from here
APARTMENT_GUILD_ID = 1401585357799292958

# Channels that should never be touched by inbox routing
RESERVED_CHANNELS = {"general", "dev", "dev2"}

OK = "✅"
WARN = "⚠️"

log = logging.getLogger(__name__)


class ParseError(Exception):
    """Raised by inbox parsers when the message can't be turned into a row."""


def is_routable(message: discord.Message, channel_name: str) -> bool:
    """True when the message is a real, in-guild message in the named channel."""
    if message.author.bot:
        return False
    if message.guild is None or message.guild.id != APARTMENT_GUILD_ID:
        return False
    chan = message.channel
    name = getattr(chan, "name", None)
    if name is None or name in RESERVED_CHANNELS:
        return False
    return name == channel_name


async def react_ok(message: discord.Message) -> None:
    try:
        await message.add_reaction(OK)
    except discord.HTTPException:
        log.exception("failed to add ok reaction in #%s", getattr(message.channel, "name", "?"))


async def react_warn(message: discord.Message) -> None:
    try:
        await message.add_reaction(WARN)
    except discord.HTTPException:
        log.exception("failed to add warn reaction in #%s", getattr(message.channel, "name", "?"))


# --- URL / money / date parsers ----------------------------------------------

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MONEY_RE = re.compile(r"\$?\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)\b")


def first_url(text: str) -> str | None:
    m = _URL_RE.search(text)
    return m.group(0).rstrip(".,;:)") if m else None


def parse_dollars_cents(text: str) -> int | None:
    """Extract the first dollar amount in ``text`` and return it in cents.

    Handles ``$23.50``, ``23.50``, ``$1,200``. Returns None if nothing found.
    """
    m = _MONEY_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        amount = float(raw)
    except ValueError:
        return None
    return int(round(amount * 100))


# --- "when" parser, lifted from sage/cogs/remind.py and adapted -------------

_UNIT_SECONDS: dict[str, int] = {
    "s": 1, "sec": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
}

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# Tokens that prefix a "when" segment in a free-form message
_IN_PREFIX_RE = re.compile(r"\bin\b", re.IGNORECASE)


def parse_when(when: str) -> datetime | None:
    """Parse a human time string into an aware UTC datetime, or None.

    Handles relative offsets (``2h``, ``in 30 minutes``) and natural phrases
    (``tomorrow``, ``tomorrow at 9am``, ``friday 3pm``, ``next week``).
    """
    now = datetime.now(timezone.utc)
    text = when.strip().lower()
    if not text:
        return None

    m = re.fullmatch(r"(?:in\s+)?(\d+)\s*([a-z]+)", text)
    if m:
        num, unit = int(m.group(1)), m.group(2)
        if unit in _UNIT_SECONDS:
            return now + _dt.timedelta(seconds=num * _UNIT_SECONDS[unit])

    time_hour, time_minute = 9, 0
    time_match = re.search(r"(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text)
    consumed_time = False
    if time_match:
        h = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = time_match.group(3)
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and (ampm or "tomorrow" in text or "today" in text or any(d in text for d in _DAY_NAMES)):
            time_hour, time_minute = h, minute
            text = (text[: time_match.start()] + text[time_match.end():]).strip()
            consumed_time = True

    base_date: _dt.date | None = None
    if "tomorrow" in text:
        base_date = now.date() + _dt.timedelta(days=1)
    elif "today" in text:
        base_date = now.date()
    elif "next week" in text:
        base_date = now.date() + _dt.timedelta(days=7)
    else:
        for i, day in enumerate(_DAY_NAMES):
            if day in text:
                days_ahead = (i - now.weekday()) % 7 or 7
                base_date = now.date() + _dt.timedelta(days=days_ahead)
                break

    if base_date is None:
        return None

    naive = datetime.combine(base_date, _dt.time(time_hour, time_minute))
    return naive.replace(tzinfo=timezone.utc)


def split_when_phrase(text: str) -> tuple[str, str] | None:
    """Split ``"<note> in <when>"`` into (note, when), or return None.

    Examples::
        "buy milk in 2h" -> ("buy milk", "2h")
        "call mom tomorrow at 9am" -> ("call mom", "tomorrow at 9am")
        "remind me about taxes friday" -> ("remind me about taxes", "friday")
    """
    text = text.strip()
    if not text:
        return None

    # 1. Try the explicit "<note> in <when>" form.
    for m in _IN_PREFIX_RE.finditer(text):
        candidate = text[m.end():].strip()
        when = parse_when(candidate)
        if when is not None:
            note = text[: m.start()].strip().rstrip(",")
            if note:
                return note, candidate

    # 2. Try natural phrases: scan for a known anchor and split around it.
    anchors = ["tomorrow", "today", "next week", *_DAY_NAMES]
    lowered = text.lower()
    for anchor in anchors:
        idx = lowered.find(anchor)
        if idx == -1:
            continue
        # Take the rest of the string from the anchor as the "when" clause.
        when_str = text[idx:].strip()
        if parse_when(when_str) is not None:
            note = text[:idx].strip().rstrip(",")
            if note:
                return note, when_str

    return None
