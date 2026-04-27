"""
agentic/memory/kg_algorithm/_common.py

Internal helpers for the algorithmic graph operations.

We re-implement the tiny ``_new_id`` / ``_require`` helpers locally
instead of importing them from kg_writer/_common. That keeps the
dependency direction pointing the right way:

    kg_writer  --> kg_algorithm   (writers can call supersede_thought)
    kg_writer  --> kg_retriever   (writers share schemas)
    kg_writer  --> kg_modifier    (writers can patch nodes)

Without ever the reverse. ``kg_algorithm`` is allowed to depend on
``kg_retriever`` for shared dataclasses (we use ThoughtInput in
supersession.py) but should not depend on kg_writer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    """Current UTC timestamp as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Fresh UUID4 as a string. Used as the ``id`` property on every node."""
    return str(uuid.uuid4())


def _require(value: Any, field_name: str) -> Any:
    """
    Application-layer null check. Raises before any DB call is issued.

    Mirror of ``kg_writer._common._require`` so kg_algorithm can stay
    standalone.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"Required field '{field_name}' is None or empty")
    return value
