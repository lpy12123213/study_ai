from __future__ import annotations

import hashlib

USER_ID_MAX_CHARS = 64
USER_ID_HASH_CHARS = 16


def normalize_user_id(user_id: str) -> str:
    uid = str(user_id or "").strip()
    if len(uid) <= USER_ID_MAX_CHARS:
        return uid
    digest = hashlib.sha256(uid.encode("utf-8")).hexdigest()[:USER_ID_HASH_CHARS]
    prefix_len = USER_ID_MAX_CHARS - USER_ID_HASH_CHARS - 1
    return f"{uid[:prefix_len]}~{digest}"
