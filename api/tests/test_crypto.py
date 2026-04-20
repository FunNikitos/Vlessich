"""Tests for ``app.crypto.SecretBoxCipher``."""
from __future__ import annotations

import pytest

from app.crypto import CipherError, SecretBoxCipher

# 32-byte test keys (NEVER use in prod).
KEY_A = "00" * 32
KEY_B = "11" * 32


def test_seal_open_roundtrip() -> None:
    cipher = SecretBoxCipher(KEY_A)
    plaintext = "PROMO-ABCD-1234"
    blob = cipher.seal(plaintext)
    assert cipher.open(blob) == plaintext


def test_seal_produces_distinct_ciphertexts_for_same_input() -> None:
    """Random nonce must yield different ciphertexts (semantic security)."""
    cipher = SecretBoxCipher(KEY_A)
    a = cipher.seal("same")
    b = cipher.seal("same")
    assert a != b
    assert cipher.open(a) == cipher.open(b) == "same"


def test_open_with_wrong_key_raises() -> None:
    blob = SecretBoxCipher(KEY_A).seal("secret")
    with pytest.raises(CipherError):
        SecretBoxCipher(KEY_B).open(blob)


def test_open_tampered_ciphertext_raises() -> None:
    cipher = SecretBoxCipher(KEY_A)
    blob = bytearray(cipher.seal("secret"))
    blob[-1] ^= 0x01  # flip last bit of MAC/payload
    with pytest.raises(CipherError):
        cipher.open(bytes(blob))


def test_invalid_key_length_raises_at_init() -> None:
    with pytest.raises(ValueError, match="secretbox key must be 32 bytes"):
        SecretBoxCipher("aa" * 16)  # 16 bytes, too short
