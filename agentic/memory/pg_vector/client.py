"""
agentic/memory/pg_vector/client.py

Async PostgreSQL connection pool for the pgvector mirror tables.

Lifecycle
---------
The pool is lazily created on first ``get_pool()`` call so importing
this module is free even when PostgreSQL is not running. Tests that
spin up a fresh process per case do not need to do anything; tests
that want to reset the pool between cases should call ``close_pool``.

Graceful degradation
--------------------
Every public read/write helper in this package wraps its asyncpg
calls in try / except. On any connection-level failure the call
returns the safe default (empty list for searches, ``False`` for
sync flips) and logs a warning. The retrieval pipeline must keep
serving recency + salience even when the embedding store is offline.

Configuration
-------------
Read from env vars at first ``PgvectorConfig.from_env()`` call::

    PG_HOST           default localhost
    PG_PORT           default 5432
    PG_USER           default companion
    PG_PASSWORD       default devpassword
    PG_DATABASE       default companion_chatbot
    PG_POOL_MIN_SIZE  default 1
    PG_POOL_MAX_SIZE  default 10
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PgvectorConfig:
    host:     str = "localhost"
    port:     int = 5432
    user:     str = "companion"
    password: str = "devpassword"
    database: str = "companion_chatbot"
    min_size: int = 1
    max_size: int = 10

    @classmethod
    def from_env(cls) -> "PgvectorConfig":
        return cls(
            host     = os.getenv("PG_HOST", "localhost"),
            port     = int(os.getenv("PG_PORT", "5432")),
            user     = os.getenv("PG_USER", "companion"),
            password = os.getenv("PG_PASSWORD", "devpassword"),
            database = os.getenv("PG_DATABASE", "companion_chatbot"),
            min_size = int(os.getenv("PG_POOL_MIN_SIZE", "1")),
            max_size = int(os.getenv("PG_POOL_MAX_SIZE", "10")),
        )


_pool = None
_unavailable: bool = False


async def get_pool():
    """
    Return the singleton asyncpg pool. Returns ``None`` when asyncpg
    is not installed or the database is unreachable; callers must
    handle the None case.
    """
    global _pool, _unavailable

    if _pool is not None:
        return _pool
    if _unavailable:
        return None

    try:
        import asyncpg  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "asyncpg not installed; pg_vector running in offline mode. "
            "Install with: pip install asyncpg"
        )
        _unavailable = True
        return None

    cfg = PgvectorConfig.from_env()
    try:
        _pool = await asyncpg.create_pool(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            database=cfg.database,
            min_size=cfg.min_size,
            max_size=cfg.max_size,
        )
        logger.info(
            "pgvector pool ready (host=%s db=%s, min=%d max=%d)",
            cfg.host, cfg.database, cfg.min_size, cfg.max_size,
        )
        return _pool
    except Exception as exc:
        logger.warning(
            "pgvector pool unavailable: %s. "
            "Semantic retrieval and embedding upserts will no-op.",
            exc,
        )
        _unavailable = True
        return None


async def close_pool() -> None:
    """Close the pool. Safe to call multiple times."""
    global _pool, _unavailable
    if _pool is not None:
        try:
            await _pool.close()
        finally:
            _pool = None
    _unavailable = False


async def is_available() -> bool:
    """Cheap probe so callers can branch without a try / except dance."""
    pool = await get_pool()
    return pool is not None
