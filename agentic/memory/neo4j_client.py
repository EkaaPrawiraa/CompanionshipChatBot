"""
agentic/memory/neo4j_client.py

Async Neo4j driver wrapper for the Python AI agent.
All LangGraph nodes that read from or write to Neo4j go through this client.

Responsibilities:
- Driver lifecycle (init, close, health check)
- Session factory for read and write operations
- Thin execute helpers so kg_writer.py and context_builder.py
  don't deal with driver internals

Connection split (per ADR 002):
  Go  -> fast CRUD (user, session open/close, assessment, topic upsert)
  Python (this file) -> AI-coupled reads/writes (Emotion, Thought, Trigger,
                        Behavior, Experience, Memory, deduplication)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator

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