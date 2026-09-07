"""SimpleFIN pull, card-agnostic. Amounts are strings -> Decimal -> int cents.

Every connected credit card is a spend source (David churns cards, so nothing
is hardcoded to one account). Balance payments are dropped deterministically
before classification; everything else gets a money-type from `classify`.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo
import datetime as dt
import re

import aiohttp

ET = ZoneInfo("America/New_York")

# A card balance payment is positive but not spend — must never credit the pool.
# Refunds are positive too and DO stay. ponytail: description heuristic; add a
# txn-id allowlist if a real refund ever matches.
_CARD_PAYMENT = re.compile(
    r"AUTOPAY|PAYMENT THANK YOU|ONLINE PAYMENT|MOBILE PAYMENT|\bPYMT\b|E-?PAYMENT"
    r"|PAYMENT TO CHASE|CARD PAYMENT", re.I)


@dataclass
class Txn:
    simplefin_id: str
    account_id: str
    date: dt.date          # posted date in ET
    cents: int             # signed: purchases negative, credits positive
    description: str
    pending: bool

    @property
    def spend_cents(self) -> int:
        """Spend-positive: a -$38.20 purchase is +3820 of spend."""
        return -self.cents


def _to_cents(amount: str) -> int:
    return int((Decimal(str(amount)) * 100).to_integral_value())


def _et_date(secs) -> dt.date:
    return dt.datetime.fromtimestamp(int(secs), tz=dt.timezone.utc).astimezone(ET).date()


def parse_accounts(payload: dict) -> list[Txn]:
    """Pure: SimpleFIN /accounts JSON -> deduped Txn list (testable, no network)."""
    by_id: dict[str, Txn] = {}
    for acct in payload.get("accounts", []):
        for t in acct.get("transactions", []):
            txn = Txn(
                simplefin_id=t["id"], account_id=acct["id"],
                date=_et_date(t.get("posted") or t.get("transacted_at")),
                cents=_to_cents(t["amount"]), description=t.get("description", ""),
                pending=bool(t.get("pending", False)))
            by_id[txn.simplefin_id] = txn          # pendings mutate; update in place
    return list(by_id.values())


async def fetch(access_url: str, account_ids: list[str], lookback_days: int) -> list[Txn]:
    """Pull `lookback_days` back, pending included, deduped/updated by id (§4.1)."""
    start = int((dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=lookback_days)).timestamp())
    params = [("start-date", str(start)), ("pending", "1")]
    params += [("account", a) for a in account_ids]
    async with aiohttp.ClientSession() as sess:
        async with sess.get(f"{access_url}/accounts", params=params,
                            timeout=aiohttp.ClientTimeout(total=60)) as resp:
            resp.raise_for_status()
            return parse_accounts(await resp.json())


def is_card_payment(t: Txn) -> bool:
    return bool(_CARD_PAYMENT.search(t.description))


def spendable(txns: list[Txn], card_ids: set[str]) -> list[Txn]:
    """Card transactions that represent real spend (balance payments dropped)."""
    return [t for t in txns if t.account_id in card_ids and not is_card_payment(t)]


async def discover_accounts(access_url: str) -> list[dict]:
    """List accounts with a card/checking guess (negative balance => credit card)."""
    async with aiohttp.ClientSession() as sess:
        async with sess.get(f"{access_url}/accounts", params={"balances-only": "1"},
                            timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()
    out = []
    for a in data.get("accounts", []):
        bal = Decimal(str(a.get("balance", "0")))
        out.append({"id": a["id"], "name": a.get("name", "?"),
                    "org": a.get("org", {}).get("name", "?"),
                    "kind": "card" if bal < 0 else "checking"})
    return out
