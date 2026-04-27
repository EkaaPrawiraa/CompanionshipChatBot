"""
agentic/memory/kg_modifier/update_node.py

Generic surgical-patch helper for any derived node.

Used by:
    * The per-label wrappers in ``per_node.py``.
    * Out-of-band scripts that already know the label and id of the
      node they want to fix.

Safety
------
Both ``label`` and the property names are validated against the
allow-lists in ``_common.py`` before they are interpolated into the
Cypher string. Property values are passed via parameters and never
interpolated.

The function returns the number of nodes affected (0 if no match,
1 on success). If the caller needs the freshly-updated property bag,
follow up with a ``kg_retriever.read_<label>(node_id)`` call.
"""

from __future__ import annotations

import logging
from typing import Any

from agentic.memory.neo4j_client import get_client
from agentic.memory.knowledge_graph.kg_modifier._common import (
    validate_label,
    validate_updates,
)

logger = logging.getLogger(__name__)


async def update_node_property(
    label: str,
    node_id: str,
    updates: dict[str, Any],
) -> int:
    """
    Surgically update one or more properties on an existing derived
    node. Returns the number of nodes affected (0 on miss, 1 on hit).

    Args:
        label:    Neo4j label, validated against ``DERIVED_LABELS``.
        node_id:  Stable UUID4 of the node.
        updates:  property -> new-value. Only keys in
                  ``UPDATABLE_PROPERTIES[label]`` are accepted.

    Raises:
        ValueError: bad label, empty / illegal updates, missing id.
    """
    label = validate_label(label)
    if not node_id:
        raise ValueError("node_id is required")
    validate_updates(label, updates)

    client = get_client()

    # The property names come from the closed allow-list above so they
    # are safe to interpolate. The values flow through parameters.
    set_clauses = ", ".join(
        f"n.{prop} = $updates.{prop}" for prop in updates
    )
    query = (
        f"""
        MATCH (n:{label} {{id: $id}})
        SET {set_clauses},
            n.updated_at = datetime()
        RETURN count(n) AS updated
        """
    )

    result = await client.execute_write(
        query,
        {"id": node_id, "updates": updates},
    )
    updated = result[0]["updated"] if result else 0
    logger.info(
        "update_node_property(%s, %s, %s) -> %d updated",
        label, node_id, sorted(updates), updated,
    )
    return updated
