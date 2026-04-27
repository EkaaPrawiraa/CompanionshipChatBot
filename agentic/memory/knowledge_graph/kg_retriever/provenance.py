"""
agentic/memory/kg_retriever/provenance.py

Reverse lookups: "which KG facts came from this message?"

Every writer stamps ``source_messages: [<message_id>]`` onto the user
anchor edge it produces. This module exposes two helpers that walk
that provenance chain:

    facts_for_message(message_id)
        Return every active edge whose source_messages list includes
        the given message id, with both endpoints denormalised.

    nodes_for_message(message_id)
        Return the distinct node ids touched by that message, paired
        with their label.

Both are used by the deleter and modifier modules to scope their
work, and by the chat client to display "what did you remember from
this message?" alongside the user's edited message.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic.memory.neo4j_client import get_client

logger = logging.getLogger(__name__)


async def facts_for_message(message_id: str) -> list[dict[str, Any]]:
    """
    Return one row per active edge that lists ``message_id`` in its
    ``source_messages`` array.
    """
    if not message_id:
        raise ValueError("message_id is required")

    return await get_client().execute_read(
        """
        MATCH (src)-[r]->(dst)
        WHERE $message_id IN coalesce(r.source_messages, [])
          AND r.t_invalid IS NULL
        RETURN labels(src)         AS src_labels,
               src.id              AS src_id,
               type(r)             AS edge_type,
               r.confidence        AS confidence,
               r.source_session    AS source_session,
               r.source_messages   AS source_messages,
               labels(dst)         AS dst_labels,
               dst.id              AS dst_id
        ORDER BY src.id, dst.id
        """,
        {"message_id": message_id},
    )


async def nodes_for_message(message_id: str) -> list[dict[str, Any]]:
    """
    Distinct node ids touched by ``message_id``, with their primary
    label and active flag.
    """
    if not message_id:
        raise ValueError("message_id is required")

    return await get_client().execute_read(
        """
        MATCH ()-[r]->(n)
        WHERE $message_id IN coalesce(r.source_messages, [])
          AND r.t_invalid IS NULL
        RETURN DISTINCT n.id         AS id,
                        labels(n)    AS labels,
                        n.active     AS active
        """,
        {"message_id": message_id},
    )
