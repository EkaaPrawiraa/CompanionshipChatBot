"""
agentic/tests/test_memory/conftest.py

Shared fixtures for the Neo4j KG writer/reader integration tests.

What these fixtures do
----------------------
* ``neo4j_client`` -- spins up the real ``Neo4jClient`` against whatever
  NEO4J_URI points at (default bolt://localhost:7687), installs it as the
  module-level singleton so every writer can pick it up via
  ``get_client()``, and tears it down at session scope.

* ``test_namespace`` -- function-scoped isolation block. It stamps every
  test run with a unique UUID, creates a disposable ``User`` + two
  ``Session`` nodes, yields the ids to the test, and then deletes every
  node that carries the namespace tag. This keeps tests hermetic without
  requiring a fresh database per test.

* ``seed_topic`` -- a reusable ``Topic`` node because the Python side does
  not own Topic writes (Go does, per ADR 002), but the relationship
  builders need one to hang RELATED_TO_TOPIC / HAS_RECURRING_THEME edges
  on.

Skipping gracefully
-------------------
If Neo4j is not reachable at collection time every test in this module is
skipped with a clear message; this file is safe to leave in the default
``pytest`` run even on a laptop without a database.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

from agentic.memory import neo4j_client as nc


# ---------------------------------------------------------------------------
# Reachability gate
# ---------------------------------------------------------------------------

def _neo4j_reachable() -> bool:
    """
    Cheap reachability probe. We import the driver lazily so the module
    still collects cleanly if the neo4j package is missing.
    """
    try:
        from neo4j import AsyncGraphDatabase  # noqa: F401
    except Exception:
        return False

    async def _check() -> bool:
        cfg = nc.Neo4jConfig.from_env()
        try:
            client = await nc.Neo4jClient.create(cfg)
            healthy = await client.health_check()
            await client.close()
            return healthy
        except Exception:
            return False

    try:
        return asyncio.run(_check())
    except Exception:
        return False


NEO4J_OK = _neo4j_reachable()
neo4j_required = pytest.mark.skipif(
    not NEO4J_OK,
    reason=(
        "Neo4j is not reachable. Set NEO4J_URI/NEO4J_USERNAME/NEO4J_PASSWORD "
        "to point at a running instance, or run docker-compose up neo4j."
    ),
)


# ---------------------------------------------------------------------------
# Client fixture
#
# We deliberately scope this per-function. pytest-asyncio 0.24 in `auto`
# mode creates a fresh event loop for every test function, and the Neo4j
# async driver binds its internal Futures to whichever loop was running
# when it was constructed. A session-scoped driver therefore ends up
# attached to a dead loop on the second test and raises
# "Future attached to a different loop". Re-creating the driver per test
# costs a few ms but keeps every async primitive on the right loop.
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def neo4j_client() -> AsyncIterator[nc.Neo4jClient]:
    if not NEO4J_OK:
        pytest.skip("Neo4j not reachable")

    client = await nc.init_client()
    try:
        yield client
    finally:
        await nc.close_client()


# ---------------------------------------------------------------------------
# Per-test namespace with User + Sessions
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def test_namespace(neo4j_client: nc.Neo4jClient) -> AsyncIterator[dict]:
    """
    Create an ephemeral (User, 2 Sessions) triple tagged with a unique
    namespace id. After the test completes every node carrying the tag is
    removed along with its edges.
    """
    ns         = f"pytest-{uuid.uuid4()}"
    user_id    = f"{ns}-user"
    session_id = f"{ns}-sess-01"
    session_id_2 = f"{ns}-sess-02"

    await neo4j_client.execute_write(
        """
        CREATE (u:User {
            id:                 $user_id,
            name:               'Test User',
            display_name:       'tester',
            preferred_language: 'en',
            created_at:         datetime(),
            consent_research:   false,
            test_namespace:     $ns,
            active:             true
        })
        CREATE (s1:Session {
            id:              $session_id,
            started_at:      datetime(),
            last_activity:   datetime(),
            ended_at:        null,
            summary:         null,
            test_namespace:  $ns,
            active:          true
        })
        CREATE (s2:Session {
            id:              $session_id_2,
            started_at:      datetime() - duration('PT3H'),
            last_activity:   datetime() - duration('PT2H30M'),
            ended_at:        null,
            summary:         null,
            test_namespace:  $ns,
            active:          true
        })
        CREATE (u)-[:HAD_SESSION {
            t_valid:        datetime(),
            t_invalid:      null,
            confidence:     1.0,
            source_session: $session_id
        }]->(s1)
        CREATE (u)-[:HAD_SESSION {
            t_valid:        datetime() - duration('PT3H'),
            t_invalid:      null,
            confidence:     1.0,
            source_session: $session_id_2
        }]->(s2)
        """,
        {
            "ns":           ns,
            "user_id":      user_id,
            "session_id":   session_id,
            "session_id_2": session_id_2,
        },
    )

    try:
        yield {
            "namespace":    ns,
            "user_id":      user_id,
            "session_id":   session_id,
            "session_id_2": session_id_2,
        }
    finally:
        # Blow away everything with our tag, plus any non-tagged nodes we
        # attached to it via a relationship during the test.
        await neo4j_client.execute_write(
            """
            MATCH (n)
            WHERE n.test_namespace = $ns
            DETACH DELETE n
            """,
            {"ns": ns},
        )


@pytest_asyncio.fixture
async def seed_topic(neo4j_client: nc.Neo4jClient, test_namespace: dict) -> str:
    """
    Topic writes are owned by the Go memory service (ADR 002), but our
    tests for RELATED_TO_TOPIC / HAS_RECURRING_THEME need a Topic to link
    to. Create one inside the namespace so the cleanup hook reaps it.
    """
    ns = test_namespace["namespace"]
    topic_id = f"{ns}-topic-academic"
    await neo4j_client.execute_write(
        """
        CREATE (t:Topic {
            id:             $id,
            name:           'academic-stress',
            category:       'academic',
            created_at:     datetime(),
            test_namespace: $ns
        })
        """,
        {"id": topic_id, "ns": ns},
    )
    return topic_id
