"""
agentic/memory/kg_encryption

Standalone encryption layer for the knowledge graph.

This package is intentionally not wired into the writer / reader call
sites yet. The plan is to compose the encryption layer into the
kg_writer and kg_retriever pipelines once the core graph behaviour is
stable. Until then, every helper here can be unit-tested in isolation.

Public surface
--------------
KMS layer
    KMSClient                 : abstract envelope-encryption interface
    LocalDevKMS               : in-memory KMS for tests / dev
    EnvelopeBackedDEK         : (raw_dek, version, wrapped_dek)

Per-user DEK cache
    DEKCache                  : async LRU cache around KMSClient
    get_default_cache         : module-level singleton accessor
    set_default_cache         : override for tests

Field-level codecs
    encrypt_field_random      : AES-256-GCM (CONFIDENTIAL fields)
    decrypt_field_random
    encrypt_field_deterministic : AES-SIV (INDEXABLE_CONFIDENTIAL)
    decrypt_field_deterministic
    derive_search_token       : deterministic blind index for keyword search

High-level dispatcher
    FieldKind                 : PLAINTEXT, CONFIDENTIAL,
                                INDEXABLE_CONFIDENTIAL, EMBEDDING
    encode_for_property       : one-shot encrypt by FieldKind
    decode_for_property       : one-shot decrypt by FieldKind

Embedding protection
    protect_embedding         : envelope-encrypt a vector blob
    recover_embedding
    quantize_embedding        : coarse-grain to mitigate inversion attacks

Field policy registry
    FIELD_POLICY              : (label, property) to FieldKind mapping
    classify                  : helper to classify a property for a label

Audit
    AuditEvent                : envelope-style audit record dataclass
    record_event              : structured logger; replace with sink later
"""

from __future__ import annotations

from agentic.memory.knowledge_graph.kg_encryption.aead import (
    encrypt_field_random,
    decrypt_field_random,
)
from agentic.memory.knowledge_graph.kg_encryption.siv import (
    encrypt_field_deterministic,
    decrypt_field_deterministic,
    derive_search_token,
)
from agentic.memory.knowledge_graph.kg_encryption.kms import (
    KMSClient,
    LocalDevKMS,
    EnvelopeBackedDEK,
)
from agentic.memory.knowledge_graph.kg_encryption.dek_cache import (
    DEKCache,
    get_default_cache,
    set_default_cache,
)
from agentic.memory.knowledge_graph.kg_encryption.field_codec import (
    FieldKind,
    encode_for_property,
    decode_for_property,
)
from agentic.memory.knowledge_graph.kg_encryption.embedding_guard import (
    protect_embedding,
    recover_embedding,
    quantize_embedding,
)
from agentic.memory.knowledge_graph.kg_encryption.policy import (
    FIELD_POLICY,
    classify,
)
from agentic.memory.knowledge_graph.kg_encryption.audit import (
    AuditEvent,
    record_event,
)


__all__ = [
    # AEAD
    "encrypt_field_random",
    "decrypt_field_random",
    # SIV
    "encrypt_field_deterministic",
    "decrypt_field_deterministic",
    "derive_search_token",
    # KMS
    "KMSClient",
    "LocalDevKMS",
    "EnvelopeBackedDEK",
    # DEK cache
    "DEKCache",
    "get_default_cache",
    "set_default_cache",
    # Field codec
    "FieldKind",
    "encode_for_property",
    "decode_for_property",
    # Embedding
    "protect_embedding",
    "recover_embedding",
    "quantize_embedding",
    # Policy
    "FIELD_POLICY",
    "classify",
    # Audit
    "AuditEvent",
    "record_event",
]
