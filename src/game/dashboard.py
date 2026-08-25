"""finance.djiang.xyz dashboard — serves the Budget Game template from the DB.

Reuses the same HTML the design preview used (`dashboard.html`); this module
just computes the DATA dict from `game_txns`/`game_players` and injects it.
Basic-auth (FINANCE_PASSWORD) — this is the one public surface, unlike the
Bearer-only Sage API. Point Caddy's finance.djiang.xyz vhost at its port.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import select

from src.db import GameAccount, GamePlayer, GameTxn
from src.game import core

ET = ZoneInfo("America/New_York")
TEMPLATE = (Path(__file__).parent / "dashboard.html").read_text()


def build_data(rows: list[GameTxn], cap_cents: int, n_cards: int,
               today: dt.date) -> dict:
    """DB rows -> the DATA dict the template's JS expects."""
    dim = calendar.monthrange(today.year, today.month)[1]
    this_month = [r for r in rows
                  if r.posted_date.year == today.year and r.posted_date.month == today.month]

    items = [core.SpendItem(date=r.posted_date, cents=-r.cents,
                            money_type=r.money_type, category=r.category) for r in this_month]
    by_day = core.variable_by_day(items)

    series, cum = [], 0
    for d in range(1, today.day + 1):
        cum += by_day.get(dt.date(today.year, today.month, d), 0)
        series.append({"day": d, "cum": cum, "pace": round(cap_cents * d / dim)})
    spent = cum
    allowed = core.allowance_cents(today, cap_cents)

    cat: dict[str, int] = {}
    split = {"Variable": 0, "Fixed": 0, "Sinking": 0}
    for r in this_month:
        split[r.money_type] = split.get(r.money_type, 0) + (-r.cents)
        if r.money_type == core.VARIABLE:
            cat[r.category] = cat.get(r.category, 0) + (-r.cents)

    recent = sorted(this_month, key=lambda r: (r.posted_date, r.id), reverse=True)[:14]
    return {
        "today": today.isoformat(), "day": today.day, "dim": dim, "cap": cap_cents,
        "spent": spent, "allowed": allowed, "on_pace": spent <= allowed,
        "series": series, "cat": cat, "split": split,
        "review_count": sum(1 for r in this_month if r.needs_review),
        "n_cards": n_cards,
        "recent": [{"date": r.posted_date.isoformat(), "desc": r.description[:32],
                    "cents": -r.cents, "cat": r.category, "mt": r.money_type,
                    "review": r.needs_review} for r in recent],
    }


def render(data: dict) -> str:
    return TEMPLATE.replace("/*__DATA__*/{}", json.dumps(data))


def create_dashboard_app(sessionmaker, guild_id: int) -> FastAPI:
    app = FastAPI(title="Budget Game")
    security = HTTPBasic()
    password = os.getenv("FINANCE_PASSWORD", "")

    def auth(creds: HTTPBasicCredentials = Depends(security)) -> None:
        ok = password and secrets.compare_digest(creds.password, password)
        if not ok:
            raise HTTPException(401, headers={"WWW-Authenticate": "Basic"})

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(_: None = Depends(auth)) -> str:
        today = dt.datetime.now(ET).date()
        async with sessionmaker() as s:
            player = (await s.scalars(select(GamePlayer).where(
                GamePlayer.guild_id == guild_id).order_by(GamePlayer.id))).first()
            if player is None:
                return "<p style='font-family:monospace'>No players yet — /game connect in Discord.</p>"
            rows = list((await s.scalars(select(GameTxn).where(
                GameTxn.user_id == player.user_id))).all())
            n_cards = len((await s.scalars(select(GameAccount).where(
                GameAccount.user_id == player.user_id,
                GameAccount.kind == "card", GameAccount.active == True))).all())  # noqa: E712
        return render(build_data(rows, player.monthly_cap_cents, n_cards, today))

    return app
