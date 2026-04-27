"""
agentic/memory/pg_vector/embeddings.py

Thin wrapper around the embedding model. Single seam so swapping
between OpenAI ``text-embedding-3-small`` and a self-hosted
``multilingual-e5-large`` (DevNotes v1.3, Section 1.2) does not
ripple through the writers.

Online path
-----------
If the OpenAI client is importable AND ``OPENAI_API_KEY`` is set,
calls hit ``text-embedding-3-small`` (1536 dim). The synchronous
client is wrapped in ``asyncio.to_thread`` to keep the API consistent
with the rest of the package.

Offline path
------------
If either condition fails the function returns a deterministic stub
vector seeded by the input text's SHA-256. The stub is unit-norm and
length-1536 so the rest of the pipeline (HNSW insert, cosine search)
keeps working in dev / CI without network access. The stub is NOT
semantically meaningful; production must run with the real model.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import struct
from typing import Iterable

logger = logging.getLogger(__name__)

EMBED_DIM:   int = 1536
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-3-small")


# ---------------------------------------------------------------------------
# Online: OpenAI text-embedding-3-small
# ---------------------------------------------------------------------------

_openai_client = None
_online_disabled: bool = False


def _try_get_openai_client():
    """Lazy-load the OpenAI client. Returns None if unavailable."""
    global _openai_client, _online_disabled
    if _online_disabled:
        return None
    if _openai_client is not None:
        return _openai_client
    if not os.getenv("OPENAI_API_KEY"):
        _online_disabled = True
        return None
    try:
        from openai import OpenAI  # type: ignore[import-not-found]
        _openai_client = OpenAI()
        return _openai_client
    except ImportError:
        logger.warning(
            "openai not installed; falling back to deterministic stub "
            "embeddings. Install with: pip install openai"
        )
        _online_disabled = True
        return None


def _embed_online(text: str) -> list[float] | None:
    client = _try_get_openai_client()
    if client is None:
        return None
    try:
        resp = client.embeddings.create(input=text, model=EMBED_MODEL)
        return list(resp.data[0].embedding)
    except Exception as exc:
        logger.warning(
            "OpenAI embed call failed (%s). Falling back to stub.", exc,
        )
        return None


# ---------------------------------------------------------------------------
# Offline: deterministic stub vector
# ---------------------------------------------------------------------------

def _embed_offline(text: str) -> list[float]:
    """
    Deterministic, unit-norm vector derived from the SHA-256 of the
    input. Used only when the OpenAI path is unavailable. Different
    texts produce different vectors; identical texts produce identical
    vectors. Useful enough for local development and CI; not useful
    for production semantic retrieval.
    """
    seed = hashlib.sha256(text.encode("utf-8")).digest()
    raw: list[float] = []
    for i in range(EMBED_DIM):
        block = hashlib.sha256(seed + i.to_bytes(4, "big")).digest()[:8]
        as_int = struct.unpack(">q", block)[0]
        raw.append(as_int / (2 ** 63))
    norm = math.sqrt(sum(x * x for x in raw)) or 1.0
    return [x / norm for x in raw]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def embed_text(text: str) -> list[float]:
    """
    Return an embedding vector of length EMBED_DIM for ``text``.

    Tries OpenAI first; falls back to the offline stub on any failure
    so callers never have to handle None.
    """
    if not text or not text.strip():
        return [0.0] * EMBED_DIM

    online = await asyncio.to_thread(_embed_online, text)
    if online is not None:
        return online
    return _embed_offline(text)


async def embed_many(texts: Iterable[str]) -> list[list[float]]:
    """Convenience wrapper for batch embeds; one call per text."""
    return [await embed_text(t) for t in texts]
