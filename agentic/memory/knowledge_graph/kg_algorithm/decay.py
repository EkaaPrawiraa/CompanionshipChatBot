"""
agentic/memory/kg_algorithm/decay.py

Memory decay job. Implements the forgetting curve for :Memory nodes.

Lives in kg_algorithm because decay is a scheduled algorithmic
operation on the graph rather than an extractor-driven write. The
kg_writer package re-exports this symbol so existing callers do not
break.

Rules (DevNotes v1.1):
    * importance is halved when a memory has not been accessed in 60 days
      and its importance is still above the floor (0.05). This runs on a
      rolling basis, so a memory can be halved multiple times across runs.
    * active is flipped to false when a memory has not been accessed in
      180 days. Archived memories are excluded from all three retrieval
      signals (recency, semantic, salience) but are NOT deleted; they can
      still be surfaced on explicit therapist or user request.

Expected to be called from a nightly background job (e.g. APScheduler
or a Kubernetes CronJob that shells into the agent container). The
function returns counts for logging and metrics.
"""

from __future__ import annotations

import logging

from agentic.memory.neo4j_client import get_client

logger = logging.getLogger(__name__)


async def run_memory_decay() -> dict[str, int]:
    """
    Apply memory decay rules. Returns
        {"halved": int, "archived": int}
    for observability.
    """
    client = get_client()

    # ── Step 1: halve importance for stale-but-active memories ─────────────
    halved_records = await client.execute_write(
        """
        MATCH (m:Memory)
        WHERE m.active = true
          AND m.last_accessed < datetime() - duration('P60D')
          AND m.importance > 0.05
        SET m.importance = m.importance / 2.0
        RETURN count(m) AS halved
        """
    )

    # ── Step 2: archive memories unreferenced for 180 days ─────────────────
    archived_records = await client.execute_write(
        """
        MATCH (m:Memory)
        WHERE m.active = true
          AND m.last_accessed < datetime() - duration('P180D')
        SET m.active = false
        RETURN count(m) AS archived
        """
    )

    halved   = halved_records[0]["halved"]     if halved_records   else 0
    archived = archived_records[0]["archived"] if archived_records else 0

    logger.info("Memory decay run: halved=%d, archived=%d", halved, archived)
    return {"halved": halved, "archived": archived}
