"""
agentic/memory/kg_writer/behavior_kg.py

Writer for the :Behavior node and the (:User)-[:EXHIBITED]->(:Behavior)
edge.

Same keyword dedup strategy as Trigger: (user, category, first 30 chars
of description). On match we increment the frequency counter and update
the timestamp. ``adaptive`` is not part of the match key because an
action can flip between adaptive and maladaptive over time (e.g. rest
vs. avoidance) -- we keep the first-seen classification and let the
recommendation engine re-label in a separate pass if needed.
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_writer._common import _new_id, _require
from agentic.memory.knowledge_graph.kg_retriever.schemas import BehaviorInput
from agentic.memory.neo4j_client        import get_client

logger = logging.getLogger(__name__)


async def write_behavior(inp: BehaviorInput) -> str:
    """
    MERGE :Behavior by (user_id, category, description prefix).
    Increments frequency on match. Returns the node id.
    """
    _require(inp.category,    "category")
    _require(inp.description, "description")
    _require(inp.user_id,     "user_id")
    _require(inp.session_id,  "session_id")

    client = get_client()

    existing = await client.execute_read_single(
        """
        MATCH (u:User {id: $user_id})-[:EXHIBITED]->(b:Behavior)
        WHERE b.category = $category
          AND toLower(b.description) CONTAINS toLower($keyword)
        RETURN b.id AS id
        LIMIT 1
        """,
        {
            "user_id":  inp.user_id,
            "category": inp.category,
            "keyword":  inp.description[:30],
        },
    )

    if existing:
        await client.execute_write(
            """
            MATCH (b:Behavior {id: $id})
            SET b.frequency = coalesce(b.frequency, 0) + 1,
                b.timestamp = datetime()
            WITH b
            MATCH (u:User {id: $user_id})-[r:EXHIBITED]->(b)
            WHERE r.t_invalid IS NULL
              AND $message_id IS NOT NULL
              AND NOT $message_id IN coalesce(r.source_messages, [])
            SET r.source_messages = coalesce(r.source_messages, []) + $message_id
            """,
            {
                "id":         existing["id"],
                "user_id":    inp.user_id,
                "message_id": inp.source_message_id,
            },
        )
        logger.debug("Behavior frequency incremented: %s", existing["id"])
        return existing["id"]

    node_id = _new_id()
    await client.execute_write(
        """
        MATCH (u:User {id: $user_id})
        CREATE (b:Behavior {
            id:                $id,
            description:       $description,
            category:          $category,
            adaptive:          $adaptive,
            frequency:         1,
            timestamp:         datetime(),
            sensitivity_level: $sensitivity_level
        })
        CREATE (u)-[:EXHIBITED {
            t_valid:         datetime(),
            t_invalid:       null,
            confidence:      $confidence,
            source_session:  $session_id,
            source_messages: CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        }]->(b)
        RETURN b.id AS id
        """,
        {
            "user_id":           inp.user_id,
            "session_id":        inp.session_id,
            "id":                node_id,
            "description":       inp.description,
            "category":          inp.category,
            "adaptive":          inp.adaptive,
            "sensitivity_level": inp.sensitivity_level,
            "confidence":        inp.confidence,
            "message_id":        inp.source_message_id,
        },
    )
    logger.debug("Behavior written: %s (adaptive=%s)", node_id, inp.adaptive)
    return node_id
