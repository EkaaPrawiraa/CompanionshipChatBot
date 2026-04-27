"""
agentic/memory/kg_encryption/kms.py

Envelope-encryption KMS facade.

A real deployment will plug AWS KMS, Google Cloud KMS, or HashiCorp
Vault Transit behind ``KMSClient`` so the master key (KEK) never leaves
the HSM. The Python side only ever sees per-user data encryption keys
(DEKs) wrapped with the KEK; we cache unwrapped DEKs in process for a
short window to keep latency manageable.

The ``LocalDevKMS`` implementation below is for unit tests and local
development. It uses an in-memory KEK and is NOT safe for production.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterator

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@dataclass(frozen=True)
class EnvelopeBackedDEK:
    """
    A data encryption key as it travels through the system.

    Attributes
    ----------
    raw_dek:
        Unwrapped 32-byte AES-256-GCM key. Held in memory only inside
        the trust boundary (the agent process). Never serialised to a
        log, a Neo4j property, or a disk file.
    raw_siv:
        Unwrapped 64-byte AES-SIV key. Used for deterministic
        ciphertexts and blind indexes.
    raw_blind:
        Unwrapped 32-byte HMAC key for ``derive_search_token``.
    version:
        Monotonic counter assigned by the KMS at generation time.
        Stamped into every ciphertext blob so a rotation worker can
        find values still bound to a retired version.
    wrapped_dek:
        Opaque ciphertext returned by the KMS. Persisted in the
        per-user secrets table; the raw_dek can be re-derived only by
        round-tripping this through the KMS again.
    """

    raw_dek:    bytes
    raw_siv:    bytes
    raw_blind:  bytes
    version:    int
    wrapped_dek: bytes


class KMSClient(ABC):
    """
    Abstract envelope-encryption interface.

    A subclass must implement ``generate_dek`` and ``unwrap_dek``;
    everything else is helper logic. ``rotate_dek`` and ``wrap`` are
    optional convenience methods that reuse those two primitives.
    """

    # ------------------------------------------------------------------
    # Abstract primitives
    # ------------------------------------------------------------------

    @abstractmethod
    async def generate_dek(self, user_id: str) -> EnvelopeBackedDEK:
        """
        Ask the KMS to mint a fresh DEK for ``user_id`` and wrap it
        with the KEK. Returns the unwrapped material plus the wrapped
        blob so the caller can persist the wrapped form.
        """

    @abstractmethod
    async def unwrap_dek(
        self, user_id: str, wrapped_dek: bytes, version: int,
    ) -> EnvelopeBackedDEK:
        """
        Unwrap a previously persisted DEK. Used by the cache when the
        in-process entry is missing or expired.
        """

    # ------------------------------------------------------------------
    # Convenience wrappers
    # ------------------------------------------------------------------

    async def rotate_dek(
        self, user_id: str, _previous_version: int,
    ) -> EnvelopeBackedDEK:
        """
        Convenience: mint a new DEK for ``user_id``. The caller is
        responsible for re-encrypting any active ciphertexts that
        still reference the previous version.
        """
        return await self.generate_dek(user_id)


# ---------------------------------------------------------------------------
# Reference in-memory implementation
# ---------------------------------------------------------------------------

class LocalDevKMS(KMSClient):
    """
    In-memory KMS for tests and local dev.

    The KEK is a single 32-byte secret held in process memory. Wrapped
    DEKs are kept in a dict so ``unwrap_dek`` can verify them in
    isolation without a real KMS round-trip.

    Production code MUST replace this with a real KMS-backed client
    (e.g. a thin wrapper around boto3 ``kms.encrypt`` /
    ``kms.decrypt``).
    """

    def __init__(self, kek: bytes | None = None) -> None:
        self._kek: bytes = kek if kek else os.urandom(32)
        # user_id, version -> wrapped_dek_blob
        self._issued: dict[tuple[str, int], bytes] = {}
        self._latest_version: dict[str, int] = {}

    async def generate_dek(self, user_id: str) -> EnvelopeBackedDEK:
        version = self._latest_version.get(user_id, 0) + 1

        # Generate a 96-byte secret: 32 (AEAD) || 64 (SIV).
        # The blind-index key is a third 32-byte slice cut from a
        # separate random draw so the SIV slice is never reused as the
        # blind-index key.
        secret = os.urandom(32 + 64)
        raw_dek   = secret[:32]
        raw_siv   = secret[32:96]
        raw_blind = os.urandom(32)

        wrapped = self._wrap(secret + raw_blind, user_id, version)

        self._issued[(user_id, version)] = wrapped
        self._latest_version[user_id] = version

        return EnvelopeBackedDEK(
            raw_dek=raw_dek,
            raw_siv=raw_siv,
            raw_blind=raw_blind,
            version=version,
            wrapped_dek=wrapped,
        )

    async def unwrap_dek(
        self, user_id: str, wrapped_dek: bytes, version: int,
    ) -> EnvelopeBackedDEK:
        secret = self._unwrap(wrapped_dek, user_id, version)
        raw_dek   = secret[:32]
        raw_siv   = secret[32:96]
        raw_blind = secret[96:128]

        return EnvelopeBackedDEK(
            raw_dek=raw_dek,
            raw_siv=raw_siv,
            raw_blind=raw_blind,
            version=version,
            wrapped_dek=wrapped_dek,
        )

    # --- internal helpers ----------------------------------------------------

    def _wrap(self, raw: bytes, user_id: str, version: int) -> bytes:
        nonce = os.urandom(12)
        aad = self._aad(user_id, version)
        ct = AESGCM(self._kek).encrypt(nonce, raw, aad)
        return nonce + ct

    def _unwrap(self, wrapped: bytes, user_id: str, version: int) -> bytes:
        if len(wrapped) < 12:
            raise ValueError("wrapped DEK blob is too short")
        nonce, ct = wrapped[:12], wrapped[12:]
        aad = self._aad(user_id, version)
        return AESGCM(self._kek).decrypt(nonce, ct, aad)

    @staticmethod
    def _aad(user_id: str, version: int) -> bytes:
        return f"kek/v{version}/u/{user_id}".encode("utf-8")

    # --- test introspection --------------------------------------------------

    def _iter_issued(self) -> Iterator[tuple[tuple[str, int], bytes]]:
        """For tests only: walk every wrapped DEK we have minted."""
        return iter(self._issued.items())
