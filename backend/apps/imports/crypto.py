"""Encryption of retained original import files (docs/11 "preserve originals encrypted").

Fernet (AES-128-CBC + HMAC-SHA256) from ``cryptography``. The key is
``ITAM_IMPORT_ENCRYPTION_KEY`` (a Fernet key) when set; otherwise it is derived from
``DJANGO_SECRET_KEY`` with HKDF-SHA256 and a fixed context label, so rotating the secret
key makes retained originals unreadable (they are only kept for the retention period).
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings


def _fernet() -> Fernet:
    configured = getattr(settings, "ITAM_IMPORT_ENCRYPTION_KEY", "")
    if configured:
        return Fernet(configured.encode() if isinstance(configured, str) else configured)
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"itam-import-originals-v1"
    ).derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(data: bytes) -> bytes:
    return _fernet().encrypt(data)


def decrypt(token: bytes) -> bytes | None:
    try:
        return _fernet().decrypt(bytes(token))
    except InvalidToken:
        return None
