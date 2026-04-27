"""
agentic/memory/kg_encryption/siv.py

Deterministic encryption helpers built on AES-SIV (RFC 5297).

When a property must be queryable by exact match (e.g. dedup checks
on Trigger.description prefix, MERGE on Person.name) the writer cannot
afford a fresh nonce per encryption: identical plaintexts must produce
identical ciphertexts. AES-SIV gives that property while still
authenticating the ciphertext, so the resulting "blind index" is safe
to store as a graph property and safe to compare with equality.

For broader keyword search (LIKE / CONTAINS), prefer
``derive_search_token`` which derives an HMAC-based token instead of
storing the SIV ciphertext itself.

Tradeoffs (called out in the threat model doc):
    * Equality leakage: an attacker who reads two SIV-encrypted
      properties learns whether they share a plaintext. This is the
      whole point and acceptable for blind indexes.
    * Dictionary attacks: a low-entropy field (e.g. emotion label out of
      a 50-word vocabulary) with a stable key allows an offline
      dictionary attack if the attacker also gets the DEK. Always
      combine SIV with a per-user DEK so attacking one user does not
      reveal another user's labels.

References
    Rogaway and Shrimpton, 2006     The SIV mode and its security
    Curtmola et al, 2006            Searchable symmetric encryption
"""

from __future__ import annotations

import base64
import hmac
import hashlib
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESSIV


_MAGIC: bytes = b"KGS1"
_FORMAT_VERSION: int = 1


def encrypt_field_deterministic(
    plaintext: str,
    dek_siv: bytes,
    *,
    key_version: int = 1,
    associated_data: bytes | None = None,
) -> str:
    """
    Deterministically encrypt ``plaintext`` with AES-SIV under
    ``dek_siv`` (must be 64 bytes; AES-SIV concatenates a MAC key and a
    cipher key).

    The same (plaintext, DEK, AAD) triple always yields the same
    ciphertext, which is what enables exact-match queries against
    encrypted properties.

    Args:
        plaintext:        UTF-8 string.
        dek_siv:          64-byte SIV key (NOT the same secret as the
                          AEAD DEK; the DEK cache returns both).
        key_version:      Stamped into the blob for rotation.
        associated_data:  Optional AAD. When provided, identical
                          plaintexts under different AAD produce
                          different ciphertexts. Pack the same triple
                          you use for AEAD: (user_id, label, property).

    Returns:
        Base64-url-safe string.
    """
    _check_dek(dek_siv)
    cipher = AESSIV(dek_siv)
    aad_list: list[bytes] = [associated_data] if associated_data else []
    ct = cipher.encrypt(plaintext.encode("utf-8"), aad_list)
    header = _MAGIC + struct.pack(">BB", _FORMAT_VERSION, key_version & 0xFF)
    return base64.urlsafe_b64encode(header + ct).decode("ascii")


def decrypt_field_deterministic(
    blob: str,
    dek_siv: bytes,
    *,
    associated_data: bytes | None = None,
) -> str:
    """
    Inverse of ``encrypt_field_deterministic``. Verifies the SIV tag.
    """
    _check_dek(dek_siv)
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    if len(raw) < len(_MAGIC) + 2:
        raise ValueError("ciphertext blob is too short")
    if raw[: len(_MAGIC)] != _MAGIC:
        raise ValueError("unexpected magic prefix on SIV blob")

    fmt_version = raw[len(_MAGIC)]
    if fmt_version != _FORMAT_VERSION:
        raise ValueError(f"unsupported SIV blob version {fmt_version}")

    ct = raw[len(_MAGIC) + 2:]
    cipher = AESSIV(dek_siv)
    aad_list: list[bytes] = [associated_data] if associated_data else []
    return cipher.decrypt(ct, aad_list).decode("utf-8")


def derive_search_token(
    plaintext: str,
    dek_blind: bytes,
    *,
    domain: str = "search",
) -> str:
    """
    Produce a deterministic HMAC-based blind index for ``plaintext``.

    Use this when you need a probe value that lives next to the
    encrypted field and lets the writer ask "do we already have a
    Trigger whose description tokenises to X?" without ever decrypting.

    The ``domain`` separator stops a token derived for one purpose
    (e.g. exact match) from being substituted into another (e.g. an
    n-gram search) under the same DEK.

    Returns:
        Hex-encoded 32-byte token.
    """
    if not isinstance(dek_blind, (bytes, bytearray)) or len(dek_blind) < 32:
        raise ValueError("blind-index DEK must be at least 32 bytes")
    msg = domain.encode("utf-8") + b"\x00" + plaintext.encode("utf-8")
    return hmac.new(bytes(dek_blind), msg, hashlib.sha256).hexdigest()


def _check_dek(dek_siv: bytes) -> None:
    """AES-SIV requires either 32 or 64 byte keys; we standardise on 64."""
    if not isinstance(dek_siv, (bytes, bytearray)) or len(dek_siv) not in (32, 64):
        raise ValueError(
            f"AES-SIV requires a 32 or 64-byte key; got {len(dek_siv)} bytes"
        )
