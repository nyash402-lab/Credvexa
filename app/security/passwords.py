"""Password transformation helpers for offline migration only."""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


_hasher = PasswordHasher()


def hash_legacy_password(password: str) -> str:
    return _hasher.hash(str(password))


def verify_password_hash(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, str(password))
    except (InvalidHashError, VerificationError):
        return False


def is_argon2id_hash(password_hash: str) -> bool:
    return str(password_hash).startswith("$argon2id$")