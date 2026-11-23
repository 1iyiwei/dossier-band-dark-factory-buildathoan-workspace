"""Password hashing with scrypt; plaintext passwords are never stored."""
from __future__ import annotations

import hashlib
import hmac
import os

_N, _R, _P = 2 ** 14, 8, 1
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    value = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${value.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                               maxmem=_MAXMEM)
        return hmac.compare_digest(value.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


def is_password_hash(encoded) -> bool:
    if not isinstance(encoded, str):
        return False
    parts = encoded.split("$")
    return len(parts) == 6 and parts[0] == "scrypt" and all(parts[1:])
