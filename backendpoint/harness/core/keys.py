"""Ed25519 signing-key loading for the Harness (Spec 3.5 / 5.4).

Private keys come from the environment as hex seeds (``.env`` is filled in by
a human) and never appear in logs, database rows or API responses — Spec 3.5
forbids storing or returning key or token material. Tests pass explicitly
generated or fixed keys instead of environment variables.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SEED_BYTES = 32


def load_private_key(
    env_var: str, *, allow_ephemeral: bool = False
) -> Ed25519PrivateKey:
    """Load an Ed25519 private key from ``env_var`` (64-char hex seed).

    ``allow_ephemeral=True`` generates a throwaway key when the variable is
    unset. That is for local tests only: a deployment without a persisted key
    cannot verify tokens or checkpoints across restarts, so production code
    must never enable it. Invalid or missing values fail closed with
    ``RuntimeError``; the value itself is never included in the message.
    """

    raw = os.getenv(env_var, "").strip()
    if not raw:
        if allow_ephemeral:
            return Ed25519PrivateKey.generate()
        raise RuntimeError(
            f"{env_var} is required (64-character hex Ed25519 seed); fill it "
            "in .env — the key must never be logged or stored"
        )
    try:
        seed = bytes.fromhex(raw)
    except ValueError:
        raise RuntimeError(f"{env_var} must be hexadecimal") from None
    if len(seed) != SEED_BYTES:
        raise RuntimeError(f"{env_var} must decode to {SEED_BYTES} bytes")
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_key_b64url(key: Ed25519PrivateKey) -> str:
    """Base64url of the raw 32-byte public key (checkpoint storage format)."""

    return b64url_encode(key.public_key().public_bytes_raw())


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


__all__ = [
    "SEED_BYTES",
    "b64url_decode",
    "b64url_encode",
    "load_private_key",
    "public_key_b64url",
]
