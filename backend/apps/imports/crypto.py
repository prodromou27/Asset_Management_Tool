"""Encryption of retained files: import originals (Task 013) and export artifacts (Task 014).

Fernet (AES-128-CBC + HMAC-SHA256) from ``cryptography``. The key is
``ITAM_IMPORT_ENCRYPTION_KEY`` (a Fernet key) when set; otherwise it is derived from
``DJANGO_SECRET_KEY`` with HKDF-SHA256 and a per-purpose context label, so rotating the
secret key makes retained files unreadable (they are only kept for their retention period)
and an import key never decrypts an export or the other way round.
"""

import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

IMPORTS = b"itam-import-originals-v1"
EXPORTS = b"itam-export-files-v1"


def _fernet(purpose: bytes) -> Fernet:
    configured = getattr(settings, "ITAM_IMPORT_ENCRYPTION_KEY", "")
    if configured:
        return Fernet(configured.encode() if isinstance(configured, str) else configured)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=purpose).derive(
        settings.SECRET_KEY.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(data: bytes, purpose: bytes = IMPORTS) -> bytes:
    return _fernet(purpose).encrypt(data)


def decrypt(token: bytes, purpose: bytes = IMPORTS) -> bytes | None:
    try:
        return _fernet(purpose).decrypt(bytes(token))
    except InvalidToken:
        return None
