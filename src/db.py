# src/db.py
from __future__ import annotations

import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import asyncpg
from dotenv import load_dotenv
from sqlalchemy import BigInteger, DateTime, Integer, Text, Boolean
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# -----------------------------------------------------------------------------
# .env loading (local dev) — safe in Railway (vars not overridden unless explicit)
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

# Don't let asyncpg pick up global PGSSLMODE
os.environ.pop("PGSSLMODE", None)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Prefer URL-style envs in this order
_URL_VAR_CANDIDATES = ("DATABASE_URL", "POSTGRES_URL", "PGURL")

# Fallback component-style env groups
_COMPONENT_GROUPS = [
    ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE"),
    (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ),
    (
        "RAILWAY_TCP_HOST",
        "RAILWAY_TCP_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    ),
]


class Base(AsyncAttrs, DeclarativeBase):
    pass


def _get_env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v


def _parse_db_url(db_url: str) -> dict:
    """Parse postgres URL into asyncpg connect kwargs."""
    db_url = db_url.replace("postgresql+asyncpg://", "postgres://", 1)
    db_url = db_url.replace("postgresql://", "postgres://", 1)

    u = urlparse(db_url)
    if u.scheme not in {"postgres", "postgresql"}:
        raise ValueError(f"Unsupported DB URL scheme: {u.scheme}")

    q = parse_qs(u.query or "")
    sslmode = (q.get("sslmode", [""])[0] or "").lower()

    return {
        "host": u.hostname or "localhost",
        "port": int(u.port or 5432),
        "user": unquote(u.username or "postgres"),
        "password": unquote(u.password or ""),
        "database": (u.path.lstrip("/") or "postgres"),
        "sslmode": sslmode,  # '', 'require', 'disable', etc.
    }


def _gather_db_params() -> dict:
    """Detect DB connection params from env (Railway/Heroku/local)."""
    # 1) URL-style
    for var in _URL_VAR_CANDIDATES:
        val = os.getenv(var)
        if val:
            p = _parse_db_url(val)
            host = p["host"]
            explicit_mode = os.getenv("DB_SSLMODE") or p["sslmode"]
            if explicit_mode:
                use_ssl = explicit_mode != "disable"
            else:
                use_ssl = host not in LOCAL_HOSTS
            _debug_print(host, p["port"], p["user"], p["database"])
            return {
                "host": host,
                "port": p["port"],
                "user": p["user"],
                "password": p["password"],
                "database": p["database"],
                "use_ssl": use_ssl,
            }

    # 2) Component-style
    env = os.environ
    for H, P, U, PW, DB in _COMPONENT_GROUPS:
        if env.get(H):
            host = env.get(H)
            port = int(env.get(P, "5432"))
            user = env.get(U, "postgres") or "postgres"
            pwd = env.get(PW, "") or ""
            db = env.get(DB, "postgres") or "postgres"
            explicit_mode = os.getenv("DB_SSLMODE")
            if explicit_mode:
                use_ssl = explicit_mode != "disable"
            else:
                use_ssl = host not in LOCAL_HOSTS
            _debug_print(host, port, user, db)
            return {
                "host": host,
                "port": port,
                "user": user,
                "password": pwd,
                "database": db,
                "use_ssl": use_ssl,
            }

    # 3) Local defaults
    host = _get_env("PUBLIC_PGHOST") or _get_env("PGHOST", "localhost")
    port = int(_get_env("PGPORT", "5432"))
    user = _get_env("PGUSER", "postgres") or "postgres"
    pwd = _get_env("PGPASSWORD", "") or ""
    db = _get_env("PGDATABASE", "postgres") or "postgres"
    explicit_mode = os.getenv("DB_SSLMODE")
    if explicit_mode:
        use_ssl = explicit_mode != "disable"
    else:
        use_ssl = host not in LOCAL_HOSTS
    _debug_print(host, port, user, db)
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": pwd,
        "database": db,
        "use_ssl": use_ssl,
    }


def _debug_print(host: str, port: int, user: str, db: str) -> None:
    print("[db] params host/port/user/db ->", host, port, user, db)
    if os.getenv("DB_PRINT_PASSWORD_DEBUG") == "1":
        # Only length, no secrets
        pwd = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD") or ""
        print("[db] password length:", len(pwd))


def _make_ssl_context(use_ssl: bool):
    if not use_ssl:
        return False  # asyncpg accepts False to disable TLS
    ctx = ssl.create_default_context()
    # If Railway uses a proxy with non-standard chain, you can disable checks in dev:
    if os.getenv("DB_TRUST_PROXY", "1") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def create_sessionmaker(echo: bool = False) -> async_sessionmaker:
    params = _gather_db_params()
    ssl_ctx = _make_ssl_context(params["use_ssl"])

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
        "postgresql+asyncpg://",  # placeholder; real conn via async_creator
        echo=echo,
        pool_pre_ping=True,
        async_creator=_creator,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


# -----------------------------------------------------------------------------
# Models
# -----------------------------------------------------------------------------
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


class ReminderEntry(Base):
    __tablename__ = "reminder_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    creator_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    partner_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    location: Mapped[str] = mapped_column(Text, default="", nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


# -----------------------------------------------------------------------------
# Schema init
# -----------------------------------------------------------------------------
async def init_db(sessionmaker: async_sessionmaker) -> None:
    async with sessionmaker().bind.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[db] init_db -> tables ensured")
