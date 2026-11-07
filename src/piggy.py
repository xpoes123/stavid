"""Piggy (the finance app) owns the household ledger. Stavid's /venmo, /pay,
/paid, /ledger and #bills read and write it over Piggy's local HTTP API, acting
as whoever sent the message (X-Piggy-User).

Env: PIGGY_API_TOKEN (Piggy's FINANCE_API_TOKEN), PIGGY_URL (default local).
"""
from __future__ import annotations

import os

import aiohttp

from src.utils import DAVID_ID, STEPH_ID

HANDLES = {DAVID_ID: "david", STEPH_ID: "steph"}


class PiggyError(Exception):
    pass


async def _call(method: str, path: str, as_id: int, json: dict | None = None) -> dict:
    handle = HANDLES.get(as_id)
    if handle is None:
        raise PiggyError("only David and Steph have a ledger")
    url = os.getenv("PIGGY_URL", "http://127.0.0.1:7794").rstrip("/") + path
    headers = {"Authorization": f"Bearer {os.getenv('PIGGY_API_TOKEN', '')}", "X-Piggy-User": handle}
    async with aiohttp.ClientSession() as s:
        async with s.request(method, url, headers=headers, json=json,
                             timeout=aiohttp.ClientTimeout(total=15)) as r:
            if r.status >= 300:
                raise PiggyError(f"Piggy {method} {path} -> {r.status}")
            return await r.json()


async def add(creditor_id: int, cents: int, note: str, payment: bool = False) -> None:
    """`creditor_id` is owed `cents` by their partner (or, payment=True, just paid them)."""
    await _call("POST", "/api/v1/ledger", creditor_id,
                {"amount_cents": cents, "direction": "i_paid" if payment else "they_owe",
                 "note": note[:200]})


async def balance(me_id: int) -> int:
    """+ = partner owes me."""
    return int((await _call("GET", "/api/v1/ledger?limit=1", me_id))["balance_cents"])


async def entries(me_id: int, limit: int = 25) -> list[dict]:
    return (await _call("GET", f"/api/v1/ledger?limit={limit}", me_id))["entries"]


async def settle(me_id: int) -> int:
    """Post the payment that zeroes the balance. Returns the cleared cents (0 = already square)."""
    net = await balance(me_id)
    if net:
        # They owe me -> they paid me; I owe them -> I paid them.
        await _call("POST", "/api/v1/ledger", me_id,
                    {"amount_cents": abs(net), "direction": "they_paid" if net > 0 else "i_paid",
                     "note": "settled up"})
    return abs(net)
