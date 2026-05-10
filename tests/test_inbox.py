"""Tests for inbox cog parsers (no Discord interaction — pure parsing)."""
from __future__ import annotations

import pytest

from src.cogs.inbox._utils import (
    first_url,
    parse_dollars_cents,
    parse_when,
    split_when_phrase,
)
from src.cogs.inbox.bills import author_is_debtor


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------


def test_first_url_https():
    assert first_url("check out https://example.com cool") == "https://example.com"


def test_first_url_strips_trailing_punct():
    assert first_url("(see https://example.com).") == "https://example.com"


def test_first_url_none():
    assert first_url("no link here") is None


def test_first_url_amazon():
    url = "https://www.amazon.com/dp/B0123/ref=foo"
    assert first_url(f"want this: {url}") == url


# ---------------------------------------------------------------------------
# Money parser
# ---------------------------------------------------------------------------


def test_dollars_with_dollar_sign():
    assert parse_dollars_cents("$23.50 dinner") == 2350


def test_dollars_without_dollar_sign():
    assert parse_dollars_cents("rent 1500") == 150000


def test_dollars_with_thousand_sep():
    assert parse_dollars_cents("$1,200 rent") == 120000


def test_dollars_no_match():
    assert parse_dollars_cents("no money here") is None


def test_dollars_first_match_wins():
    assert parse_dollars_cents("$10 plus $20") == 1000


def test_dollars_decimal_one_digit():
    assert parse_dollars_cents("$0.5") == 50


# ---------------------------------------------------------------------------
# parse_when (relative + natural)
# ---------------------------------------------------------------------------


def test_parse_when_relative_minutes():
    dt = parse_when("30m")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_when_relative_hours():
    dt = parse_when("2h")
    assert dt is not None


def test_parse_when_in_minutes():
    assert parse_when("in 30 minutes") is not None


def test_parse_when_tomorrow():
    assert parse_when("tomorrow") is not None


def test_parse_when_tomorrow_at():
    dt = parse_when("tomorrow at 9am")
    assert dt is not None
    assert dt.hour == 9


def test_parse_when_friday():
    assert parse_when("friday") is not None


def test_parse_when_garbage():
    assert parse_when("blah blah") is None


def test_parse_when_empty():
    assert parse_when("") is None


# ---------------------------------------------------------------------------
# split_when_phrase
# ---------------------------------------------------------------------------


def test_split_when_in_form():
    assert split_when_phrase("buy milk in 2h") == ("buy milk", "2h")


def test_split_when_in_minutes():
    assert split_when_phrase("call mom in 30 minutes") == ("call mom", "30 minutes")


def test_split_when_tomorrow():
    note, when = split_when_phrase("call mom tomorrow at 9am")
    assert note == "call mom"
    assert "tomorrow" in when


def test_split_when_no_when_returns_none():
    assert split_when_phrase("just a regular note") is None


def test_split_when_friday():
    note, when = split_when_phrase("pay rent friday")
    assert note == "pay rent"
    assert "friday" in when


def test_split_when_strips_trailing_comma():
    note, _ = split_when_phrase("buy milk, in 2h")
    assert note == "buy milk"


def test_split_when_empty():
    assert split_when_phrase("") is None


def test_split_when_in_alone_no_match():
    """``in`` without a parseable phrase after it is not a valid split."""
    assert split_when_phrase("believe in yourself") is None


# ---------------------------------------------------------------------------
# bills.author_is_debtor — direction detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "I paid stephanie 95.4",
        "i paid steph 30 for dinner",
        "I owe steph 50",
        "i owe david 15 for the bill",
        "I gave david 25 for groceries",
        "i gave steph 12.5",
        "paid stephanie 30",
        "paid david 100 — rent share",
        "owe stephanie 20",
        "owe david 75",
        "gave steph 12.5",
        "gave david 60 split",
    ],
)
def test_bills_flip_when_author_is_debtor(msg):
    """Leading 'I paid/I owe/I gave/paid X/owe X/gave X' should flip direction."""
    assert author_is_debtor(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "$95.40 flowers",
        "stephanie owes me 95.4",
        "Stephanie owes me 30",
        "100 for rent",
        "david owes me 50 for utilities",
        "$25 dinner",
        "60 split netflix",
        "rent 1500 due 2026-06-01",
        "groceries 87.32",
        "  $12 coffee",
    ],
)
def test_bills_default_when_author_is_creditor(msg):
    """Phrases without a flip prefix keep the default (author = creditor)."""
    assert author_is_debtor(msg) is False


def test_bills_flip_case_insensitive():
    assert author_is_debtor("I PAID stephanie 95.4") is True
    assert author_is_debtor("Owe Stephanie 30") is True


def test_bills_flip_requires_target_after_paid():
    """Bare 'paid' or 'owe' with nothing after is not a flip — too ambiguous."""
    assert author_is_debtor("paid") is False
    assert author_is_debtor("owe") is False
    assert author_is_debtor("gave") is False


def test_bills_flip_only_at_message_start():
    """A flip phrase later in the message must not flip direction."""
    assert author_is_debtor("dinner — I paid for it last time") is False
    assert author_is_debtor("flowers, I owe you nothing") is False
