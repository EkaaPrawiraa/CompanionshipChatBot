"""
agentic/memory/kg_encryption/audit.py

Lightweight audit-trail helpers for the encryption layer.

Every encrypt / decrypt / rotation event should emit an ``AuditEvent``
so the security team can answer "who decrypted user X's Memory.summary
between 03:00 and 03:05?" The implementation here is intentionally
minimal: we log structured records via stdlib logging. The integration
step will replace ``record_event`` with a real sink (Kafka topic,
SIEM appender, or an append-only Postgres table).

The AuditEvent dataclass is the stable schema; the sink is swappable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Optional


logger = logging.getLogger("kg_encryption.audit")


@dataclass(frozen=True)
class AuditEvent:
    """
    A structured record describing one encryption-relevant operation.

    Attributes
    ----------
    action:
        Operation name (e.g. ``encrypt_property``, ``decrypt_property``,
        ``rotate_dek``, ``unwrap_dek``).
    user_id:
        Subject of the encryption operation.
    label:
        Neo4j node label this event refers to. Optional for cache-level
        events that are not bound to a specific label.
    property_name:
        Property name when applicable.
    field_kind:
        ``FieldKind.value`` to keep the audit decoupled from the enum
        import in downstream sinks.
    key_version:
        Version stamp of the DEK that produced or consumed the
        ciphertext. None for events with no key (e.g. PLAINTEXT
        fast path).
    actor:
        Who initiated the call. ``"agent"`` when triggered by the chat
        loop, ``"job:decay"`` for the decay worker, ``"job:rotate"`` for
        the rotation worker, ``"admin"`` for ad-hoc operator scripts.
    request_id:
        Correlation id from the upstream request, when present. Lets us
        tie an audit row back to a specific user message.
    timestamp_ms:
        Wall-clock epoch in milliseconds.
    extra:
        Free-form key-value metadata (e.g. ``{"node_id": "...", "edge_type": "..."}``).
    """

    action:        str
    user_id:       str
    label:         Optional[str] = None
    property_name: Optional[str] = None
    field_kind:    Optional[str] = None
    key_version:   Optional[int] = None
    actor:         str = "agent"
    request_id:    Optional[str] = None
    timestamp_ms:  int = field(default_factory=lambda: int(time.time() * 1000))
    extra:         dict = field(default_factory=dict)


def record_event(event: AuditEvent) -> None:
    """
    Default sink: emit the event as a single-line JSON record on the
    ``kg_encryption.audit`` logger.

    Replace this body with a Kafka producer, a SIEM appender, or an
    append-only Postgres insert when wiring the encryption layer into
    production.
    """
    payload = json.dumps(asdict(event), separators=(",", ":"), sort_keys=True)
    logger.info(payload)


def record_decrypt(
    user_id: str,
    label: str,
    property_name: str,
    *,
    key_version: int,
    actor: str = "agent",
    request_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """Convenience wrapper for the most common audit case."""
    record_event(AuditEvent(
        action="decrypt_property",
        user_id=user_id,
        label=label,
        property_name=property_name,
        key_version=key_version,
        actor=actor,
        request_id=request_id,
        extra=extra or {},
    ))


def record_encrypt(
    user_id: str,
    label: str,
    property_name: str,
    *,
    field_kind: str,
    key_version: int,
    actor: str = "agent",
    request_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """Sibling of ``record_decrypt`` for write-side audit."""
    record_event(AuditEvent(
        action="encrypt_property",
        user_id=user_id,
        label=label,
        property_name=property_name,
        field_kind=field_kind,
        key_version=key_version,
        actor=actor,
        request_id=request_id,
        extra=extra or {},
    ))


def record_rotation(
    user_id: str,
    *,
    old_version: int,
    new_version: int,
    actor: str = "job:rotate",
    extra: dict | None = None,
) -> None:
    """Audit a DEK rotation."""
    record_event(AuditEvent(
        action="rotate_dek",
        user_id=user_id,
        key_version=new_version,
        actor=actor,
        extra={
            "old_version": old_version,
            "new_version": new_version,
            **(extra or {}),
        },
    ))
