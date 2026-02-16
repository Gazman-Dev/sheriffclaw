from __future__ import annotations

import hashlib
import hmac
import json
import os


class SecretCryptoError(Exception):
    pass


def _kdf(passphrase: str, salt: bytes) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hashlib.blake2b(key=key, digest_size=32, person=b"poc-secrets")
        block.update(nonce)
        block.update(counter.to_bytes(8, "big"))
        out.extend(block.digest())
        counter += 1
    return bytes(a ^ b for a, b in zip(data, out[: len(data)]))


def encrypt_blob(data: dict[str, object], passphrase: str) -> bytes:
    plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
    salt = os.urandom(16)
    nonce = os.urandom(16)
    keymat = _kdf(passphrase, salt)
    enc_key, mac_key = keymat[:32], keymat[32:]
    ciphertext = _xor_stream(plaintext, enc_key, nonce)
    tag = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    envelope = {
        "v": 1,
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "ciphertext": ciphertext.hex(),
        "tag": tag.hex(),
    }
    return json.dumps(envelope, separators=(",", ":")).encode("utf-8")


def decrypt_blob(blob: bytes, passphrase: str) -> dict[str, object]:
    try:
        envelope = json.loads(blob.decode("utf-8"))
        salt = bytes.fromhex(envelope["salt"])
        nonce = bytes.fromhex(envelope["nonce"])
        ciphertext = bytes.fromhex(envelope["ciphertext"])
        tag = bytes.fromhex(envelope["tag"])
    except Exception as exc:
        raise SecretCryptoError("invalid encrypted blob") from exc

    keymat = _kdf(passphrase, salt)
    enc_key, mac_key = keymat[:32], keymat[32:]
    expected = hmac.new(mac_key, nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, tag):
        raise SecretCryptoError("wrong passphrase or corrupted blob")
    plaintext = _xor_stream(ciphertext, enc_key, nonce)
    return json.loads(plaintext.decode("utf-8"))
