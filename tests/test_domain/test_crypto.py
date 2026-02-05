"""Tests for decision_hub.domain.crypto -- Fernet encryption helpers."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from decision_hub.domain.crypto import decrypt_value, encrypt_value


def test_encrypt_decrypt_roundtrip(fernet_key: str) -> None:
    """Encrypting then decrypting should return the original value."""
    plaintext = "sk-super-secret-api-key"
    ciphertext = encrypt_value(plaintext, fernet_key)

    assert isinstance(ciphertext, bytes)
    assert ciphertext != plaintext.encode()  # must actually be encrypted

    recovered = decrypt_value(ciphertext, fernet_key)
    assert recovered == plaintext


def test_different_keys_fail() -> None:
    """Decrypting with a different Fernet key should fail."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    ciphertext = encrypt_value("my-secret", key_a)

    with pytest.raises(InvalidToken):
        decrypt_value(ciphertext, key_b)


def test_encrypt_empty_string(fernet_key: str) -> None:
    """Empty strings should encrypt and decrypt correctly."""
    ciphertext = encrypt_value("", fernet_key)
    assert decrypt_value(ciphertext, fernet_key) == ""
