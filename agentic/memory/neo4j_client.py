"""
agentic/memory/neo4j_client.py

Async Neo4j driver wrapper for the Python AI agent.
All LangGraph nodes that read from or write to Neo4j go through this client.

Responsibilities:
- Driver lifecycle (init, close, health check)
- Session factory for read and write operations
- Thin execute helpers so kg_writer.py and context_builder.py
  don't deal with driver internals
- Idle-flush long-term memory worker that periodically re-runs post-session
  bookkeeping for sessions whose user has gone inactive.

Connection split (per ADR 002):
  Go  -> fast CRUD (user, session open/close, assessment, topic upsert)
  Python (this file) -> AI-coupled reads/writes (Emotion, Thought, Trigger,
                        Behavior, Experience, Memory, deduplication)
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Awaitable, Callable

from neo4j import AsyncGraphDatabase, AsyncDriver, AsyncSession, RoutingControl

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Neo4jConfig:
    uri: str      = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "devpassword"
    database: str = "neo4j"
    max_connection_pool_size: int = 50

    @classmethod
    def from_env(cls) -> "Neo4jConfig":
        """Load config from environment variables.
        Set these in your .env file:
            NEO4J_URI=bolt://localhost:7687
            NEO4J_USERNAME=neo4j
            NEO4J_PASSWORD=yourpassword
            NEO4J_DATABASE=neo4j
        """
        return cls(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            username=os.getenv("NEO4J_USERNAME", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "devpassword"),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
            max_connection_pool_size=int(os.getenv("NEO4J_POOL_SIZE", "50")),
        )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class Neo4jClient:
    """
    Async Neo4j client. Create one instance at agent startup and share it
    across all LangGraph nodes via dependency injection or a module-level
    singleton (see get_client() below).

    Usage:
        client = await Neo4jClient.create()
        await client.execute_write(query, params)
        await client.close()

    Or use the async context manager:
        async with Neo4jClient.lifespan() as client:
            ...
    """

    def __init__(self, driver: AsyncDriver, config: Neo4jConfig) -> None:
        self._driver = driver
        self._config = config

    # ── Factory ──────────────────────────────────────────────────────────────

    @classmethod
    async def create(cls, config: Neo4jConfig | None = None) -> "Neo4jClient":
        """Create the client and verify connectivity before returning."""
        cfg = config or Neo4jConfig.from_env()
        driver = AsyncGraphDatabase.driver(
            cfg.uri,
            auth=(cfg.username, cfg.password),
            max_connection_pool_size=cfg.max_connection_pool_size,
        )
        # Verify the connection is live.
        await driver.verify_connectivity()
        logger.info("Neo4j connected: %s (db=%s)", cfg.uri, cfg.database)
        return cls(driver, cfg)

    @classmethod
    @asynccontextmanager
    async def lifespan(
        cls, config: Neo4jConfig | None = None
    ) -> AsyncGenerator["Neo4jClient", None]:
        """Async context manager for use in FastAPI lifespan or test fixtures."""
        client = await cls.create(config)
        try:
            yield client
        finally:
            await client.close()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._driver.close()
        logger.info("Neo4j driver closed.")

    async def health_check(self) -> bool:
        """Returns True if the database is reachable."""
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception as exc:
            logger.warning("Neo4j health check failed: %s", exc)
            return False

    # ── Session helpers ───────────────────────────────────────────────────────

    @asynccontextmanager
    async def write_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yields an async write session. Always use as an async context manager."""
        async with self._driver.session(
            database=self._config.database,
            default_access_mode="WRITE",
        ) as session:
            yield session

    @asynccontextmanager
    async def read_session(self) -> AsyncGenerator[AsyncSession, None]:
        """Yields an async read session."""
        async with self._driver.session(
            database=self._config.database,
            default_access_mode="READ",
        ) as session:
            yield session

    # ── Execute helpers ───────────────────────────────────────────────────────

    async def execute_write(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Run a write query and return all records as a list of dicts.
        Handles transaction management internally.
        """
        async with self.write_session() as session:
            result = await session.run(query, params or {})
            records = await result.data()
            return records

    async def execute_read(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Run a read query and return all records as a list of dicts.
        """
        async with self.read_session() as session:
            result = await session.run(query, params or {})
            records = await result.data()
            return records

    async def execute_write_single(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Run a write query and return only the first record, or None.
        Useful for MERGE + RETURN patterns.
        """
        records = await self.execute_write(query, params)
        return records[0] if records else None

    async def execute_read_single(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Run a read query and return only the first record, or None."""
        records = await self.execute_read(query, params)
        return records[0] if records else None


# ---------------------------------------------------------------------------
# Module-level singleton
# Initialized once in agentic/server/main.py on startup.
# All LangGraph nodes import get_client() to access the shared instance.
# ---------------------------------------------------------------------------

_client: Neo4jClient | None = None


async def init_client(config: Neo4jConfig | None = None) -> Neo4jClient:
    """
    Call once at application startup:
        from agentic.memory.neo4j_client import init_client
        client = await init_client()
    """
    global _client
    _client = await Neo4jClient.create(config)
    return _client


def get_client() -> Neo4jClient:
    """
    Return the shared client instance. Raises RuntimeError if init_client()
    has not been called yet.
    """
    if _client is None:
        raise RuntimeError(
            "Neo4j client not initialized. "
            "Call await init_client() at application startup."
        )
    return _client


async def close_client() -> None:
    """Call at application shutdown."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None


# ---------------------------------------------------------------------------
# Idle-flush long-term memory worker
#
# Design goal: keep the knowledge graph up to date even when a user drifts
# away from an open session without calling session_end.py. Every hour we
# scan for sessions whose last activity is older than IDLE_THRESHOLD but
# that still have ended_at = NULL and no :Memory summary attached, and we
# hand them to a caller-supplied flush callback.
#
# This replaces the earlier implicit assumption that ``session_end`` always
# fires on the happy path; mobile clients drop connections all the time, so
# we cannot rely on it. The worker is safe to run alongside a normal
# session_end call because:
#
#   * the memory writer already dedups on (user_id, summary, embedding), so
#     re-running a flush for a session that already has a Memory is a no-op;
#   * the worker filters on `s.ended_at IS NULL AND NOT EXISTS { HAS_MEMORY }`
#     so sessions that completed cleanly are skipped by construction;
#   * all writes go through execute_write which is transactional per call.
#
# The callback signature is intentionally minimal:
#
#     async def flush(user_id: str, session_id: str) -> None: ...
#
# so that whatever agent-side orchestration owns summarisation (typically
# ``agentic.agent.nodes.session_end``) can be plugged in without the client
# taking a hard dependency on the LangGraph layer.
# ---------------------------------------------------------------------------

# Default thresholds. Override via env vars or by passing arguments to
# start_idle_memory_worker directly.
DEFAULT_IDLE_FLUSH_INTERVAL_SECONDS: int = 60 * 60   # run every hour
DEFAULT_USER_IDLE_THRESHOLD_MINUTES: int = 60        # consider idle after 60 min


FlushCallback = Callable[[str, str], Awaitable[None]]


async def find_idle_sessions(
    idle_minutes: int = DEFAULT_USER_IDLE_THRESHOLD_MINUTES,
    limit: int = 100,
) -> list[dict[str, str]]:
    """
    Return sessions whose owner has been idle for at least ``idle_minutes``
    and that have not yet been summarised into a :Memory node.

    "Idle" is inferred from two signals:
      * Session.last_activity (refreshed by the chat handler on every
        inbound message). If the property is missing we fall back to
        Session.started_at.
      * Absence of a (:Session)-[:CONTAINS_MEMORY]->(:Memory) edge.

    Sessions with ended_at already set are skipped -- those already flushed
    through the normal session_end path.
    """
    client = get_client()
    records = await client.execute_read(
        """
        MATCH (u:User)-[:HAD_SESSION]->(s:Session)
        WHERE s.ended_at IS NULL
          AND NOT EXISTS {
              MATCH (s)-[:CONTAINS_MEMORY]->(:Memory)
          }
          AND coalesce(s.last_activity, s.started_at)
              < datetime() - duration({minutes: $idle_minutes})
        RETURN u.id AS user_id,
               s.id AS session_id,
               coalesce(s.last_activity, s.started_at) AS last_activity
        ORDER BY last_activity ASC
        LIMIT $limit
        """,
        {"idle_minutes": idle_minutes, "limit": limit},
    )
    return [
        {
            "user_id":       r["user_id"],
            "session_id":    r["session_id"],
            "last_activity": str(r.get("last_activity")),
        }
        for r in records
    ]


async def mark_session_flushed(session_id: str) -> None:
    """
    Stamp ``flushed_at`` on the session so the worker does not re-enqueue
    it on the next tick even if the caller chose not to set ended_at
    (e.g. because the user might still come back and add more turns).
    The dedup filter in ``find_idle_sessions`` leans on the :Memory edge,
    but ``flushed_at`` is a lightweight belt-and-braces marker for logs
    and debugging.
    """
    await get_client().execute_write(
        """
        MATCH (s:Session {id: $session_id})
        SET s.flushed_at = datetime()
        """,
        {"session_id": session_id},
    )


async def run_idle_memory_flush(
    flush: FlushCallback,
    idle_minutes: int = DEFAULT_USER_IDLE_THRESHOLD_MINUTES,
    batch_size: int = 100,
) -> dict[str, int]:
    """
    One sweep: find idle sessions and invoke ``flush(user_id, session_id)``
    for each. Returns observability counters {"found": N, "flushed": M,
    "failed": K}.

    The callback is awaited sequentially so a burst of idle sessions does
    not overload whatever downstream summariser is being called. Failures
    are logged but do not abort the sweep.
    """
    sessions = await find_idle_sessions(
        idle_minutes=idle_minutes,
        limit=batch_size,
    )
    flushed = 0
    failed  = 0
    for row in sessions:
        try:
            await flush(row["user_id"], row["session_id"])
            await mark_session_flushed(row["session_id"])
            flushed += 1
        except Exception as exc:
            failed += 1
            logger.exception(
                "Idle memory flush failed for session %s: %s",
                row["session_id"], exc,
            )

    logger.info(
        "Idle memory flush sweep complete: found=%d flushed=%d failed=%d",
        len(sessions), flushed, failed,
    )
    return {"found": len(sessions), "flushed": flushed, "failed": failed}


# Keep a handle on the worker task so callers can shut it down cleanly.
_idle_worker_task: asyncio.Task[None] | None = None


async def _idle_memory_worker_loop(
    flush: FlushCallback,
    interval_seconds: int,
    idle_minutes: int,
    batch_size: int,
) -> None:
    """The long-running loop. Not meant to be awaited directly."""
    logger.info(
        "Idle memory worker started: interval=%ds idle_threshold=%dmin",
        interval_seconds, idle_minutes,
    )
    try:
        while True:
            try:
                await run_idle_memory_flush(
                    flush=flush,
                    idle_minutes=idle_minutes,
                    batch_size=batch_size,
                )
            except Exception as exc:
                # Never let one bad sweep kill the whole worker.
                logger.exception("Idle memory worker sweep errored: %s", exc)
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("Idle memory worker cancelled, exiting cleanly.")
        raise


def start_idle_memory_worker(
    flush: FlushCallback,
    interval_seconds: int = DEFAULT_IDLE_FLUSH_INTERVAL_SECONDS,
    idle_minutes: int = DEFAULT_USER_IDLE_THRESHOLD_MINUTES,
    batch_size: int = 100,
) -> asyncio.Task[None]:
    """
    Start the idle-flush background worker. Call once at application
    startup (e.g. from the FastAPI lifespan or agentic.server.main).
    Returns the asyncio.Task so the caller can cancel it.

    If a worker is already running the existing task is returned unchanged.
    """
    global _idle_worker_task
    if _idle_worker_task is not None and not _idle_worker_task.done():
        logger.warning("Idle memory worker already running, returning existing task.")
        return _idle_worker_task

    loop = asyncio.get_event_loop()
    _idle_worker_task = loop.create_task(
        _idle_memory_worker_loop(
            flush=flush,
            interval_seconds=interval_seconds,
            idle_minutes=idle_minutes,
            batch_size=batch_size,
        )
    )
    return _idle_worker_task


async def stop_idle_memory_worker() -> None:
    """Cancel the idle memory worker if it is running."""
    global _idle_worker_task
    task = _idle_worker_task
    _idle_worker_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Idle memory worker shutdown raised an error.")