# src/db.py
from __future__ import annotations

import os
import ssl
from datetime import datetime, timezone
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from sqlalchemy import BigInteger, DateTime, Integer, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

# Prevent asyncpg from picking up sslmode from env
os.environ.pop("PGSSLMODE", None)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class Base(AsyncAttrs, DeclarativeBase): ...


def _get_env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v


def _gather_db_params() -> dict:
    host = _get_env("PUBLIC_PGHOST") or _get_env("PGHOST", "localhost")
    port = int(_get_env("PGPORT", "5432"))
    user = _get_env("PGUSER", "postgres") or "postgres"
    pwd = _get_env("PGPASSWORD", "") or ""
    db = _get_env("PGDATABASE", "postgres") or "postgres"
    use_ssl = False if host in LOCAL_HOSTS else True

    # Debug (no secrets)
    print("[db] params host/port/user/db ->", host, port, user, db)
    if os.getenv("DB_PRINT_PASSWORD_DEBUG") == "1":
        print("[db] password length:", len(pwd), "repr:", repr(pwd))

    return {
        "host": host,
        "port": port,
        "user": user,
        "password": pwd,
        "database": db,
        "use_ssl": use_ssl,
    }


def _make_ssl_context(use_ssl: bool):
    if not use_ssl:
        return False
    ctx = ssl.create_default_context()
    # Railway proxy can present a self-signed chain; disable verification for dev
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def create_sessionmaker(echo: bool = False) -> async_sessionmaker:
    params = _gather_db_params()
    ssl_ctx = _make_ssl_context(params["use_ssl"])

    # Use async_creator to avoid URL/percent-encoding/sslmode pitfalls entirely
    async def _creator():
        return await asyncpg.connect(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            database=params["database"],
            ssl=ssl_ctx,
            timeout=10,
        )

    engine = create_async_engine(
        "postgresql+asyncpg://",  # placeholder; async_creator supplies the real connection
        echo=echo,
        pool_pre_ping=True,
        async_creator=_creator,  # ← key line
    )
    return async_sessionmaker(engine, expire_on_commit=False)


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    creditor_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    debtor_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


async def init_db(sessionmaker: async_sessionmaker) -> None:
    async with sessionmaker().bind.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[db] init_db -> tables ensured")
