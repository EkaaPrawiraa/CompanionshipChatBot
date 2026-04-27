"""
agentic/memory/kg_encryption/field_codec.py

High-level dispatcher that maps a ``FieldKind`` to the right cipher.

Callers in the writer / reader pipelines should not have to know
whether ``Person.name`` is deterministically encrypted or whether
``Memory.summary`` uses random AEAD: they ask the codec to encode or
decode and pass a ``FieldKind`` so the codec picks the right primitive.

Wire format
-----------
Plaintext fields go through unchanged.

Encrypted fields are stored as the base64 blob produced by
``aead.encrypt_field_random`` or ``siv.encrypt_field_deterministic``.
A small magic prefix in the blob tells the decoder which cipher
produced it; that magic is enforced by the underlying modules so the
codec stays simple.

Embedding fields are structured (a list of floats), so the codec hands
them off to ``embedding_guard`` rather than re-implementing the
per-vector logic here.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from agentic.memory.knowledge_graph.kg_encryption.aead import (
    encrypt_field_random,
    decrypt_field_random,
)
from agentic.memory.knowledge_graph.kg_encryption.siv import (
    encrypt_field_deterministic,
    decrypt_field_deterministic,
)
from agentic.memory.knowledge_graph.kg_encryption.embedding_guard import (
    protect_embedding,
    recover_embedding,
)
from agentic.memory.knowledge_graph.kg_encryption.kms import EnvelopeBackedDEK


class FieldKind(str, Enum):
    """
    Encryption category for a graph property.

    PLAINTEXT
        Stored as-is. Allowed for low-risk fields like timestamps, UUIDs,
        bounded numeric scalars (intensity in [0,1]).

    CONFIDENTIAL
        AES-256-GCM with a fresh nonce per write. Use for free-form text
        that is never queried by exact value (Memory.summary,
        Experience.description, Thought.content).

    INDEXABLE_CONFIDENTIAL
        AES-SIV deterministic. Use for fields that need exact-match
        equality on the server (Person.name, Trigger.description prefix,
        Topic.id mapping). Equality between two ciphertexts of the same
        DEK is observable; this is the price of indexability.

    EMBEDDING
        Vector embeddings. Routed through embedding_guard which decides
        whether to encrypt the whole vector at rest or keep a reduced
        version for vector-similarity retrieval. See the encryption
        documentation for the tradeoffs.
    """

    PLAINTEXT              = "plaintext"
    CONFIDENTIAL           = "confidential"
    INDEXABLE_CONFIDENTIAL = "indexable_confidential"
    EMBEDDING              = "embedding"


def encode_for_property(
    value: Any,
    kind: FieldKind,
    dek: EnvelopeBackedDEK,
    *,
    associated_data: bytes | None = None,
) -> Any:
    """
    Encode ``value`` according to the field's ``kind``.

    PLAINTEXT pass-through is intentional so callers can route every
    property through this dispatcher uniformly. None values are also
    returned unchanged because Neo4j happily stores nulls.
    """
    if value is None:
        return None

    if kind is FieldKind.PLAINTEXT:
        return value

    if kind is FieldKind.CONFIDENTIAL:
        if not isinstance(value, str):
            raise TypeError("CONFIDENTIAL fields must be strings before encryption")
        return encrypt_field_random(
            value,
            dek.raw_dek,
            key_version=dek.version,
            associated_data=associated_data,
        )

    if kind is FieldKind.INDEXABLE_CONFIDENTIAL:
        if not isinstance(value, str):
            raise TypeError(
                "INDEXABLE_CONFIDENTIAL fields must be strings before encryption"
            )
        return encrypt_field_deterministic(
            value,
            dek.raw_siv,
            key_version=dek.version,
            associated_data=associated_data,
        )

    if kind is FieldKind.EMBEDDING:
        if not isinstance(value, list):
            raise TypeError("EMBEDDING fields must be a list of floats")
        return protect_embedding(value, dek)

    raise ValueError(f"unsupported FieldKind: {kind}")


def decode_for_property(
    blob: Any,
    kind: FieldKind,
    dek: EnvelopeBackedDEK,
    *,
    associated_data: bytes | None = None,
) -> Any:
    """
    Reverse of ``encode_for_property``.

    The decoder must be told the FieldKind so it knows which primitive
    to invoke. Since the wire formats include their own magic prefixes,
    a malformed blob will raise rather than silently misinterpret bytes
    from a different cipher.
    """
    if blob is None:
        return None

    if kind is FieldKind.PLAINTEXT:
        return blob

    if kind is FieldKind.CONFIDENTIAL:
        return decrypt_field_random(
            blob, dek.raw_dek, associated_data=associated_data,
        )

    if kind is FieldKind.INDEXABLE_CONFIDENTIAL:
        return decrypt_field_deterministic(
            blob, dek.raw_siv, associated_data=associated_data,
        )

    if kind is FieldKind.EMBEDDING:
        return recover_embedding(blob, dek)

    raise ValueError(f"unsupported FieldKind: {kind}")
