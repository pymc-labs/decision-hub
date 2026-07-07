"""SHA-256 checksum helpers shared between client and server.

Both `dhub-cli` (client) and `decision-hub-server` need to compute the
same digest over a skill zip to detect no-op publishes. Keeping the
implementation here guarantees they can never drift.
"""

import hashlib


def sha256_hex(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of ``data``.

    The digest is the canonical checksum used to detect whether a
    skill's contents have changed between publishes.
    """
    return hashlib.sha256(data).hexdigest()


def verify_sha256(data: bytes, expected: str) -> None:
    """Raise ``ValueError`` if ``sha256_hex(data) != expected``.

    Constant-time comparison is not required — checksums are computed
    over content the caller already owns and are not authentication
    tokens — so a plain string equality suffices.
    """
    actual = sha256_hex(data)
    if actual != expected:
        raise ValueError(f"Checksum mismatch: expected {expected}, got {actual}.")
