#  File: shared/crypto.py

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def encrypt_text(text: str, password: str) -> str:
    # Generate a random 16-byte salt
    salt = os.urandom(16)
    # Derive the key from the password and salt
    key = _derive_key(password, salt)
    f = Fernet(key)
    # Encrypt the data
    token = f.encrypt(text.encode("utf-8"))
    # Prepend the salt to the token and base64 encode the whole thing
    return base64.urlsafe_b64encode(salt + token).decode("ascii")


def decrypt_text(ciphertext_b64: str, password: str) -> str:
    try:
        # Decode the base64 blob
        data = base64.urlsafe_b64decode(ciphertext_b64.encode("ascii"))

        # We expect at least 16 bytes for the salt
        if len(data) < 16:
            raise ValueError("Invalid ciphertext data")

        salt = data[:16]
        token = data[16:]

        # Derive the key again
        key = _derive_key(password, salt)
        f = Fernet(key)

        # Decrypt
        return f.decrypt(token).decode("utf-8")
    except Exception as e:
        # Raise a ValueError to match previous interface contract for failure
        raise ValueError("Decryption failed") from e