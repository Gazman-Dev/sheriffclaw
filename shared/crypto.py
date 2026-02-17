from __future__ import annotations

import base64
import hashlib


def _key(password: str) -> bytes:
    return hashlib.sha256(password.encode("utf-8")).digest()


def encrypt_text(text: str, password: str) -> str:
    raw = text.encode("utf-8")
    key = _key(password)
    out = bytes(raw[i] ^ key[i % len(key)] for i in range(len(raw)))
    return base64.b64encode(out).decode("ascii")


def decrypt_text(ciphertext_b64: str, password: str) -> str:
    raw = base64.b64decode(ciphertext_b64.encode("ascii"))
    key = _key(password)
    out = bytes(raw[i] ^ key[i % len(key)] for i in range(len(raw)))
    return out.decode("utf-8")
