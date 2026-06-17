"""Testes do serviço de criptografia (vault de certificados)."""

import os
import pytest

from app.services.crypto import decrypt_bytes, encrypt_bytes


@pytest.fixture()
def master_key():
    return os.urandom(32)


def test_encrypt_decrypt_roundtrip(master_key):
    plaintext = b"dado secreto do certificado"
    ciphertext = encrypt_bytes(plaintext, master_key)
    assert ciphertext != plaintext
    assert decrypt_bytes(ciphertext, master_key) == plaintext


def test_ciphertext_includes_nonce(master_key):
    # AES-GCM: nonce(12) + tag(16) + ciphertext — sempre > len(plaintext)
    plaintext = b"abc"
    ciphertext = encrypt_bytes(plaintext, master_key)
    assert len(ciphertext) > len(plaintext) + 12


def test_different_keys_cannot_decrypt(master_key):
    plaintext = b"segredo"
    ciphertext = encrypt_bytes(plaintext, master_key)
    wrong_key = os.urandom(32)
    with pytest.raises(Exception):
        decrypt_bytes(ciphertext, wrong_key)


def test_tampered_ciphertext_raises(master_key):
    plaintext = b"dados"
    ciphertext = bytearray(encrypt_bytes(plaintext, master_key))
    ciphertext[-1] ^= 0xFF  # corrompe último byte (tag GCM)
    with pytest.raises(Exception):
        decrypt_bytes(bytes(ciphertext), master_key)


def test_empty_plaintext(master_key):
    plaintext = b""
    ciphertext = encrypt_bytes(plaintext, master_key)
    assert decrypt_bytes(ciphertext, master_key) == plaintext


def test_large_payload(master_key):
    plaintext = os.urandom(1024 * 64)  # 64 KB
    ciphertext = encrypt_bytes(plaintext, master_key)
    assert decrypt_bytes(ciphertext, master_key) == plaintext
