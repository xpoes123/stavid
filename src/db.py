# src/db.py
from __future__ import annotations

import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dotenv import load_dotenv
from sqlalchemy import BigInteger, Boolean, DateTime, Integer, Text
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# -----------------------------------------------------------------------------
# Load .env for local runs (no effect on Heroku)
# -----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.local", override=True)

# Avoid ambient PGSSLMODE; we control TLS explicitly
os.environ.pop("PGSSLMODE", None)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
LIBPQ_SSL_KEYS = {"sslmode", "sslrootcert", "sslcert", "sslkey", "sslcrl"}


# -----------------------------------------------------------------------------
# URL helpers
# -----------------------------------------------------------------------------
def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or os.getenv("PGURL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    return url


def _strip_libpq_ssl_params(url: str) -> str:
    """Remove libpq-specific SSL params (sslmode, sslrootcert, etc.) from URL."""
    u = urlparse(url)
    q = parse_qs(u.query or "", keep_blank_values=True)
    for k in list(q.keys()):
        if k.lower() in LIBPQ_SSL_KEYS:
            q.pop(k, None)
    new_query = urlencode(q, doseq=True)
    return urlunparse(u._replace(query=new_query))


def _normalize_asyncpg_url(url: str) -> str:
    """Coerce scheme to SQLAlchemy's asyncpg URL."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


def _ssl_required(raw_url: str) -> bool:
    """Decide whether to enable TLS for asyncpg."""
    # Explicit override via env
    if m := os.getenv("DB_SSLMODE"):
        return m.lower() != "disable"

    u = urlparse(raw_url)
    host = (u.hostname or "localhost").lower()
    # If user put sslmode in URL, respect it for the decision only
    q = parse_qs(u.query or "")
    smode = (q.get("sslmode", [""])[0] or "").lower()
    if smode:
        return smode != "disable"

    return host not in LOCAL_HOSTS


def _make_ssl_context(use_ssl: bool):
    """Verifying TLS by default; load CA from env or certifi fallback."""
    if not use_ssl:
        return False  # asyncpg accepts False to disable TLS

    ctx = ssl.create_default_context()

    # Prefer explicit root cert if provided
    ca_file = os.getenv("DB_SSLROOTCERT") or os.getenv("SSL_CERT_FILE")
    if ca_file and os.path.exists(ca_file):
        ctx.load_verify_locations(cafile=ca_file)
    else:
        # Fallback to certifi bundle if available
        try:
            import certifi  # type: ignore

            ctx.load_verify_locations(cafile=certifi.where())
        except Exception:
            # leave platform defaults
            pass

    # Only relax verification if explicitly requested (dev only)
    if os.getenv("DB_TRUST_PROXY") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


# -----------------------------------------------------------------------------
# SQLAlchemy base/models
# -----------------------------------------------------------------------------
class Base(AsyncAttrs, DeclarativeBase):
    pass


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
# Engine / Session
# -----------------------------------------------------------------------------
def create_sessionmaker(echo: bool = False) -> async_sessionmaker:
    raw_url = _get_db_url()
    # Remove libpq SSL params for asyncpg, but still *use* them to decide TLS
    sanitized = _strip_libpq_ssl_params(raw_url)
    url = _normalize_asyncpg_url(sanitized)

    ssl_ctx = _make_ssl_context(_ssl_required(raw_url))
    connect_args = {"ssl": ssl_ctx} if ssl_ctx is not False else {"ssl": False}

    engine = create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        connect_args=connect_args,  # forwarded to asyncpg.connect()
    )
    return async_sessionmaker(engine, expire_on_commit=False)


# -----------------------------------------------------------------------------
# Schema init
# -----------------------------------------------------------------------------
async def init_db(sessionmaker: async_sessionmaker) -> None:
    async with sessionmaker().bind.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("[db] init_db -> tables ensured")
