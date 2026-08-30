"""Encryption and keyed-digest utilities for sensitive migration fields."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from cryptography.fernet import Fernet, InvalidToken


def encrypt_sensitive_value(value: str, encryption_key: str | None = None) -> str:
    return _fernet(encryption_key).encrypt(str(value).encode("utf-8")).decode("ascii")


def decrypt_sensitive_value(ciphertext: str, encryption_key: str | None = None) -> str:
    try:
        return _fernet(encryption_key).decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise ValueError("Sensitive value cannot be decrypted with the configured key.") from exc


def sensitive_digest(value: str, digest_key: str | None = None) -> str:
    key = _required_value("FIELD_DIGEST_KEY", digest_key).encode("utf-8")
    normalized_value = str(value).strip().upper().encode("utf-8")
    return hmac.new(key, normalized_value, hashlib.sha256).hexdigest()


def _fernet(encryption_key: str | None) -> Fernet:
    key = _required_value("FIELD_ENCRYPTION_KEY", encryption_key)
    try:
        base64.urlsafe_b64decode(key.encode("ascii"))
        return Fernet(key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("FIELD_ENCRYPTION_KEY must be a valid Fernet key.") from exc


def _required_value(name: str, supplied_value: str | None) -> str:
    value = supplied_value if supplied_value is not None else os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} must be configured for secure migration.")
    return value