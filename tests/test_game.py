"""Budget Game pure logic — money-type gating, pace/streak, parsing. Offline."""
import datetime as dt

from src.game.core import (SpendItem, allowance_cents, cumulative_to,
                           score_day, variable_by_day)
from src.game.simplefin import Txn, is_card_payment, parse_accounts, spendable
from src.game.classify import parse_response, normalize


def _item(day, cents, mt="Variable"):
    return SpendItem(date=day, cents=cents, money_type=mt, category="X")


# ── core: only Variable counts ───────────────────────────────────────────────

def test_only_variable_counts():
    d = dt.date(2026, 9, 10)
    items = [_item(d, 4000, "Variable"), _item(d, 90000, "Fixed"),
             _item(d, 60000, "Sinking")]
    by = variable_by_day(items)
    assert by == {d: 4000}                       # fixed rent + sinking flight excluded


def test_prorated_allowance():
    # Day 15 of a 30-day month at $1200 cap -> $600.00.
    assert allowance_cents(dt.date(2026, 9, 15), 120000) == 60000


def test_streak_increments_on_pace():
    d = dt.date(2026, 9, 10)                       # allowance 120000*10/30 = 40000
    score, f = score_day(d, {d: 30000}, cap_cents=120000, streak=5,
                         freezes_remaining=1, freeze_month="2026-09",
                         last_scored=None, freezes_per_month=1, shadow=False)
    assert score.on_pace and f["streak"] == 6


def test_freeze_then_break():
    d = dt.date(2026, 9, 10)
    s1, f = score_day(d, {d: 90000}, cap_cents=120000, streak=5,
                      freezes_remaining=1, freeze_month="2026-09", last_scored=None,
                      freezes_per_month=1, shadow=False)
    assert s1.froze and f["streak"] == 6 and f["freezes_remaining"] == 0
    d2 = dt.date(2026, 9, 11)
    s2, f2 = score_day(d2, {d2: 90000, d: 90000}, cap_cents=120000, streak=f["streak"],
                       freezes_remaining=f["freezes_remaining"], freeze_month="2026-09",
                       last_scored=f["last_scored"], freezes_per_month=1, shadow=False)
    assert not s2.froze and f2["streak"] == 0


def test_shadow_no_accrual():
    d = dt.date(2026, 9, 3)
    _, f = score_day(d, {d: 5000}, cap_cents=120000, streak=0, freezes_remaining=1,
                     freeze_month="2026-09", last_scored=None, freezes_per_month=1,
                     shadow=True)
    assert f["streak"] == 0 and f["last_scored"] is None


def test_scoring_idempotent():
    d = dt.date(2026, 9, 10)
    _, f = score_day(d, {d: 10000}, cap_cents=120000, streak=5, freezes_remaining=1,
                     freeze_month="2026-09", last_scored=None, freezes_per_month=1,
                     shadow=False)
    _, f2 = score_day(d, {d: 10000}, cap_cents=120000, streak=f["streak"],
                      freezes_remaining=f["freezes_remaining"], freeze_month="2026-09",
                      last_scored=f["last_scored"], freezes_per_month=1, shadow=False)
    assert f2["streak"] == 6                        # not 7


# ── simplefin: sign + payment exclusion + dedupe ─────────────────────────────

def test_card_payment_excluded_refund_kept():
    payload = {"accounts": [{"id": "C", "transactions": [
        {"id": "1", "posted": 1756000000, "amount": "-38.20", "description": "CHIPOTLE"},
        {"id": "2", "posted": 1756000000, "amount": "500.00", "description": "AUTOPAY PAYMENT THANK YOU"},
        {"id": "3", "posted": 1756000000, "amount": "12.00", "description": "MERCHANT REFUND"},
    ]}]}
    txns = parse_accounts(payload)
    assert len(txns) == 3 and all(isinstance(t.cents, int) for t in txns)
    sp = spendable(txns, {"C"})
    assert {t.simplefin_id for t in sp} == {"1", "3"}          # payment dropped
    assert sum(t.spend_cents for t in sp) == 3820 - 1200       # +purchase -refund


def test_dedupe_by_id_keeps_latest():
    payload = {"accounts": [{"id": "C", "transactions": [
        {"id": "9", "posted": 1756000000, "amount": "-10.00", "description": "auth"},
        {"id": "9", "posted": 1756000000, "amount": "-12.50", "description": "settled+tip"},
    ]}]}
    txns = parse_accounts(payload)
    assert len(txns) == 1 and txns[0].cents == -1250            # mutated pending updated


def test_payment_pattern():
    assert is_card_payment(Txn("x", "C", dt.date(2026, 9, 1), 5000, "Payment to Chase card ending 9400", False))
    assert not is_card_payment(Txn("x", "C", dt.date(2026, 9, 1), -5000, "TRADER JOES", False))


# ── classify: parsing + money_type gate ──────────────────────────────────────

def test_parse_response_defaults_bad_to_review():
    by = {"a": Txn("a", "C", dt.date(2026, 9, 1), -1000, "X", False),
          "b": Txn("b", "C", dt.date(2026, 9, 1), -2000, "Y", False)}
    text = '{"results":[{"id":"a","category":"Dining","money_type":"Variable","confidence":0.95}]}'
    cs = parse_response(text, by)
    a = next(c for c in cs if c.txn.simplefin_id == "a")
    b = next(c for c in cs if c.txn.simplefin_id == "b")   # missing from model output
    assert a.category == "Dining" and not a.needs_review
    assert b.confidence == 0.0 and b.needs_review          # unclassified -> ask-queue


def test_normalize_strips_numbers():
    assert normalize("CHILIS MADISON #1720") == "CHILIS MADISON"


if __name__ == "__main__":
    import sys
    mod = sys.modules[__name__]
    for n in dir(mod):
        if n.startswith("test_"):
            getattr(mod, n)()
    print("budget game core: all pass ✅")
