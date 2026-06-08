from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_ENC_V1_PREFIX = "enc:v1:"
_ENC_V2_PREFIX = "enc:v2:"
_ENC_PREFIX = _ENC_V2_PREFIX
_SALT_BYTES = 16
_V1_NONCE_BYTES = 16
_V1_TAG_BYTES = 32
_V2_NONCE_BYTES = 12
_V2_TAG_BYTES = 16
_KEY_BYTES = 32
_V2_AAD = b"study-ai:model-config:v2"


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
    except (OSError, UnicodeError, ValueError, binascii.Error):
        pass

    key = os.urandom(_KEY_BYTES)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(_b64_encode(key))
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except FileExistsError:
        try:
            raw = path.read_text(encoding="ascii").strip()
            data = _b64_decode(raw)
            if len(data) >= _KEY_BYTES:
                return data[:_KEY_BYTES]
        except (OSError, UnicodeError, ValueError, binascii.Error):
            pass
    except OSError:
        # Last-resort process-local key. Avoid deriving reusable encryption keys
        # from weak or placeholder JWT secrets.
        key = os.urandom(_KEY_BYTES)
    return key


def _derive_v1_key(salt: bytes) -> bytes:
    root_key = _load_or_create_root_key()
    return hashlib.pbkdf2_hmac("sha256", root_key, b"study-ai:model-config:" + salt, 120_000, dklen=_KEY_BYTES)


def _derive_v2_key(salt: bytes) -> bytes:
    root_key = _load_or_create_root_key()
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=salt,
        info=_V2_AAD,
    ).derive(root_key)


def _legacy_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:length])


def is_encrypted_string(value: str) -> bool:
    raw = str(value or "")
    return raw.startswith(_ENC_V1_PREFIX) or raw.startswith(_ENC_V2_PREFIX)


def encrypt_string(value: str) -> str:
    plaintext = str(value or "").encode("utf-8")
    if not plaintext:
        return ""
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_V2_NONCE_BYTES)
    key = _derive_v2_key(salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, _V2_AAD)
    return _ENC_V2_PREFIX + _b64_encode(salt + nonce + ciphertext)


def _decrypt_v1(raw: str) -> str:
    payload = _b64_decode(raw[len(_ENC_V1_PREFIX) :])
    min_len = _SALT_BYTES + _V1_NONCE_BYTES + _V1_TAG_BYTES + 1
    if len(payload) < min_len:
        return ""
    salt = payload[:_SALT_BYTES]
    nonce = payload[_SALT_BYTES : _SALT_BYTES + _V1_NONCE_BYTES]
    tag = payload[-_V1_TAG_BYTES:]
    ciphertext = payload[_SALT_BYTES + _V1_NONCE_BYTES : -_V1_TAG_BYTES]
    key = _derive_v1_key(salt)
    expected = hmac.new(key, b"v1" + salt + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        return ""
    stream = _legacy_keystream(key, nonce, len(ciphertext))
    plaintext = bytes(a ^ b for a, b in zip(ciphertext, stream))
    return plaintext.decode("utf-8")


def _decrypt_v2(raw: str) -> str:
    payload = _b64_decode(raw[len(_ENC_V2_PREFIX) :])
    min_len = _SALT_BYTES + _V2_NONCE_BYTES + _V2_TAG_BYTES
    if len(payload) < min_len:
        return ""
    salt = payload[:_SALT_BYTES]
    nonce = payload[_SALT_BYTES : _SALT_BYTES + _V2_NONCE_BYTES]
    ciphertext = payload[_SALT_BYTES + _V2_NONCE_BYTES :]
    key = _derive_v2_key(salt)
    return AESGCM(key).decrypt(nonce, ciphertext, _V2_AAD).decode("utf-8")


def decrypt_string(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.startswith(_ENC_V2_PREFIX):
        decrypt = _decrypt_v2
    elif raw.startswith(_ENC_V1_PREFIX):
        decrypt = _decrypt_v1
    else:
        return raw

    try:
        return decrypt(raw)
    except (OSError, UnicodeDecodeError, ValueError, binascii.Error, InvalidTag):
        return ""


def mask_secret(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "****"
    return f"{raw[:4]}...{raw[-4:]}"
