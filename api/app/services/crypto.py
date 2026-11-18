"""Encryption at rest for voice samples & consent audio (PRD §2.2 privacy).

Fernet (AES-128-CBC + HMAC) keyed from a hash of JWT_SECRET. Swapping to
per-tenant KMS keys is a drop-in replacement of the two functions.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    digest = hashlib.sha256(("bohurupi-at-rest:" + settings.jwt_secret).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_file(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt_file(token: bytes) -> bytes:
    try:
        return _fernet().decrypt(token)
    except InvalidToken as e:
        raise ValueError("Stored sample cannot be decrypted (key changed?)") from e
