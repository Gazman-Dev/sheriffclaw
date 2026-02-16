from __future__ import annotations

import hashlib
import hmac
import os

_VERIFIER_MESSAGE = b"openclaw-master-verifier"


def _derive(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)


def create_verifier(master_password: str) -> dict[str, str]:
    salt = os.urandom(16)
    keymat = _derive(master_password, salt)
    verifier = hmac.new(keymat, _VERIFIER_MESSAGE, hashlib.sha256).digest()
    return {"salt": salt.hex(), "verifier": verifier.hex()}


def verify_password(master_password: str, verifier_record: dict) -> bool:
    try:
        salt = bytes.fromhex(str(verifier_record["salt"]))
        expected = bytes.fromhex(str(verifier_record["verifier"]))
    except Exception:
        return False
    keymat = _derive(master_password, salt)
    actual = hmac.new(keymat, _VERIFIER_MESSAGE, hashlib.sha256).digest()
    return hmac.compare_digest(actual, expected)
