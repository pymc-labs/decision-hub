"""Tests for ``dhub_core.hashing`` — the canonical publish-checksum helpers.

These pin the SHA-256 hex contract used by *both* client (``dhub-cli``) and
server (``decision-hub-server``). If either side drifts from this hash,
"no-op publish" detection breaks silently.
"""

import hashlib

import pytest

from dhub_core.hashing import sha256_hex, verify_sha256


class TestSha256Hex:
    def test_matches_stdlib(self) -> None:
        payload = b"decision-hub"
        assert sha256_hex(payload) == hashlib.sha256(payload).hexdigest()

    def test_empty_bytes(self) -> None:
        # SHA-256 of the empty string is a well-known value.
        assert sha256_hex(b"") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

    def test_deterministic(self) -> None:
        payload = b"pymc-labs/pymc-modeling@1.2.3"
        assert sha256_hex(payload) == sha256_hex(payload)

    def test_lowercase_hex(self) -> None:
        digest = sha256_hex(b"anything")
        assert digest.lower() == digest


class TestVerifySha256:
    def test_ok_when_match(self) -> None:
        payload = b"registry"
        # Should not raise.
        verify_sha256(payload, sha256_hex(payload))

    def test_raises_on_mismatch(self) -> None:
        with pytest.raises(ValueError, match="Checksum mismatch"):
            verify_sha256(b"one", sha256_hex(b"two"))

    def test_error_message_carries_expected_and_actual(self) -> None:
        payload = b"payload"
        expected = "0" * 64
        with pytest.raises(ValueError) as exc_info:
            verify_sha256(payload, expected)
        message = str(exc_info.value)
        assert expected in message
        assert sha256_hex(payload) in message
