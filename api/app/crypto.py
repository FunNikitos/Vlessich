"""Libsodium secretbox cipher for at-rest encryption.

Used for:
- ``codes.code_enc`` (encrypted code plaintext; lookup by ``code_hash``).
- ``devices.xray_uuid_enc`` (encrypted Xray UUID).

Key: 32 bytes, passed as 64-char hex via ``API_SECRETBOX_KEY``.
Ciphertext layout: ``nonce(24) || box`` (nacl's ``encrypt`` does this by default).
"""
from __future__ import annotations

from functools import lru_cache

from nacl.exceptions import CryptoError
from nacl.secret import SecretBox

from app.config import get_settings


class CipherError(Exception):
    """Raised on tamper / wrong-key / malformed ciphertext."""


class SecretBoxCipher:
    """Thin wrapper around ``nacl.secret.SecretBox`` with friendly errors."""

    def __init__(self, key_hex: str) -> None:
        key = bytes.fromhex(key_hex)
        if len(key) != SecretBox.KEY_SIZE:
            raise ValueError(
                f"secretbox key must be {SecretBox.KEY_SIZE} bytes "
                f"({SecretBox.KEY_SIZE * 2} hex chars), got {len(key)} bytes"
            )
        self._box = SecretBox(key)

    def seal(self, plaintext: str) -> bytes:
        """Encrypt UTF-8 text; nonce is generated internally and prepended."""
        return self._box.encrypt(plaintext.encode("utf-8"))

    def open(self, ciphertext: bytes) -> str:
        """Decrypt; raises ``CipherError`` on any failure (tamper/wrong key)."""
        try:
            return self._box.decrypt(ciphertext).decode("utf-8")
        except CryptoError as exc:
            raise CipherError("secretbox decryption failed") from exc


@lru_cache(maxsize=1)
def get_cipher() -> SecretBoxCipher:
    """DI entry-point; single instance per process."""
    return SecretBoxCipher(get_settings().secretbox_key.get_secret_value())
