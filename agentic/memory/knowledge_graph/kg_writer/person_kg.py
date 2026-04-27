"""
agentic/memory/kg_writer/person_kg.py

Writer for the :Person node and the
(:User)-[:HAS_RELATIONSHIP_WITH]->(:Person) edge.

Per the canonical KG schema (KG_Schema_Design.md, section 3 and the
Person node spec in section 2.8) the User edge is HAS_RELATIONSHIP_WITH
with a ``quality`` property summarising the bond as supportive,
complicated, negative, or neutral. The earlier KNOWS edge has been
retired.

Uses Cypher MERGE keyed on (user_id, name) so the same person node is
reused across sessions. The MERGE is scoped by ``owner_user_id`` so two
different users with a same-named contact ("Mom") do not collide on the
same node.

Properties tracked on the node:
  * sentiment       -- running average of mention sentiment, [-1, 1]
  * mention_count   -- total mentions across all sessions
  * first_mentioned -- onset, set on create
  * last_mentioned  -- recency, refreshed every match (drives the
                       Haque & Rubya 2023 absence-detection guardrail)
"""

from __future__ import annotations

import logging

from agentic.memory.knowledge_graph.kg_writer._common import _new_id, _require
from agentic.memory.knowledge_graph.kg_retriever.schemas import PersonInput
from agentic.memory.neo4j_client        import get_client

logger = logging.getLogger(__name__)


async def write_person(inp: PersonInput) -> str:
    """
    Upsert a :Person for this user. On match: sentiment is averaged with
    the incoming value, mention_count is incremented, and last_mentioned
    is refreshed. Returns the node id of the merged or newly-created
    node.

    The (:User)-[:HAS_RELATIONSHIP_WITH]->(:Person) edge carries the
    coarse relationship quality (supportive | complicated | negative |
    neutral) plus the standard bi-temporal properties.
    """
    _require(inp.name,       "name")
    _require(inp.role,       "role")
    _require(inp.user_id,    "user_id")
    _require(inp.session_id, "session_id")

    client  = get_client()
    node_id = _new_id()

    record = await client.execute_write_single(
        """
        MATCH (u:User {id: $user_id})

        MERGE (p:Person {name: $name, owner_user_id: $user_id})
        ON CREATE SET
            p.id              = $id,
            p.role            = $role,
            p.sentiment       = $sentiment,
            p.mention_count   = 1,
            p.first_mentioned = datetime(),
            p.last_mentioned  = datetime()
        ON MATCH SET
            p.sentiment       = (p.sentiment + $sentiment) / 2.0,
            p.mention_count   = p.mention_count + 1,
            p.last_mentioned  = datetime()

        MERGE (u)-[r:HAS_RELATIONSHIP_WITH]->(p)
        ON CREATE SET
            r.quality         = $quality,
            r.t_valid         = datetime(),
            r.t_invalid       = null,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE WHEN $message_id IS NULL THEN [] ELSE [$message_id] END
        ON MATCH SET
            r.quality         = $quality,
            r.confidence      = $confidence,
            r.source_session  = $session_id,
            r.source_messages = CASE
                WHEN $message_id IS NULL OR $message_id IN coalesce(r.source_messages, [])
                THEN coalesce(r.source_messages, [])
                ELSE coalesce(r.source_messages, []) + $message_id
            END

        RETURN p.id AS id
        """,
        {
            "user_id":    inp.user_id,
            "session_id": inp.session_id,
            "id":         node_id,
            "name":       inp.name,
            "role":       inp.role,
            "sentiment":  inp.sentiment,
            "quality":    inp.relationship_quality,
            "confidence": inp.confidence,
            "message_id": inp.source_message_id,
        },
    )
    actual_id = record["id"] if record else node_id
    logger.debug("Person upserted: %s (%s)", actual_id, inp.name)
    return actual_id
