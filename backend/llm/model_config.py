from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from backend.core.encryption import decrypt_string


def _truthy(value: str) -> bool:
    v = str(value or "").strip().lower()
    return v in {"1", "true", "yes", "y", "on"}


def resolve_model_config_path(*, repo_root: Path) -> Path:
    """
    Resolve the model config path.

    Defaults to `<repo_root>/config/model.json`, but can be overridden by MODEL_CONFIG_PATH.
    """

    raw = str(os.getenv("MODEL_CONFIG_PATH") or "").strip()
    if raw:
        try:
            return Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            return Path(raw)
    return (repo_root / "config" / "model.json").resolve()


def normalize_base_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    if not raw:
        return ""
    # Allow users to paste the full endpoint; normalize to OpenAI-compatible base URL.
    if raw.endswith("/chat/completions"):
        raw = raw[: -len("/chat/completions")].rstrip("/")
    return raw


def _normalize_base_url(value: str) -> str:
    return normalize_base_url(value)


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    base_url: str
    api_key: str


@dataclass(frozen=True)
class ModelJsonConfig:
    path: Path
    active_provider: str
    providers: Dict[str, ProviderConfig]
    models: Dict[str, Any]
    params: Dict[str, Any]
    pinned: bool


def load_model_json_config(*, repo_root: Path) -> Optional[ModelJsonConfig]:
    """
    Load `<repo_root>/config/model.json` if present.

    This file is intended to store local-only provider endpoints + API keys and must not be committed.
    """

    path = resolve_model_config_path(repo_root=repo_root)
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, dict):
        return None

    active = str(payload.get("active_provider") or "").strip()
    providers_raw = payload.get("providers")
    models = payload.get("models") if isinstance(payload.get("models"), dict) else {}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}

    providers: Dict[str, ProviderConfig] = {}
    if isinstance(providers_raw, dict):
        for k, v in providers_raw.items():
            name = str(k or "").strip()
            if not name:
                continue
            if not isinstance(v, dict):
                continue
            base_url = _normalize_base_url(str(v.get("base_url") or ""))
            api_key = str(v.get("api_key") or "").strip()
            encrypted_api_key = str(v.get("api_key_encrypted") or "").strip()
            if encrypted_api_key:
                api_key = decrypt_string(encrypted_api_key)
            elif api_key:
                api_key = decrypt_string(api_key)
            if not base_url and not api_key:
                continue
            key = name.lower()
            providers[key] = ProviderConfig(name=key, base_url=base_url, api_key=api_key)

    active_key = active.lower()
    if "pinned" in payload:
        pinned_raw = payload.get("pinned")
        pinned = bool(pinned_raw) if isinstance(pinned_raw, bool) else _truthy(str(pinned_raw or ""))
    else:
        pinned = bool(active_key and providers.get(active_key) and not _truthy(payload.get("auto") or "0"))

    # If active_provider is invalid, still load providers/models/params but don't pin the runtime.
    if active_key and active_key not in providers:
        pinned = False

    return ModelJsonConfig(
        path=path,
        active_provider=active_key,
        providers=providers,
        models=dict(models) if isinstance(models, dict) else {},
        params=dict(params) if isinstance(params, dict) else {},
        pinned=pinned,
    )
