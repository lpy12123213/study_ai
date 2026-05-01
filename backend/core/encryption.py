from __future__ import annotations

import base64
import hashlib
import hmac
import os
from pathlib import Path

_ENC_PREFIX = "enc:v1:"
_SALT_BYTES = 16
_NONCE_BYTES = 16
_TAG_BYTES = 32
_KEY_BYTES = 32


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_encryption_key_path() -> Path:
    raw = str(os.getenv("LOCAL_ENCRYPTION_KEY_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (_repo_root() / ".local" / "secrets" / "model_config.key").resolve()


def _b64_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64_decode(raw: str) -> bytes:
    value = str(raw or "").strip()
    if not value:
        return b""
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def _load_or_create_root_key() -> bytes:
    path = resolve_encryption_key_path()
    try:
        if path.exists():
            raw = path.read_text(encoding="ascii").strip()
            data = _b64_decode(raw)
            if len(data) >= _KEY_BYTES:
                return data[:_KEY_BYTES]
    except Exception:
        pass

    key = os.urandom(_KEY_BYTES)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_b64_encode(key), encoding="ascii")
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        # Fall back to a deterministic process-local key only when the key file cannot be written.
        seed = f"{_repo_root()}:{os.getenv('JWT_SECRET') or ''}".encode("utf-8", errors="ignore")
        key = hashlib.sha256(seed).digest()
    return key


def _derive_key(salt: bytes) -> bytes:
    root_key = _load_or_create_root_key()
    return hashlib.pbkdf2_hmac("sha256", root_key, b"study-ai:model-config:" + salt, 120_000, dklen=_KEY_BYTES)


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def is_encrypted_string(value: str) -> bool:
    return str(value or "").startswith(_ENC_PREFIX)


def encrypt_string(value: str) -> str:
    plaintext = str(value or "").encode("utf-8")
    if not plaintext:
        return ""
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(salt)
    stream = _keystream(key, nonce, len(plaintext))
    ciphertext = bytes(a ^ b for a, b in zip(plaintext, stream))
    tag = hmac.new(key, b"v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    return _ENC_PREFIX + _b64_encode(salt + nonce + ciphertext + tag)


def decrypt_string(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not is_encrypted_string(raw):
        return raw

    try:
        payload = _b64_decode(raw[len(_ENC_PREFIX) :])
        min_len = _SALT_BYTES + _NONCE_BYTES + _TAG_BYTES + 1
        if len(payload) < min_len:
            return ""
        salt = payload[:_SALT_BYTES]
        nonce = payload[_SALT_BYTES : _SALT_BYTES + _NONCE_BYTES]
        tag = payload[-_TAG_BYTES:]
        ciphertext = payload[_SALT_BYTES + _NONCE_BYTES : -_TAG_BYTES]
        key = _derive_key(salt)
        expected = hmac.new(key, b"v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            return ""
        stream = _keystream(key, nonce, len(ciphertext))
        plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
        return plaintext.decode("utf-8")
    except Exception:
        return ""


def mask_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "****"
    return f"{raw[:4]}...{raw[-4:]}"
