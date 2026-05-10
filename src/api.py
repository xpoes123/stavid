"""Local read/write HTTP API for Sage to call.

Bound to 127.0.0.1 only — both bots live on the same VPS, so external auth
isn't a concern. Bearer token still required (`STAVID_API_TOKEN` in .env)
to keep accidents from neighbouring services on the box.

Filters everything by the David + Stephanie guild ID. If you ever add
Stavid to a second guild, this needs a guild_id query param.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from src.db import (
    BucketListItem,
    LedgerEntry,
    OutingWishlistItem,
    ReminderEntry,
    ShoppingItem,
    WatchlistItem,
)

GUILD_ID = 1401585357799292958  # David + Stephanie's apartment guild


# --- Pydantic shapes (read responses) ---


class ShoppingOut(BaseModel):
    id: int
    name: str
    link: str
    note: str
    added_by: int
    bought: bool
    created_at: datetime | None = None


class WatchlistOut(BaseModel):
    id: int
    title: str
    media_type: str
    link: str
    note: str
    added_by: int
    watched: bool


class BucketOut(BaseModel):
    id: int
    title: str
    category: str
    link: str
    note: str
    added_by: int
    completed: bool


class OutingOut(BaseModel):
    id: int
    name: str
    category: str
    budget: str
    neighborhood: str
    link: str
    note: str
    visited: bool


class ReminderOut(BaseModel):
    id: int
    creator_id: int
    partner_id: int
    note: str
    location: str
    time: datetime
    done: bool


class LedgerOut(BaseModel):
    id: int
    creditor_id: int
    debtor_id: int
    amount_cents: int
    note: str
    created_at: datetime | None = None


class SummaryOut(BaseModel):
    shopping_open: int
    watchlist_unwatched: int
    bucket_open: int
    outings_unvisited: int
    reminders_pending: int


# --- Pydantic shapes (write requests) ---


class ShoppingIn(BaseModel):
    name: str = Field(min_length=1)
    link: str = ""
    note: str = ""
    added_by: int


class WatchlistIn(BaseModel):
    title: str = Field(min_length=1)
    media_type: str = Field(pattern="^(movie|show)$")
    link: str = ""
    note: str = ""
    added_by: int


class BucketIn(BaseModel):
    title: str = Field(min_length=1)
    category: str = "other"
    link: str = ""
    note: str = ""
    added_by: int


class OutingIn(BaseModel):
    name: str = Field(min_length=1)
    category: str = "other"
    budget: str = ""
    neighborhood: str = ""
    link: str = ""
    note: str = ""
    added_by: int


# --- Auth ---


def _require_bearer(authorization: Annotated[str, Header()] = "") -> None:
    """Bearer-token auth; rejects with 401/503 on missing/invalid."""
    expected = os.getenv("STAVID_API_TOKEN")
    if not expected:
        raise HTTPException(503, "STAVID_API_TOKEN not configured")
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing Authorization: Bearer <token>")
    presented = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(401, "Invalid token")


# --- App factory ---


def create_app(sessionmaker) -> FastAPI:
    """Build the FastAPI app. The bot's sessionmaker is captured here so
    every request reuses the bot's already-warm asyncpg pool."""
    app = FastAPI(title="Stavid Local API", docs_url=None, redoc_url=None)

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True}

    # --- shopping list ---

    @app.get("/shopping", response_model=list[ShoppingOut])
    async def list_shopping(
        _: None = Depends(_require_bearer),
        bought: bool | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        async with sessionmaker() as s:
            stmt = (
                select(ShoppingItem)
                .where(ShoppingItem.guild_id == GUILD_ID)
                .order_by(desc(ShoppingItem.created_at))
                .limit(limit)
            )
            if bought is not None:
                stmt = stmt.where(ShoppingItem.bought == bought)
            rows = (await s.execute(stmt)).scalars().all()
        return [ShoppingOut(
            id=r.id, name=r.name, link=r.link, note=r.note,
            added_by=r.added_by, bought=r.bought, created_at=r.created_at,
        ) for r in rows]

    @app.post("/shopping", response_model=ShoppingOut, status_code=201)
    async def add_shopping(req: ShoppingIn, _: None = Depends(_require_bearer)):
        async with sessionmaker() as s:
            row = ShoppingItem(
                guild_id=GUILD_ID, name=req.name, link=req.link,
                note=req.note, added_by=req.added_by, bought=False,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
        return ShoppingOut(
            id=row.id, name=row.name, link=row.link, note=row.note,
            added_by=row.added_by, bought=row.bought, created_at=row.created_at,
        )

    @app.post("/shopping/{item_id}/bought", response_model=ShoppingOut)
    async def mark_shopping_bought(
        item_id: int, _: None = Depends(_require_bearer),
    ):
        async with sessionmaker() as s:
            row = await s.get(ShoppingItem, item_id)
            if row is None or row.guild_id != GUILD_ID:
                raise HTTPException(404, f"Shopping item {item_id} not found")
            row.bought = True
            await s.commit()
            await s.refresh(row)
        return ShoppingOut(
            id=row.id, name=row.name, link=row.link, note=row.note,
            added_by=row.added_by, bought=row.bought, created_at=row.created_at,
        )

    # --- watchlist ---

    @app.get("/watchlist", response_model=list[WatchlistOut])
    async def list_watchlist(
        _: None = Depends(_require_bearer),
        watched: bool | None = None,
        media_type: str | None = Query(default=None, pattern="^(movie|show)$"),
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        async with sessionmaker() as s:
            stmt = (
                select(WatchlistItem)
                .where(WatchlistItem.guild_id == GUILD_ID)
                .order_by(desc(WatchlistItem.id))
                .limit(limit)
            )
            if watched is not None:
                stmt = stmt.where(WatchlistItem.watched == watched)
            if media_type:
                stmt = stmt.where(WatchlistItem.media_type == media_type)
            rows = (await s.execute(stmt)).scalars().all()
        return [WatchlistOut(
            id=r.id, title=r.title, media_type=r.media_type, link=r.link,
            note=r.note, added_by=r.added_by, watched=r.watched,
        ) for r in rows]

    @app.post("/watchlist", response_model=WatchlistOut, status_code=201)
    async def add_watchlist(req: WatchlistIn, _: None = Depends(_require_bearer)):
        async with sessionmaker() as s:
            row = WatchlistItem(
                guild_id=GUILD_ID, title=req.title, media_type=req.media_type,
                link=req.link, note=req.note, added_by=req.added_by, watched=False,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
        return WatchlistOut(
            id=row.id, title=row.title, media_type=row.media_type, link=row.link,
            note=row.note, added_by=row.added_by, watched=row.watched,
        )

    @app.post("/watchlist/{item_id}/watched", response_model=WatchlistOut)
    async def mark_watchlist_watched(
        item_id: int, _: None = Depends(_require_bearer),
    ):
        async with sessionmaker() as s:
            row = await s.get(WatchlistItem, item_id)
            if row is None or row.guild_id != GUILD_ID:
                raise HTTPException(404, f"Watchlist item {item_id} not found")
            row.watched = True
            await s.commit()
            await s.refresh(row)
        return WatchlistOut(
            id=row.id, title=row.title, media_type=row.media_type, link=row.link,
            note=row.note, added_by=row.added_by, watched=row.watched,
        )

    # --- bucket list ---

    @app.get("/bucket", response_model=list[BucketOut])
    async def list_bucket(
        _: None = Depends(_require_bearer),
        completed: bool | None = None,
        category: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        async with sessionmaker() as s:
            stmt = (
                select(BucketListItem)
                .where(BucketListItem.guild_id == GUILD_ID)
                .order_by(desc(BucketListItem.id))
                .limit(limit)
            )
            if completed is not None:
                stmt = stmt.where(BucketListItem.completed == completed)
            if category:
                stmt = stmt.where(BucketListItem.category == category)
            rows = (await s.execute(stmt)).scalars().all()
        return [BucketOut(
            id=r.id, title=r.title, category=r.category, link=r.link,
            note=r.note, added_by=r.added_by, completed=r.completed,
        ) for r in rows]

    @app.post("/bucket", response_model=BucketOut, status_code=201)
    async def add_bucket(req: BucketIn, _: None = Depends(_require_bearer)):
        async with sessionmaker() as s:
            row = BucketListItem(
                guild_id=GUILD_ID, title=req.title, category=req.category,
                link=req.link, note=req.note, added_by=req.added_by, completed=False,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
        return BucketOut(
            id=row.id, title=row.title, category=row.category, link=row.link,
            note=row.note, added_by=row.added_by, completed=row.completed,
        )

    @app.post("/bucket/{item_id}/completed", response_model=BucketOut)
    async def mark_bucket_completed(
        item_id: int, _: None = Depends(_require_bearer),
    ):
        async with sessionmaker() as s:
            row = await s.get(BucketListItem, item_id)
            if row is None or row.guild_id != GUILD_ID:
                raise HTTPException(404, f"Bucket item {item_id} not found")
            row.completed = True
            await s.commit()
            await s.refresh(row)
        return BucketOut(
            id=row.id, title=row.title, category=row.category, link=row.link,
            note=row.note, added_by=row.added_by, completed=row.completed,
        )

    # --- outings (restaurants + activities to try) ---

    @app.get("/outings", response_model=list[OutingOut])
    async def list_outings(
        _: None = Depends(_require_bearer),
        visited: bool | None = None,
        category: str | None = None,
        budget: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
    ):
        async with sessionmaker() as s:
            stmt = (
                select(OutingWishlistItem)
                .where(OutingWishlistItem.guild_id == GUILD_ID)
                .order_by(desc(OutingWishlistItem.id))
                .limit(limit)
            )
            if visited is not None:
                stmt = stmt.where(OutingWishlistItem.visited == visited)
            if category:
                stmt = stmt.where(OutingWishlistItem.category == category)
            if budget:
                stmt = stmt.where(OutingWishlistItem.budget == budget)
            rows = (await s.execute(stmt)).scalars().all()
        return [OutingOut(
            id=r.id, name=r.name, category=r.category, budget=r.budget,
            neighborhood=r.neighborhood, link=r.link, note=r.note,
            visited=r.visited,
        ) for r in rows]

    @app.post("/outings", response_model=OutingOut, status_code=201)
    async def add_outing(req: OutingIn, _: None = Depends(_require_bearer)):
        async with sessionmaker() as s:
            row = OutingWishlistItem(
                guild_id=GUILD_ID, name=req.name, category=req.category,
                budget=req.budget, neighborhood=req.neighborhood, link=req.link,
                note=req.note, added_by=req.added_by,
            )
            s.add(row)
            await s.commit()
            await s.refresh(row)
        return OutingOut(
            id=row.id, name=row.name, category=row.category, budget=row.budget,
            neighborhood=row.neighborhood, link=row.link, note=row.note,
            visited=row.visited,
        )

    @app.post("/outings/{item_id}/visited", response_model=OutingOut)
    async def mark_outing_visited(
        item_id: int, _: None = Depends(_require_bearer),
    ):
        async with sessionmaker() as s:
            row = await s.get(OutingWishlistItem, item_id)
            if row is None or row.guild_id != GUILD_ID:
                raise HTTPException(404, f"Outing item {item_id} not found")
            row.visited = True
            await s.commit()
            await s.refresh(row)
        return OutingOut(
            id=row.id, name=row.name, category=row.category, budget=row.budget,
            neighborhood=row.neighborhood, link=row.link, note=row.note,
            visited=row.visited,
        )

    # --- reminders (read-only; Stavid's slash commands stay canonical for create) ---

    @app.get("/reminders", response_model=list[ReminderOut])
    async def list_reminders(
        _: None = Depends(_require_bearer),
        done: bool | None = None,
        creator_id: int | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ):
        async with sessionmaker() as s:
            stmt = (
                select(ReminderEntry)
                .where(ReminderEntry.guild_id == GUILD_ID)
                .order_by(ReminderEntry.time)
                .limit(limit)
            )
            if done is not None:
                stmt = stmt.where(ReminderEntry.done == done)
            if creator_id is not None:
                stmt = stmt.where(ReminderEntry.creator_id == creator_id)
            rows = (await s.execute(stmt)).scalars().all()
        return [ReminderOut(
            id=r.id, creator_id=r.creator_id, partner_id=r.partner_id,
            note=r.note, location=r.location, time=r.time, done=r.done,
        ) for r in rows]

    # --- ledger (read-only) ---

    @app.get("/ledger", response_model=list[LedgerOut])
    async def list_ledger(
        _: None = Depends(_require_bearer),
        limit: int = Query(default=50, ge=1, le=500),
    ):
        async with sessionmaker() as s:
            stmt = (
                select(LedgerEntry)
                .where(LedgerEntry.guild_id == GUILD_ID)
                .order_by(desc(LedgerEntry.created_at))
                .limit(limit)
            )
            rows = (await s.execute(stmt)).scalars().all()
        return [LedgerOut(
            id=r.id, creditor_id=r.creditor_id, debtor_id=r.debtor_id,
            amount_cents=r.amount_cents, note=r.note, created_at=r.created_at,
        ) for r in rows]

    # --- top-level summary (one round-trip "what's open across everything") ---

    @app.get("/summary", response_model=SummaryOut)
    async def summary(_: None = Depends(_require_bearer)):
        async with sessionmaker() as s:
            from sqlalchemy import func
            shopping_open = await s.scalar(
                select(func.count()).select_from(ShoppingItem)
                .where(ShoppingItem.guild_id == GUILD_ID)
                .where(ShoppingItem.bought.is_(False))
            )
            watch_open = await s.scalar(
                select(func.count()).select_from(WatchlistItem)
                .where(WatchlistItem.guild_id == GUILD_ID)
                .where(WatchlistItem.watched.is_(False))
            )
            bucket_open = await s.scalar(
                select(func.count()).select_from(BucketListItem)
                .where(BucketListItem.guild_id == GUILD_ID)
                .where(BucketListItem.completed.is_(False))
            )
            outings_open = await s.scalar(
                select(func.count()).select_from(OutingWishlistItem)
                .where(OutingWishlistItem.guild_id == GUILD_ID)
                .where(OutingWishlistItem.visited.is_(False))
            )
            reminders_open = await s.scalar(
                select(func.count()).select_from(ReminderEntry)
                .where(ReminderEntry.guild_id == GUILD_ID)
                .where(ReminderEntry.done.is_(False))
            )
        return SummaryOut(
            shopping_open=shopping_open or 0,
            watchlist_unwatched=watch_open or 0,
            bucket_open=bucket_open or 0,
            outings_unvisited=outings_open or 0,
            reminders_pending=reminders_open or 0,
        )

    return app
