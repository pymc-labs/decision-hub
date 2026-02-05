"""Fernet symmetric encryption for securing API keys at rest."""

from cryptography.fernet import Fernet


def encrypt_value(plaintext: str, fernet_key: str) -> bytes:
    """Encrypt a plaintext value using Fernet symmetric encryption.

    Args:
        plaintext: The value to encrypt.
        fernet_key: URL-safe base64-encoded 32-byte Fernet key.

    Returns:
        Encrypted ciphertext as bytes.
    """
    f = Fernet(fernet_key.encode())
    return f.encrypt(plaintext.encode())


def decrypt_value(ciphertext: bytes, fernet_key: str) -> str:
    """Decrypt a Fernet-encrypted value.

    Args:
        ciphertext: The encrypted bytes to decrypt.
        fernet_key: URL-safe base64-encoded 32-byte Fernet key.

    Returns:
        Decrypted plaintext string.
    """
    f = Fernet(fernet_key.encode())
    return f.decrypt(ciphertext).decode()
