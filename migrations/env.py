# migrations/env.py
from __future__ import annotations

import os
import sys
from pathlib import Path
from logging.config import fileConfig
from urllib.parse import urlparse

from alembic import context
from sqlalchemy import engine_from_config, pool

# --- Make app code importable (project root) ---
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# Import your Declarative Base (and models via module import)
from src.db import Base  # importing this registers models on Base.metadata

# Alembic config
config = context.config

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- Build a sync (psycopg2) URL with SSL when needed ---
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _coerce_sync_url(url: str) -> str:
    # Normalize driver to psycopg2 (sync)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    # Ensure SSL for non-local hosts unless an explicit sslmode is present
    host = urlparse(url).hostname or "localhost"
    explicit_sslmode = os.getenv("DB_SSLMODE")  # e.g., "require", "disable"
    if host not in LOCAL_HOSTS:
        if "sslmode=" not in url:
            sep = "&" if "?" in url else "?"
            sslmode = explicit_sslmode or "require"
            url = f"{url}{sep}sslmode={sslmode}"
    return url


# Prefer DATABASE_URL from the environment; else use alembic.ini and coerce
env_url = os.getenv("DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", _coerce_sync_url(env_url))
else:
    ini_url = config.get_main_option("sqlalchemy.url") or ""
    if ini_url:
        config.set_main_option("sqlalchemy.url", _coerce_sync_url(ini_url))

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("No sqlalchemy.url configured for offline migrations.")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
