"""
agentic/memory/kg_encryption/aead.py

AES-256-GCM authenticated encryption for confidential graph properties.

This is the default cipher for any field that does NOT need to be
queried by exact value. Each call uses a fresh 96-bit random nonce so
two encryptions of the same plaintext produce different ciphertexts;
this is what blocks frequency analysis of mood labels, distortion
labels, and other low-entropy strings.

The output blob layout is a single, self-describing byte string so the
consumer never has to remember which fields are nonce vs ciphertext:

    blob := MAGIC (4B) | VERSION (1B) | KEY_VERSION (1B) | NONCE (12B) | CIPHERTEXT_AND_TAG

The blob is base64-url-safe encoded before being stored on a Neo4j
property because Neo4j string properties are UTF-8 and arbitrary bytes
are not safe to round-trip there.

References
    NIST SP 800-38D                AES-GCM specification
    Bellare and Namprempre 2008    AEAD security definitions
"""

from __future__ import annotations

import base64
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# 4-byte ASCII magic identifies blobs produced by this module.
_MAGIC: bytes = b"KGE1"
# Bumped when the wire format changes.
_FORMAT_VERSION: int = 1
# 12 bytes is the NIST-recommended nonce length for GCM.
_NONCE_LEN: int = 12


def encrypt_field_random(
    plaintext: str,
    dek: bytes,
    *,
    key_version: int = 1,
    associated_data: bytes | None = None,
) -> str:
    """
    Encrypt ``plaintext`` with AES-256-GCM under ``dek`` (32 bytes).

    Args:
        plaintext:        UTF-8 string to encrypt. Empty strings are
                          allowed and produce a deterministic-length
                          ciphertext (header + tag only).
        dek:              32-byte data encryption key.
        key_version:      Stamped into the blob so future rotations can
                          identify which DEK encrypted this value
                          without trial-decrypting all live keys.
        associated_data:  Optional AAD bound into the GCM tag. Use the
                          tuple (user_id, label, property) packed as
                          UTF-8 bytes to prevent ciphertext shuffling
                          between fields.

    Returns:
        Base64-url-safe string suitable for storing on a Neo4j property.

    Raises:
        ValueError: if ``dek`` is not 32 bytes long.
    """
    _check_dek(dek)
    nonce = os.urandom(_NONCE_LEN)
    cipher = AESGCM(dek)
    ct_and_tag = cipher.encrypt(nonce, plaintext.encode("utf-8"), associated_data)

    header = _MAGIC + struct.pack(">BB", _FORMAT_VERSION, key_version & 0xFF)
    blob = header + nonce + ct_and_tag
    return base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt_field_random(
    blob: str,
    dek: bytes,
    *,
    associated_data: bytes | None = None,
) -> str:
    """
    Inverse of ``encrypt_field_random``. Verifies the GCM tag and
    returns the original UTF-8 plaintext.

    Raises:
        ValueError:  bad blob format or wrong magic.
        InvalidTag:  AAD or DEK does not match what was used to encrypt.
    """
    _check_dek(dek)
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    if len(raw) < len(_MAGIC) + 2 + _NONCE_LEN:
        raise ValueError("ciphertext blob is too short")

    magic = raw[: len(_MAGIC)]
    if magic != _MAGIC:
        raise ValueError(f"unexpected magic prefix: {magic!r}")

    fmt_version, _key_version = struct.unpack(">BB", raw[len(_MAGIC): len(_MAGIC) + 2])
    if fmt_version != _FORMAT_VERSION:
        raise ValueError(f"unsupported AEAD blob version {fmt_version}")

    offset = len(_MAGIC) + 2
    nonce = raw[offset: offset + _NONCE_LEN]
    ciphertext = raw[offset + _NONCE_LEN:]

    cipher = AESGCM(dek)
    plaintext = cipher.decrypt(nonce, ciphertext, associated_data)
    return plaintext.decode("utf-8")


def parse_key_version(blob: str) -> int:
    """
    Extract the key_version byte from a blob without performing a
    decryption. Used by the rotation worker to find ciphertexts still
    bound to a retired DEK.
    """
    raw = base64.urlsafe_b64decode(blob.encode("ascii"))
    if len(raw) < len(_MAGIC) + 2 or raw[: len(_MAGIC)] != _MAGIC:
        raise ValueError("not a kg_encryption AEAD blob")
    return raw[len(_MAGIC) + 1]


def _check_dek(dek: bytes) -> None:
    if not isinstance(dek, (bytes, bytearray)) or len(dek) != 32:
        raise ValueError(
            f"AES-256-GCM requires a 32-byte DEK; got {len(dek)} bytes"
        )
