"""
agentic/memory/kg_encryption/dek_cache.py

Per-user data-encryption-key cache.

The KMS round-trip (envelope unwrap) is the slowest hop in the
encryption pipeline. We cache unwrapped DEKs in process memory keyed by
``user_id`` for a short TTL (default 5 minutes) so a chat session does
not pay the unwrap cost on every property write.

The cache is async-safe: concurrent reads for the same user share a
single in-flight unwrap via ``asyncio.Lock``.

Operational concerns
--------------------
* TTL is intentionally short. A long-running agent process should not
  hold a user's DEK longer than a single conversation window. The
  ``evict`` method exists so the session-end hook can flush the entry
  proactively.
* Memory hardening (mlock, secure zero) is out of scope here; the
  cryptography library returns plain bytes and Python does not give us
  a portable way to scrub them. The trust boundary is the agent
  process, so we accept that risk.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from agentic.memory.knowledge_graph.kg_encryption.kms import (
    EnvelopeBackedDEK,
    KMSClient,
    LocalDevKMS,
)


# ---------------------------------------------------------------------------
# DEKCache
# ---------------------------------------------------------------------------

class DEKCache:
    """
    Async LRU-ish cache around a ``KMSClient`` with TTL eviction.

    Use ``get_or_create`` for the common hot path: it returns the
    current DEK for a user, minting one on first call.
    """

    def __init__(
        self,
        kms: KMSClient,
        ttl_seconds: float = 300.0,
        max_entries: int = 1024,
    ) -> None:
        self._kms = kms
        self._ttl = ttl_seconds
        self._max = max_entries

        # user_id -> (deadline_epoch, dek)
        self._entries: dict[str, tuple[float, EnvelopeBackedDEK]] = {}
        # user_id -> wrapped_dek persisted by the secrets store. In
        # production this should come from a database, not the cache.
        self._wrapped_store: dict[str, tuple[int, bytes]] = {}

        # One lock per user prevents thundering-herd unwraps during
        # concurrent message handling.
        self._locks: dict[str, asyncio.Lock] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_or_create(self, user_id: str) -> EnvelopeBackedDEK:
        """
        Return the active DEK for ``user_id``. Creates one if the user
        has never had a DEK before; refreshes from KMS if the cached
        entry has expired.
        """
        cached = self._get_fresh(user_id)
        if cached is not None:
            return cached

        async with self._lock_for(user_id):
            # Re-check inside the lock (another waiter may have just
            # populated the entry).
            cached = self._get_fresh(user_id)
            if cached is not None:
                return cached

            persisted = self._wrapped_store.get(user_id)
            if persisted is None:
                dek = await self._kms.generate_dek(user_id)
                self._wrapped_store[user_id] = (dek.version, dek.wrapped_dek)
            else:
                version, wrapped = persisted
                dek = await self._kms.unwrap_dek(user_id, wrapped, version)

            self._store(user_id, dek)
            return dek

    async def rotate(self, user_id: str) -> EnvelopeBackedDEK:
        """
        Mint a fresh DEK for the user. The caller is responsible for
        re-encrypting properties that still carry the old version.
        """
        async with self._lock_for(user_id):
            previous = self._wrapped_store.get(user_id)
            previous_version = previous[0] if previous else 0
            new_dek = await self._kms.rotate_dek(user_id, previous_version)
            self._wrapped_store[user_id] = (new_dek.version, new_dek.wrapped_dek)
            self._store(user_id, new_dek)
            return new_dek

    def evict(self, user_id: str) -> None:
        """Drop the in-memory DEK so the next access has to unwrap again."""
        self._entries.pop(user_id, None)

    def evict_all(self) -> None:
        """Flush the entire cache. Intended for shutdown hooks and tests."""
        self._entries.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_fresh(self, user_id: str) -> Optional[EnvelopeBackedDEK]:
        entry = self._entries.get(user_id)
        if entry is None:
            return None
        deadline, dek = entry
        if time.monotonic() >= deadline:
            self._entries.pop(user_id, None)
            return None
        return dek

    def _store(self, user_id: str, dek: EnvelopeBackedDEK) -> None:
        self._evict_if_full()
        self._entries[user_id] = (time.monotonic() + self._ttl, dek)

    def _evict_if_full(self) -> None:
        if len(self._entries) < self._max:
            return
        # Drop the entry whose deadline is closest to now (approximates
        # LRU without tracking access order).
        oldest_user = min(self._entries, key=lambda u: self._entries[u][0])
        self._entries.pop(oldest_user, None)

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        lock = self._locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[user_id] = lock
        return lock


# ---------------------------------------------------------------------------
# Module-level singleton accessors
#
# The integration step will replace ``_default`` with a real KMS-backed
# cache (probably constructed from settings during app startup). For
# now, callers that touch the encryption layer directly will get a
# LocalDevKMS singleton, which is fine for unit tests.
# ---------------------------------------------------------------------------

_default: DEKCache | None = None


def get_default_cache() -> DEKCache:
    """Return the process-wide DEK cache, lazy-initialising on first call."""
    global _default
    if _default is None:
        _default = DEKCache(kms=LocalDevKMS())
    return _default


def set_default_cache(cache: DEKCache | None) -> None:
    """
    Override the default cache. Call ``set_default_cache(None)`` to
    force lazy re-initialisation on the next ``get_default_cache``.
    """
    global _default
    _default = cache
