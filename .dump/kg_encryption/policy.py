"""
agentic/memory/kg_encryption/policy.py

Policy registry: which property on which node label gets which
``FieldKind``.

Treat this as the single source of truth for the encryption posture of
the graph. The integration step will read it when wiring the writers
and readers; the audit log uses it to flag unexpected fields.

Conventions
-----------
* Properties listed under a label are encrypted using the matching
  FieldKind. Properties NOT listed default to ``FieldKind.PLAINTEXT``.
* Numeric scalars and timestamps are kept plaintext; encrypting them
  defeats indexing without a meaningful confidentiality gain because
  their value space is small and frequency-stable.
* Free-form text and labels go through CONFIDENTIAL.
* Anything used by Cypher equality (id, name, role) goes through
  INDEXABLE_CONFIDENTIAL so we can still MERGE on it.
* Embeddings are routed through ``FieldKind.EMBEDDING`` and the
  embedding_guard module decides exact behaviour.
"""

from __future__ import annotations

from agentic.memory.knowledge_graph.kg_encryption.field_codec import FieldKind


# ---------------------------------------------------------------------------
# (Label, property) -> FieldKind
#
# Reflects the canonical KG schema and the encryption documentation in
# docs/security/kg_encryption.docx, section "Field categorisation".
# ---------------------------------------------------------------------------

FIELD_POLICY: dict[str, dict[str, FieldKind]] = {
    "User": {
        # User.id is owned by the Go service and stays plaintext for
        # cross-service joins. Display fields, when present, are
        # confidential.
        "display_name":      FieldKind.CONFIDENTIAL,
        "email_blind_index": FieldKind.INDEXABLE_CONFIDENTIAL,
    },
    "Session": {
        # Session timestamps stay plaintext for windowed queries.
        "summary":           FieldKind.CONFIDENTIAL,
    },
    "Experience": {
        "description":       FieldKind.CONFIDENTIAL,
        "embedding":         FieldKind.EMBEDDING,
        "sensitivity_level": FieldKind.PLAINTEXT,
    },
    "Emotion": {
        "label":              FieldKind.INDEXABLE_CONFIDENTIAL,
        "source_text":        FieldKind.CONFIDENTIAL,
        "sensitivity_level":  FieldKind.PLAINTEXT,
    },
    "Thought": {
        "content":           FieldKind.CONFIDENTIAL,
        "thought_type":      FieldKind.INDEXABLE_CONFIDENTIAL,
        "distortion":        FieldKind.INDEXABLE_CONFIDENTIAL,
        "embedding":         FieldKind.EMBEDDING,
        "sensitivity_level": FieldKind.PLAINTEXT,
    },
    "Trigger": {
        "category":          FieldKind.INDEXABLE_CONFIDENTIAL,
        "description":       FieldKind.CONFIDENTIAL,
        "aliases":           FieldKind.CONFIDENTIAL,
        "sensitivity_level": FieldKind.PLAINTEXT,
    },
    "Behavior": {
        "description":       FieldKind.CONFIDENTIAL,
        "category":          FieldKind.INDEXABLE_CONFIDENTIAL,
        "sensitivity_level": FieldKind.PLAINTEXT,
    },
    "Person": {
        "name":               FieldKind.INDEXABLE_CONFIDENTIAL,
        "role":               FieldKind.INDEXABLE_CONFIDENTIAL,
        "relationship_quality": FieldKind.INDEXABLE_CONFIDENTIAL,
        "sensitivity_level":  FieldKind.PLAINTEXT,
    },
    "Memory": {
        "summary":           FieldKind.CONFIDENTIAL,
        "embedding":         FieldKind.EMBEDDING,
        "sensitivity_level": FieldKind.PLAINTEXT,
    },
    "Topic": {
        # Topic is a shared catalog. Its name stays plaintext for
        # cross-user analytics; per-user edges into Topic carry no
        # plaintext beyond timestamps.
        "name": FieldKind.PLAINTEXT,
    },
}


def classify(label: str, property_name: str) -> FieldKind:
    """
    Look up the ``FieldKind`` for a (label, property) pair.

    Unknown pairs default to ``PLAINTEXT`` so writers do not fail on
    new properties; emit a structured audit event upstream so the
    policy can be reviewed before launch.
    """
    label_policy = FIELD_POLICY.get(label, {})
    return label_policy.get(property_name, FieldKind.PLAINTEXT)
