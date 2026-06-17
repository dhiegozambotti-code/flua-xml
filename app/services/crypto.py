"""Envelope encryption para o vault de certificados.

Cada blob é criptografado com AES-256-GCM usando um nonce aleatório de 12 bytes.
Formato do ciphertext: nonce (12 bytes) || tag (16 bytes) || ciphertext.
"""

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def encrypt_bytes(plaintext: bytes, master_key: bytes) -> bytes:
    nonce = os.urandom(12)
    aesgcm = AESGCM(master_key)
    ct = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ct


def decrypt_bytes(ciphertext: bytes, master_key: bytes) -> bytes:
    nonce = ciphertext[:12]
    ct = ciphertext[12:]
    aesgcm = AESGCM(master_key)
    return aesgcm.decrypt(nonce, ct, None)
